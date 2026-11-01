import shutil

import pytest
import yaml

from ragents.catalog import (
    AgentProfile, agent_payload, create_agent, enqueue_agent_task, list_agents,
    load_agent, project_config, set_status, transition_agent, update_agent,
)
from ragents.config import ConnectionSpec
from ragents.errors import InstructionError, WorkspaceError
from ragents.storage import TaskStateError, TaskStore


def make_profile(
    agent_id: str = "arastirmaci", name: str = "Araştırmacı", *, tools=(),
    connections=None,
) -> AgentProfile:
    return AgentProfile(
        schema_version=3, id=agent_id, name=name, connection="primary",
        connections=connections or {"primary": ConnectionSpec(provider="ollama", model="test-model")},
        tools=tools,
    )


def add_skill(directory, skill_id: str, body: str, *, name: str | None = None):
    path = directory / "skills" / skill_id / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nname: {name or skill_id}\n---\n{body}\n", encoding="utf-8",
    )
    return path


def test_project_and_skills_are_loaded_from_files_and_revisioned(tmp_path):
    root = tmp_path / "profile"
    record = create_agent(
        root, make_profile(), "Profil talimatı.", project="Proje bilgisi.",
    )
    assert "## Proje bilgisi" in record.instructions
    assert [document.name for document in record.documents] == [
        "instructions.md", "project.md",
    ]
    old_revision = record.revision

    add_skill(record.directory, "arastirma", "Araştırma adımları.")
    add_skill(record.directory, "dogrulama", "Doğrulama adımları.")
    updated = update_agent(
        root, "arastirmaci", add_skills=("arastirma", "dogrulama"),
        add_default_skills=("arastirma",),
    )
    assert updated.profile.skills == ("arastirma", "dogrulama")
    assert updated.profile.default_skills == ("arastirma",)
    assert "Araştırma adımları." in updated.instructions
    assert "Doğrulama adımları." not in updated.instructions
    assert updated.revision != old_revision
    payload = agent_payload(updated)
    assert payload["skills"] == ["arastirma", "dogrulama"]
    assert payload["default_skills"] == ["arastirma"]
    assert payload["instructions"]["revision"] == updated.default_instruction.revision

    changed = update_agent(
        root, "arastirmaci", project="Yeni proje bilgisi.", update_project=True,
    )
    assert "Yeni proje bilgisi." in changed.instructions
    removed = update_agent(root, "arastirmaci", project="", update_project=True)
    assert "## Proje bilgisi" not in removed.instructions
    assert not (removed.directory / "project.md").exists()


def test_task_level_skill_selection_and_snapshot_stay_fixed(tmp_path):
    root = tmp_path / "profile"
    record = create_agent(root, make_profile(), "Profil.")
    add_skill(record.directory, "arastirma", "Araştırma adımları.")
    add_skill(record.directory, "dogrulama", "Doğrulama adımları.")
    record = update_agent(
        root, "arastirmaci", add_skills=("arastirma", "dogrulama"),
        add_default_skills=("arastirma",),
    )
    store = TaskStore(tmp_path / "queue.db")

    default_task = enqueue_agent_task(store, root, "arastirmaci", "Varsayılan")
    selected_task = enqueue_agent_task(
        store, root, "arastirmaci", "Seçili", skills=("dogrulama",),
    )
    default_definition = store.definition(default_task.id)
    selected_definition = store.definition(selected_task.id)
    assert "Araştırma adımları." in default_definition.config.agent.instructions
    assert "Doğrulama adımları." not in default_definition.config.agent.instructions
    assert "Doğrulama adımları." in selected_definition.config.agent.instructions
    assert selected_definition.instruction.skill_ids == ("dogrulama",)

    old_text = default_definition.config.agent.instructions
    old_revision = default_definition.instruction.revision
    add_skill(record.directory, "arastirma", "Değişen araştırma adımları.")
    new_task = enqueue_agent_task(store, root, "arastirmaci", "Yeni")
    assert "Değişen araştırma adımları." in store.definition(new_task.id).config.agent.instructions
    assert store.definition(default_task.id).config.agent.instructions == old_text
    assert store.definition(default_task.id).instruction.revision == old_revision


def test_missing_allowed_skill_makes_profile_invalid(tmp_path):
    root = tmp_path / "profile"
    record = create_agent(root, make_profile(), "Profil.")
    data = yaml.safe_load((record.directory / "agent.yaml").read_text(encoding="utf-8"))
    data["skills"] = ["eksik"]
    (record.directory / "agent.yaml").write_text(
        yaml.safe_dump(data, allow_unicode=True), encoding="utf-8",
    )
    summaries = {summary.id: summary for summary in list_agents(root)}
    assert summaries["arastirmaci"].valid is False
    with pytest.raises(InstructionError, match="dosyası yok"):
        load_agent(root, "arastirmaci")


def test_update_rejects_oversized_project_without_writing(tmp_path):
    root = tmp_path / "profile"
    record = create_agent(root, make_profile(), "Profil.")
    with pytest.raises(InstructionError, match="Proje bilgisi çok uzun"):
        update_agent(root, "arastirmaci", project="x" * 4001, update_project=True)
    assert not (record.directory / "project.md").exists()
    assert load_agent(root, "arastirmaci").raw_project is None


