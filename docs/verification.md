# İlk adım doğrulaması

Tarih: 1 Kasım 2026. Ortam: Windows, Python 3.14.7.

- Pydantic AI slim 2.64.0 ve OpenAI uyumlu sağlayıcı eki bağımsız `.venv`
  içine kuruldu; editable paket ve CLI giriş noktası oluşturuldu.
- `python -m pip check`: bağımlılık uyuşmazlığı bulunmadı.
- 12 pytest senaryosu: ayar yükleme, endpoint kısıtı, CLI bağımsız native
  döngü, izinli araç, istek/araç/token sınırları, zaman aşımı, eksik anahtar,
  yerel bağlantının farklı sağlayıcı anahtarını almaması, demo ve hata gizliliği.
- Dört test dosyasında üretim modülü importları ve gölgeleme kontrol edildi.
  `load_config`, `NativeEngine.run`, `resolve_connection` ve `main` ayrı ayrı
  etkisizleştirildiğinde ilgili test paketi başarısız oldu. Her denemede kaynak
  dosya `finally` içinde yedekten geri yüklendi ve byte eşitliği doğrulandı.
- `ragents demo`, iki örnekte `ragents check` ve sürüm komutu çalıştırıldı.

Gerçek Ollama/OpenRouter çağrısı veya harcama yapılmadı. Bu testler uzak model
uyumluluğunu, model kalitesini, sandbox izolasyonunu veya servis dayanıklılığını
kanıtlamaz. Framework karşılaştırması ve Faz 0'ın kalan kabul kriterleri açıktır.

## Entegrasyon genişletmesi

Aynı gün ChatGPT OAuth ve OpenCode Go/Zen eklendi. Test paketi 26 senaryoya
genişledi. Gerçek kasa/tarayıcı erişimi test fixture'ında kapatıldı.

- Go/Zen: endpoint ve anahtar ayrımı, uygulama servisinden bellek içi HTTP
  transport'a kadar istek/yanıt ve bağlantı değiştirilince ajan kimliğinin korunması.
- ChatGPT: şifreli büyük token saklama, token rotasyonunun kaydı, yerel hesap
  ayrımı, kalıcı host ID, yeniden girişte client ID, reddedilmiş plan izni,
  süreç kilidi ve düz metin kasa backend'inin reddi.
- ChatGPT Responses protokolü: doğru endpoint/bearer, `stream=true`, `store=false`,
  desteklenmeyen output tavanının gönderilmemesi ve 403'te tek istek.
- CLI: yerel auth durum kontrolü ve üç yeni örnek ayar dosyasının doğrulanması.
- Dört yeni test dosyasında import/gölgeleme kontrolü ve üretim fonksiyonu
  mutasyonu yapıldı: `resolve_connection`, `ChatGPTStore.save`, `NativeEngine.run`,
  `application.run_task`. Her test bozuk uygulamayı yakaladı; dosyalar birebir geri yüklendi.

Kasa anahtarı ve OAuth oturumu kullanıcı hesabında oluşturulmadı. Canlı tarayıcı
callback'i ve gerçek sağlayıcı başarısı henüz doğrulanmadı. Ayrıntılar
[entegrasyon rehberinde](provider-integrations.md).

## İlk üç adımın tamamlanması

Yukarıdaki sonuçlar kendi uygulama anlarına aittir. Kullanıcı daha sonra
ChatGPT girişini tamamladı; bu aşamada yeni giriş başlatılmadı.

- `gpt-6-luna` ile iki kısa canlı istek başarılı: her biri 38 giriş / 9 çıkış
  tokenı; toplam 76 giriş / 18 çıkış tokenı bildirildi. Dolar maliyeti üretilmedi.
- İkinci canlı görev SQLite'a kaydedildi. Aynı anahtar ve içerikle yeniden
  çalıştırma, aynı run kimliğiyle `cached: true` döndürdü; model tekrar çağrılmadı.
- 49 çevrimdışı test geçti: yeni girdi/toplam token bütçeleri, her istekte kalan
  çıktı tavanı, bağlam karakter sınırı, eski tur seçimi, araç çıktısı sınırlama,
  kalıcılık, sonuç/tüketim kaydı, eşzamanlı claim, idempotency, iptal/zaman aşımı,
  aktif süreç kilidini koruyan kurtarma ve CLI görev akışları.
- Beş yeni test dosyasında statik import/gölgeleme kontrolü ve mutasyon yapıldı:
  `NativeEngine.run`, `ContextGuard.process`, `TaskStore.enqueue`,
  `TaskService.execute`, `execute_saved`. Beşinde de bozuk üretim fonksiyonu
  testleri başarısız yaptı; her kaynak `finally` içinde byte eşitliğiyle geri yüklendi.
