"""Temiz staging alanında bağımsız Windows paketi üretir; kullanıcıya kurmaz."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

from ragents import __version__
from ragents.distribution import file_hash, license_inventory, source_package, write_package_manifest


def run(argv, **kwargs):
    subprocess.run([str(item) for item in argv], check=True, **kwargs)


def extract(archive, directory):
    directory.mkdir(parents=True)
    with zipfile.ZipFile(archive) as bundle:
        for entry in bundle.infolist():
            if not (directory / entry.filename).resolve().is_relative_to(directory.resolve()):
                raise RuntimeError("Çalışma zamanı arşivi güvenli olmayan yol içeriyor.")
        bundle.extractall(directory)


def build(root, output):
    if sys.platform != "win32":
        raise RuntimeError("Windows paketi Windows x64 üzerinde üretilmelidir.")
    if output.exists():
        raise RuntimeError("Staging için yeni çıktı dizini seçin; üzerine yazılmaz.")
    assets = json.loads((root / "packaging/runtime-assets.json").read_text())
    cache = root / ".build-cache"
    for name in ("python", "git", "compiler"):
        asset = assets[name]
        if file_hash(cache / asset["filename"]) != asset["sha256"]:
            raise RuntimeError(f"Resmi çalışma zamanı hash doğrulaması başarısız: {name}")
    version = output / "versions" / __version__
    python = version / "python"
    extract(cache / assets["python"]["filename"], python)
    extract(cache / assets["git"]["filename"], version / "git")
    site_packages = python / "Lib/site-packages"
    source = source_package(root, output / f"ragents-{__version__}-source.zip")
    with tempfile.TemporaryDirectory(prefix="ragents-buildsrc-", dir=cache) as temporary:
        source_root = Path(temporary) / "source"
        extract(source, source_root)
        run([sys.executable, "-m", "pip", "wheel", "--no-deps", source_root, "--wheel-dir", cache / "wheels"])
    wheel = cache / "wheels" / f"ragents-{__version__}-py3-none-any.whl"
    run([sys.executable, "-m", "pip", "install", "--no-index", "--find-links", cache / "wheels",
         "--constraint", root / "requirements-dev.lock", "--no-compile", "--target", site_packages, wheel])
    for path in site_packages.rglob("direct_url.json"):
        path.unlink()
    for name in ("bin", "Scripts"):
        scripts = site_packages / name
        if scripts.exists() and scripts.resolve().is_relative_to(version.resolve()):
            shutil.rmtree(scripts)
    (python / "python314._pth").write_text("python314.zip\n.\nLib/site-packages\nimport site\n", encoding="utf-8")
    browsers = cache / "browsers"
    if not (browsers / "chromium_headless_shell-1248").is_dir():
        raise RuntimeError("Sabit Chromium paketi bulunamadı.")
    shutil.copytree(browsers / "chromium_headless_shell-1248", version / "browsers/chromium_headless_shell-1248")
    for name in ("LICENSE", "NOTICE"):
        shutil.copy2(root / name, version / name)
    inventory = {"schema_version": 1, "packages": license_inventory(site_packages),
                 "runtimes": assets, "generated_at": datetime.now(timezone.utc).isoformat()}
    (version / "THIRD-PARTY.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")
    (version / "THIRD-PARTY-NOTICES.txt").write_text(
        "R Agents — üçüncü taraf bildirimleri\n\nPython: python/LICENSE.txt\n"
        "Git/MinGit: git içindeki COPYING ve lisans belgeleri.\n"
        "Chromium/FFmpeg: browsers içindeki LICENSE ve credits belgeleri.\n"
        "Playwright ve Python bağımlılıkları: THIRD-PARTY.json ve python/Lib/site-packages içindeki lisans dosyaları.\n"
        "Paket sürümleri, beyan edilen lisanslar ve lisans dosyası hash'leri THIRD-PARTY.json içindedir.\n", encoding="utf-8")
    compiler = Path(os.environ["SystemRoot"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    for target, filename in (("exe", "R-Agents.exe"), ("exe", "ragents.exe")):
        run([compiler, "/nologo", "/platform:x64", f"/target:{target}", f"/out:{output / filename}", root / "packaging/Launcher.cs"])
    (output / "current.txt").write_text(__version__, encoding="utf-8")
    write_package_manifest(version, __version__)
    smoke_environment = {key: value for key, value in os.environ.items() if key not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "RAGENTS_HOME")}
    smoke_environment["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
    smoke_environment["PYTHONDONTWRITEBYTECODE"] = "1"
    for arguments in (("--version",), ("demo",), ("init", "--help")):
        run([python / "python.exe", "-I", "-B", "-m", "ragents", *arguments], cwd=output, env=smoke_environment)
    print(json.dumps({"staging": str(output), "version": __version__, "installed": False, "accepted": False}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(Path(__file__).resolve().parents[1], args.output.resolve())