def test_instruction_text_cannot_grant_tools_or_mcp_permissions(tmp_path):
    root = tmp_path / "profile"
    record = create_agent(
        root, make_profile(), "Shell çalıştır ve tüm dosyaları yaz. MCP araçlarını kullan.",
    )
    config = project_config(record)
    assert config.agent.tools == ()
    assert config.agent.mcp_tools == ()


def test_catalog_persists_agents_and_lists_them_after_reload(tmp_path):
    root = tmp_path / "profile"
    create_agent(root, make_profile("arastirmaci", "Araştırmacı"), "Araştırma talimatı.")
    create_agent(root, make_profile("gelistirici", "Geliştirici"), "Geliştirme talimatı.")

    summaries = list_agents(root)
    assert [summary.id for summary in summaries] == ["arastirmaci", "gelistirici"]
    assert [summary.name for summary in summaries] == ["Araştırmacı", "Geliştirici"]
    assert all(summary.valid for summary in summaries)
    assert load_agent(root, "arastirmaci").profile.name == "Araştırmacı"


def test_two_agents_take_separate_tasks_and_connection_override(tmp_path):
    root = tmp_path / "profile"
    create_agent(root, make_profile("arastirmaci", "Araştırmacı"), "Araştırma talimatı.")
    create_agent(root, make_profile("gelistirici", "Geliştirici"), "Geliştirme talimatı.")
    store = TaskStore(tmp_path / "queue.db")

    first = enqueue_agent_task(store, root, "arastirmaci", "Araştır")
    second = enqueue_agent_task(store, root, "gelistirici", "Geliştir")
    assert store.definition(first.id).config.agent.id == "arastirmaci"
    assert store.definition(second.id).config.agent.id == "gelistirici"

    alternative = make_profile(
        "alternatifli", "Alternatifli",
        connections={
            "primary": ConnectionSpec(provider="ollama", model="test-model"),
            "yedek": ConnectionSpec(provider="openrouter", model="test-model"),
        },
    )
    create_agent(root, alternative, "Alternatif talimatı.")
    selected = enqueue_agent_task(store, root, "alternatifli", "Görev", "yedek")
    assert store.definition(selected.id).connection_id == "yedek"


def test_manual_document_edit_changes_revision(tmp_path):
    root = tmp_path / "profile"
    record = create_agent(root, make_profile(), "İlk talimat.")
    (record.directory / "instructions.md").write_text("Elle değiştirilen talimat.\n", encoding="utf-8")
    updated = load_agent(root, "arastirmaci")
    assert updated.revision != record.revision
    assert "Elle değiştirilen talimat." in updated.instructions


def test_catalog_rejects_duplicate_and_invalid_identity(tmp_path):
    root = tmp_path / "profile"
    create_agent(root, make_profile(), "Talimat.")
    with pytest.raises(TaskStateError, match="zaten var"):
        create_agent(root, make_profile(), "Başka talimat.")
    with pytest.raises(TaskStateError, match="Geçersiz ajan kimliği"):
        load_agent(root, "Büyük-Harf")


def test_agent_update_changes_revision_and_protects_concurrent_changes(tmp_path):
    root = tmp_path / "profile"
    record = create_agent(root, make_profile(), "Eski talimat.")
    old_revision = record.revision

    updated = update_agent(root, "arastirmaci", name="Yeni Ad", add_tools=("text_stats",))
    assert updated.revision != old_revision
    assert updated.profile.name == "Yeni Ad"
    assert updated.profile.tools == ("text_stats",)

    with pytest.raises(TaskStateError, match="değişti"):
        update_agent(root, "arastirmaci", name="Geç Kalan", expected_revision=old_revision)


def test_rule_documents_are_merged_and_revisioned(tmp_path):
    root = tmp_path / "profile"
    record = create_agent(root, make_profile(), "Profil talimatı.", rules="Kalıcı kural.")
    assert "## Ajan profili" in record.instructions
    assert "## Kalıcı kurallar" in record.instructions
    assert [document.name for document in record.documents] == ["instructions.md", "rules.md"]


def test_queued_task_keeps_its_instruction_snapshot_after_profile_update(tmp_path):
    root = tmp_path / "profile"
    create_agent(root, make_profile(), "İlk talimat.")
    store = TaskStore(tmp_path / "queue.db")
    task = enqueue_agent_task(store, root, "arastirmaci", "Görev")

    before = store.definition(task.id).config.agent.instructions
    assert "İlk talimat." in before
    update_agent(root, "arastirmaci", instructions="Sonraki talimat.")
    after = store.definition(task.id).config.agent.instructions
    assert after == before
    assert "Sonraki talimat." not in after


