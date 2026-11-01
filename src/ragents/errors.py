class ContextLimitError(RuntimeError):
    def __init__(self):
        super().__init__("Görev bağlam sınırını aşıyor. Görevi küçültün veya bağlam sınırını artırın.")


class InstructionError(RuntimeError):
    """Kullanıcıya gösterilebilir talimat, proje veya skill hatası."""


class WorkspaceError(RuntimeError):
    """Kullanıcıya gösterilebilir workspace, dosya erişimi veya artifact hatası."""


class SandboxError(RuntimeError):
    """Kullanıcıya gösterilebilir sandbox politikası veya yürütme hatası."""


class AuthError(RuntimeError):
    """Yalnız güvenli, kullanıcıya gösterilebilir kimlik hataları."""


class ProviderAccessError(RuntimeError):
    def __init__(self, status_code: int):
        hints = {
            401: "Anahtarı veya OAuth oturumunu kontrol edin.",
            403: "Hesap, plan ve model erişim iznini kontrol edin.",
            429: "Kullanım/kapasite limitini kontrol edip daha sonra yeniden deneyin.",
        }
        super().__init__(f"Model sağlayıcısı isteği reddetti (HTTP {status_code}). "
                         + hints.get(status_code, "Sağlayıcının durumunu kontrol edin."))
        self.status_code = status_code
