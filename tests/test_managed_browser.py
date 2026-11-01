import asyncio
from pathlib import Path
import sys
import pytest

from ragents.managed_browser import BrowserWorkflow, ManagedBrowser
from ragents.web_tools import SafeWebClient, WebResponse
from ragents.workspace import WorkspaceGrant


def test_browser_uses_real_playwright_with_network_denied_by_os(tmp_path):
    if sys.platform != "win32":
        pytest.skip("Yönetilen tarayıcı ilk sürümde Windows")
    browsers = Path(".build-cache/browsers").resolve()
    if not (browsers / "chromium_headless_shell-1248").is_dir():
        pytest.skip("Ürün Chromium paketi bulunamadı")
    (tmp_path / "out").mkdir()
    fetched = []
    def transport(url, address, method, headers, body):
        fetched.append(url)
        return WebResponse(200, {"content-type": "text/html"},
            b'<html><body><label>Name<input id="name"></label><h1>Evidence</h1></body></html>')
    client = SafeWebClient(resolver=lambda *args: ["93.184.216.34"], transport=transport)
    grant = WorkspaceGrant(root=tmp_path, writable_paths=("out",), allow_network=True)
    browser = ManagedBrowser(grant, browsers=browsers, client=client)
    workflow = BrowserWorkflow.model_validate({"actions": [
        {"action": "navigate", "url": "https://public.test/"},
        {"action": "fill", "selector": "#name", "text": "Test"},
        {"action": "expect_text", "selector": "h1", "text": "Evidence"},
        {"action": "screenshot", "path": "out/evidence.png"}]})
    result = asyncio.run(browser.run(workflow))
    assert result["stats"] == {"expected": 1, "unexpected": 0, "skipped": 0, "flaky": 0}, result
    assert result["browser_network_allowed"] is False
    assert (tmp_path / "out/evidence.png").is_file()
    assert fetched == ["https://public.test/"]
