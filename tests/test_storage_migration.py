import hashlib
import json
from pathlib import Path

from ragents.config import load_config
from ragents.storage import TaskStore


def test_older_config_defaults_do_not_break_existing_idempotency_key(tmp_path):
    config = load_config(Path("examples/ollama.yaml"))
    store = TaskStore(tmp_path / "old.db")
    task = store.enqueue(config, "Görev", idempotency_key="existing")
    payload = store.definition(task.id).model_dump(mode="json")
    payload.pop("instruction")
    payload["config"].pop("mcp_servers")
    payload["config"]["agent"].pop("mcp_tools")
    payload["config"]["agent"].pop("tool_selection")
    old = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    with store.connect() as db:
        db.execute("UPDATE tasks SET definition_json=?, fingerprint=? WHERE id=?",
                   (old, hashlib.sha256(old.encode()).hexdigest(), task.id))
    assert store.enqueue(config, "Görev", idempotency_key="existing").id == task.id
    assert store.definition(task.id).instruction is None
