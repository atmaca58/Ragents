"""Çalışma zamanlarını yeniden dağıtmadan çevrimiçi kurulum varlıklarını hazırlar."""
import argparse
import json
import re
from pathlib import Path
import shutil
import zipfile

from ragents import __version__
from ragents.distribution import file_hash


def prepare(root, stage, output):
    output.mkdir(parents=True, exist_ok=False)
    version = __version__
    release_tag = "v" + version.replace(".dev", "-dev.")
    # Paketlenen uygulamanın canlı kaynakla aynı olduğunu doğrula.
    packaged = stage / "versions" / version / "python/Lib/site-packages/ragents"
    for source in (root / "src/ragents").rglob("*.py"):
        if source.read_bytes() != (packaged / source.relative_to(root / "src/ragents")).read_bytes():
            raise RuntimeError("Test edilen staging ile uygulama kaynağı farklı.")
    wheel = root / ".build-cache/wheels" / f"ragents-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel) as archive:
        for source in (root / "src/ragents").rglob("*.py"):
            if archive.read("ragents/" + source.relative_to(root / "src/ragents").as_posix()) != source.read_bytes():
                raise RuntimeError("Wheel ile uygulama kaynağı farklı.")
    shutil.copy2(wheel, output / wheel.name)
    shutil.copy2(root / "requirements-dev.lock", output / "requirements-dev.lock")
    with zipfile.ZipFile(output / "ragents-launchers.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in ("ragents.exe", "R-Agents.exe"):
            archive.write(stage / name, name)
    runtimes = json.loads((root / "packaging/runtime-assets.json").read_text())

    def asset(name):
        return {"name": name, "sha256": file_hash(output / name)}

    manifest = {
        "schema_version": 1, "release_tag": release_tag,
        "version": version, "accepted": False, "signed": False,
        "python": runtimes["python"], "git": runtimes["git"],
        "pip": {
            "url": "https://files.pythonhosted.org/packages/f3/6e/1736e5b4ae2b778ef2f81c47d797de9f891d4d8acb047a24ca37a60294dd/pip-26.2.1-py3-none-any.whl",
            "sha256": "71138adf1f4ca900cdb7d289c21b7494329f2332b6d85f0e1c42108c0384ed3e",
        },
        "wheel": asset(wheel.name), "constraints": asset("requirements-dev.lock"),
        "launchers": asset("ragents-launchers.zip"),
    }
    target = output / "install-manifest.json"
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    bootstrap = root / "scripts/install.ps1"
    text = bootstrap.read_text(encoding="utf-8-sig")
    text = re.sub(r"(?m)^\$ReleaseTag = '[^']+'$", f"$ReleaseTag = '{release_tag}'", text)
    updated, count = re.subn(r"(?m)^\$ManifestHash = '[a-f0-9]{64}'$",
                            f"$ManifestHash = '{file_hash(target)}'", text)
    if count != 1:
        raise RuntimeError("Bootstrap içinde tam bir manifest hash alanı gereklidir.")
    # irm | iex, PowerShell 5.1'de metnin başındaki BOM'u param bloğu olarak algılamaz.
    bootstrap.write_text(updated, encoding="utf-8")
    (output / "SHA256SUMS").write_text("".join(
        f"{file_hash(path)}  {path.name}\n" for path in sorted(output.iterdir()) if path.is_file()), encoding="utf-8")
    print(json.dumps({"release": manifest["release_tag"], "manifest_sha256": file_hash(target)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepare(Path(__file__).resolve().parents[1], args.stage.resolve(), args.output.resolve())
