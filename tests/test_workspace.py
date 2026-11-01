import os
from pathlib import Path
import subprocess

import pytest

from ragents.errors import WorkspaceError
from ragents.workspace import (
    MAX_LIST_ENTRIES, MAX_READ_BYTES, MAX_SEARCH_RESULTS, Workspace,
    resolve_agent_workspace,
)


def make_workspace(tmp_path, protected=()):
    root = tmp_path / "workspace"
    root.mkdir()
    return root, Workspace(root, tuple(protected))


def test_list_search_and_read_stay_inside_workspace(tmp_path):
    root, workspace = make_workspace(tmp_path)
    (root / "notlar").mkdir()
    (root / "notlar" / "bir.txt").write_text("Merhaba dünya\nikinci satır\n", encoding="utf-8")
    (root / "ikili.bin").write_bytes(b"metin\x00gizli")
    (root / "buyuk.txt").write_text("x" * 100, encoding="utf-8")

    listed = workspace.list_files(".", depth=2)
    assert [item["path"] for item in listed["entries"]] == [
        "buyuk.txt", "ikili.bin", "notlar", "notlar/bir.txt",
    ]
    assert listed["truncated"] is False

    found = workspace.search_text("dünya")
    assert found["matches"] == [{"path": "notlar/bir.txt", "line": 1, "text": "Merhaba dünya"}]
    assert found["files_scanned"] == 2
    assert workspace.search_text("MERHABA")["count"] == 1
    assert workspace.search_text("MERHABA", case_sensitive=True)["count"] == 0

    read = workspace.read_file("notlar/bir.txt", start_line=2, max_lines=1)
    assert read["content"] == "ikinci satır"
    assert read["truncated"] is False
    assert read["total_bytes"] > 0

    with pytest.raises(WorkspaceError, match="İkili"):
        workspace.read_file("ikili.bin")


@pytest.mark.parametrize("path", [
    "../gizli.txt",
    "notlar/../../gizli.txt",
    "C:\\Windows\\win.ini",
    "\\\\server\\share\\gizli.txt",
    "NUL",
    "CON.txt",
    "dosya.txt:stream",
    "bosluk ",
])
def test_path_escape_and_windows_special_paths_are_rejected(tmp_path, path):
    _, workspace = make_workspace(tmp_path)
    with pytest.raises(WorkspaceError):
        workspace.read_file(path)


def test_list_and_search_have_hard_limits(tmp_path):
    root, workspace = make_workspace(tmp_path)
    for index in range(MAX_LIST_ENTRIES + 5):
        (root / f"dosya-{index:03}.txt").write_text(str(index), encoding="utf-8")

    listed = workspace.list_files(".", max_entries=MAX_LIST_ENTRIES)
    assert listed["count"] == MAX_LIST_ENTRIES
    assert listed["truncated"] is True

    for index in range(MAX_SEARCH_RESULTS + 5):
        (root / f"eslesme-{index:03}.txt").write_text("aranan", encoding="utf-8")
    found = workspace.search_text("aranan", max_results=MAX_SEARCH_RESULTS)
    assert found["count"] == MAX_SEARCH_RESULTS
    assert found["truncated"] is True


def test_read_truncates_at_byte_and_line_limits(tmp_path):
    root, workspace = make_workspace(tmp_path)
    (root / "uzun.txt").write_text("a" * 500 + "\n" + "b" * 500, encoding="utf-8")
    result = workspace.read_file("uzun.txt", max_lines=1)
    assert len(result["content"]) == 400
    assert result["truncated"] is True
    assert result["total_bytes"] > 0

    (root / "tek-satir.txt").write_text("b" * 500, encoding="utf-8")
    single = workspace.read_file("tek-satir.txt")
    assert len(single["content"]) == 400
    assert single["truncated"] is True


