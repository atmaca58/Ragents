"""Secret taşımayan, hash doğrulamalı ve önce önizlenen profil paketleri."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import stat
import tempfile
import zipfile

from filelock import FileLock
from pydantic import Field
import yaml

from ragents.backups import backup_database
from ragents.catalog import AgentProfile, list_agents, load_agent
from ragents.config import Spec
from ragents.operation_hash import digest
from ragents.profile_paths import protected_profile_paths
from ragents.storage import TaskStateError, TaskStore
from ragents.workspace import normalize_relative_path, resolve_agent_workspace


MAX_BUNDLE_BYTES = 256 * 1024 * 1024
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_FILES = 10000


class ProfileManifest(Spec):
    schema_version: int = Field(ge=1, le=1)
    files: dict[str, str] = Field(max_length=MAX_FILES)
    workspaces: tuple[str, ...]
    includes_history: bool = False
    includes_workspaces: bool = False
    includes_artifacts: bool = False


def _allowed(name: str) -> bool:
    parts = PurePosixPath(name).parts
    if len(parts) < 2:
        return False
    if parts[0] == "agents":
        return (len(parts) == 3 and parts[2] in ("agent.yaml", "instructions.md", "project.md", "rules.md")
                or len(parts) == 5 and parts[2] == "skills" and parts[4] == "SKILL.md")
    return (name in ("connections/catalog.json", "connections/search.json", "connections/workspaces.json") or name == "data/ragents.db"
            or parts[0] == "teams" and len(parts) == 2 and name.endswith(".json")
            or parts[0] in ("workspaces", "artifact-blobs") and len(parts) >= 3)


def _safe_name(name: str) -> str:
    if "\\" in name or name.startswith("/") or normalize_relative_path(name) != name:
        raise TaskStateError("Paket dosya yolu güvenli değil.")
    return name


def _read_bundle(bundle: Path):
    files = {}
    total = 0
    with zipfile.ZipFile(bundle) as archive:
        entries = archive.infolist()
        if len(entries) > MAX_FILES + 1:
            raise TaskStateError("Paket çok fazla dosya içeriyor.")
        seen = set()
        for entry in entries:
            name = _safe_name(entry.filename)
            if name.casefold() in seen or stat.S_ISLNK(entry.external_attr >> 16):
                raise TaskStateError("Paket tekrarlı yol veya bağlantı içeriyor.")
            seen.add(name.casefold())
            total += entry.file_size
            if entry.file_size > MAX_FILE_BYTES or total > MAX_BUNDLE_BYTES:
                raise TaskStateError("Paket boyut sınırını aşıyor.")
            if name != "manifest.json" and not _allowed(name):
                raise TaskStateError("Paket izin verilmeyen profil dosyası içeriyor.")
            files[name] = archive.read(entry)
    if "manifest.json" not in files:
        raise TaskStateError("Paket manifesti bulunamadı.")
    manifest = ProfileManifest.model_validate_json(files.pop("manifest.json"))
    if set(files) != set(manifest.files):
        raise TaskStateError("Paket dosyaları manifestle eşleşmiyor.")
    if any(hashlib.sha256(content).hexdigest() != manifest.files[name] for name, content in files.items()):
        raise TaskStateError("Paket dosyasının hash doğrulaması başarısız.")
    return manifest, files


def export_profile(root: Path, output: Path, *, include_history=False, include_workspaces=False,
                   include_artifacts=False) -> Path:
    root, output = root.resolve(), output.resolve()
    if output.exists() or output.is_relative_to(root):
        raise TaskStateError("Paket için profil dışında yeni bir çıktı dosyası seçin.")
    files = {}
    with FileLock(root / "data" / "setup.lock"):
        agents = list_agents(root, include_archived=True)
        if any(not agent.valid for agent in agents):
            raise TaskStateError("Geçersiz ajan profili dışa aktarılamaz.")
        for summary in agents:
            record = load_agent(root, summary.id)
            profile = record.profile.model_copy(update={"workspace": f"workspaces/{summary.id}", "setup_request_id": None})
            files[f"agents/{summary.id}/agent.yaml"] = yaml.safe_dump(profile.model_dump(mode="json"), allow_unicode=True).encode()
            for document in record.documents:
                files[f"agents/{summary.id}/{document.name}"] = (record.directory / document.name).read_bytes()
            if include_workspaces:
                _collect_tree(record.workspace, f"workspaces/{summary.id}", files)
        for name in ("connections", "teams"):
            directory = root / name
            if directory.is_dir():
                _collect_tree(directory, name, files, filter_allowed=True)
        binding_name = "connections/workspaces.json"
        if binding_name in files:
            shared = {load_agent(root, agent.id).profile.shared_workspace_id: f"workspaces/{agent.id}"
                      for agent in agents if load_agent(root, agent.id).profile.shared_workspace_id}
            files[binding_name] = json.dumps(shared).encode()
        if include_artifacts and (root / "artifact-blobs").is_dir():
            _collect_tree(root / "artifact-blobs", "artifact-blobs", files, filter_allowed=True)
        if include_history and (root / "data/ragents.db").is_file():
            with tempfile.TemporaryDirectory(prefix="ragents-backup-") as temporary:
                backup = backup_database(root / "data/ragents.db", Path(temporary) / "ragents.db")
                _disable_database(backup)
                files["data/ragents.db"] = backup.read_bytes()
    if len(files) > MAX_FILES or any(len(value) > MAX_FILE_BYTES for value in files.values()) or sum(map(len, files.values())) > MAX_BUNDLE_BYTES:
        raise TaskStateError("Seçilen profil verileri paket boyut sınırını aşıyor.")
    manifest = ProfileManifest(schema_version=1, files={name: hashlib.sha256(value).hexdigest() for name, value in files.items()},
        workspaces=tuple(agent.id for agent in agents), includes_history=include_history,
        includes_workspaces=include_workspaces, includes_artifacts=include_artifacts)
    output.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        stream = output.open("xb")
        created = True
        with stream, zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", manifest.model_dump_json())
            for name, value in files.items():
                archive.writestr(name, value)
    except BaseException:
        if created:
            output.unlink(missing_ok=True)
        raise
    return output


def _collect_tree(directory, prefix, files, *, filter_allowed=False):
    for path in directory.rglob("*"):
        if path.is_symlink() or path.is_junction():
            raise TaskStateError("Bağlantılı dosya veya dizin pakete alınamaz.")
        if not path.is_file():
            continue
        name = f"{prefix}/{path.relative_to(directory).as_posix()}"
        if filter_allowed and not _allowed(name):
            continue
        if path.stat().st_size > MAX_FILE_BYTES or len(files) >= MAX_FILES:
            raise TaskStateError("Seçilen dosyalar paket sınırını aşıyor.")
        files[_safe_name(name)] = path.read_bytes()


def _disable_database(path):
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("DELETE FROM setup_requests")
        db.execute("UPDATE tasks SET enabled=0, status=CASE WHEN status='running' THEN 'interrupted' ELSE status END")
        db.execute("UPDATE runs SET status='interrupted', error_code='profile_imported' WHERE status='running'")
        db.execute("UPDATE schedules SET enabled=0")
        for row in db.execute("SELECT id,record_json FROM team_runs").fetchall():
            record = json.loads(row[1])
            record.update(status="cancelled", error_code="profile_imported")
            db.execute("UPDATE team_runs SET record_json=? WHERE id=?", (json.dumps(record), row[0]))


def _rebase_definition(value, target, mapping):
    workspace = value.get("workspace")
    if workspace is not None:
        identity = value["config"]["agent"]["id"]
        workspace["root"] = mapping.get(identity, str(target / "workspaces" / identity))
        workspace["protected_paths"] = [str(path) for path in protected_profile_paths(target)]
    return value


def _rebase_database(path, target, mapping):
    with closing(sqlite3.connect(path)) as db, db:
        for table, identity_columns in (("tasks", ("id",)), ("task_revisions", ("task_id", "revision")),
                                        ("schedules", ("id",))):
            rows = db.execute(f"SELECT {','.join(identity_columns)},definition_json FROM {table}").fetchall()
            for row in rows:
                definition = _rebase_definition(json.loads(row[-1]), target, mapping)
                predicate = " AND ".join(f"{column}=?" for column in identity_columns)
                db.execute(f"UPDATE {table} SET definition_json=? WHERE {predicate}",
                           (json.dumps(definition, ensure_ascii=False), *row[:-1]))
        for identity, payload in db.execute("SELECT id,record_json FROM team_runs").fetchall():
            record = json.loads(payload)
            record["profile_root"] = str(target)
            record["definitions"] = {key: _rebase_definition(value, target, mapping)
                                     for key, value in record["definitions"].items()}
            db.execute("UPDATE team_runs SET record_json=? WHERE id=?", (json.dumps(record, ensure_ascii=False), identity))


def preview_import(bundle: Path, target: Path, mapping: dict[str, str]) -> dict:
    target = target.resolve()
    if target.exists():
        raise TaskStateError("İçe aktarma yalnız yeni profil köküne yapılabilir.")
    manifest, files = _read_bundle(bundle)
    if set(mapping) != set(manifest.workspaces):
        raise TaskStateError("Her ajan workspace'i için açık yol eşlemesi gereklidir.")
    resolved = {}
    shared_ids = {}
    for identity in manifest.workspaces:
        profile_path = f"agents/{identity}/agent.yaml"
        if profile_path not in files:
            raise TaskStateError("Workspace için ajan tanımı bulunamadı.")
        profile = AgentProfile.model_validate(yaml.safe_load(files[profile_path]))
        if profile.id != identity:
            raise TaskStateError("Paket ajan kimliğiyle eşleşmiyor.")
        workspace = resolve_agent_workspace(target, identity, mapping[identity],
            protected_paths=protected_profile_paths(target))
        if manifest.includes_workspaces and not workspace.is_relative_to(target / "workspaces"):
            raise TaskStateError("Workspace içeriği yalnız yeni profilin workspaces dizinine açılabilir.")
        for other_id, other in resolved.items():
            if workspace == other and profile.shared_workspace_id and profile.shared_workspace_id == shared_ids[other_id]:
                continue
            if workspace == other or workspace.is_relative_to(other) or other.is_relative_to(workspace):
                raise TaskStateError("Eşlenen workspace yolları çakışıyor.")
        if profile.shared_workspace_id and any(shared_ids[key] == profile.shared_workspace_id and value != workspace
                                               for key, value in resolved.items()):
            raise TaskStateError("Aynı ortak workspace tek hedef yola eşlenmelidir.")
        resolved[identity] = workspace
        shared_ids[identity] = profile.shared_workspace_id
    preview = {"target": str(target), "agents": list(manifest.workspaces),
               "workspaces": {key: str(value) for key, value in resolved.items()},
               "requires_reauthentication": True, "agents_and_schedules_disabled": True,
               "files": len(files), "manifest_hash": digest(manifest.model_dump(mode="json"))}
    return preview | {"operation_hash": digest(preview)}


def import_profile(bundle: Path, target: Path, mapping: dict[str, str], operation_hash: str) -> dict:
    target = target.resolve()
    preview = preview_import(bundle, target, mapping)
    if preview["operation_hash"] != operation_hash:
        raise TaskStateError("İçe aktarma önizlemesi değişti; yeniden inceleyin.")
    manifest, files = _read_bundle(bundle)
    if digest(manifest.model_dump(mode="json")) != preview["manifest_hash"]:
        raise TaskStateError("Paket önizlemeden sonra değişti.")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent, prefix=".ragents-import-") as temporary:
        stage = Path(temporary) / "profile"
        stage.mkdir()
        for name, content in files.items():
            if name.startswith("workspaces/"):
                _, identity, relative = name.split("/", 2)
                workspace = Path(preview["workspaces"][identity])
                destination = stage / workspace.relative_to(target) / relative
            else:
                destination = stage / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() and destination.read_bytes() != content:
                raise TaskStateError("Paylaşılan workspace dosyaları farklı içerikle çakışıyor.")
            destination.write_bytes(content)
        shared = {}
        for identity, workspace in preview["workspaces"].items():
            path = stage / "agents" / identity / "agent.yaml"
            profile = AgentProfile.model_validate(yaml.safe_load(path.read_bytes()))
            profile = profile.model_copy(update={"workspace": workspace, "status": "disabled", "setup_request_id": None})
            if profile.shared_workspace_id:
                shared[profile.shared_workspace_id] = workspace
            path.write_text(yaml.safe_dump(profile.model_dump(mode="json"), allow_unicode=True), encoding="utf-8")
            if Path(workspace).is_relative_to(target):
                (stage / Path(workspace).relative_to(target)).mkdir(parents=True, exist_ok=True)
        if shared:
            directory = stage / "connections"
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "workspaces.json").write_text(json.dumps(shared), encoding="utf-8")
        database = stage / "data/ragents.db"
        if database.exists():
            TaskStore(database)
            _disable_database(database)
            _rebase_database(database, target, preview["workspaces"])
        os.rename(stage, target)
    return preview
