# R Agents V2 geliştirme rehberi

Bu dizin, kullanıcının onayladığı V2 tasarımının bağımsız uygulamasıdır.
Üst dizindeki CLI adapter / LLM SDK kullanmama kuralı `agent-runtime/` içindeki
V1 için geçerlidir. Burada Pydantic AI ve doğrudan sağlayıcı SDK'sı kullanılır.
V1 kodunu, ajanlarını veya veritabanını bu projeye taşımayın ve değiştirmeyin.

- Kaynak: `src/ragents/`; test: `tests/`; komutlar bu dizinden çalıştırılır.
- Kurulum: `.venv/Scripts/python -m pip install -e ".[dev]"`.
- Test: `.venv/Scripts/python -m pytest`. Testlerde gerçek model/ağ/CLI kullanılmaz.
- Çekirdek sözleşmeleri framework nesneleri içermez. Pydantic AI yalnız `engines/`
  ve sağlayıcı/OAuth uygulama modüllerinde; motor oluşturma `providers.py` içinde kalır.
- API anahtarları ortam değişkeninden okunur; OAuth tokenları şifreli depoda,
  şifreleme anahtarı güvenli işletim sistemi kasasında tutulur. Ayar/telemetriye yazılmaz.
- Testlerde gerçek kimlik kasası veya tarayıcı açılmaz; sahte Vault ve geçici kök kullanılır.
- Kullanıcı metinleri Türkçe, kod tanımlayıcıları İngilizcedir.
- Bir özelliğin iskeletinin bulunması, servis/MCP/sandbox desteği olduğu anlamına gelmez.
- V2 görev deposu `data/ragents.db`; `storage.py` / `task_service.py` yönetir.
  Testlerde yalnız geçici SQLite dosyaları kullanın. Görev/sonuç ürün verisi
  kalıcıdır; çalışma metadatasına ham sağlayıcı hatası veya kimlik bilgisi koymayın.
- `run --key` tamamlanmış görevin sonucunu yeniden kullanır. `tasks retry`
  yalnız sıraya alır; `recover` aktif süreç kilidini geçemez. Worker başlangıçta
  kurtarma yapar, kesilmiş/başarısız işleri otomatik tekrar çalıştırmaz.
- `worker.py` tek veritabanında tek supervisor ve sınırlı eşzamanlılık uygular.
  Testlerde canlı kuyrukta worker başlatmayın; geçici DB ve sahte runner/model kullanın.
- `mcp_server.py` V2 yönetim MCP'sidir; stdio ve salt okunur varsayılanı koruyun.
  `mcp_http_server.py` yalnız loopback HTTP açar; Host/Origin korumasını kapatmayın.
  `submit_task.connection_id` yalnız kayıtlı bağlantılardan seçilir; sıradaki
  görevde dondurulur. Yönetim MCP'sinden keyfi config/endpoint/anahtar almayın.
  Görev gönderme/iptal/retry yalnız `--allow-execute` ile açılır. Model işlemini
  MCP isteğinde çalıştırmayın; mevcut kuyruğa kaydedin ve worker'a bırakın.
- Araç MCP'si `mcp_transport.py` / `mcp_client.py` ile bağlanır. Açık ajan izin
  listesi ve görev seçimi uygulanır; sunucunun tüm araçlarını modele aktarmayın.
  SDK/Pydantic AI köprüsü yalnız `engines/mcp_tools.py` içinde kalır.
- `setup_cli.py` / `setup_profile.py` yalnız yeni profil oluşturur; mevcut
  dizinin üzerine yazmaz. Kullanıcı istemci ayarlarını veya canlı DB'yi değiştirmez.
  `diagnostics.py` yerel kontrolü model çağrısından ayırır; canlı test yalnız
  `--verify` / `--live` veya açık sihirbaz seçimiyle, araçsız ve tek istekle yapılır.
