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
from pydantic import ValidationError
from ragents.web_tools import WebResponse


def test_keyless_provider_rejects_credentials():
    with pytest.raises(ValidationError):
        SearchConnection(provider='exa_free', secret_ref='not-for-keyless')


def test_keyless_search_configuration_needs_no_secret(tmp_path, capsys):
    from ragents.cli import main
    from ragents.search import search_connection
    assert main(['search', '--root', str(tmp_path), 'configure', '--provider', 'exa_free']) == 0
    assert search_connection(tmp_path).provider == 'exa_free'
    assert search_connection(tmp_path).secret_ref is None


def test_free_ring_uses_only_named_keyless_endpoints_and_reports_attempts():
    import json
    from ragents.search_keyless import ENDPOINTS
    calls = []
    class Client:
        def request(self, url, **kwargs):
            calls.append((url, kwargs))
            if len(calls) == 1:
                raise WebAccessError('quota')
            body = {'jsonrpc': '2.0', 'id': 1, 'result': {'content': [{'type': 'text', 'text': json.dumps({'results': [{'title': 'Evidence', 'url': 'https://example.org', 'excerpts': ['source']} ]})}]}}
            return url, WebResponse(200, {'content-type': 'application/json'}, json.dumps(body).encode())
    result = SearchService(SearchConnection(provider='keyless'), client=Client()).search('Python')
    assert result['provider'] == 'parallel_free'
    assert result['selected_provider'] == 'keyless'
    assert result['attempts'] == [{'provider': 'exa_free', 'status': 'failed', 'reason': 'quota'}, {'provider': 'parallel_free', 'status': 'succeeded'}]
    assert [url for url, _ in calls] == [ENDPOINTS['exa_free'][0], ENDPOINTS['parallel_free'][0]]
    for _, kwargs in calls:
        assert 'Authorization' not in kwargs['headers']
        arguments = json.loads(kwargs['body'])['params']['arguments']
        assert 'model_name' not in arguments


def test_searxng_does_not_switch_without_explicit_fallback():
    calls = []
    class Client:
        def json_request(self, url, **kwargs):
            calls.append(url)
            raise WebAccessError('quota')
        def request(self, *args, **kwargs):
            pytest.fail('Unauthorized fallback')
    with pytest.raises(WebAccessError):
        SearchService(SearchConnection(provider='searxng', endpoint='https://search.example.org'), client=Client()).search('Python')
    assert len(calls) == 1


def test_explicit_searxng_fallback_never_forwards_primary_credentials(monkeypatch):
    import json
    monkeypatch.setenv('TEST_SEARCH_TOKEN', 'primary-secret')
    class Client:
        def json_request(self, url, **kwargs):
            assert kwargs['headers'] == {'Authorization': 'Bearer primary-secret'}
            raise WebAccessError('quota')
        def request(self, url, **kwargs):
            assert 'primary-secret' not in str(kwargs)
            payload = {'jsonrpc': '2.0', 'id': 1, 'result': {'content': [{'type': 'text', 'text': 'Title: Docs\nURL: https://example.org\nHighlights: Content'}]}}
            return url, WebResponse(200, {}, json.dumps(payload).encode())
    result = SearchService(SearchConnection(provider='searxng', endpoint='https://search.example.org', api_key_env='TEST_SEARCH_TOKEN', keyless_fallback=True), client=Client()).search('Python')
    assert result['provider'] == 'exa_free'
    assert len(result['attempts']) == 2


@pytest.mark.parametrize('payload', [
    {'id': 1, 'error': {'message': 'quota'}},
    {'id': 1, 'result': {'isError': True, 'content': [{'type': 'text', 'text': 'quota'}]}},
    {'id': 99, 'result': {'content': [{'type': 'text', 'text': 'wrong request'}]}},
])
def test_mcp_errors_and_unrelated_replies_are_not_success(payload):
    import json
    from ragents.search_keyless import parse_mcp_response
    with pytest.raises(WebAccessError):
        parse_mcp_response(json.dumps(payload).encode())


def test_sse_mcp_preserves_unicode_line_separator():
    import json
    from ragents.search_keyless import parse_mcp_response
    text = 'Türkçe\u2028日本語'
    payload = {'id': 1, 'result': {'content': [{'type': 'text', 'text': text}]}}
    wire = ('event: message\r\ndata: ' + json.dumps(payload, ensure_ascii=False) + '\r\n\r\n').encode()
    assert parse_mcp_response(wire) == text


def test_all_free_providers_failing_is_bounded():
    from ragents.search_keyless import KEYLESS_PROVIDERS
    calls = []
    class Client:
        def request(self, url, **kwargs):
            calls.append(url)
            raise WebAccessError('quota')
    with pytest.raises(WebAccessError, match='Ücretli servise geçilmedi'):
        SearchService(SearchConnection(provider='keyless'), client=Client()).search('Python')
    assert len(calls) == len(KEYLESS_PROVIDERS)


@pytest.mark.parametrize("provider", ["duckduckgo", "firecrawl_free"])
def test_removed_experimental_providers_cannot_be_configured(provider):
    with pytest.raises(ValidationError):
        SearchConnection(provider=provider)
