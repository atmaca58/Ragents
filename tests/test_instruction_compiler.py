from pathlib import Path

import pytest

from ragents.errors import InstructionError
from ragents.instructions import (
    InstructionPolicy, compile_instructions, load_skill, resolve_skill_ids,
)


def make_agent_dir(tmp_path, instructions="Profil talimatı.") -> Path:
    directory = tmp_path / "agent"
    directory.mkdir()
    (directory / "instructions.md").write_text(instructions, encoding="utf-8")
    return directory


def make_skill(directory: Path, skill_id: str, body: str = "Skill gövdesi.", *, frontmatter: str | None = None):
    path = directory / "skills" / skill_id / "SKILL.md"
    path.parent.mkdir(parents=True)
    front = frontmatter if frontmatter is not None else f"---\nname: {skill_id.title()}\n---\n"
    path.write_text(front + body + "\n", encoding="utf-8")
    return path


def test_compiler_merges_profile_project_selected_skill_and_rules_in_order(tmp_path):
    directory = make_agent_dir(tmp_path)
    (directory / "project.md").write_text("Proje bilgisi.", encoding="utf-8")
    (directory / "rules.md").write_text("Kalıcı kural.", encoding="utf-8")
    make_skill(directory, "arastirma", "Araştırma adımları.")
    make_skill(directory, "dogrulama", "Doğrulama adımları.")
    policy = InstructionPolicy(
        max_chars=16000, allowed_skills=("arastirma", "dogrulama"),
        default_skills=("arastirma",),
    )

    compiled = compile_instructions(directory, policy)
    text = compiled.text
    assert text.index("## Ajan profili") < text.index("## Proje bilgisi")
    assert text.index("## Proje bilgisi") < text.index("## Seçili skill: Arastirma")
    assert text.index("## Seçili skill: Arastirma") < text.index("## Kalıcı kurallar")
    assert "Araştırma adımları." in text
    assert "Doğrulama adımları." not in text
    assert compiled.snapshot.skill_ids == ("arastirma",)
    assert [source.kind for source in compiled.snapshot.sources] == [
        "profile", "project", "skill", "rules",
    ]


def test_explicit_skill_selection_overrides_defaults_and_rejects_unknown(tmp_path):
    directory = make_agent_dir(tmp_path)
    make_skill(directory, "arastirma", "Araştırma.")
    make_skill(directory, "dogrulama", "Doğrulama.")
    policy = InstructionPolicy(
        max_chars=16000, allowed_skills=("arastirma", "dogrulama"),
        default_skills=("arastirma",),
    )

    compiled = compile_instructions(directory, policy, ("dogrulama",))
    assert compiled.snapshot.skill_ids == ("dogrulama",)
    assert "Doğrulama." in compiled.text
    assert "Araştırma." not in compiled.text

    with pytest.raises(InstructionError, match="izinli değil"):
        compile_instructions(directory, policy, ("bilinmeyen",))
    with pytest.raises(InstructionError, match="Varsayılan skill"):
        resolve_skill_ids(InstructionPolicy(16000, ("a",), ("b",)))
    assert resolve_skill_ids(policy, ("dogrulama", "dogrulama")) == ("dogrulama",)


def test_compiled_text_is_deterministic_and_revision_tracks_content(tmp_path):
    directory = make_agent_dir(tmp_path)
    policy = InstructionPolicy(max_chars=16000)
    first = compile_instructions(directory, policy)
    second = compile_instructions(directory, policy)
    assert first.text == second.text
    assert first.snapshot.revision == second.snapshot.revision

    (directory / "instructions.md").write_text("Yeni profil.", encoding="utf-8")
    changed = compile_instructions(directory, policy)
    assert changed.snapshot.revision != first.snapshot.revision
    assert "Yeni profil." in changed.text


def test_compiler_rejects_section_and_total_size_overflow(tmp_path):
    directory = make_agent_dir(tmp_path, "x" * 8001)
    with pytest.raises(InstructionError, match="Ajan profili çok uzun"):
        compile_instructions(directory, InstructionPolicy(16000))

    (directory / "instructions.md").write_text("Profil.", encoding="utf-8")
    (directory / "project.md").write_text("x" * 4001, encoding="utf-8")
    with pytest.raises(InstructionError, match="Proje bilgisi çok uzun"):
        compile_instructions(directory, InstructionPolicy(16000))

    (directory / "project.md").unlink()
    (directory / "rules.md").write_text("x" * 4001, encoding="utf-8")
    with pytest.raises(InstructionError, match="Kalıcı kurallar çok uzun"):
        compile_instructions(directory, InstructionPolicy(16000))

    (directory / "rules.md").unlink()
    make_skill(directory, "buyuk", "x" * 4001)
    with pytest.raises(InstructionError, match="Skill buyuk çok uzun"):
        compile_instructions(
            directory, InstructionPolicy(16000, ("buyuk",)), ("buyuk",),
        )

    with pytest.raises(InstructionError, match="Derlenmiş talimat çok uzun"):
        compile_instructions(directory, InstructionPolicy(16))


def test_missing_skill_and_invalid_utf8_are_rejected(tmp_path):
    directory = make_agent_dir(tmp_path)
    policy = InstructionPolicy(16000, ("eksik",), ())
    with pytest.raises(InstructionError, match="dosyası yok"):
        compile_instructions(directory, policy, ("eksik",))

    (directory / "instructions.md").write_bytes(b"\xff\xfe")
    with pytest.raises(InstructionError, match="UTF-8"):
        compile_instructions(directory, InstructionPolicy(16000))


def test_skill_frontmatter_and_body_are_validated(tmp_path):
    directory = make_agent_dir(tmp_path)
    make_skill(directory, "bozuk", "Gövde.", frontmatter="---\nbilinmeyen: alan\n---\n")
    with pytest.raises(InstructionError, match="frontmatter geçersiz"):
        load_skill(directory, "bozuk")

    make_skill(directory, "bos", "   ", frontmatter="")
    with pytest.raises(InstructionError, match="gövdesi boş"):
        load_skill(directory, "bos")

    path = make_skill(directory, "sade", "Frontmatter olmadan.", frontmatter="")
    skill = load_skill(directory, "sade")
    assert skill.name == "sade"
    assert path.exists()


def test_instruction_file_symlink_is_rejected(tmp_path):
    directory = make_agent_dir(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("Dışarıdaki talimat.", encoding="utf-8")
    target = directory / "instructions.md"
    target.unlink()
    try:
        target.symlink_to(outside)
    except OSError:
        pytest.skip("Windows sembolik bağlantı yetkisi yok.")
    with pytest.raises(InstructionError, match="sembolik bağlantı"):
        compile_instructions(directory, InstructionPolicy(16000))
