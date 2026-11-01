"""Kişisel durumu dışlayan kaynak allowlist'i, checksum ve lisans envanteri."""
import hashlib
from importlib.metadata import distributions
import json
from pathlib import Path
import re
import zipfile

from ragents.storage import TaskStateError


SOURCE_DIRECTORIES = frozenset({"src", "tests", "docs", "scripts", "examples", "packaging", ".github"})
SOURCE_FILES = frozenset({"README.md", "CONTRIBUTING.md", "CHANGELOG.md", "LICENSE", "NOTICE", "pyproject.toml", "requirements-dev.lock",
                          "AGENTS.md", ".gitignore", ".gitattributes"})
BLOCKED_PARTS = frozenset({"__pycache__", ".pytest_cache", ".venv", "data", "auth", "agents", "local-profile"})


def file_hash(path):
    sha = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def source_files(root):
    root = root.resolve()
    files = []
    candidates = [root / name for name in SOURCE_FILES if (root / name).is_file()]
    for name in SOURCE_DIRECTORIES:
        candidates.extend((root / name).rglob("*"))
    for path in sorted(candidates):
        relative = path.relative_to(root)
        if relative.parts[0] not in SOURCE_DIRECTORIES and relative.as_posix() not in SOURCE_FILES:
            continue
        if any(part in BLOCKED_PARTS or part.endswith(".egg-info") for part in relative.parts):
            continue
        if path.suffix in (".pyc", ".pyo", ".db", ".zip", ".patch") or path.name.startswith(".env"):
            continue
        if path.is_symlink() or path.is_junction():
            raise TaskStateError("Dağıtım kaynaklarında bağlantılı dosya veya dizin var.")
        if path.is_file():
            files.append(path)
    return files


def source_package(root: Path, output: Path):
    root, output = root.resolve(), output.resolve()
    if output.exists():
        raise TaskStateError("Kaynak paketi için yeni çıktı dosyası seçin.")
    selected = source_files(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream, zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in selected:
            archive.write(path, path.relative_to(root).as_posix())
    return output


def license_inventory(site_packages: Path):
    packages = []
    for package in distributions(path=[str(site_packages)]):
        license_files = []
        for relative in package.files or ():
            if any("license" in part.lower() or part.lower() in ("copying", "notice") for part in relative.parts):
                path = package.locate_file(relative)
                if path.is_file():
                    license_files.append({"path": str(relative).replace("\\", "/"), "sha256": file_hash(path)})
        expression = package.metadata.get("License-Expression")
        classifiers = [value for value in package.metadata.get_all("Classifier", []) if value.startswith("License ::")]
        packages.append({"name": package.metadata["Name"], "version": package.version,
            "license_expression": expression, "license_classifiers": classifiers,
            "license_files": license_files, "declared_license": package.metadata.get("License", "")[:8000]})
    return sorted(packages, key=lambda package: package["name"].lower())


def write_package_manifest(root: Path, version: str):
    files = {path.relative_to(root).as_posix(): file_hash(path) for path in sorted(root.rglob("*")) if path.is_file()
             and path.name != "package-manifest.json"}
    manifest = {"schema_version": 1, "version": version, "platform": "windows-x64", "files": files,
                "signed": False, "accepted": False}
    (root / "package-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def verify_package(root: Path):
    manifest = json.loads((root / "package-manifest.json").read_text(encoding="utf-8"))
    for name, expected in manifest["files"].items():
        path = root / name
        if not path.resolve().is_relative_to(root.resolve()) or not path.is_file() or file_hash(path) != expected:
            raise TaskStateError("Ürün paketi dosya/hash doğrulaması başarısız.")
    return manifest