def test_utf8_and_symlink_escape_are_rejected(tmp_path):
    root, workspace = make_workspace(tmp_path)
    (root / "bozuk.txt").write_bytes(b"\xff\xfe")
    with pytest.raises(WorkspaceError, match="UTF-8"):
        workspace.read_file("bozuk.txt")

    outside = tmp_path / "outside.txt"
    outside.write_text("dışarıdaki dosya", encoding="utf-8")
    link = root / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Windows sembolik bağlantı yetkisi yok.")
    with pytest.raises(WorkspaceError, match="sembolik"):
        workspace.read_file("link.txt")


def test_symlinked_parent_is_canonicalized_but_final_root_link_is_rejected(tmp_path):
    real = tmp_path / "real-parent"
    real.mkdir()
    (real / "workspace").mkdir()
    parent_link = tmp_path / "parent-link"
    if os.name == "nt":
        created = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(parent_link), str(real)],
            capture_output=True, text=True,
        )
        if created.returncode != 0:
            pytest.skip("Junction oluşturulamadı.")
    else:
        try:
            parent_link.symlink_to(real, target_is_directory=True)
        except OSError:
            pytest.skip("Sembolik bağlantı oluşturulamadı.")

    workspace = Workspace(parent_link / "workspace")
    assert workspace.root == (real / "workspace").resolve()
    (real / "workspace" / "ok.txt").write_text("ok", encoding="utf-8")
    assert workspace.read_file("ok.txt")["content"] == "ok"

    final_link = tmp_path / "final-link"
    if os.name == "nt":
        created = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(final_link), str(real / "workspace")],
            capture_output=True, text=True,
        )
        if created.returncode != 0:
            pytest.skip("Junction oluşturulamadı.")
    else:
        try:
            final_link.symlink_to(real / "workspace", target_is_directory=True)
        except OSError:
            pytest.skip("Sembolik bağlantı oluşturulamadı.")
    with pytest.raises(WorkspaceError, match="kökü"):
        Workspace(final_link)


@pytest.mark.skipif(os.name != "nt", reason="Windows junction testi")
def test_junction_escape_is_rejected(tmp_path):
    root, workspace = make_workspace(tmp_path)
    outside = tmp_path / "outside-dir"
    outside.mkdir()
    (outside / "gizli.txt").write_text("dışarıdaki dosya", encoding="utf-8")
    junction = root / "baglanti"
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
        capture_output=True, text=True,
    )
    if created.returncode != 0:
        pytest.skip("Junction oluşturulamadı.")
    with pytest.raises(WorkspaceError, match="sembolik"):
        workspace.read_file("baglanti/gizli.txt")


def test_workspace_cannot_contain_protected_paths(tmp_path):
    protected = tmp_path / "gizli"
    protected.mkdir()
    (protected / "token.txt").write_text("gizli", encoding="utf-8")
    with pytest.raises(WorkspaceError, match="kapsayamaz"):
        Workspace(tmp_path, (protected,))


def test_resolve_workspace_uses_default_and_validates_custom_location(tmp_path):
    catalog = tmp_path / "profile"
    agents = catalog / "agents"
    data = catalog / "data"
    agents.mkdir(parents=True)
    data.mkdir()
    protected = (agents, data, catalog / "ragents.yaml")

    default = resolve_agent_workspace(catalog, "ajan", None, protected_paths=protected)
    assert default == (catalog / "workspaces" / "ajan").resolve()
    assert not default.exists()

    custom = tmp_path / "proje"
    custom.mkdir()
    assert resolve_agent_workspace(
        catalog, "ajan", str(custom), protected_paths=protected, require_exists=True,
    ) == custom.resolve()

    with pytest.raises(WorkspaceError, match="mevcut"):
        resolve_agent_workspace(
            catalog, "ajan", str(tmp_path / "yok"), protected_paths=protected,
            require_exists=True,
        )
    with pytest.raises(WorkspaceError, match="üst dizine"):
        resolve_agent_workspace(catalog, "ajan", "../kacis", protected_paths=protected)
    with pytest.raises(WorkspaceError, match="kapsayamaz"):
        resolve_agent_workspace(catalog, "ajan", str(agents), protected_paths=protected)
    with pytest.raises(WorkspaceError, match="UNC"):
        resolve_agent_workspace(catalog, "ajan", r"\\server\share\proje", protected_paths=protected)
