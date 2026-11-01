import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ragents.storage import TaskStateError
from ragents.uninstall import remove_client, installed_root


def test_uninstall_preserves_other_client_settings(tmp_path):
    install = tmp_path / 'app'
    path = tmp_path / 'client.json'
    path.write_text(json.dumps({'theme': 'dark', 'mcpServers': {
        'other': {'command': 'other'}, 'r_agents': {'command': str(install / 'ragents.exe'), 'args': ['mcp', 'serve']}}}))
    assert remove_client(path, 'claude', install)
    result = json.loads(path.read_text())
    assert result == {'theme': 'dark', 'mcpServers': {'other': {'command': 'other'}}}
    assert not remove_client(path, 'claude', install)


def test_uninstall_refuses_foreign_or_changed_registration(tmp_path):
    path = tmp_path / 'config.toml'
    path.write_text('[mcp_servers.r_agents]\ncommand="other"\n')
    original = path.read_bytes()
    with pytest.raises(TaskStateError):
        remove_client(path, 'codex', tmp_path / 'app')
    assert path.read_bytes() == original


def test_uninstall_does_not_delete_source_checkout(monkeypatch, tmp_path):
    monkeypatch.setattr('ragents.uninstall.sys.executable', str(tmp_path / '.venv/Scripts/python.exe'))
    with pytest.raises(TaskStateError):
        installed_root()
