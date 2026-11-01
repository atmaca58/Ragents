"""MCP SDK OAuth sunucusu; bağlantı izni yalnız yerel terminalden gelir."""
from contextlib import contextmanager
import json
from pathlib import Path
import secrets
import time
from urllib.parse import urlsplit, urlencode

from filelock import FileLock
from mcp.server.auth.provider import AccessToken, AuthorizationCode, RefreshToken, AuthorizeError, TokenError, RegistrationError
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from ragents.auth import ChatGPTStore, atomic_write
from ragents.operation_hash import digest
from ragents.storage import TaskStateError


SCOPES = ("read", "configure", "manage", "execute", "publish")


class RemoteOAuthProvider:
    def __init__(self, root: Path, public_url: str, *, vault=None):
        parsed = urlsplit(public_url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
            raise TaskStateError("Uzak MCP için kök HTTPS dış adresi gereklidir.")
        self.issuer = public_url.rstrip("/")
        self.resource = self.issuer + "/mcp"
        self.root = root.resolve()
        self.credentials = ChatGPTStore("mcp-server", root=self.root, vault=vault)
        self.path = self.root / "auth/mcp-server.enc"
        self.lock = FileLock(self.root / "locks/mcp-oauth.lock", timeout=5)

    @contextmanager
    def state(self):
        self.root.joinpath("locks").mkdir(parents=True, exist_ok=True)
        with self.lock:
            if (self.root / "locks/maintenance.flag").exists():
                raise TaskStateError("Profil güncelleniyor; uzak bağlantı geçici olarak kapalı.")
            cipher = self.credentials.cipher()
            data = json.loads(cipher.decrypt(self.path.read_bytes())) if self.path.exists() else {
                "clients": {}, "pending": {}, "codes": {}, "access": {}, "refresh": {}}
            yield data
            atomic_write(self.path, cipher.encrypt(json.dumps(data, ensure_ascii=False).encode()))

    async def get_client(self, client_id):
        with self.state() as data:
            client = data["clients"].get(client_id)
        return OAuthClientInformationFull.model_validate(client) if client else None

    async def register_client(self, client_info):
        for redirect in client_info.redirect_uris or ():
            parsed = urlsplit(str(redirect))
            if (parsed.username or parsed.password or parsed.fragment or not parsed.hostname
                    or parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "::1"))):
                raise RegistrationError("invalid_redirect_uri", "HTTPS veya yerel loopback callback gereklidir.")
        if not client_info.redirect_uris:
            raise RegistrationError("invalid_redirect_uri")
        with self.state() as data:
            if len(data["clients"]) >= 100 or client_info.client_id in data["clients"]:
                raise RegistrationError("invalid_client_metadata", "İstemci kayıt sınırı veya kimlik çakışması.")
            data["clients"][client_info.client_id] = client_info.model_dump(mode="json")

    async def authorize(self, client, params):
        scopes = params.scopes or ["read"]
        if not set(scopes) <= set(SCOPES) or "read" not in scopes:
            raise AuthorizeError("invalid_scope")
        if params.resource != self.resource:
            raise AuthorizeError("invalid_target")
        if params.redirect_uri not in (client.redirect_uris or ()):
            raise AuthorizeError("invalid_request")
        identity = secrets.token_urlsafe(32)
        grant = {"client_id": client.client_id, "client_name": client.client_name,
                 "params": params.model_dump(mode="json"), "scopes": scopes,
                 "expires_at": time.time() + 300, "status": "pending"}
        grant["operation_hash"] = digest(grant)
        with self.state() as data:
            data["pending"] = {key: value for key, value in data["pending"].items() if value["expires_at"] > time.time()}
            if len(data["pending"]) >= 50:
                raise AuthorizeError("temporarily_unavailable")
            data["pending"][identity] = grant
        return self.issuer + "/oauth/pending/" + identity

    def pending(self):
        with self.state() as data:
            return [{"id": identity, "client_name": value["client_name"], "client_id": value["client_id"],
                     "redirect_uri": value["params"]["redirect_uri"], "scopes": value["scopes"],
                     "expires_at": value["expires_at"], "operation_hash": value["operation_hash"]}
                    for identity, value in data["pending"].items()
                    if value["status"] == "pending" and value["expires_at"] > time.time()]

    def approve_local(self, identity, operation_hash):
        with self.state() as data:
            grant = data["pending"].get(identity)
            if (grant is None or grant["status"] != "pending" or grant["expires_at"] <= time.time()
                    or not secrets.compare_digest(grant["operation_hash"], operation_hash)):
                raise TaskStateError("Bağlantı onayı geçersiz veya süresi dolmuş.")
            grant["status"] = "approved"
            code = secrets.token_urlsafe(32)
            grant["code"] = code
            params = grant["params"]
            data["codes"][code] = AuthorizationCode(code=code, scopes=grant["scopes"], expires_at=time.time() + 120,
                client_id=grant["client_id"], code_challenge=params["code_challenge"],
                redirect_uri=params["redirect_uri"], redirect_uri_provided_explicitly=params["redirect_uri_provided_explicitly"],
                resource=self.resource, subject="local-owner").model_dump(mode="json")

    def complete(self, identity):
        with self.state() as data:
            grant = data["pending"].get(identity)
            if not grant or grant["expires_at"] <= time.time():
                raise TaskStateError("Bağlantı talebinin süresi doldu.")
            if grant["status"] != "approved":
                return None
            params = grant["params"]
            query = {"code": grant["code"], "iss": self.issuer}
            if params["state"] is not None:
                query["state"] = params["state"]
            return params["redirect_uri"] + ("&" if "?" in params["redirect_uri"] else "?") + urlencode(query)

    async def load_authorization_code(self, client, authorization_code):
        with self.state() as data:
            code = data["codes"].get(authorization_code)
            if code and code["client_id"] == client.client_id and code["expires_at"] > time.time():
                return AuthorizationCode.model_validate(code)

    def _issue(self, data, client_id, scopes, *, family=None):
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        family = family or secrets.token_urlsafe(16)
        common = {"client_id": client_id, "scopes": scopes, "resource": self.resource,
                  "subject": "local-owner", "family": family}
        data["access"][access] = {**common, "expires_at": int(time.time()) + 600}
        data["refresh"][refresh] = {**common, "expires_at": int(time.time()) + 7 * 86400}
        return OAuthToken(access_token=access, refresh_token=refresh, expires_in=600,
                          token_type="Bearer", scope=" ".join(scopes))

    async def exchange_authorization_code(self, client, authorization_code):
        with self.state() as data:
            code = data["codes"].pop(authorization_code.code, None)
            if not code or code["client_id"] != client.client_id or code["expires_at"] <= time.time():
                raise TokenError("invalid_grant")
            token = self._issue(data, client.client_id, code["scopes"])
        return token

    async def load_refresh_token(self, client, refresh_token):
        with self.state() as data:
            value = data["refresh"].get(refresh_token)
            if value and value["client_id"] == client.client_id and value["expires_at"] > time.time():
                return RefreshToken(token=refresh_token, **{key: item for key, item in value.items() if key != "family"})

    async def exchange_refresh_token(self, client, refresh_token, scopes):
        with self.state() as data:
            value = data["refresh"].get(refresh_token.token)
            if (not value or value["client_id"] != client.client_id or value["expires_at"] <= time.time()
                    or not set(scopes) <= set(value["scopes"])):
                raise TokenError("invalid_grant")
            self._revoke_family(data, value["family"])
            return self._issue(data, client.client_id, scopes, family=value["family"])

    async def load_access_token(self, token):
        with self.state() as data:
            value = data["access"].get(token)
            if value and value["expires_at"] > time.time():
                return AccessToken(token=token, **{key: item for key, item in value.items() if key != "family"})

    def _revoke_family(self, data, family):
        for collection in ("access", "refresh"):
            data[collection] = {key: value for key, value in data[collection].items() if value["family"] != family}

    async def revoke_token(self, token):
        with self.state() as data:
            value = data["access"].get(token.token) or data["refresh"].get(token.token)
            if value:
                self._revoke_family(data, value["family"])
