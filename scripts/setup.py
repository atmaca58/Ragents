"""Bağımlılık gerektirmeyen ortak Windows/macOS/Linux kurucusu."""
import argparse
from pathlib import Path
import subprocess
import sys


def install(root: Path, *, platform: str, run_tests: bool, skip_configure: bool,
            profile_directory: str | None, runner=subprocess.run) -> None:
    python = root / ".venv" / ("Scripts/python.exe" if platform == "win32" else "bin/python")
    if not python.is_file():
        runner([sys.executable, "-m", "venv", str(root / ".venv")], cwd=root, check=True)
    command = [str(python), "-m", "pip", "install"]
    if platform == "win32":
        command.extend(["-r", "requirements-dev.lock"])
    runner([*command, "-e", ".[dev]"], cwd=root, check=True)
    runner([str(python), "-m", "pip", "check"], cwd=root, check=True)
    if run_tests:
        runner([str(python), "-m", "pytest"], cwd=root, check=True)
    if not skip_configure:
        command = [str(python), "-m", "ragents", "setup"]
        if profile_directory is not None:
            command.extend(["--directory", profile_directory])
        runner(command, cwd=root, check=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="R Agents ortak kurulum akışı")
    parser.add_argument("--run-tests", action="store_true")
    parser.add_argument("--skip-configure", action="store_true")
    parser.add_argument("--profile-directory")
    args = parser.parse_args(argv)
    if not (3, 12) <= sys.version_info[:2] < (3, 15):
        print("Python 3.12–3.14 gerekli.", file=sys.stderr)
        return 2
    try:
        install(Path(__file__).resolve().parents[1], platform=sys.platform,
                run_tests=args.run_tests, skip_configure=args.skip_configure,
                profile_directory=args.profile_directory)
    except (OSError, subprocess.CalledProcessError):
        print("Kurulum tamamlanamadı; yukarıdaki komut hatasını kontrol edin. Mevcut profiller korunur.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    print("Kurulum tamamlandı. Profil oluşturduysanız start-worker.py ile worker'ı başlatabilirsiniz.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
