"""Talimat, proje, kural ve skill dosyalarını tek metne derler."""

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import Annotated, Literal, Mapping

from pydantic import Field, ValidationError
import yaml

from ragents.config import MAX_INSTRUCTION_CHARS, Spec
from ragents.errors import InstructionError
from ragents.relevance import keywords_match


SKILL_ID_PATTERN = r"^[a-z0-9][a-z0-9-]{0,31}$"
SkillId = Annotated[str, Field(pattern=SKILL_ID_PATTERN)]

MAX_PROFILE_CHARS = 8000
MAX_PROJECT_CHARS = 4000
MAX_RULES_CHARS = 4000
MAX_SKILL_CHARS = 4000
MAX_SKILLS_TOTAL_CHARS = 8000

PROFILE_FILE = "instructions.md"
PROJECT_FILE = "project.md"
RULES_FILE = "rules.md"
SKILL_FILE = "SKILL.md"


class InstructionSource(Spec):
    kind: Literal["profile", "project", "skill", "memory", "rules"]
    name: str
    sha256: str
    chars: int


class InstructionSnapshot(Spec):
    revision: str
    total_chars: int
    sources: tuple[InstructionSource, ...]
    skill_ids: tuple[str, ...] = ()


class SkillMetadata(Spec):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    keywords: tuple[Annotated[str, Field(min_length=1, max_length=60)], ...] = Field(
        default=(), max_length=30,
    )


@dataclass(frozen=True)
class SkillDocument:
    id: str
    name: str
    description: str | None
    keywords: tuple[str, ...]
    body: str
    source_sha256: str
    source_chars: int


@dataclass(frozen=True)
class InstructionPolicy:
    max_chars: int
    allowed_skills: tuple[str, ...] = ()
    default_skills: tuple[str, ...] = ()


@dataclass(frozen=True)
class CompiledInstructions:
    text: str
    snapshot: InstructionSnapshot


@dataclass(frozen=True)
class MemoryDocument:
    id: str
    revision: int
    text: str
    sha256: str


def _is_link(path: Path) -> bool:
    checker = getattr(path, "is_junction", None)
    return path.is_symlink() or (checker is not None and checker())


def _ensure_inside(directory: Path, path: Path) -> None:
    try:
        path.resolve().relative_to(directory.resolve())
    except ValueError:
        raise InstructionError("Talimat dosyası ajan dizininin dışına çıkamaz.") from None


def read_text_file(directory: Path, relative: str | Path, *, required: bool, label: str) -> str | None:
    path = directory / relative
    if not path.exists():
        if required:
            raise InstructionError(f"{label} dosyası yok.")
        return None
    if _is_link(path):
        raise InstructionError(f"{label} sembolik bağlantı olamaz.")
    _ensure_inside(directory, path)
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise InstructionError(f"{label} UTF-8 metin olmalıdır.") from None
    except OSError:
        raise InstructionError(f"{label} okunamadı.") from None


def _check_length(label: str, text: str, limit: int) -> None:
    if len(text) > limit:
        raise InstructionError(f"{label} çok uzun: {len(text)} karakter; en fazla {limit} olabilir.")