- Kalite düzenlemesi: R16 (bağlam ve görev yürütme sorumluluklarını ayrı modüllere
  alma), R1 (liste/gösterimde ortak metadata kolonları); görev listesi tek SELECT
  kullanır, görev başına ek sorgu oluşturmaz.

Canlı token yenileme zorlanmadı. Go/Zen ve diğer sağlayıcıların canlı denemeleri
ertelendi. Süreç kaybı testi geçici SQLite + gerçek dosya kilidiyle yapıldı;
zorla kapatılan ayrı bir worker veya dağıtık servis testi değildir.
Kapsam ve komutlar [uygulama raporunda](first-three-steps.md).

## Sürekli servis ve MCP

1 Kasım 2026, Windows/Python 3.14.7: paket MCP SDK 2.3.0 ile yeniden kuruldu,
`requirements-dev.lock` güncellendi. `pip check` temiz.

- **80 çevrimdışı test geçti.** Önceki 49 senaryoya 31 yeni senaryo eklendi.
- Worker: FIFO, eşzamanlılık sınırı, ikinci supervisor'ın reddi, sonradan iş
  ekleme, kontrollü kapanış, bekleyen işleri koruma, başarısız işten sonra devam,
  sahipsiz çalışmaları kurtarma ve otomatik yeniden çağrı yapmama.
- İptal/süre: sıradaki işi çağrısız iptal, başka DB istemcisinden aktif işi iptal,
  tüm runner süre sınırı, iptal/başarı kayıt yarışı, retry'da eski iptali almama,
  runner temizliğinde ve MCP aracı beklerken iptal. Aynı ChatGPT hesabının async
  kilitte beklemesi ayrıca test edildi; gerçek kasa/oturum kullanılmadı.
- Araç MCP'si: görev/izin seçimi, araç ve şema bütçesi, ilgisiz sunucuya hiç
  bağlanmama, izinsiz çağrıyı engelleme, JSON Schema argüman denetimi, büyük
  sonucu sınırlama, model hatasını MCP hatası olarak yanlış sınıflandırmama.
- Gerçek SDK protokolü bellek içi ve stdio alt süreciyle denendi. Streamable HTTP
  MCP ve bearer header aktarımı gerçek SDK + ASGI transport ile sınandı; dış
  ağ bağlantısı açılmadı. Yönetim MCP'si gerçek CLI alt süreciyle de bağlandı;
  stdout'ta protokolü bozan ilave JSON yoktu.
- V2 yönetim MCP'si varsayılan salt okunur; execute izniyle idempotent enqueue
  ve iptal yapıyor. MCP isteğinde model çağırmıyor. Eski görev ayarlarındaki
  eksik varsayılan alanlar idempotency anahtarlarını bozmuyor.
- Kuyruk → worker → uygulama → native FunctionModel → gerçek stdio metin aracı
  → SQLite sonuç zinciri birlikte doğrulandı. Model sahte; araç mevcut
  `text_stats` fonksiyonunu tekrar kullanıyor.
- Dokümandaki `mcp tools --config examples/ollama-mcp.yaml --prompt "kelime say"`
  komutu aynen çalıştı: tek seçili araç `local-tools__text_stats`, şema boyutu
  286 karakter, model isteği **0**.
- **TEST PROVENANCE REPORT:** 12 yeni test dosyasında statik import/gölgeleme
  denetimi temiz; 12 sözdizimi geçerli üretim fonksiyonu mutasyonu testleri
  başarısız yaptı. Her kaynak `finally` içinde yedekten birebir geri yüklendi.
  Mutasyon sonrası tam pytest tekrarı da geçti: **80 passed in 14.77s**.
