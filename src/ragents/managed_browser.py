"""Ağsız AppContainer içindeki Playwright için denetimli HTTP broker'ı."""
import os
from pathlib import Path
import sys
import asyncio
from typing import Literal

from pydantic import Field, model_validator

from ragents.config import Spec
from ragents.errors import SandboxError, WorkspaceError
from ragents.web_tools import SafeWebClient, WebAccessError
from ragents.workspace import Workspace, normalize_relative_path


class BrowserAction(Spec):
    action: Literal["navigate", "click", "fill", "screenshot", "expect_text", "expect_visible"]
    url: str | None = Field(default=None, max_length=4096)
    selector: str | None = Field(default=None, max_length=500)
    text: str | None = Field(default=None, max_length=4000)
    path: str | None = Field(default=None, max_length=512)

    @model_validator(mode="after")
    def required_fields(self):
        from urllib.parse import urlsplit
        if self.action == "navigate":
            parsed = urlsplit(self.url or "")
            if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Tarayıcı yalnız kimlik bilgisi içermeyen HTTP(S) adresine gidebilir.")
        if self.action in ("click", "fill", "expect_text", "expect_visible") and not self.selector:
            raise ValueError("Bu tarayıcı işlemi selector gerektirir.")
        if self.action in ("fill", "expect_text") and self.text is None:
            raise ValueError("Bu tarayıcı işlemi metin gerektirir.")
        if self.action == "screenshot":
            if not self.path or not self.path.endswith(".png"):
                raise ValueError("Ekran görüntüsü için göreli .png yolu gereklidir.")
            normalize_relative_path(self.path)
        return self


class BrowserWorkflow(Spec):
    actions: tuple[BrowserAction, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def starts_with_navigation(self):
        if self.actions[0].action != "navigate":
            raise ValueError("Tarayıcı akışı gezinme ile başlamalıdır.")
        return self


def browser_runtime():
    bundled = Path(sys.executable).parent.parent / "browsers"
    if bundled.is_dir():
        return bundled
    configured = os.environ.get("RAGENTS_BROWSER_PATH")
    if configured and Path(configured).is_dir():
        return Path(configured).resolve()
    raise SandboxError("Ürün Chromium çalışma zamanı bulunamadı; kurulum veya tarayıcı yolunu kontrol edin.")


class ManagedBrowser:
    def __init__(self, grant, *, browsers=None, client=None):
        if not grant.allow_network:
            raise WorkspaceError("Tarayıcı broker'ı açık ağ izni gerektirir.")
        self.grant = grant
        self.browsers = browsers or browser_runtime()
        self.client = client or SafeWebClient(allowed_local=grant.local_web_targets)

    async def run(self, workflow: BrowserWorkflow):
        if sys.platform != "win32":
            raise SandboxError("Yönetilen tarayıcı ilk sürümde yalnız Windows'ta desteklenir.")
        from playwright.async_api import async_playwright, expect
        workspace = Workspace(self.grant.root, self.grant.protected_paths, writable_paths=self.grant.writable_paths)
        screenshots = {}
        for action in workflow.actions:
            if action.action == "screenshot":
                target = workspace._target(action.path, must_exist=False, access="write")
                if not target.parent.is_dir():
                    raise WorkspaceError("Ekran görüntüsünün hedef dizini mevcut olmalıdır.")
                screenshots[action.path] = target
        requests = 0
        stats = {"expected": 0, "unexpected": 0, "skipped": 0, "flaky": 0}
        checks = []
        environment = {"RAGENTS_CHROMIUM_RUNTIME": str(self.browsers),
                       "RAGENTS_BROWSER_TIMEOUT": str(min(self.grant.command_timeout_seconds, 120)),
                       "SystemRoot": os.environ.get("SystemRoot", "C:\\Windows"), "PYTHONUTF8": "1"}
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(executable_path=sys.executable, ignore_default_args=True,
                args=["-I", "-u", "-m", "ragents.chromium_sandbox"], env=environment, timeout=30000)
            try:
                context = await browser.new_context(service_workers="block", accept_downloads=False)
                context.set_default_timeout(5000)
                async def routed(route):
                    nonlocal requests
                    request = route.request
                    requests += 1
                    try:
                        if requests > 64:
                            raise WebAccessError("Tarayıcı istek sınırı aşıldı.")
                        headers = {key: value for key, value in request.headers.items()
                                   if key.lower() not in ("host", "connection", "content-length", "accept-encoding")}
                        _, response = await asyncio.to_thread(self.client.request, request.url, method=request.method,
                            headers=headers, body=request.post_data_buffer, return_redirect=True)
                        await route.fulfill(status=response.status, headers=response.headers, body=response.body)
                    except (WebAccessError, ValueError, OSError):
                        await route.abort("blockedbyclient")
                await context.route("**/*", routed)
                await context.route_web_socket("**/*", lambda websocket: websocket.close())
                page = await context.new_page()
                for action in workflow.actions:
                    try:
                        if action.action == "navigate":
                            await page.goto(action.url, wait_until="domcontentloaded")
                        elif action.action == "click":
                            await page.locator(action.selector).click()
                        elif action.action == "fill":
                            await page.locator(action.selector).fill(action.text)
                        elif action.action == "screenshot":
                            await page.screenshot(path=str(screenshots[action.path]), full_page=True)
                        elif action.action == "expect_text":
                            await expect(page.locator(action.selector)).to_contain_text(action.text, timeout=3000)
                            stats["expected"] += 1
                        elif action.action == "expect_visible":
                            await expect(page.locator(action.selector)).to_be_visible(timeout=3000)
                            stats["expected"] += 1
                        checks.append({"action": action.action, "status": "passed"})
                    except Exception:
                        stats["unexpected"] += 1
                        checks.append({"action": action.action, "status": "failed"})
                        break
                return {"stats": stats, "checks": checks, "url": page.url, "title": await page.title(),
                        "engine": "playwright-python", "browser_version": browser.version,
                        "browser_network_allowed": False, "broker_requests": requests, "producer": "managed_playwright"}
            finally:
                await browser.close()
