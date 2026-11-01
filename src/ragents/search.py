"""Açık seçilmiş sağlayıcılar; yalnız izinli anahtarsız yedek, ücretli geçiş yok."""
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Literal, get_args
from urllib.parse import urlencode, urlsplit

from pydantic import Field, model_validator

from ragents.catalog import _write_atomic
from ragents.config import Spec
from ragents.profile_paths import profile_root
from ragents.web_tools import SafeWebClient, WebAccessError
from ragents.secrets import SecretStore
from ragents.search_keyless import KEYLESS_PROVIDERS, keyless_search


SearchProvider = Literal["disabled", "duckduckgo", "tavily", "brave", "searxng", "keyless", "exa_free", "parallel_free", "firecrawl_free", "keenable_free"]
SEARCH_PROVIDERS = get_args(SearchProvider)


class SearchConnection(Spec):
    schema_version: Literal[1] = 1
    provider: SearchProvider = "disabled"
    keyless_fallback: bool = False
    endpoint: str | None = Field(default=None, max_length=2048)
    api_key_env: str | None = Field(default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    secret_ref: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")

    @model_validator(mode="after")
    def validate_provider(self):
        if self.provider in ("duckduckgo", "keyless", *KEYLESS_PROVIDERS) and (self.api_key_env or self.secret_ref):
            raise ValueError("Seçilen sağlayıcı anahtarsızdır; anahtar kaynağı tanımlamayın.")
        if self.keyless_fallback and self.provider in ("disabled", "keyless", *KEYLESS_PROVIDERS):
            raise ValueError("Bu sağlayıcı için ek anahtarsız yedek seçimi geçersiz.")
        if self.api_key_env and self.secret_ref:
            raise ValueError("Anahtar kaynağı olarak ortam veya kasa seçin.")
        if self.provider == "searxng":
            parsed = urlsplit(self.endpoint or "")
            if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                    or parsed.query or parsed.fragment):
                raise ValueError("SearXNG adresi kimlik bilgisi içermeyen HTTPS adresi olmalıdır.")
        elif self.endpoint is not None:
            raise ValueError("Özel arama adresi yalnız SearXNG için kullanılabilir.")
        return self


def search_connection(root: Path | None = None):
    path = profile_root(root) / "connections/search.json"
    return SearchConnection.model_validate_json(path.read_bytes()) if path.is_file() else SearchConnection()


def save_search_connection(root: Path, connection: SearchConnection):
    _write_atomic(profile_root(root) / "connections/search.json", connection.model_dump_json())


class SearchService:
    def __init__(self, connection: SearchConnection, *, client=None, secrets=None):
        self.connection = connection
        self.client = client or SafeWebClient()
        self.secrets = secrets or SecretStore()

    def search(self, query: str, *, count: int = 5):
        if not query.strip() or len(query) > 1000 or not 1 <= count <= 10:
            raise WebAccessError("Arama metni veya sonuç sayısı geçersiz.")
        connection = self.connection
        providers = list(KEYLESS_PROVIDERS) if connection.provider == "keyless" else [connection.provider]
        if connection.keyless_fallback:
            providers.extend(KEYLESS_PROVIDERS)
        attempts = []
        for provider in providers:
            selected = (connection.model_copy(update={"keyless_fallback": False}) if provider == connection.provider else
                        SearchConnection(provider=provider))
            try:
                result = SearchService(selected, client=self.client, secrets=self.secrets)._search_once(query, count=count)
            except WebAccessError as error:
                attempts.append({"provider": provider, "status": "failed", "reason": str(error)[:300]})
                if len(providers) == 1:
                    raise
                continue
            attempts.append({"provider": provider, "status": "succeeded"})
            return {**result, "selected_provider": connection.provider, "attempts": attempts}
        raise WebAccessError("İzin verilen ücretsiz arama kaynakları yanıt vermedi: " + ", ".join(providers) + ". Ücretli servise geçilmedi.")

    def _search_once(self, query: str, *, count: int = 5):
        if not query.strip() or len(query) > 1000 or not 1 <= count <= 10:
            raise WebAccessError("Arama metni veya sonuç sayısı geçersiz.")
        connection = self.connection
        if connection.provider == "disabled":
            raise WebAccessError("Web arama bağlı değil; yerel yönetimde sağlayıcı seçin.")
        key = (os.environ.get(connection.api_key_env, "") if connection.api_key_env else
               self.secrets.get(connection.secret_ref) if connection.secret_ref else "")
        if connection.provider in ("tavily", "brave") and not key:
            raise WebAccessError("Arama sağlayıcısının API anahtarı eksik.")
        if connection.provider in KEYLESS_PROVIDERS:
            items = keyless_search(self.client, connection.provider, query, count)
        elif connection.provider == "duckduckgo":
            from ragents.search_duckduckgo import search_duckduckgo
            items = search_duckduckgo(self.client, query, count)
        elif connection.provider == "tavily":
            payload = self.client.json_request("https://api.tavily.com/search", method="POST",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                payload={"query": query, "max_results": count, "search_depth": "basic", "include_answer": False})
            items = payload.get("results", [])
        elif connection.provider == "brave":
            payload = self.client.json_request("https://api.search.brave.com/res/v1/web/search?" + urlencode({"q": query, "count": count}),
                                               headers={"X-Subscription-Token": key})
            items = payload.get("web", {}).get("results", [])
        else:
            payload = self.client.json_request(connection.endpoint.rstrip("/") + "/search?" + urlencode({"q": query, "format": "json"}),
                headers={"Authorization": f"Bearer {key}"} if key else {})
            items = payload.get("results", [])
        if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
            raise WebAccessError("Arama sağlayıcısı geçerli sonuç listesi vermedi.")
        retrieved = datetime.now(timezone.utc).isoformat()
        results = []
        for item in items[:count]:
            url = item.get("url", "")
            if not isinstance(url, str):
                continue
            try:
                parsed = urlsplit(url)
            except ValueError:
                continue
            if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
                continue
            results.append({"title": str(item.get("title", ""))[:300], "url": item["url"][:4096],
                "content": str(item.get("content", item.get("description", "")))[:2000],
                "published_at": item.get("published_date", item.get("age")), "retrieved_at": retrieved})
        return {"provider": connection.provider, "results": results, "untrusted_content": True,
                "experimental": connection.provider in ("duckduckgo", "firecrawl_free")}
