"""Playwright'ın devralınan CDP borularını ağsız Chromium'a aktarır."""
import os
from pathlib import Path
import sys
import tempfile


def main():
    from ragents.sandbox import SandboxPolicy, SandboxControl
    from ragents.sandbox_windows import WindowsAppContainerBackend
    browsers = Path(os.environ["RAGENTS_CHROMIUM_RUNTIME"]).resolve()
    executable = browsers / "chromium_headless_shell-1248/chrome-headless-shell-win64/chrome-headless-shell.exe"
    if not executable.is_file():
        return 2
    with tempfile.TemporaryDirectory(prefix="ragents-browser-") as directory:
        root = Path(directory)
        policy = SandboxPolicy(workspace=root, writable_paths=(".",), network=False,
            runtime_roots=(browsers,), timeout_seconds=float(os.environ.get("RAGENTS_BROWSER_TIMEOUT", "60")),
            max_processes=32, max_memory_mb=2048)
        result = WindowsAppContainerBackend().run([str(executable), "--headless", "--no-sandbox", "--disable-gpu",
            "--disable-background-networking", "--disable-component-update", "--no-first-run",
            "--remote-debugging-pipe", "--user-data-dir=" + str(root / "profile")],
            policy, input=None, control=SandboxControl(), extra_fds=(3, 4))
        return result.exit_code or 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        print("Yalıtılmış Chromium başlatılamadı.", file=sys.stderr)
        raise SystemExit(2)
