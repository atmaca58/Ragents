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
from types import SimpleNamespace

from pydantic import ValidationError
from ragents.web_tools import SafeWebClient, WebResponse


def ddg_service(html, *, status=200):
    calls = []
    def transport(url, address, method, headers, body):
        calls.append((url, headers))
        return WebResponse(status, {'content-type': 'text/html; charset=UTF-8'}, html.encode())
    client = SafeWebClient(resolver=lambda *_: ['8.8.8.8'], transport=transport)
    return SearchService(SearchConnection(provider='duckduckgo'), client=client), calls


def test_keyless_search_normalizes_results_without_credentials():
    service, calls = ddg_service('''<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fdocs">Python <b>docs</b></a>
        <a class="result__snippet">A &amp; B</a>
        <a class="result__a" href="javascript:alert(1)">Bad</a>''')
    result = service.search('Türkçe & Python')
    assert len(calls) == 1 and calls[0][1] == {}
    assert '%26' in calls[0][0]
    assert result['experimental'] and result['untrusted_content']
    assert len(result['results']) == 1
    item = result['results'][0]
    assert item['url'] == 'https://example.org/docs'
    assert item['title'] == 'Python docs' and item['content'] == 'A & B'
    assert item['retrieved_at'] and item['published_at'] is None


@pytest.mark.parametrize('html,status', [('<form id="challenge-form"></form>', 200), ('blocked', 202), ('unexpected layout', 200)])
def test_keyless_block_or_changed_format_fails_without_fallback(html, status):
    service, calls = ddg_service(html, status=status)
    with pytest.raises(WebAccessError):
        service.search('Python')
    assert len(calls) == 1


def test_keyless_real_empty_results_are_not_format_failure():
    service, _ = ddg_service('<div class="no-results">No results</div>')
    assert service.search('unknown query')['results'] == []


def test_keyless_provider_rejects_credentials():
    with pytest.raises(ValidationError):
        SearchConnection(provider='duckduckgo', secret_ref='not-for-ddg')


def test_keyless_search_configuration_needs_no_secret(tmp_path, capsys):
    from ragents.cli import main
    from ragents.search import search_connection
    assert main(['search', '--root', str(tmp_path), 'configure', '--provider', 'duckduckgo']) == 0
    assert search_connection(tmp_path).provider == 'duckduckgo'
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
