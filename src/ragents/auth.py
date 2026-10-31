import asyncio
from collections.abc import Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import asdict
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Protocol
import uuid

from cryptography.fernet import Fernet, InvalidToken
from filelock import FileLock, Timeout
from pydantic import TypeAdapter
from pydantic_ai.providers.openai_chatgpt import OpenAIChatGPTCredentials

from ragents.errors import AuthError


class Vault(Protocol):
    def get(self, name: str) -> str | None: ...
    def set(self, name: str, value: str) -> None: ...


class SystemVault:
    def __init__(self):
        import keyring

        backend = keyring.get_keyring()
        candidates = getattr(backend, "backends", [backend])
        trusted = {"Windows", "macOS", "SecretService", "kwallet", "libsecret"}
        self.backend = next((item for item in candidates
                             if type(item).__module__ in {f"keyring.backends.{name}" for name in trusted}), None)
        if self.backend is None:
            raise AuthError("Güvenli işletim sistemi kimlik kasası bulunamadı. Düz metin depolama kullanılmaz.")

    def get(self, name: str) -> str | None:
        try:
            return self.backend.get_password("R Agents ChatGPT", name)
        except Exception:
            raise AuthError("İşletim sistemi kimlik kasası okunamadı.") from None

    def set(self, name: str, value: str) -> None:
        try:
            self.backend.set_password("R Agents ChatGPT", name, value)
        except Exception:
            raise AuthError("İşletim sistemi kimlik kasasına yazılamadı.") from None


def auth_root() -> Path:
    return Path(os.environ.get("RAGENTS_HOME", str(Path.home() / ".ragents"))).resolve()


def validate_account(account: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", account):
        raise AuthError("Hesap etiketi küçük harf, sayı ve tire içermeli; en fazla 64 karakter olmalıdır.")
    return account


def account_lock(account: str, root: Path | None = None) -> FileLock:
    directory = (root or auth_root()) / "locks"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    return FileLock(directory / f"chatgpt-{validate_account(account)}.lock")


@contextmanager
def account_guard(account: str, root: Path | None = None) -> Iterator[None]:
    lock = account_lock(account, root)
    try:
        lock.acquire(timeout=0)
    except Timeout:
        raise AuthError("Bu ChatGPT hesabı başka bir R Agents işleminde kullanılıyor; işlem bitince tekrar deneyin.") from None
    try:
        yield
    finally:
        lock.release()


@asynccontextmanager
async def async_account_guard(account: str, root: Path | None = None):
    lock = account_lock(account, root)
    while True:
        try:
            lock.acquire(timeout=0)
            break
        except Timeout:
            await asyncio.sleep(0.1)
    try:
        yield
    finally:
        lock.release()


class ChatGPTStore:
    """Çağıran, yükleme–yenileme–kaydetme boyunca account_guard tutmalıdır."""

    def __init__(self, account: str = "default", *, vault: Vault | None = None, root: Path | None = None):
        self.account = validate_account(account)
        self.root = root or auth_root()
        self.path = self.root / "auth" / f"chatgpt-{self.account}.enc"
        self._vault = vault

    def cipher(self) -> Fernet:
        if self._vault is None:
            self._vault = SystemVault()
        name = f"{self.account}:encryption-key"
        key = self._vault.get(name)
        if key is None:
            if self.path.exists():
                raise AuthError("ChatGPT oturumunun şifreleme anahtarı bulunamadı; yeniden giriş yapın.")
            key = Fernet.generate_key().decode("ascii")
            self._vault.set(name, key)
        return Fernet(key.encode("ascii"))

    async def save(self, credentials: OpenAIChatGPTCredentials) -> None:
        payload = json.dumps(asdict(credentials)).encode("utf-8")
        encrypted = await asyncio.to_thread(lambda: self.cipher().encrypt(payload))
        atomic_write(self.path, encrypted)

    async def load(self) -> OpenAIChatGPTCredentials | None:
        if not self.path.exists():
            return None
        try:
            payload = await asyncio.to_thread(lambda: self.cipher().decrypt(self.path.read_bytes()))
            return TypeAdapter(OpenAIChatGPTCredentials).validate_json(payload)
        except (InvalidToken, ValueError):
            raise AuthError("ChatGPT oturumu okunamadı; yeniden giriş yapın.") from None

    def logout(self) -> None:
        self.path.unlink(missing_ok=True)


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            temporary.chmod(0o600)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            stream.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def get_host_id(root: Path | None = None) -> str:
    root = root or auth_root()
    directory = root / "locks"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with FileLock(directory / "installation.lock", timeout=0):
        path = root / "auth" / "host-id"
        if path.exists():
            return uuid.UUID(path.read_text(encoding="ascii")).urn
        host_id = uuid.uuid4().urn
        atomic_write(path, host_id.encode("ascii"))
        return host_id
