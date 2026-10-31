import asyncio
from collections.abc import Callable
import webbrowser

from pydantic_ai.providers.openai_chatgpt import OpenAIChatGPTOAuthFlow

from ragents.auth import ChatGPTStore, account_guard, get_host_id
from ragents.errors import AuthError


async def sign_in(
    store: ChatGPTStore, *, opener: Callable[[str], bool] | None = None,
    flow_factory=OpenAIChatGPTOAuthFlow,
) -> dict:
    with account_guard(store.account, store.root):
        saved = await store.load()
        # Kasaya yazılabildiğini tarayıcıyı açmadan doğrula.
        await asyncio.to_thread(store.cipher)
        flow = flow_factory(
            app_name="R Agents", host_id=get_host_id(store.root),
            client_id=saved.client_id if saved else None,
        )
        extra = {"prompt": "consent"} if saved and not saved.plan_usage_granted else None
        url = flow.authorization_url(extra_params=extra)
        if not await asyncio.to_thread(opener or webbrowser.open, url):
            raise AuthError("Tarayıcı açılamadı. Yerel grafik oturumundan tekrar deneyin.")
        try:
            async with asyncio.timeout(180):
                credentials = await flow.exchange_code_from_callback()
        except TimeoutError:
            raise AuthError("ChatGPT girişi süre sınırına ulaştı; yeniden deneyin.") from None
        await store.save(credentials)
        return {"provider": "chatgpt", "account": store.account, "signed_in": True,
                "plan_usage_granted": credentials.plan_usage_granted}


async def auth_status(store: ChatGPTStore) -> dict:
    with account_guard(store.account, store.root):
        saved = await store.load()
        return {"provider": "chatgpt", "account": store.account, "signed_in": saved is not None,
                "plan_usage_granted": saved.plan_usage_granted if saved else False,
                "remote_validated": False}


def sign_out(store: ChatGPTStore) -> dict:
    with account_guard(store.account, store.root):
        store.logout()
    return {"provider": "chatgpt", "account": store.account, "signed_in": False,
            "remote_revoked": False}