def _split_frontmatter(text: str, label: str) -> tuple[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return "", text
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "\n".join(lines[1:index]), "\n".join(lines[index + 1:])
    raise InstructionError(f"{label} frontmatter kapanışı bulunamadı.")


def load_skill(directory: Path, skill_id: str) -> SkillDocument:
    if not re.fullmatch(SKILL_ID_PATTERN, skill_id):
        raise InstructionError(f"Geçersiz skill kimliği: {skill_id}")
    label = f"Skill {skill_id}"
    raw = read_text_file(
        directory, Path("skills") / skill_id / SKILL_FILE, required=True, label=label,
    )
    if raw is None:
        raise InstructionError(f"{label} dosyası yok.")
    text = raw.removeprefix("\ufeff")
    frontmatter, body = _split_frontmatter(text, label)
    metadata = SkillMetadata()
    if frontmatter.strip():
        try:
            data = yaml.safe_load(frontmatter)
        except yaml.YAMLError:
            raise InstructionError(f"{label} frontmatter YAML biçimi geçersiz.") from None
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise InstructionError(f"{label} frontmatter bir nesne olmalıdır.")
        try:
            metadata = SkillMetadata.model_validate(data)
        except ValidationError as error:
            item = error.errors()[0]
            location = ".".join(str(part) for part in item["loc"])
            message = f"{location}: {item['msg']}" if location else item["msg"]
            raise InstructionError(f"{label} frontmatter geçersiz: {message}") from None
    body = body.strip()
    if not body:
        raise InstructionError(f"{label} gövdesi boş olamaz.")
    _check_length(label, body, MAX_SKILL_CHARS)
    return SkillDocument(
        id=skill_id, name=metadata.name or skill_id,
        description=metadata.description, keywords=tuple(metadata.keywords),
        body=body, source_sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        source_chars=len(raw),
    )


def resolve_skill_ids(policy: InstructionPolicy, requested: tuple[str, ...] = ()) -> tuple[str, ...]:
    allowed = tuple(policy.allowed_skills)
    if len(set(allowed)) != len(allowed):
        raise InstructionError("Skill kataloğunda aynı kimlik tekrar edemez.")
    defaults = tuple(policy.default_skills)
    if len(set(defaults)) != len(defaults):
        raise InstructionError("Varsayılan skill listesinde aynı kimlik tekrar edemez.")
    if any(skill not in allowed for skill in defaults):
        raise InstructionError("Varsayılan skill izinli katalogda tanımlı değil.")
    selected = tuple(dict.fromkeys(requested)) if requested else defaults
    unknown = [skill for skill in selected if skill not in allowed]
    if unknown:
        raise InstructionError("Skill izinli değil: " + ", ".join(unknown))
    return selected


def _build(
    policy: InstructionPolicy, instructions: str, project: str | None,
    rules: str | None, skills: tuple[SkillDocument, ...],
    memories: tuple[MemoryDocument, ...] = (),
) -> CompiledInstructions:
    if not instructions.strip():
        raise InstructionError("Ajan talimatı boş olamaz.")
    _check_length("Ajan profili", instructions, MAX_PROFILE_CHARS)
    sources: list[InstructionSource] = [InstructionSource(
        kind="profile", name=PROFILE_FILE,
        sha256=hashlib.sha256(instructions.encode("utf-8")).hexdigest(), chars=len(instructions),
    )]
    parts = ["## Ajan profili\n\n" + instructions.strip()]
    project_text = project.strip() if project and project.strip() else None
    if project_text is not None:
        _check_length("Proje bilgisi", project_text, MAX_PROJECT_CHARS)
        parts.append("## Proje bilgisi\n\n" + project_text)
        sources.append(InstructionSource(
            kind="project", name=PROJECT_FILE,
            sha256=hashlib.sha256(project.encode("utf-8")).hexdigest(),
            chars=len(project),
        ))
    seen: set[str] = set()
    skill_chars = 0
    for skill in skills:
        if skill.id in seen:
            raise InstructionError(f"Skill iki kez seçilemez: {skill.id}")
        seen.add(skill.id)
        if not skill.body.strip():
            raise InstructionError(f"Skill {skill.id} gövdesi boş olamaz.")
        _check_length(f"Skill {skill.id}", skill.body, MAX_SKILL_CHARS)
        skill_chars += len(skill.body)
        parts.append(f"## Seçili skill: {skill.name}\n\n{skill.body}")
        sources.append(InstructionSource(
            kind="skill", name=skill.id, sha256=skill.source_sha256,
            chars=skill.source_chars,
        ))
    if skill_chars > MAX_SKILLS_TOTAL_CHARS:
        raise InstructionError(
            f"Skill metinleri çok uzun: {skill_chars} karakter; en fazla {MAX_SKILLS_TOTAL_CHARS} olabilir."
        )
    for memory in memories:
        parts.append(f"## Onaylı proje kaydı: {memory.id}\n\n{memory.text}")
        sources.append(InstructionSource(kind="memory", name=f"{memory.id}@{memory.revision}",
                                         sha256=memory.sha256, chars=len(memory.text)))
    rules_text = rules.strip() if rules and rules.strip() else None
    if rules_text is not None:
        _check_length("Kalıcı kurallar", rules_text, MAX_RULES_CHARS)
        parts.append("## Kalıcı kurallar\n\n" + rules_text)
        sources.append(InstructionSource(
            kind="rules", name=RULES_FILE,
            sha256=hashlib.sha256(rules.encode("utf-8")).hexdigest(),
            chars=len(rules),
        ))
    text = "\n\n".join(parts)
    limit = min(policy.max_chars, MAX_INSTRUCTION_CHARS)
    _check_length("Derlenmiş talimat", text, limit)
    snapshot = InstructionSnapshot(
        revision=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        total_chars=len(text), sources=tuple(sources),
        skill_ids=tuple(skill.id for skill in skills),
    )
    return CompiledInstructions(text=text, snapshot=snapshot)


def compile_texts(
    policy: InstructionPolicy, instructions: str, project: str | None,
    rules: str | None, skills: Mapping[str, SkillDocument],
    selected_skills: tuple[str, ...] = (),
) -> CompiledInstructions:
    selected = resolve_skill_ids(policy, selected_skills)
    try:
        documents = tuple(skills[skill] for skill in selected)
    except KeyError as error:
        raise InstructionError(f"Skill dosyası yüklenemedi: {error.args[0]}") from None
    return _build(policy, instructions, project, rules, documents)


def compile_instructions(
    directory: Path, policy: InstructionPolicy, selected_skills: tuple[str, ...] = (),
    *, prompt: str | None = None, memories: tuple[MemoryDocument, ...] = (),
) -> CompiledInstructions:
    selected = resolve_skill_ids(policy, selected_skills)
    if not selected_skills and prompt:
        related = tuple(identity for identity in policy.allowed_skills
                        if identity not in selected and keywords_match(load_skill(directory, identity).keywords, prompt))
        selected = (*selected, *related)
    instructions = read_text_file(directory, PROFILE_FILE, required=True, label="Ajan talimatı")
    if instructions is None:
        raise InstructionError(f"{PROFILE_FILE} dosyası yok.")
    project = read_text_file(directory, PROJECT_FILE, required=False, label="Proje bilgisi")
    rules = read_text_file(directory, RULES_FILE, required=False, label="Kalıcı kurallar")
    documents = tuple(load_skill(directory, skill) for skill in selected)
    return _build(policy, instructions, project, rules, documents, memories)
