# R Agents V2 geliştirme rehberi

Güncel ürün hedefi `docs/product-delivery.md`: ilk tamamlanmış ürün Windows 11
x64; macOS/Linux native kabulüne kadar deneysel. Kullanıcı profili ortak
`profile_paths.py` çözücüsünden gelir; CLI/worker/MCP/auth için ayrı varsayılan
kök üretmeyin. Uygulama durumu ve açık kapılar `docs/windows-product-progress.md`.
Kişisel ajan göçü ve GitHub yayını ürün kabulünden sonra yapılır.
İstisna (2 Kasım 2026): kullanıcı mevcut geliştirmeyi şimdi commit/push edip
depoyu herkese açık yapmayı ve tek komutluk geliştirme kurulumu yayımlamayı
açıkça istedi. Bu yayını kabul edilmiş/bitmiş ürün diye sunmayın; kişisel
ajan geçişi hâlâ son adımdır.

Arama sağlayıcılarında kullanıcı tercihi: yeni bir kaynak ancak gerçek
anahtarsız/ilgili bağlantı ve arama kontrolü geçtiyse ürün menüsü ve otomatik
zincire eklenir. Başarısız veya deneysel adaptörleri yayın paketine almayın;
kullanıcıya çalışmayan seçenek göstermeyin.

Ana ürün arayüzü terminaldir (`terminal_setup.py`, `client_connections.py`).
Yeni ürün web paneli eklemeyin. MCP taslağı yerel etkileşimli terminalde,
görülen işlem hash'iyle onaylanır; MCP veya pipe insan onayı üretemez.
Sağlayıcının zorunlu OAuth ve istemci bağlantı sayfaları istisnadır, korunur.
Kullanıcı VM istemiyor; kabul kendi Windows bilgisayarında yapılacak ve temiz
makine kabulü diye sunulmayacak. Ek ücretli model çağrısı yapılmaz.

SQLite şeması `storage.SCHEMA_VERSION` ile yönetilir. Takvim aynı DB'deki
`schedules`/`schedule_fires`; hafıza `memory_entries`/`memory_revisions`
tablolarını kullanır. Hafıza onayı yerel akıştır, MCP'ye onay aracı eklemeyin.
Takvim ve programatik işlerde ikinci kuyruk veya keyfi Python import/komut
handler'ı eklemeyin. Kaynak kilitleri `execution_locks.py` ile manuel ve worker
işlerinde ortak uygulanır; meşgul projeler bağımsız işleri bekletmemelidir.

Bu dizin, kullanıcının onayladığı V2 tasarımının bağımsız uygulamasıdır.
Üst dizindeki CLI adapter / LLM SDK kullanmama kuralı `agent-runtime/` içindeki
V1 için geçerlidir. Burada Pydantic AI ve doğrudan sağlayıcı SDK'sı kullanılır.
V1 kodunu, ajanlarını veya veritabanını bu projeye taşımayın ve değiştirmeyin.

- Kaynak: `src/ragents/`; test: `tests/`; komutlar bu dizinden çalıştırılır.
- Hedef platformlar Windows, macOS ve Linux'tur. Ortak kurucu `scripts/setup.py`;
  PS/sh dosyaları ince sarmalayıcıdır. Windows venv `Scripts/python.exe`, POSIX
  `bin/python` kullanır. Yeni OS bağımlılıklarını çekirdeğe yaymayın; sandbox ve
  servis backend'leri ortak sözleşme altında platforma göre uygulanmalıdır.
  Gerçek runner kanıtı olmadan başka platform için test edildi demeyin.
- Kurulum: Windows `.venv/Scripts/python -m pip install -e ".[dev]"`, macOS/Linux
  `.venv/bin/python -m pip install -e ".[dev]"`.
