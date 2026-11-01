import json
from pathlib import Path
import os
import shlex
import sys

import yaml

from ragents.config import ProjectConfig
from ragents.storage import TaskStateError


def write_profile(directory: Path, config: ProjectConfig) -> dict:
    directory = directory.resolve()
    config_path = directory / "ragents.yaml"
    database = directory / "data" / "ragents.db"
    worker = [sys.executable, "-m", "ragents", "worker", "--root", str(directory), "--db", str(database)]
    args = ["-m", "ragents", "mcp", "serve", "--root", str(directory), "--db", str(database), "--config", str(config_path), "--allow-execute"]
    client = {"command": sys.executable, "args": args}
    files = {
        "ragents.yaml": yaml.safe_dump(config.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
        "mcp-client.json": json.dumps({"mcpServers": {"r-agents": client}}, ensure_ascii=False, indent=2) + "\n",
        "codex-mcp.toml": "[mcp_servers.r_agents]\ncommand = " + json.dumps(sys.executable, ensure_ascii=False) + "\nargs = " + json.dumps(args, ensure_ascii=False) + "\n",
        "start-worker.ps1": "$ErrorActionPreference = 'Stop'\n& " + " ".join("'" + item.replace("'", "''") + "'" for item in worker) + "\nexit $LASTEXITCODE\n",
        "start-worker.sh": "#!/bin/sh\nexec " + shlex.join(worker) + ' "$@"\n',
        "start-worker.py": (
            "from pathlib import Path\nimport sys\nfrom ragents.cli import main\n\n"
            'database = Path(__file__).resolve().parent / "data" / "ragents.db"\n'
            'raise SystemExit(main(["worker", "--root", str(database.parent.parent), "--db", str(database), *sys.argv[1:]]))\n'
        ),
    }
    try:
        directory.mkdir(parents=True, mode=0o700)
    except FileExistsError:
        raise TaskStateError("Kurulum dizini zaten var; üzerine yazılmaz. Yeni dizin seçin veya doctor kullanın.") from None
    for name, content in files.items():
        with (directory / name).open("x", encoding="utf-8-sig" if name.endswith(".ps1") else "utf-8", newline="\n") as stream:
            stream.write(content)
        if name.endswith(".sh") and os.name != "nt":
            (directory / name).chmod(0o700)
    return {"configured": True, "started": False, "directory": str(directory), "config": str(config_path),
            "worker_argv": worker,
            "mcp_argv": [sys.executable, *args]}
