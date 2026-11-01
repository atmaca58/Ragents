import asyncio
import hashlib
import base64
import pytest

from mcp.server.auth.provider import AuthorizationParams, TokenError
from mcp.shared.auth import OAuthClientInformationFull
from ragents.remote_oauth import RemoteOAuthProvider


class Vault:
    def __init__(self):
        self.values = {}
    def get(self, name):
        return self.values.get(name)
    def set(self, name, value):
        self.values[name] = value


def test_remote_grant_needs_local_consent_is_single_use_and_revocable(tmp_path):
    provider = RemoteOAuthProvider(tmp_path, "https://agents.example.test", vault=Vault())
    client = OAuthClientInformationFull(client_id="desktop", client_name="MCP Client",
        redirect_uris=["https://client.example.test/callback"], token_endpoint_auth_method="none")

    async def scenario():
        await provider.register_client(client)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(b"verifier").digest()).decode().rstrip("=")
        url = await provider.authorize(client, AuthorizationParams(state="state", scopes=["read"],
            code_challenge=challenge, redirect_uri=client.redirect_uris[0],
            redirect_uri_provided_explicitly=True, resource=provider.resource))
        identity = url.rsplit("/", 1)[1]
        assert provider.complete(identity) is None
        pending = provider.pending()[0]
        provider.approve_local(identity, pending["operation_hash"])
        redirect = provider.complete(identity)
        from urllib.parse import urlsplit, parse_qs
        code = parse_qs(urlsplit(redirect).query)["code"][0]
        loaded = await provider.load_authorization_code(client, code)
        token = await provider.exchange_authorization_code(client, loaded)
        assert (await provider.load_access_token(token.access_token)).resource == provider.resource
        assert await provider.load_authorization_code(client, code) is None
        access = await provider.load_access_token(token.access_token)
        await provider.revoke_token(access)
        assert await provider.load_access_token(token.access_token) is None
        assert await provider.load_refresh_token(client, token.refresh_token) is None
        assert token.access_token.encode() not in (tmp_path / "auth/mcp-server.enc").read_bytes()

    asyncio.run(scenario())


def test_remote_http_rejects_unauthenticated_mcp_and_advertises_oauth(tmp_path):
    from starlette.testclient import TestClient
    from ragents.mcp_server import create_server
    from ragents.mcp_http_server import management_app
    from ragents.storage import TaskStore
    provider = RemoteOAuthProvider(tmp_path, "https://agents.example.test", vault=Vault())
    server = create_server(TaskStore(tmp_path / "data/ragents.db"), {}, root=tmp_path, remote_provider=provider)
    with TestClient(management_app(server, remote_provider=provider), base_url=provider.issuer) as client:
        response = client.post("/mcp", json={"jsonrpc": "2.0", "method": "initialize", "id": 1})
        assert response.status_code == 401
        assert "oauth-protected-resource" in response.headers["www-authenticate"]
        metadata = client.get("/.well-known/oauth-authorization-server")
        assert metadata.status_code == 200
        assert metadata.json()["issuer"] == provider.issuer


def test_read_scope_cannot_execute_tools(tmp_path):
    from types import SimpleNamespace
    from mcp.server.auth.middleware.auth_context import auth_context_var
    from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
    from mcp.shared.exceptions import MCPError
    from ragents.mcp_authorization import ScopeMiddleware
    from mcp.server.auth.provider import AccessToken
    token = AccessToken(token="read-token", client_id="client", scopes=["read"])
    class Provider:
        async def load_access_token(self, value):
            return token
    async def scenario():
        async def next_call(ctx):
            return {"allowed": True}
        context = auth_context_var.set(AuthenticatedUser(token))
        try:
            with pytest.raises(MCPError, match="yetkisi"):
                await ScopeMiddleware(Provider())(SimpleNamespace(method="tools/call", params={"name": "start_team"}), next_call)
            assert await ScopeMiddleware(Provider())(SimpleNamespace(method="tools/call", params={"name": "list_agents"}), next_call)
        finally:
            auth_context_var.reset(context)
    asyncio.run(scenario())


def test_sdk_token_endpoint_checks_pkce_and_resource(tmp_path):
    from starlette.testclient import TestClient
    from urllib.parse import parse_qs, urlsplit
    from ragents.mcp_server import create_server
    from ragents.mcp_http_server import management_app
    from ragents.storage import TaskStore
    provider = RemoteOAuthProvider(tmp_path, "https://agents.example.test", vault=Vault())
    client = OAuthClientInformationFull(client_id="desktop", redirect_uris=["https://client.example.test/callback"],
                                        token_endpoint_auth_method="none", scope="read")
    verifier = "a" * 64
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    async def grant():
        await provider.register_client(client)
        url = await provider.authorize(client, AuthorizationParams(state="state", scopes=["read"],
            code_challenge=challenge, redirect_uri=client.redirect_uris[0],
            redirect_uri_provided_explicitly=True, resource=provider.resource))
        pending = provider.pending()[0]
        provider.approve_local(pending["id"], pending["operation_hash"])
        return parse_qs(urlsplit(provider.complete(pending["id"])).query)["code"][0]
    code = asyncio.run(grant())
    server = create_server(TaskStore(tmp_path / "data/ragents.db"), {}, root=tmp_path, remote_provider=provider)
    with TestClient(management_app(server, remote_provider=provider), base_url=provider.issuer) as http:
        data = {"grant_type": "authorization_code", "code": code, "client_id": "desktop",
                "redirect_uri": str(client.redirect_uris[0]), "resource": provider.resource,
                "code_verifier": "b" * 64}
        assert http.post("/token", data=data).status_code == 400
        data["code_verifier"] = verifier
        response = http.post("/token", data=data)
        assert response.status_code == 200, response.text
        assert response.json()["access_token"]
        assert http.post("/token", data=data).status_code == 400