- Test: Windows `.venv/Scripts/python -m pytest`, macOS/Linux
  `.venv/bin/python -m pytest`. Testlerde gerçek model/ağ/CLI kullanılmaz.
  Platform sözleşmesi ve kanıt sınırı `docs/platform-support.md` içindedir.
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
- Görev yönetiminde SQLite doğruluk kaynağıdır; `task_markdown.py` yalnız
  içe/dışa aktarma görünümüdür. Başlık, açıklama, öncelik, etkinlik ve
  bağımlılıklar `TaskMetadata` içinde doğrulanır; kuyruk
  `priority DESC, created_at ASC` sırasıyla yalnız etkin, arşivsiz ve tüm
  bağımlılıkları `succeeded` görevleri alır. `running`, `succeeded` ve arşivli
  görev düzenlenemez; her gerçek değişiklik `definition_revision` değerini
  artırır ve `task_revisions` geçmişine yazılır. Döngü, kendine bağımlılık,
  eksik hedef ve 32'den fazla bağımlılık reddedilir. Arşiv geri alınabilir bir
  gizlemedir; görev silinmez. Markdown import her blok için yeni görev oluşturur,
  mevcut görevleri güncellemez ve atomik değildir. Kullanıcı akışı
  `docs/task-management.md` içindedir.
- `catalog.py` kalıcı ajan profillerini `<profile>/agents/<id>/` altında
  yönetir; `agents_cli.py` yaşam döngüsü yüzeyidir. `instructions.py` yalnız
  `instructions.md`, `project.md`, `rules.md` ve seçili `SKILL.md` dosyalarını
  derler; talimat metni YAML'ye ikinci kez yazılmaz. Görev kuyruğa girerken
  derlenmiş metin, workspace grant'i ve `InstructionSnapshot` görev tanımına
  kopyalanır. Profil dosyalarına yazan araç eklemeyin.
- `workspace.py` okuma araçlarını (`list_files`, `search_text`, `read_file`),
  izinli yazma/yama kapsamını ve artifact fark taramasını yönetir; `fileops.py`
  yazma/yamayı sandbox içinde uygular. Yol doğrulamasını, symlink/junction
  reddini, `agents/`, `data/` ve `RAGENTS_HOME` korumasını, okuma/yazma
  kapsamlarını ve çıktı sınırlarını kaldırmayın. Workspace araçları yalnız
  `agent.yaml` `tools` listesindeki açık izinle modele verilir; yazma/komut
  araçları ayrıca görev grant'inde `writable_paths`/`commands` ister. Artifact
  yolları workspace'e göre göreli kalmalıdır; yazma araçları `producer=file_tool`
  ile açık kayıt yapar, fark taraması `workspace_scan` olarak kalır.
- `verification.py` görev çıktısını model beyanından bağımsız doğrular.
  `TaskDefinition.verification` görevle dondurulur; dosya, JSON şema, komut ve
  Playwright JSON kontrolleri `TaskService` içinde model çağrısından sonra
  çalışır. Başarısız/hatalı doğrulama görevi `failed` yapar; model sonucu ve
  kanıt saklanır. Doğrulama komutlarını `run_command` allowlist'ine eklemeyin;
  aynı sandbox, yazma/ağ izni ve yayın sınıflandırması ayrıca uygulanır.
  `BROWSER PASS` metnini kanıt saymayın; yalnız Playwright `stats` sayıları
  geçerlidir. Kullanıcı akışı `docs/task-verification.md` içindedir.
- `sandbox.py` ortak yürütme sözleşmesidir; backend'ler `sandbox_windows.py`
  (AppContainer + Job Object) ve `sandbox_posix.py` (macOS Seatbelt, Linux
  bubblewrap) içindedir. Varsayılan ağ kapalı, yazma yalnız `writable_paths`
  (yoksa salt okunur) ve ortam allowlist'i dar olmalıdır. Backend yoksa
  çalıştırmayı reddedin; `shell=True`, izolasyonsuz yedek yol veya üst süreç
  ortamının tamamını taşıma eklemeyin. `run_command` yalnız görev grant'inde
  açıkça listelenen çalıştırılabilirleri kabul eder; `allow_publish` olmadan
  push/yayın komutlarını çalıştırmayın. stdio MCP sürecini sandbox saymayın.
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
