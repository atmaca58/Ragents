from pathlib import Path
import zipfile
import pytest

from ragents.distribution import source_package
from ragents.storage import TaskStateError


def test_source_distribution_uses_allowlist_and_excludes_personal_state(tmp_path):
    root = tmp_path / "source"
    (root / "src/ragents").mkdir(parents=True)
    (root / "src/ragents/__init__.py").write_text("# product", encoding="utf-8")
    (root / "LICENSE").write_text("license", encoding="utf-8")
    (root / "data").mkdir()
    (root / "data/agents.db").write_bytes(b"private")
    (root / "agents").mkdir()
    (root / "agents/personal.yaml").write_text("private", encoding="utf-8")
    output = source_package(root, tmp_path / "source.zip")
    with zipfile.ZipFile(output) as archive:
        assert "src/ragents/__init__.py" in archive.namelist()
        assert not any(name.startswith(("data/", "agents/")) for name in archive.namelist())
