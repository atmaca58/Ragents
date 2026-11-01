from pathlib import Path
from xml.etree import ElementTree as ET

from ragents.windows_service import scheduler_xml, task_name


def test_task_scheduler_uses_explicit_profile_and_non_elevated_hidden_supervisor(tmp_path):
    root = tmp_path / "profile with spaces"
    xml = scheduler_xml(root, Path("C:/Program Files/RAgents/python/pythonw.exe"), "DOMAIN\\User")
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    tree = ET.fromstring(xml)
    assert tree.find(".//t:RunLevel", ns).text == "LeastPrivilege"
    assert tree.find(".//t:Hidden", ns).text == "true"
    assert "supervise" in tree.find(".//t:Arguments", ns).text
    assert str(root.resolve()) in tree.find(".//t:Arguments", ns).text
    assert tree.find(".//t:RestartOnFailure/t:Count", ns).text == "3"
    assert task_name(root) == task_name(root.resolve())


def test_windows_supervisor_job_kills_descendants(tmp_path):
    import sys
    import time
    import pytest
    from ragents.windows_service import WindowsChild
    if sys.platform != "win32":
        pytest.skip("Native Windows Job Object testi")
    ready, leaked = tmp_path / "ready", tmp_path / "leaked"
    script = tmp_path / "child.py"
    script.write_text("import pathlib, subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, '-c', \"import time,pathlib; time.sleep(2); pathlib.Path(sys.argv[1]).write_text('leaked')\", sys.argv[2]])\n"
        "pathlib.Path(sys.argv[1]).write_text('ready')\ntime.sleep(30)\n", encoding="utf-8")
    # Alt süreç kendi sys importunu kullanır; üretim kodu WindowsChild içindedir.
    script.write_text(script.read_text(encoding="utf-8").replace("import time,pathlib;", "import time,pathlib,sys;"), encoding="utf-8")
    child = WindowsChild([sys.executable, str(script), str(ready), str(leaked)])
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready.exists()
    finally:
        child.close()
    time.sleep(2.2)
    assert not leaked.exists()
