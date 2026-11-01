"""Sınırlandırılmış çalışma alanı okuma ve artifact tespiti."""

import codecs
from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from ragents.config import Spec
from ragents.errors import WorkspaceError


MAX_PATH_CHARS = 512
MAX_LIST_ENTRIES = 200
MAX_LIST_DEPTH = 3
MAX_SEARCH_RESULTS = 50
MAX_SEARCH_FILES = 1000
MAX_SEARCH_FILE_BYTES = 1_048_576
MAX_WALK_DIRS = 5_000
MAX_SNIPPET_CHARS = 300
MAX_READ_BYTES = 65_536
MAX_READ_LINES = 200
MAX_LINE_CHARS = 400
MAX_WRITE_BYTES = 262_144
MAX_PATCH_FILE_BYTES = 1_048_576
MAX_ARTIFACTS = 200
MAX_ARTIFACT_SCAN = 20_000
MAX_HASH_BYTES = 33_554_432
MAX_COMMAND_NAME_CHARS = 64
COMMAND_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")

IGNORED_DIRS = frozenset({".git", ".hg", ".svn", ".venv", "node_modules", "__pycache__"})
RESERVED_NAMES = frozenset({
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
})


class TaskPermissions(Spec):
    """Görev bazlı okuma, yazma, komut ve dış etki izinleri."""

    readable_paths: tuple[str, ...] = ()
    writable_paths: tuple[str, ...] = ()
    commands: tuple[str, ...] = ()
    allow_network: bool = False
    allow_publish: bool = False
    local_web_targets: tuple[str, ...] = Field(default=(), max_length=16)
    command_timeout_seconds: float = Field(default=60, ge=0.1, le=3600)
    max_output_bytes: int = Field(default=65_536, ge=1024, le=1_048_576)

    @field_validator("readable_paths", "writable_paths")
    @classmethod
    def normalize_scope(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        try:
            paths = [normalize_relative_path(item) for item in value]
        except WorkspaceError as error:
            raise ValueError(str(error)) from None
        return tuple(dict.fromkeys(paths))

    @field_validator("commands")
    @classmethod
    def validate_commands(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for name in value:
            if not isinstance(name, str) or not COMMAND_NAME.fullmatch(name):
                raise ValueError(
                    "Komut izni yalnız çalıştırılabilir adı olmalıdır; yol veya kabuk metni kullanılamaz."
                )
        return tuple(dict.fromkeys(value))

    @field_validator("local_web_targets")
    @classmethod
    def validate_local_targets(cls, values):
        from ragents.web_tools import local_web_origin
        return tuple(dict.fromkeys(local_web_origin(value) for value in values))

    @model_validator(mode="after")
    def validate_scopes(self) -> "TaskPermissions":
        if self.readable_paths:
            for writable in self.writable_paths:
                if not any(_relative_within(writable, readable)
                           for readable in self.readable_paths):
                    raise ValueError("Yazılabilir dizin okunabilir kapsam içinde olmalıdır.")
        return self


class WorkspaceGrant(TaskPermissions):
    """Görevle birlikte dondurulan workspace, izinler ve korumalı yollar."""

    root: Path
    protected_paths: tuple[Path, ...] = ()

    @model_validator(mode="after")
    def validate_root(self) -> "WorkspaceGrant":
        if not self.root.is_absolute():
            raise ValueError("Workspace kökü mutlak bir yol olmalıdır.")
        if _is_unc(self.root):
            raise ValueError("UNC workspace yolu desteklenmez.")
        return self


@dataclass(frozen=True)
class ArtifactDraft:
    path: str
    size_bytes: int
    sha256: str | None


@dataclass
class ArtifactLog:
    """Yazma araçlarının açıkça kaydettiği artifact'ler."""

    drafts: list[ArtifactDraft] = field(default_factory=list)

    def record(self, draft: ArtifactDraft) -> None:
        for index, existing in enumerate(self.drafts):
            if existing.path == draft.path:
                self.drafts[index] = draft
                return
        self.drafts.append(draft)


def _is_unc(path: Path) -> bool:
    return path.drive.startswith("\\\\") or str(path).startswith(("\\\\", "//"))


def _is_link(path: Path) -> bool:
    checker = getattr(path, "is_junction", None)
    return path.is_symlink() or (checker is not None and checker())


def _reject_workspace_root_link(path: Path) -> None:
    if _is_link(path):
        raise WorkspaceError("Workspace kökü sembolik bağlantı veya junction olamaz.")


def _resolve(path: Path) -> Path:
    try:
        return path.expanduser().resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        raise WorkspaceError("Workspace yolu çözümlenemedi.") from None


def _inside(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def _validate_location(path: Path, protected_paths: tuple[Path, ...]) -> None:
    if path == Path(path.anchor):
        raise WorkspaceError("Sürücü kökü workspace olarak kullanılamaz.")
    for protected in protected_paths:
        target = _resolve(protected)
        if path == target or _inside(path, target):
            raise WorkspaceError("Workspace katalog, veri veya kimlik dizinini kapsayamaz.")
        if target.is_dir() and _inside(target, path):
            raise WorkspaceError("Workspace katalog, veri veya kimlik dizinini kapsayamaz.")


def resolve_agent_workspace(
    catalog_root: Path, agent_id: str, configured: str | None, *,
    protected_paths: tuple[Path, ...] = (), require_exists: bool = False,
) -> Path:
    """Ajanın workspace yolunu doğrula; varsayılan yolu oluşturma."""
    root = _resolve(Path(catalog_root))
    if configured is None or not configured.strip():
        configured = f"workspaces/{agent_id}"
    raw = Path(configured).expanduser()
    if _is_unc(raw):
        raise WorkspaceError("UNC workspace yolu desteklenmez.")
    if (raw.drive or raw.anchor) and not raw.is_absolute():
        raise WorkspaceError("Workspace yolu sürücüye göre değil, mutlak veya katalog köküne göre olmalıdır.")
    if ".." in raw.parts:
        raise WorkspaceError("Workspace yolu üst dizine çıkamaz.")
    path = raw if raw.is_absolute() else root / raw
    _reject_workspace_root_link(path)
    resolved = _resolve(path)
    _validate_location(resolved, protected_paths)
    if resolved.exists() and not resolved.is_dir():
        raise WorkspaceError("Workspace yolu bir dizin olmalıdır.")
    if require_exists and not resolved.is_dir():
        raise WorkspaceError("Workspace dizini mevcut olmalıdır.")
    return resolved


def _validate_relative(relative: str) -> Path:
    if not isinstance(relative, str):
        raise WorkspaceError("Dosya yolu metin olmalıdır.")
    if not relative:
        relative = "."
    if len(relative) > MAX_PATH_CHARS:
        raise WorkspaceError("Dosya yolu çok uzun.")
    if "\x00" in relative:
        raise WorkspaceError("Dosya yolu geçersiz karakter içeriyor.")
    raw = Path(relative)
    if raw.is_absolute() or raw.drive or raw.anchor:
        raise WorkspaceError("Yalnız workspace içindeki göreli yollar kullanılabilir.")
    for part in raw.parts:
        if part in ("", ".", ".."):
            if part == "..":
                raise WorkspaceError("Workspace dışına çıkan yollar reddedilir.")
            continue
        if ":" in part:
            raise WorkspaceError("Windows alternatif veri akışı yolları reddedilir.")
        if part != part.rstrip(" ."):
            raise WorkspaceError("Dosya yolunda sondaki boşluk veya nokta kullanılamaz.")
        if part.split(".")[0].upper() in RESERVED_NAMES:
            raise WorkspaceError("Windows cihaz adları dosya yolu olarak kullanılamaz.")
    return raw


def normalize_relative_path(relative: str) -> str:
    """Göreli izin yolunu POSIX biçimine getir; kaçış ve symlink metnini reddet."""
    raw = _validate_relative(relative)
    return raw.as_posix() if raw.parts else "."


def _relative_within(child: str, parent: str) -> bool:
    if parent == ".":
        return True
    child_parts = tuple(os.path.normcase(part) for part in Path(child).parts)
    parent_parts = tuple(os.path.normcase(part) for part in Path(parent).parts)
    return (len(child_parts) >= len(parent_parts)
            and child_parts[:len(parent_parts)] == parent_parts)


class Workspace:
    """Kökü sabitlenmiş, izin kapsamlı okuma ve yazma erişimi."""

    def __init__(
        self, root: Path, protected_paths: tuple[Path, ...] = (), *,
        readable_paths: tuple[str, ...] = (), writable_paths: tuple[str, ...] = (),
    ):
        original = Path(root).expanduser()
        if _is_unc(original):
            raise WorkspaceError("UNC workspace yolu desteklenmez.")
        _reject_workspace_root_link(original)
        resolved = _resolve(original)
        if not resolved.exists() or not resolved.is_dir():
            raise WorkspaceError("Workspace dizini bulunamadı.")
        _validate_location(resolved, protected_paths)
        self.root = resolved
        self.protected_paths = tuple(_resolve(path) for path in protected_paths)
        self.readable_paths = tuple(dict.fromkeys(
            normalize_relative_path(item) for item in readable_paths
        ))
        self.writable_paths = tuple(dict.fromkeys(
            normalize_relative_path(item) for item in writable_paths
        ))
        self._readable_roots = self._scope_roots(self.readable_paths) or (self.root,)
        self._writable_roots = self._scope_roots(self.writable_paths)

    def _scope_roots(self, relatives: tuple[str, ...]) -> tuple[Path, ...]:
        roots: list[Path] = []
        for relative in relatives:
            target = self._target(relative, must_exist=False, access=None)
            if not target.is_dir():
                raise WorkspaceError("İzin verilen yol mevcut bir dizin olmalıdır.")
            roots.append(target)
        return tuple(roots)

    def _target(
        self, relative: str, *, must_exist: bool = True,
        access: Literal["read", "write"] | None = None,
    ) -> Path:
        raw = _validate_relative(relative)
        current = self.root
        for part in raw.parts:
            if part in ("", "."):
                continue
            current = current / part
            if _is_link(current):
                raise WorkspaceError("Workspace içinde sembolik bağlantı veya junction kullanılamaz.")
        target = _resolve(current)
        try:
            target.relative_to(self.root)
        except ValueError:
            raise WorkspaceError("Dosya workspace dışına çıkamaz.") from None
        for protected in self.protected_paths:
            if target == protected or _inside(target, protected):
                raise WorkspaceError("Korumalı dizin veya kimlik dosyası okunamaz.")
        if access == "read":
            if not any(target == base or _inside(target, base) for base in self._readable_roots):
                raise WorkspaceError("Dosya izinli okunabilir dizinlerin dışında.")
        elif access == "write":
            if not any(target == base or _inside(target, base) for base in self._writable_roots):
                raise WorkspaceError("Dosya izinli yazılabilir dizinlerin dışında.")
        if must_exist and not target.exists():
            raise WorkspaceError("Dosya veya dizin bulunamadı.")
        return target

    @property
    def readable_roots(self) -> tuple[Path, ...]:
        return self._readable_roots

    @property
    def writable_roots(self) -> tuple[Path, ...]:
        return self._writable_roots

    def checked_path(
        self, relative: str, *, must_exist: bool = True,
        access: Literal["read", "write"] | None = "read",
    ) -> Path:
        """Workspace içindeki yolu doğrula; symlink, korumalı dizin ve kaçış reddedilir."""
        return self._target(relative, must_exist=must_exist, access=access)

    def checked_file(
        self, relative: str, *, access: Literal["read", "write"] | None = "read",
    ) -> Path:
        target = self._target(relative, access=access)
        if not target.is_file():
            raise WorkspaceError("Yol bir dosya olmalıdır.")
        return target

    def checked_directory(
        self, relative: str, *, access: Literal["read", "write"] | None = "read",
    ) -> Path:
        target = self._target(relative, access=access)
        if not target.is_dir():
            raise WorkspaceError("Yol bir dizin olmalıdır.")
        return target

    def relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def list_files(self, relative: str = ".", depth: int = 1, max_entries: int = 100) -> dict[str, Any]:
        depth = max(1, min(int(depth), MAX_LIST_DEPTH))
        max_entries = max(1, min(int(max_entries), MAX_LIST_ENTRIES))
        target = self._target(relative, access="read")
        if not target.is_dir():
            raise WorkspaceError("Listelenecek yol bir dizin olmalıdır.")
        entries: list[dict[str, Any]] = []
        queue: list[tuple[Path, int]] = [(target, 1)]
        truncated = False
        while queue and not truncated:
            directory, level = queue.pop(0)
            try:
                with os.scandir(directory) as scan:
                    children = sorted(scan, key=lambda entry: entry.name)
            except OSError:
                raise WorkspaceError("Dizin okunamadı.") from None
            for entry in children:
                path = Path(entry.path)
                if _is_link(path) or self._is_protected(path):
                    continue
                if len(entries) >= max_entries:
                    truncated = True
                    break
                try:
                    if entry.is_dir(follow_symlinks=False):
                        entries.append({"path": self.relative(path), "type": "directory"})
                        if level < depth:
                            queue.append((path, level + 1))
                    elif entry.is_file(follow_symlinks=False):
                        entries.append({
                            "path": self.relative(path), "type": "file",
                            "size": entry.stat(follow_symlinks=False).st_size,
                        })
                except OSError:
                    continue
        entries.sort(key=lambda item: item["path"])
        return {"path": self.relative(target), "entries": entries,
                "count": len(entries), "truncated": truncated}

    def _is_protected(self, path: Path) -> bool:
        target = _resolve(path)
        return any(target == protected or _inside(target, protected) for protected in self.protected_paths)

    def _walk_files(
        self, target: Path, *, limit: int, ignored_dirs: frozenset[str] = IGNORED_DIRS,
    ) -> list[Path]:
        files: list[Path] = []
        if target.is_file():
            return [target]
        queue = [target]
        walked = 0
        while queue and len(files) < limit and walked < MAX_WALK_DIRS:
            directory = queue.pop(0)
            walked += 1
            try:
                with os.scandir(directory) as scan:
                    children = sorted(scan, key=lambda entry: entry.name)
            except OSError:
                continue
            for entry in children:
                path = Path(entry.path)
                if _is_link(path) or self._is_protected(path):
                    continue
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name.lower() not in ignored_dirs:
                            queue.append(path)
                    elif entry.is_file(follow_symlinks=False):
                        files.append(path)
                        if len(files) >= limit:
                            break
                except OSError:
                    continue
        return files

    def search_text(
        self, query: str, relative: str = ".", case_sensitive: bool = False,
        max_results: int = 50,
    ) -> dict[str, Any]:
        if not isinstance(query, str) or not query.strip():
            raise WorkspaceError("Arama metni boş olamaz.")
        if len(query) > 200:
            raise WorkspaceError("Arama metni en fazla 200 karakter olabilir.")
        max_results = max(1, min(int(max_results), MAX_SEARCH_RESULTS))
        target = self._target(relative, access="read")
        if not target.exists():
            raise WorkspaceError("Aranacak dosya veya dizin bulunamadı.")
        files = self._walk_files(target, limit=MAX_SEARCH_FILES)
        truncated = len(files) >= MAX_SEARCH_FILES
        needle = query if case_sensitive else query.casefold()
        matches: list[dict[str, Any]] = []
        scanned = 0
        for path in files:
            if len(matches) >= max_results:
                truncated = True
                break
            try:
                size = path.stat().st_size
                if size > MAX_SEARCH_FILE_BYTES:
                    continue
                with path.open("rb") as stream:
                    raw = stream.read(MAX_SEARCH_FILE_BYTES + 1)
            except OSError:
                continue
            if b"\x00" in raw:
                continue
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                continue
            scanned += 1
            for line_number, line in enumerate(text.splitlines(), 1):
                haystack = line if case_sensitive else line.casefold()
                if needle not in haystack:
                    continue
                snippet = line.strip()
                if len(snippet) > MAX_SNIPPET_CHARS:
                    snippet = snippet[:MAX_SNIPPET_CHARS] + "…"
                matches.append({
                    "path": self.relative(path), "line": line_number, "text": snippet,
                })
                if len(matches) >= max_results:
                    truncated = True
                    break
        return {"query": query, "path": self.relative(target), "matches": matches,
                "count": len(matches), "files_scanned": scanned, "truncated": truncated}

    def read_file(self, relative: str, start_line: int = 1, max_lines: int = 200) -> dict[str, Any]:
        target = self._target(relative, access="read")
        if not target.is_file():
            raise WorkspaceError("Okunacak yol bir dosya olmalıdır.")
        start_line = max(1, int(start_line))
        max_lines = max(1, min(int(max_lines), MAX_READ_LINES))
        try:
            size = target.stat().st_size
            with target.open("rb") as stream:
                scanned = 0
                for _ in range(start_line - 1):
                    skipped = stream.readline(MAX_HASH_BYTES - scanned + 1)
                    scanned += len(skipped)
                    if scanned > MAX_HASH_BYTES:
                        raise WorkspaceError("İstenen satır dosya tarama sınırını aşıyor.")
                    if b"\x00" in skipped:
                        raise WorkspaceError("İkili dosyalar metin olarak okunamaz.")
                    if not skipped:
                        break
                raw = stream.read(MAX_READ_BYTES + 1)
        except OSError:
            raise WorkspaceError("Dosya okunamadı.") from None
        if b"\x00" in raw:
            raise WorkspaceError("İkili dosyalar metin olarak okunamaz.")
        byte_truncated = len(raw) > MAX_READ_BYTES
        raw = raw[:MAX_READ_BYTES]
        decoder = codecs.getincrementaldecoder("utf-8")("strict")
        try:
            text = decoder.decode(raw, final=not byte_truncated)
        except UnicodeDecodeError:
            raise WorkspaceError("Dosya UTF-8 metin olmalıdır.") from None
        lines = text.splitlines()
        selected = lines[:max_lines]
        content = "\n".join(line[:MAX_LINE_CHARS] for line in selected)
        line_truncated = len(selected) < len(lines)
        clipped = any(len(line) > MAX_LINE_CHARS for line in selected)
        return {
            "path": self.relative(target),
            "start_line": start_line,
            "end_line": start_line + len(selected) - 1 if selected else start_line - 1,
            "content": content,
            "truncated": byte_truncated or line_truncated or clipped,
            "total_bytes": size,
        }

    def write_file(self, relative: str, content: str, *, overwrite: bool = False) -> dict[str, Any]:
        """İzinli dizin içinde UTF-8 dosya oluştur veya açık izinle değiştir."""
        if not isinstance(content, str):
            raise WorkspaceError("Dosya içeriği metin olmalıdır.")
        data = content.encode("utf-8")
        if len(data) > MAX_WRITE_BYTES:
            raise WorkspaceError("Dosya içeriği izin verilen boyutu aşıyor.")
        target = self._target(relative, must_exist=False, access="write")
        existed = target.exists()
        if existed:
            if not target.is_file():
                raise WorkspaceError("Yazılacak yol bir dosya olmalıdır.")
            if not overwrite:
                raise WorkspaceError("Dosya zaten var; değiştirmek için overwrite=true kullanın.")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise WorkspaceError("Dosya dizini oluşturulamadı.") from None
        target = self._target(relative, must_exist=False, access="write")
        if target.exists() and not existed and not overwrite:
            raise WorkspaceError("Dosya bu sırada oluştu; overwrite=true olmadan değiştirilemez.")
        self._atomic_write(target, data)
        return {
            "path": self.relative(target), "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(), "created": not existed,
        }

    def apply_patch(
        self, relative: str, old_text: str, new_text: str, *,
        replace_all: bool = False, expected_sha256: str | None = None,
    ) -> dict[str, Any]:
        """Tek eşleşmeli metin yaması uygula; isteğe bağlı ön hash doğrula."""
        if not isinstance(old_text, str) or not old_text:
            raise WorkspaceError("Yama için aranacak metin boş olamaz.")
        if not isinstance(new_text, str):
            raise WorkspaceError("Yeni metin bir metin olmalıdır.")
        target = self._target(relative, must_exist=True, access="write")
        if not target.is_file():
            raise WorkspaceError("Yama uygulanacak yol bir dosya olmalıdır.")
        try:
            size = target.stat().st_size
            if size > MAX_PATCH_FILE_BYTES:
                raise WorkspaceError("Dosya yama için çok büyük.")
            raw = target.read_bytes()
        except OSError:
            raise WorkspaceError("Dosya okunamadı.") from None
        if b"\x00" in raw:
            raise WorkspaceError("İkili dosyalara metin yaması uygulanamaz.")
        digest = hashlib.sha256(raw).hexdigest()
        if expected_sha256 is not None and expected_sha256 != digest:
            raise WorkspaceError("Dosya beklenen sürümle eşleşmiyor; yeniden okuyup yamayı yenileyin.")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise WorkspaceError("Dosya UTF-8 metin olmalıdır.") from None
        matches = text.count(old_text)
        normalized = False
        if matches == 0:
            normalized_text = text.replace("\r\n", "\n").replace("\r", "\n")
            normalized_old = old_text.replace("\r\n", "\n").replace("\r", "\n")
            normalized_matches = normalized_text.count(normalized_old)
            if normalized_matches:
                text = normalized_text
                old_text = normalized_old
                new_text = new_text.replace("\r\n", "\n").replace("\r", "\n")
                matches = normalized_matches
                normalized = True
        if matches == 0:
            raise WorkspaceError("Yama aranan metni dosyada bulamadı.")
        if matches > 1 and not replace_all:
            raise WorkspaceError("Yama metni dosyada birden çok kez geçiyor; daha özgül bir yama kullanın.")
        updated_text = text.replace(old_text, new_text, -1 if replace_all else 1)
        data = updated_text.encode("utf-8")
        if len(data) > MAX_WRITE_BYTES:
            raise WorkspaceError("Yama sonucu izin verilen dosya boyutunu aşıyor.")
        self._atomic_write(target, data)
        return {
            "path": self.relative(target), "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(), "replacements": matches,
            "normalized_newlines": normalized,
        }

    def artifact_draft(self, relative: str) -> ArtifactDraft:
        target = self._target(relative, access=None)
        if not target.is_file():
            raise WorkspaceError("Artifact yolu bir dosya olmalıdır.")
        try:
            size = target.stat().st_size
            digest = _sha256(target) if size <= MAX_HASH_BYTES else None
        except OSError:
            raise WorkspaceError("Artifact dosyası okunamadı.") from None
        return ArtifactDraft(path=self.relative(target), size_bytes=size, sha256=digest)

    @staticmethod
    def _atomic_write(target: Path, data: bytes) -> None:
        temporary: str | None = None
        try:
            descriptor, temporary = tempfile.mkstemp(prefix=".ragents-", dir=target.parent)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            temporary = None
        except OSError:
            raise WorkspaceError("Dosya yazılamadı.") from None
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass

    def snapshot(self, limit: int = MAX_ARTIFACT_SCAN) -> dict[str, tuple[int, int]]:
        result: dict[str, tuple[int, int]] = {}
        for path in self._walk_files(self.root, limit=limit):
            try:
                stat = path.stat()
            except OSError:
                continue
            result[self.relative(path)] = (stat.st_size, stat.st_mtime_ns)
        return result

    def collect_artifacts(self, before: dict[str, tuple[int, int]]) -> tuple[ArtifactDraft, ...]:
        after = self.snapshot()
        changed = [
            path for path, fingerprint in after.items()
            if before.get(path) != fingerprint
        ]
        drafts: list[ArtifactDraft] = []
        for relative in sorted(changed)[:MAX_ARTIFACTS]:
            path = self._target(relative)
            try:
                size = path.stat().st_size
                digest = _sha256(path) if size <= MAX_HASH_BYTES else None
            except OSError:
                continue
            drafts.append(ArtifactDraft(path=relative, size_bytes=size, sha256=digest))
        return tuple(drafts)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