- Kalite düzenlemeleri: R16 (runner yaşam döngüsünü `invoke` içine alma; MCP
  bağlantısı/araç köprüsü/sunucu sorumluluklarını ayırma), R8 (yerel saf araç
  seçimini transport I/O'sundan ayırma). V1 MCP'nin varsayılan salt okunur ve
  açık yetki deseni korundu; V1 motoru/DB'si kopyalanmadı.

Bu aşamada ücretli veya canlı LLM çağrısı yapılmadı. Worker testleri geçici
DB'de çalıştı; canlı V2 kuyruğunda sürekli worker başlatılmadı. Windows otomatik
başlangıç/servis kurulumu, uzaktaki gerçek MCP sunucusu, zorla öldürülmüş ayrı
worker süreci, dağıtık çalışma, sert sandbox ve uzak yönetim OAuth'u sınanmadı.
İptal uzaktaki yan etkiyi veya tüketimi geri alma garantisi değildir.
Komutlar ve sınırlar [servis/MCP rehberinde](service-and-mcp.md).
# Dış yönetim MCP tamamlaması — 1 Kasım 2026

Görev bazında kayıtlı `connection_id` seçimi ve güvenli bağlantı keşfi eklendi.
Stdio yanında yalnız loopback'te Streamable HTTP sunucusu, Codex TOML/genel
istemci JSON ayarları ve iki kaynaklı örnek ajan dosyası hazırlandı.
Güncel kullanım: [dış yönetim rehberi](external-management.md).

- Tam çevrimdışı paket: **85 test geçti**; `pip check` temiz.
- MCP istemcisi → HTTP → SQLite kuyruk → worker → gerçek native motor/sahte
  FunctionModel → kayıtlı sonuç akışı geçti. Görev kaynağı Luna olarak seçildi;
  gerçek Luna/sağlayıcı çağrısı yapılmadı. Aynı görev yeniden gönderildiğinde
  fazladan model isteği oluşmadı; anahtarın başka bağlantıyla kullanımı reddedildi.
- MCP üzerinden aktif görev iptali, sonuç yokluğu, varsayılan salt okunur
  erişim, CLI HTTP loopback ayarı ve yabancı Host/Origin reddi doğrulandı.
- Yeni/değişen test dosyalarında üretim importu ve gölgeleme kontrolü temiz.
  Sunucu fabrikası, HTTP uygulaması ve MCP CLI üzerinde üç ayrı geçerli
  mutasyon testleri düşürdü; kaynaklar byte düzeyinde birebir geri yüklendi.
  İlk mutasyon denemesi dekoratörlü iç fonksiyonda geçersiz stub ürettiği için
  dosyaya yazılmadan durdu; geçerli hedefle kontrol tekrarlandı.
- YAML/JSON/TOML örnekleri ayrıştırıldı; istemci argümanlarının eşleştiği ve
  bu çalışma alanındaki executable yolunun mevcut olduğu kontrol edildi.

Windows/Python 3.14.7. Canlı DB, V1, gerçek OAuth kasası ve kişisel istemci
ayarları değiştirilmedi. Kalıcı worker/HTTP süreci başlatılmadı. ChatGPT
arayüzü ve Secure MCP Tunnel hesap erişimiyle uçtan uca test edilmedi;
sunucu tarafının yerel SDK testi bu bağlantının tamamlandığı iddiası değildir.
Yerel HTTP uygulama OAuth'u veya çok kullanıcılı ekip yetkileri sağlamaz.

# Kurulum ve özelleştirme tamamlaması — 1 Kasım 2026

- `setup`, sağlayıcı/model ve özelleştirilmiş ajan ayarını; aynı profil DB'sine
  bağlı Codex TOML, genel MCP JSON ve PowerShell worker başlatıcısını üretir.
  Kurulum scripti bu sihirbaza bağlandı; `-SkipConfigure` otomasyon yoludur.
- `doctor` yerel kontrolü gerçek model testinden ayırır. `--live` / `--verify`
  testleri bir model isteği ve sıfır araç çağrısıyla sınırlıdır. ChatGPT girişi
  mevcut `sign_in` / şifreli hesap deposunu kullanır; yeni OAuth akışı yazılmaz.
- **100 çevrimdışı test geçti (23,54 saniye)**; `pip check` temiz.
  15 yeni senaryo: sağlayıcı ortam referansları/gizlilik, etkileşimli kurulum,
  yeni ajan/istemci üretimi, Unicode dosya yolları, endpoint kimlik bilgisi
  reddi, profil koruma, eksik kimlik, giriş sınırı ve tek istekli test akışı.
- Üretilen JSON doğrudan gerçek stdio MCP alt sürecine verildi; görev oluşturma
  → yeni profil DB'si → worker → native FunctionModel → MCP sonucu doğrulandı.
- Üç yeni test dosyasında üretim importu/gölgeleme kontrolü temiz; kurulum,
  tanılama ve profil üretiminde üç ayrı mutasyon testleri düşürdü. Kaynaklar
  byte düzeyinde geri yüklendi ve tam paket yeniden çalıştırıldı.
- Kurulum scriptinin ve üretilen worker başlatıcısının PowerShell sözdizimi
  doğrulandı. Scriptle temiz makinede bağımlılık kurulumu yeniden yapılmadı.

Gerçek sağlayıcı isteği, tarayıcı girişi veya canlı kuyruk işlemi yapılmadı.
Kişisel istemci ayarları ve mevcut OAuth oturumu değiştirilmedi; sürekli süreç
açık bırakılmadı. Yerel servis kurulumu tamamlandı; sandbox, çoklu ajan iş
birliği ve işletim sistemi otomatik servis kaydı bu aşamanın kapsamı değildir.
[Kurulum ve kullanım](setup-and-customization.md).

