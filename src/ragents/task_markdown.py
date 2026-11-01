"""Görevlerin Markdown içe/dışa aktarma görünümü.

Doğruluk kaynağı SQLite'tır. Markdown yalnız okunabilir bir dışa aktarma ve
elle hazırlanan görev planlarını içe aktarma biçimidir; dışa aktarılan dosyayı
düzenleyip içe aktarmak yeni görevler oluşturur, mevcut görevleri güncellemez.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from pydantic import Field, ValidationError
import yaml

from ragents.catalog import enqueue_agent_task, load_agent
from ragents.config import Spec
from ragents.storage import TaskSnapshot, TaskStateError, TaskStore
from ragents.verification import VerificationPlan
from ragents.programmatic import ProgrammaticJob


MAX_IMPORT_TASKS = 200
MAX_IMPORT_BYTES = 1_048_576
BLOCK = re.compile(
    r"<!--\s*ragents:task:start\s*-->(.*?)<!--\s*ragents:task:end\s*-->",
    re.DOTALL,
)
FRONT_MATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


class MarkdownTask(Spec):
    ref: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    title: str = Field(min_length=1, max_length=200)
    agent: str = Field(min_length=1, max_length=100)
    connection: str | None = None
    description: str = Field(default="", max_length=4000)
    priority: int = Field(default=0, ge=-1000, le=1000)
    enabled: bool = True
    depends_on: tuple[str, ...] = Field(default=(), max_length=32)
    verification: VerificationPlan | None = None
    programmatic: ProgrammaticJob | None = None


def _front_matter(block: str, index: int) -> tuple[MarkdownTask, str]:
    match = FRONT_MATTER.match(block.strip())
    if match is None:
        raise TaskStateError(
            f"Markdown görev bloğu {index} YAML ön bilgisi ve görev metni içermelidir."
        )
    try:
        raw: Any = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        raise TaskStateError(f"Markdown görev bloğu {index} geçerli YAML değil.") from None
    if not isinstance(raw, dict):
        raise TaskStateError(f"Markdown görev bloğu {index} bir YAML nesnesi olmalıdır.")
    try:
        task = MarkdownTask.model_validate(raw)
    except ValidationError as error:
        first = error.errors()[0]
        path = ".".join(str(part) for part in first.get("loc", ())) or "blok"
        raise TaskStateError(
            f"Markdown görev bloğu {index} geçersiz ({path}): {first.get('msg', 'değer')}."
        ) from None
    prompt = match.group(2).strip()
    if not prompt:
        raise TaskStateError(f"Markdown görev bloğu {index} görev metni içermelidir.")
    return task, prompt


def _topological_order(tasks: dict[str, MarkdownTask]) -> list[str]:
    dependents: dict[str, list[str]] = {title: [] for title in tasks}
    indegree: dict[str, int] = {}
    for title, task in tasks.items():
        indegree[title] = len(task.depends_on)
        for dependency in task.depends_on:
            if dependency not in tasks:
                raise TaskStateError(
                    f"'{title}' görevinin bağımlılığı Markdown içinde yok: {dependency}."
                )
            dependents[dependency].append(title)
    queue = [title for title in tasks if indegree[title] == 0]
    order: list[str] = []
    while queue:
        current = queue.pop(0)
        order.append(current)
        for dependent in dependents[current]:
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                queue.append(dependent)
    if len(order) != len(tasks):
        remaining = sorted(title for title in tasks if title not in order)
        raise TaskStateError(
            "Markdown görev bağımlılıkları döngü oluşturuyor: " + ", ".join(remaining)
        )
    return order


def import_markdown(store: TaskStore, root: Path, text: str) -> list[TaskSnapshot]:
    """Markdown bloklarını yeni görevler olarak ekle; mevcut görevleri değiştirme."""
    if len(text.encode("utf-8")) > MAX_IMPORT_BYTES:
        raise TaskStateError("Markdown görev dosyası çok büyük.")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = BLOCK.findall(normalized)
    if not blocks:
        raise TaskStateError("Markdown dosyasında ragents görev bloğu bulunamadı.")
    if len(blocks) > MAX_IMPORT_TASKS:
        raise TaskStateError(f"Markdown dosyası en fazla {MAX_IMPORT_TASKS} görev içerebilir.")
    parsed = [_front_matter(block, index + 1) for index, block in enumerate(blocks)]
    tasks: dict[str, MarkdownTask] = {}
    prompts: dict[str, str] = {}
    for task, prompt in parsed:
        reference = task.ref or task.title
        if reference in tasks:
            raise TaskStateError(f"Markdown içinde yinelenen görev başlığı/referansı: {reference}.")
        tasks[reference] = task
        prompts[reference] = prompt
    for task in tasks.values():
        record = load_agent(root, task.agent)
        if record.profile.status != "active":
            raise TaskStateError(
                f"Ajan '{task.agent}' etkin değil; Markdown görevi içe aktarılamaz."
            )
    order = _topological_order(tasks)
    created: dict[str, TaskSnapshot] = {}
    for title in order:
        task = tasks[title]
        created[title] = enqueue_agent_task(
            store, root, task.agent, prompts[title], task.connection,
            title=task.title, description=task.description,
            priority=task.priority, enabled=task.enabled,
            dependencies=tuple(created[dependency].id for dependency in task.depends_on),
            verification=task.verification,
            programmatic=task.programmatic,
        )
    return [created[title] for title in order]


def export_markdown(store: TaskStore, *, limit: int = 1000) -> str:
    """Görevleri en eski önce olacak biçimde Markdown görünümüne aktar."""
    tasks = list(reversed(store.list(limit=limit, include_archived=True)))
    blocks: list[str] = []
    for task in tasks:
        definition = store.definition(task.id)
        data: dict[str, Any] = {
            "ref": task.id,
            "title": task.title,
            "agent": task.agent_id,
            "connection": definition.connection_id,
            "description": task.description,
            "priority": task.priority,
            "enabled": task.enabled,
            "depends_on": list(store.dependencies(task.id)),
        }
        if definition.verification is not None:
            data["verification"] = definition.verification.model_dump(mode="json")
        if definition.programmatic is not None:
            data["programmatic"] = definition.programmatic.model_dump(mode="json")
        front = yaml.safe_dump(
            data, allow_unicode=True, sort_keys=False, default_flow_style=False,
        ).strip()
        blocks.append(
            "<!-- ragents:task:start -->\n"
            f"---\n{front}\n---\n"
            f"{definition.prompt}\n"
            "<!-- ragents:task:end -->"
        )
    if not blocks:
        return "# R Agents görevleri\n\nGörev yok.\n"
    return "# R Agents görevleri\n\n" + "\n\n".join(blocks) + "\n"
