import asyncio

import pytest
from pydantic_ai.providers.openai_chatgpt import OpenAIChatGPTCredentials

from ragents.auth import ChatGPTStore, SystemVault, account_guard, get_host_id
from ragents.chatgpt_login import sign_in, auth_status
from ragents.errors import AuthError
from ragents.config import ConnectionSpec
from ragents import providers


class MemoryVault:
    def __init__(self):
        self.items = {}

    def get(self, name):
        return self.items.get(name)

    def set(self, name, value):
        self.items[name] = value

    def delete(self, name):
        self.items.pop(name, None)


def make_credentials(**overrides):
    return OpenAIChatGPTCredentials(**{
        "client_id": "test-client", "access_token": "test-access",
        "refresh_token": "test-refresh", "scope": "openid chatgpt.tokens.use.direct",
        **overrides,
    })


def test_credentials_roundtrip_is_account_scoped_and_refresh_is_persisted(tmp_path):
    vault = MemoryVault()

    async def run():
        first = ChatGPTStore("personal", vault=vault, root=tmp_path)
        await first.save(make_credentials())
        rotated = make_credentials(access_token="rotated-access", refresh_token="rotated-refresh")
        await first.save(rotated)
        assert await ChatGPTStore("personal", vault=vault, root=tmp_path).load() == rotated
        assert await ChatGPTStore("work", vault=vault, root=tmp_path).load() is None
        assert "rotated-refresh" not in repr(rotated)

    asyncio.run(run())


def test_credential_file_is_encrypted_even_for_large_tokens(tmp_path):
    store = ChatGPTStore(vault=MemoryVault(), root=tmp_path)
    credentials = make_credentials(access_token="large-secret-" * 1000)
    asyncio.run(store.save(credentials))
    assert b"large-secret" not in store.path.read_bytes()
    assert asyncio.run(store.load()) == credentials


def test_signin_reuses_client_and_stable_host_and_records_declined_plan(tmp_path):
    vault = MemoryVault()
    store = ChatGPTStore(vault=vault, root=tmp_path)
    received = []

    class Flow:
        def __init__(self, **kwargs):
            received.append(kwargs)

        def authorization_url(self, **kwargs):
            return "https://auth.openai.com/example"

        async def exchange_code_from_callback(self):
            return make_credentials(scope="openid")

    async def run():
        await store.save(make_credentials())
        status = await sign_in(store, opener=lambda url: True, flow_factory=Flow)
        assert status["signed_in"] is True
        assert status["plan_usage_granted"] is False
        assert received[0]["client_id"] == "test-client"
        assert received[0]["host_id"] == get_host_id(tmp_path)
        assert (await auth_status(store))["remote_validated"] is False

    asyncio.run(run())


def test_same_account_cannot_refresh_in_two_runs(tmp_path):
    with account_guard("default", tmp_path):
        with pytest.raises(AuthError, match="başka"):
            with account_guard("default", tmp_path):
                pytest.fail("Aynı hesap kilidi ikinci kez alınmamalı")


def test_plaintext_vault_backend_is_rejected(monkeypatch):
    import keyring

    class PlainTextBackend:
        pass

    monkeypatch.setattr(keyring, "get_keyring", lambda: PlainTextBackend())
    with pytest.raises(AuthError, match="Düz metin"):
        SystemVault()


def test_plan_permission_is_required_before_engine_is_exposed(tmp_path, monkeypatch):
    store = ChatGPTStore(vault=MemoryVault(), root=tmp_path)
    asyncio.run(store.save(make_credentials(scope="openid")))
    monkeypatch.setattr(providers, "ChatGPTStore", lambda account: store)

    async def run():
        async with providers.open_engine(ConnectionSpec(provider="chatgpt", model="example-model")):
            pytest.fail("Plan izni yokken motor açılmamalı")

    with pytest.raises(AuthError, match="plan kullanma izni"):
        asyncio.run(run())
