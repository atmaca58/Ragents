import pytest

from ragents.search import SearchConnection, SearchService
from ragents.web_tools import WebAccessError


def test_search_quota_error_does_not_fall_back(monkeypatch):
    monkeypatch.setenv("TEST_TAVILY_KEY", "secret")
    calls = []
    class Client:
        def json_request(self, url, **kwargs):
            calls.append(url)
            raise WebAccessError("Sağlayıcı kotası doldu")
    service = SearchService(SearchConnection(provider="tavily", api_key_env="TEST_TAVILY_KEY"), client=Client())
    with pytest.raises(WebAccessError, match="kotası"):
        service.search("araştır")
    assert calls == ["https://api.tavily.com/search"]
