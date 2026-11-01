import json
from contextlib import asynccontextmanager

from pydantic_ai.models.test import TestModel

from ragents import application
from ragents.catalog import load_agent
from ragents.cli import main
from ragents.engines.native import NativeEngine
from ragents.storage import TaskStore


def run_json(capsys, *args):
    assert main(list(args)) == 0
    return json.loads(capsys.readouterr().out)


def test_cli_creates_lists_updates_and_revisions_agent_without_model(tmp_path, capsys):
    root = tmp_path / "profile"
    base = ["agents", "--root", str(root)]
    created = run_json(
        capsys, *base, "create", "--id", "arastirmaci", "--name", "Araştırmacı",
        "--provider", "ollama", "--model", "test-model", "--instructions", "İlk talimat.",
    )
    assert created["agent"]["id"] == "arastirmaci"
    revision = created["agent"]["revision"]

    listed = run_json(capsys, *base, "list")
    assert [agent["id"] for agent in listed["agents"]] == ["arastirmaci"]

    shown = run_json(capsys, *base, "show", "arastirmaci")
    assert shown["agent"]["instructions"]["documents"][0]["name"] == "instructions.md"

    updated = run_json(
        capsys, *base, "update", "arastirmaci", "--name", "Yeni Ad",
        "--if-revision", revision,
    )
    assert updated["agent"]["name"] == "Yeni Ad"
    assert updated["agent"]["revision"] != revision


def test_cli_imports_existing_config_and_queues_task_without_model(tmp_path, capsys):
    root = tmp_path / "profile"
    created = run_json(capsys, "agents", "--root", str(root), "create", "--from-config", "examples/ollama.yaml")
    assert created["agent"]["id"] == "ornek-ajan"
    assert created["agent"]["connection"] == "local"

    database = tmp_path / "ragents.db"
    queued = run_json(
        capsys, "tasks", "--db", str(database), "--root", str(root),
        "add", "--agent", "ornek-ajan", "--key", "katalog-1", "Görev",
    )
    assert queued["task"]["status"] == "queued"
    definition = TaskStore(database).definition(queued["task"]["id"])
    assert "Türkçe yanıt ver" in definition.config.agent.instructions
    assert definition.config.agent.id == "ornek-ajan"


def test_cli_agent_task_uses_profile_database_when_db_is_not_given(tmp_path, capsys):
    root = tmp_path / "profile"
    run_json(capsys, "agents", "--root", str(root), "create",
             "--id", "arastirmaci", "--name", "Araştırmacı",
             "--provider", "ollama", "--model", "test-model")
    queued = run_json(capsys, "tasks", "--root", str(root),
                      "add", "--agent", "arastirmaci", "Görev")
    database = root / "data" / "ragents.db"
    assert database.is_file()
    assert TaskStore(database).get(queued["task"]["id"]).status == "queued"
    listed = run_json(capsys, "tasks", "--root", str(root), "list")
    assert listed["tasks"][0]["id"] == queued["task"]["id"]


def test_cli_project_skill_flags_and_task_skill_snapshot(tmp_path, capsys):
    root = tmp_path / "profile"
    base = ["agents", "--root", str(root)]
    run_json(capsys, *base, "create", "--id", "arastirmaci", "--name", "Araştırmacı",
             "--provider", "ollama", "--model", "test-model", "--project", "Proje bilgisi.")
    skill = root / "agents" / "arastirmaci" / "skills" / "arastirma" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: Araştırma\n---\nAraştırma adımları.\n", encoding="utf-8")

    updated = run_json(capsys, *base, "update", "arastirmaci",
                       "--add-skill", "arastirma", "--add-default-skill", "arastirma")
    assert updated["agent"]["skills"] == ["arastirma"]
    assert updated["agent"]["default_skills"] == ["arastirma"]
    assert updated["agent"]["instructions"]["documents"][1]["name"] == "project.md"

    queued = run_json(capsys, "tasks", "--root", str(root), "add", "--agent", "arastirmaci",
                      "--skill", "arastirma", "Görev")
    shown = run_json(capsys, "tasks", "--root", str(root), "show", queued["task"]["id"])
    assert shown["instruction"]["skill_ids"] == ["arastirma"]
    assert shown["instruction"]["total_chars"] > 0
    assert shown["workspace"]["root"] == str((root / "workspaces" / "arastirmaci").resolve())


def test_cli_unknown_skill_is_rejected_with_exit_code_two(tmp_path, capsys):
    root = tmp_path / "profile"
    run_json(capsys, "agents", "--root", str(root), "create", "--id", "arastirmaci",
             "--name", "Araştırmacı", "--provider", "ollama", "--model", "test-model")
    capsys.readouterr()
    code = main(["tasks", "--root", str(root), "add", "--agent", "arastirmaci",
                 "--skill", "yok", "Görev"])
    captured = capsys.readouterr()
    assert code == 2
    assert "izinli değil" in captured.err


