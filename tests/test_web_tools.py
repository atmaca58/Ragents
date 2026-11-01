import pytest

from ragents.web_tools import SafeWebClient, WebAccessError


def test_fetch_rejects_private_destinations_before_transport():
    calls = []
    client = SafeWebClient(resolver=lambda host, port: ["127.0.0.1"],
                           transport=lambda *args: calls.append(args))
    with pytest.raises(WebAccessError, match="Özel"):
        client.read_page("https://public-looking.test/page")
    assert not calls


def test_redirect_is_resolved_again_and_does_not_reach_private_host():
    from ragents.web_tools import WebResponse
    calls = []
    def transport(url, address, method, headers, body):
        calls.append(url)
        return WebResponse(302, {"location": "http://127.0.0.1/private"}, b"")
    client = SafeWebClient(resolver=lambda host, port: ["127.0.0.1" if host == "127.0.0.1" else "93.184.216.34"],
                           transport=transport)
    with pytest.raises(WebAccessError, match="Özel"):
        client.read_page("http://public.test/")
    assert calls == ["http://public.test/"]


def test_page_content_strips_scripts_and_preserves_source():
    from ragents.web_tools import WebResponse
    client = SafeWebClient(resolver=lambda *args: ["93.184.216.34"], transport=lambda *args:
        WebResponse(200, {"content-type": "text/html"}, b"<h1>Source</h1><script>EVIL</script><p>Evidence</p>"))
    page = client.read_page("https://public.test/report")
    assert page["url"] == "https://public.test/report"
    assert page["untrusted_content"]
    assert "Evidence" in page["content"] and "EVIL" not in page["content"]


def test_local_development_grant_is_exact_host_and_port():
    from ragents.web_tools import WebResponse
    calls = []
    def transport(url, *args):
        calls.append(url)
        return WebResponse(200, {"content-type": "text/plain"}, b"local app")
    client = SafeWebClient(allowed_local=("http://127.0.0.1:3000",),
                           resolver=lambda *args: ["127.0.0.1"], transport=transport)
    assert client.read_page("http://127.0.0.1:3000/health")["content"] == "local app"
    with pytest.raises(WebAccessError):
        client.read_page("http://127.0.0.1:3001/private")
    assert len(calls) == 1