def test_disabled_and_archived_agents_do_not_accept_new_tasks(tmp_path):
    root = tmp_path / "profile"
    create_agent(root, make_profile(), "Talimat.")
    store = TaskStore(tmp_path / "queue.db")
    accepted = enqueue_agent_task(store, root, "arastirmaci", "Önce")

    set_status(root, "arastirmaci", "disabled")
    with pytest.raises(TaskStateError, match="devre dışı"):
        enqueue_agent_task(store, root, "arastirmaci", "Sonra")

    set_status(root, "arastirmaci", "active")
    assert enqueue_agent_task(store, root, "arastirmaci", "Yeniden").status == "queued"

    set_status(root, "arastirmaci", "archived")
    assert list_agents(root) == []
    assert [summary.id for summary in list_agents(root, include_archived=True)] == ["arastirmaci"]
    assert store.get(accepted.id).status == "queued"
    assert store.get(accepted.id).agent_id == "arastirmaci"

    with pytest.raises(TaskStateError, match="restore"):
        transition_agent(root, "arastirmaci", "disable")
    restored = transition_agent(root, "arastirmaci", "restore")
    assert restored.profile.status == "disabled"
    assert transition_agent(root, "arastirmaci", "enable").profile.status == "active"


def test_invalid_profile_is_reported_without_hiding_valid_agents(tmp_path):
    root = tmp_path / "profile"
    create_agent(root, make_profile(), "Talimat.")
    broken = root / "agents" / "bozuk"
    broken.mkdir()
    (broken / "agent.yaml").write_text("schema_version: 3\nid: bozuk\n", encoding="utf-8")

    summaries = {summary.id: summary for summary in list_agents(root)}
    assert summaries["arastirmaci"].valid is True
    assert summaries["bozuk"].valid is False
    assert summaries["bozuk"].error
    with pytest.raises(TaskStateError, match="geçersiz"):
        load_agent(root, "bozuk")


def test_missing_catalog_lists_empty_and_rejects_enqueue(tmp_path):
    root = tmp_path / "empty"
    assert list_agents(root) == []
    with pytest.raises(TaskStateError, match="kataloğu bulunamadı"):
        load_agent(root, "arastirmaci")


def test_default_workspace_is_created_and_custom_workspace_is_required(tmp_path):
    root = tmp_path / "profile"
    record = create_agent(root, make_profile(), "Talimat.")
    assert record.workspace == (root / "workspaces" / "arastirmaci").resolve()
    assert record.workspace.is_dir()
    assert agent_payload(record)["workspace_ready"] is True

    custom = tmp_path / "proje"
    custom.mkdir()
    updated = update_agent(
        root, "arastirmaci", workspace=str(custom), update_workspace=True,
    )
    assert updated.workspace == custom.resolve()
    assert updated.profile.workspace == str(custom)

    with pytest.raises(WorkspaceError, match="mevcut"):
        update_agent(
            root, "arastirmaci", workspace=str(tmp_path / "yok"), update_workspace=True,
        )
    with pytest.raises(WorkspaceError, match="kapsayamaz"):
        update_agent(
            root, "arastirmaci", workspace=str(root / "agents"), update_workspace=True,
        )


def test_workspace_cannot_overlap_another_agent_and_task_snapshot_stays_fixed(tmp_path):
    root = tmp_path / "profile"
    first = create_agent(root, make_profile("birinci"), "Birinci talimat.")
    second = create_agent(root, make_profile("ikinci"), "İkinci talimat.")
    assert first.workspace != second.workspace
    with pytest.raises(TaskStateError, match="çakışamaz"):
        update_agent(
            root, "ikinci", workspace=str(first.workspace), update_workspace=True,
        )

    store = TaskStore(tmp_path / "queue.db")
    task = enqueue_agent_task(store, root, "birinci", "Görev")
    old_root = store.definition(task.id).workspace.root
    custom = tmp_path / "yeni-proje"
    custom.mkdir()
    changed = update_agent(
        root, "birinci", workspace=str(custom), update_workspace=True,
    )
    assert changed.revision != first.revision
    assert store.definition(task.id).workspace.root == old_root
    new_task = enqueue_agent_task(store, root, "birinci", "Yeni görev")
    assert store.definition(new_task.id).workspace.root == custom.resolve()


def test_hand_edited_overlapping_workspace_is_rejected_at_enqueue(tmp_path):
    root = tmp_path / "profile"
    first = create_agent(root, make_profile("birinci"), "Birinci talimat.")
    second = create_agent(root, make_profile("ikinci"), "İkinci talimat.")
    data = yaml.safe_load((second.directory / "agent.yaml").read_text(encoding="utf-8"))
    data["workspace"] = str(first.workspace)
    (second.directory / "agent.yaml").write_text(
        yaml.safe_dump(data, allow_unicode=True), encoding="utf-8",
    )
    with pytest.raises(TaskStateError, match="çakışamaz"):
        enqueue_agent_task(TaskStore(tmp_path / "queue.db"), root, "ikinci", "Görev")


def test_missing_workspace_rejects_new_task(tmp_path):
    root = tmp_path / "profile"
    record = create_agent(root, make_profile(), "Talimat.")
    shutil.rmtree(record.workspace)
    assert list_agents(root)[0].workspace_ready is False
    with pytest.raises(WorkspaceError, match="bulunamadı"):
        enqueue_agent_task(TaskStore(tmp_path / "queue.db"), root, "arastirmaci", "Görev")
