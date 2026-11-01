from ragents.instructions import InstructionPolicy, compile_instructions


def test_only_relevant_or_default_skills_are_loaded_for_task(tmp_path):
    (tmp_path / "instructions.md").write_text("Görevi tamamla.", encoding="utf-8")
    for identity, keyword in (("database", "sqlite"), ("design", "renk")):
        directory = tmp_path / "skills" / identity
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text(
            f"---\nkeywords: [{keyword}]\n---\n{identity} talimatı", encoding="utf-8")
    policy = InstructionPolicy(max_chars=16000, allowed_skills=("database", "design"))
    compiled = compile_instructions(tmp_path, policy, prompt="SQLite indekslerini incele.")
    assert compiled.snapshot.skill_ids == ("database",)
    assert "database talimatı" in compiled.text
    assert "design talimatı" not in compiled.text
    explicit = compile_instructions(tmp_path, policy, ("design",), prompt="SQLite")
    assert explicit.snapshot.skill_ids == ("design",)
