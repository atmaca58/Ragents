from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
import os

from openai import AsyncOpenAI
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.openai_chatgpt import (
    CredentialsPersistenceError, CredentialsRefreshError, OpenAIChatGPTProvider,
)

from ragents.auth import ChatGPTStore, async_account_guard
from ragents.config import ConnectionSpec
from ragents.connections import FIXED_ENDPOINTS
from ragents.contracts import Engine
from ragents.engines.native import NativeEngine
from ragents.errors import AuthError, ProviderAccessError


def resolve_connection(connection: ConnectionSpec) -> tuple[str, str]:
    if connection.provider == "chatgpt":
        raise AuthError("ChatGPT için API anahtarı kullanılmaz; auth login chatgpt ile giriş yapın.")
    if connection.provider == "ollama":
        endpoint = str(connection.base_url or "http://localhost:11434/v1")
        key = "ollama-local"
    else:
        endpoint = FIXED_ENDPOINTS[connection.provider]
        key = ""
    env_name = connection.api_key_env
    if env_name:
        key = os.environ.get(env_name, "").strip()
    if not key:
        raise ValueError(f"API anahtarı eksik: {env_name or 'api_key_env tanımlayın'}")
    return endpoint, key


@asynccontextmanager
async def open_engine(connection: ConnectionSpec) -> AsyncIterator[Engine]:
    try:
        async with _open_engine(connection) as engine:
            yield engine
    except CredentialsPersistenceError:
        raise AuthError("ChatGPT oturumu yenilendi ancak kaydedilemedi. Kasayı kontrol edip yeniden giriş yapın.") from None
    except CredentialsRefreshError:
        raise AuthError("ChatGPT oturumu yenilenemedi; bağlantınızı kontrol edip yeniden giriş yapın.") from None
    except ModelHTTPError as error:
        raise ProviderAccessError(error.status_code) from None


@asynccontextmanager
async def _open_engine(connection: ConnectionSpec) -> AsyncIterator[Engine]:
    if connection.provider == "chatgpt":
        async with open_chatgpt_engine(connection) as engine:
            yield engine
        return
    endpoint, key = resolve_connection(connection)
    async with AsyncOpenAI(
        base_url=endpoint, api_key=key, max_retries=0, timeout=60,
    ) as client:
        model_type = OpenAIResponsesModel if connection.wire_api == "responses" else OpenAIChatModel
        model = model_type(
            connection.model, provider=OpenAIProvider(openai_client=client),
        )
        yield NativeEngine(model)


@asynccontextmanager
async def open_chatgpt_engine(connection: ConnectionSpec) -> AsyncIterator[Engine]:
    store = ChatGPTStore(connection.oauth_account or "default")
    async with async_account_guard(store.account, store.root):
        credentials = await store.load()
        if credentials is None:
            raise AuthError("Önce ragents auth login chatgpt komutuyla giriş yapın.")
        if not credentials.plan_usage_granted:
            raise AuthError("ChatGPT plan kullanma izni verilmemiş; auth login chatgpt ile yeniden izin verin.")
        provider = OpenAIChatGPTProvider(credential_source=store)
        provider.client.max_retries = 0
        async with provider.client:
            model = OpenAIResponsesModel(connection.model, provider=provider)
            yield NativeEngine(model, request_token_cap=False)