def test_cli_workspace_and_workspace_tool_flags(tmp_path, capsys):
    root = tmp_path / "profile"
    custom = tmp_path / "proje"
    custom.mkdir()
    created = run_json(
        capsys, "agents", "--root", str(root), "create", "--id", "arastirmaci",
        "--name", "Araştırmacı", "--provider", "ollama", "--model", "test-model",
        "--workspace", str(custom), "--tool", "read_file", "--tool", "list_files",
    )
    assert created["agent"]["workspace"] == str(custom.resolve())
    assert created["agent"]["workspace_ready"] is True
    assert created["agent"]["tools"] == ["read_file", "list_files"]

    updated = run_json(
        capsys, "agents", "--root", str(root), "update", "arastirmaci",
        "--default-workspace",
    )
    assert updated["agent"]["workspace"] == str((root / "workspaces" / "arastirmaci").resolve())
    assert (root / "workspaces" / "arastirmaci").is_dir()


def test_cli_missing_custom_workspace_is_rejected(tmp_path, capsys):
    code = main([
        "agents", "--root", str(tmp_path / "profile"), "create", "--id", "arastirmaci",
        "--name", "Araştırmacı", "--provider", "ollama", "--model", "test-model",
        "--workspace", str(tmp_path / "yok"),
    ])
    captured = capsys.readouterr()
    assert code == 2
    assert "mevcut" in captured.err


def test_cli_skill_with_config_is_rejected(tmp_path, capsys):
    code = main(["tasks", "--root", str(tmp_path / "profile"), "add",
                 "--config", "examples/ollama.yaml", "--skill", "arastirma", "Görev"])
    captured = capsys.readouterr()
    assert code == 2
    assert "--skill yalnız --agent" in captured.err


def test_cli_disabled_agent_is_rejected_with_exit_code_two(tmp_path, capsys):
    root = tmp_path / "profile"
    base = ["agents", "--root", str(root)]
    run_json(capsys, *base, "create", "--id", "arastirmaci", "--name", "Araştırmacı",
             "--provider", "ollama", "--model", "test-model")
    run_json(capsys, *base, "disable", "arastirmaci")
    capsys.readouterr()

    code = main(["tasks", "--db", str(tmp_path / "ragents.db"), "--root", str(root),
                 "add", "--agent", "arastirmaci", "Görev"])
    captured = capsys.readouterr()
    assert code == 2
    assert "yeni görev alamaz" in captured.err


def test_cli_archived_agent_is_hidden_unless_all_is_requested(tmp_path, capsys):
    root = tmp_path / "profile"
    base = ["agents", "--root", str(root)]
    run_json(capsys, *base, "create", "--id", "arastirmaci", "--name", "Araştırmacı",
             "--provider", "ollama", "--model", "test-model")
    run_json(capsys, *base, "archive", "arastirmaci")

    assert run_json(capsys, *base, "list")["agents"] == []
    archived = run_json(capsys, *base, "list", "--all")["agents"]
    assert [agent["status"] for agent in archived] == ["archived"]

    restored = run_json(capsys, *base, "restore", "arastirmaci")
    assert restored["agent"]["status"] == "disabled"
    enabled = run_json(capsys, *base, "enable", "arastirmaci")
    assert enabled["agent"]["status"] == "active"


def test_cli_create_rejects_ambiguous_source_flags(tmp_path, capsys):
    code = main(["agents", "--root", str(tmp_path / "profile"), "create",
                 "--from-config", "examples/ollama.yaml", "--provider", "ollama"])
    captured = capsys.readouterr()
    assert code == 2
    assert "birlikte kullanılamaz" in captured.err


def test_cli_update_can_replace_the_default_connection_spec(tmp_path, capsys):
    root = tmp_path / "profile"
    base = ["agents", "--root", str(root)]
    run_json(capsys, *base, "create", "--id", "arastirmaci", "--name", "Araştırmacı",
             "--provider", "ollama", "--model", "eski-model")
    updated = run_json(capsys, *base, "update", "arastirmaci",
                       "--provider", "ollama", "--model", "yeni-model")
    assert updated["agent"]["connection"] == "primary"
    connection = load_agent(root, "arastirmaci").profile.connections["primary"]
    assert connection.model == "yeni-model"


def test_cli_update_rejects_stale_revision(tmp_path, capsys):
    root = tmp_path / "profile"
    base = ["agents", "--root", str(root)]
    run_json(capsys, *base, "create", "--id", "arastirmaci", "--name", "Araştırmacı",
             "--provider", "ollama", "--model", "test-model")
    capsys.readouterr()

    code = main([*base, "update", "arastirmaci", "--name", "Geç", "--if-revision", "0" * 64])
    captured = capsys.readouterr()
    assert code == 2
    assert "değişti" in captured.err


def test_cli_run_with_catalog_agent_uses_snapshot_and_fake_engine(tmp_path, capsys, monkeypatch):
    root = tmp_path / "profile"
    base = ["agents", "--root", str(root)]
    run_json(capsys, *base, "create", "--id", "arastirmaci", "--name", "Araştırmacı",
             "--provider", "ollama", "--model", "test-model", "--instructions", "Katalog talimatı.")

    calls = []

    @asynccontextmanager
    async def open_test_engine(connection):
        calls.append(connection.model)
        yield NativeEngine(TestModel(custom_output_text="Katalog yanıtı"))

    monkeypatch.setattr(application, "open_engine", open_test_engine)
    database = tmp_path / "ragents.db"
    payload = run_json(capsys, "run", "--db", str(database), "--root", str(root),
                       "--agent", "arastirmaci", "--key", "katalog-run", "Görev")
    assert payload["result"]["output"] == "Katalog yanıtı"
    assert calls == ["test-model"]
    assert TaskStore(database).get(payload["task_id"]).status == "succeeded"
