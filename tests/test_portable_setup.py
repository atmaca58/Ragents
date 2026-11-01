import json
import os
from pathlib import Path
import subprocess
import sys

from ragents.cli import main


def test_profile_has_python_and_posix_launchers_that_use_profile_database(tmp_path, capsys):
    directory = tmp_path / "agents ' project"
    assert main(["setup", "--non-interactive", "--provider", "ollama", "--model", "test-model",
                 "--directory", str(directory)]) == 0
    capsys.readouterr()
    launcher = directory / "start-worker.py"
    assert launcher.is_file()
    shell = (directory / "start-worker.sh").read_text(encoding="utf-8")
    assert shell.startswith("#!/bin/sh\n")
    assert "exec " in shell
    assert b"\r\n" not in (directory / "start-worker.sh").read_bytes()
    result = subprocess.run([sys.executable, str(launcher), "--once"],
                            capture_output=True, text=True, encoding="utf-8", timeout=20,
                            env={**os.environ, "PYTHONUTF8": "1"})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["worker"] == "stopped"
    assert (directory / "data" / "ragents.db").is_file()
    if os.name != "nt":
        result = subprocess.run(["sh", str(directory / "start-worker.sh"), "--once"],
                                capture_output=True, text=True, encoding="utf-8", timeout=20,
                                env={**os.environ, "PYTHONUTF8": "1"})
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["worker"] == "stopped"


def test_bootstrap_selects_platform_interpreter_and_dependency_source(tmp_path):
    import runpy

    installer = runpy.run_path("scripts/setup.py")
    for platform, relative in [("win32", "Scripts/python.exe"), ("darwin", "bin/python"), ("linux", "bin/python")]:
        root = tmp_path / platform
        python = root / ".venv" / relative
        python.parent.mkdir(parents=True)
        python.touch()
        calls = []

        def runner(argv, **options):
            assert options == {"cwd": root, "check": True}
            calls.append(argv)

        installer["install"](root, platform=platform, run_tests=True, skip_configure=False,
                             profile_directory="my agents", runner=runner)
        assert all(command[0] == str(python) for command in calls)
        assert ("-r" in calls[0]) is (platform == "win32")
        assert calls[1][-2:] == ["pip", "check"]
        assert calls[2][-1] == "pytest"
        assert calls[3][-3:] == ["setup", "--directory", "my agents"]


def test_mcp_python_placeholder_uses_running_interpreter_on_all_platforms():
    import asyncio
    from ragents.config import ProjectConfig, load_config
    from ragents.mcp_transport import open_gateway

    data = load_config(Path("examples/ollama-mcp.yaml")).model_dump()
    data["mcp_servers"]["local-tools"]["command"] = "{python}"

    async def scenario():
        async with open_gateway(ProjectConfig.model_validate(data), "kelime say") as gateway:
            result = await gateway.call("local-tools__text_stats", {"text": "bir iki"})
            assert json.loads(result)["words"] == 2

    asyncio.run(scenario())
