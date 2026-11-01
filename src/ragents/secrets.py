"""Profil dışındaki Windows kasasında adlandırılmış API anahtarları."""
import re

from ragents.auth import SystemVault
from ragents.errors import AuthError


class SecretStore:
    def __init__(self, vault=None):
        self.vault = vault

    def _key(self, reference):
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", reference):
            raise AuthError("Gizli bilgi referansı geçersiz.")
        from ragents.profile_paths import profile_root
        import hashlib
        profile_id = hashlib.sha256(str(profile_root()).encode()).hexdigest()[:32]
        return f"api:{profile_id}:{reference}"

    def get(self, reference):
        key = self._key(reference)
        return (self.vault or SystemVault()).get(key)

    def set(self, reference, value):
        from ragents.profile_paths import profile_root
        if (profile_root() / "locks/maintenance.flag").exists():
            raise AuthError("Profil bakım modunda; anahtar kaydı geçici olarak kapalı.")
        key = self._key(reference)
        if not value.strip() or len(value) > 2048 or "\n" in value or "\r" in value:
            raise AuthError("API anahtarı boş, çok uzun veya geçersiz.")
        (self.vault or SystemVault()).set(key, value)
