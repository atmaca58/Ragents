"""Açık seçilmiş tek arama sağlayıcısı; sessiz yedek veya faturalama yok."""
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Literal
from urllib.parse import urlencode, urlsplit

from pydantic import Field, model_validator

from ragents.catalog import _write_atomic
from ragents.config import Spec
from ragents.profile_paths import profile_root
from ragents.web_tools import SafeWebClient, WebAccessError
from ragents.secrets import SecretStore


class SearchConnection(Spec):
    schema_version: Literal[1] = 1
    provider: Literal["disabled", "tavily", "brave", "searxng"] = "disabled"
    endpoint: str | None = Field(default=None, max_length=2048)
    api_key_env: str | None = Field(default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    secret_ref: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")

    @model_validator(mode="after")
    def validate_provider(self):
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
        if connection.provider == "disabled":
            raise WebAccessError("Web arama bağlı değil; yerel yönetimde sağlayıcı seçin.")
        key = (os.environ.get(connection.api_key_env, "") if connection.api_key_env else
               self.secrets.get(connection.secret_ref) if connection.secret_ref else "")
        if connection.provider in ("tavily", "brave") and not key:
            raise WebAccessError("Arama sağlayıcısının API anahtarı eksik.")
        if connection.provider == "tavily":
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
        retrieved = datetime.now(timezone.utc).isoformat()
        results = []
        for item in items[:count]:
            parsed = urlsplit(item.get("url", ""))
            if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
                continue
            results.append({"title": str(item.get("title", ""))[:300], "url": item["url"][:4096],
                "content": str(item.get("content", item.get("description", "")))[:2000],
                "published_at": item.get("published_date", item.get("age")), "retrieved_at": retrieved})
        return {"provider": connection.provider, "results": results, "untrusted_content": True}
