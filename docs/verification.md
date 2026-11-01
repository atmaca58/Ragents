# Güncel Windows ürün temeli — 1 Kasım 2026

Onaylanan ürün planının bu uygulama kesitinde yürütme/izolasyon, ortak kaynak
kilitleri, tek profil kökü, takvim/programatik işler, kaynaklı/onaylı hafıza,
ilgili skill seçimi, katalog MCP ve tutarlı DB yedeği doğrulandı. Tam ürün
teslimi tamamlanmadı; açık kapılar [uygulama kaydında](windows-product-progress.md).

```powershell
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe scripts/check_product_provenance.py
.\.venv\Scripts\python.exe -m pytest -q -ra -o addopts= --basetemp C:/RAgents-Kaynak/.test-output/product-final-verified
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
.\.venv\Scripts\python.exe -m pip check
```

- **252 geçti, 3 atlandı / 255 senaryo; 203,30 saniye.** İki Windows symlink
  yetkisi testi ve bir POSIX native sandbox testi atlandı.
- **15 üretim hedefinde statik import/gölgeleme + mutasyon kontrolü geçti.**
  Her kaynak dosyası mutasyon sonrası byte düzeyinde geri yüklendi.
- Windows'ta eski ACL yetki birikimi önce gerçek AppContainer ile gösterildi;
  yürütme başına SID düzeltmesinden sonra aynı backend'in sonraki salt okunur
  çalışması yazamadı. Mevcut Windows yazma/ağ/alt süreç testleri de geçti.
- İptal bariyerleri, CLI verification exit kodu, büyük dosya sayfalaması,
  başlıkları aynı görevlerin aktarımı ve endpoint secret reddi regresyonları geçti.
- İki DB'nin aynı workspace'i, aynı ajanın farklı işlerini seri çalıştırması;
  bağımsız projenin meşgul proje ardında kalmaması doğrulandı.
- Takvim yeniden başlatma/telafi/çift tetikleme ve enqueue sonrası çökme
  idempotency'si; programatik işte sıfır model isteği doğrulandı.
- Hafıza doğrulanmış kaynak + yerel onay ister; metin revizyonu onayı düşürür,
  eski task snapshot'ı değişmez ve MCP yazma izni onay/çalıştırma yetkisine dönüşmez.
- Editable wheel standart build izolasyonuyla üretildi ve kuruldu; bağımlılık
  kontrolü `No broken requirements found.`. `--no-build-isolation` denemesi
  venv'de build backend kurulu olmadığından başarısızdı; standart kurulum geçti.
- İlk kısıtlı test ortamında temp/asyncio soket sınırlamaları görüldü; testler
  yerel süreç/soket erişimiyle, yalnız geçici DB ve sahte modellerle çalıştırıldı.
  Canlı V1/V2 DB, kişisel ajanlar, gerçek kasa ve ücretli model kullanılmadı.
- Güvenlik sınırları için ayrı salt okunur araştırma ve aday yama incelemesi
  yapıldı; raporlanan URL/SID/iptal sınırlarında ek somut bypass bildirilmedi.
  macOS native süreç temizliği ve tam ürün güvenlik onayı iddia edilmiyor.

Aşağıdaki kayıtlar önceki geliştirme kesitlerinin tarihsel kanıtıdır.

# İlk adım doğrulaması

Tarih: 1 Kasım 2026. Gerçek yerel test ortamı: Windows, Python 3.14.7.
Windows, macOS ve Linux için hedef kapsam ve doğrulanmamış alanlar
[platform desteğinde](platform-support.md) kayıtlıdır.

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

# A01 — Kalıcı ajan kataloğu — 1 Kasım 2026

- `catalog.py` kalıcı ajan profillerini `local-profile/agents/<id>/` altında
  yönetir; `agents_cli.py` oluşturma/listeleme/gösterme/güncelleme/devre dışı
  bırakma/arşivleme/geri getirme yüzeyini ekler. Profil bağlantıları ajan
  dizininde kendi kendine yeterlidir; `--from-config` mevcut `ragents.yaml`
  dosyasını kataloğa aktarır.
- Görev kuyruğa girerken ajan profili o anki talimat metniyle `ProjectConfig`
  biçiminde görev tanımına kopyalanır; sonradan yapılan profil düzenlemesi
  kuyruktaki görevi değiştirmez. Revizyon, `agent.yaml` (durum hariç) ve talimat
  dosyalarının SHA-256 özetidir; elle Markdown düzenlemesi de algılanır.
- **119 çevrimdışı test geçti**; `pip check` temiz. 19 yeni senaryo: iki ajanın
  ayrı görev alması, yeniden yükleme, kimlik/bağlantı doğrulaması, talimat/kural
  birleştirme, revizyon ve `--if-revision`, elle dosya düzenleme, görev snapshot'ı,
  devre dışı/arşiv/geri getirme, bozuk profilin listelenmesi, bağlantı modeli
  güncelleme ve CLI akışları.
- `data/verify_provenance.py` 17 hedefte statik import/gölgeleme ve mutasyon
  kontrolü çalıştırdı; beş yeni hedef (`load_agent`, `merge_documents`,
  `enqueue_agent_task`, `transition_agent`, `_create_profile`) mutasyonla düştü.
  Kaynaklar byte düzeyinde geri yüklendi.
- Geçici profil ve geçici SQLite ile `agents create --from-config`,
  `list/show/update/disable/archive/restore`, `tasks add --agent` ve sahte
  motorlu `run --agent` denendi. Canlı `data/ragents.db`, V1, gerçek sağlayıcı,
  canlı kuyruk ve kullanıcı istemci ayarları değiştirilmedi.

A01 tamamlandığında workspace/dosya araçları (A03), sandbox (A04), bağımsız
doğrulama (A06), MCP üzerinden katalog yönetimi (A11) ve zamanlanmış görevler
yoktu; talimat derleyicisi A02 ile eklendi. Eşzamanlı iki katalog editörü için kilit yalnız
CLI süreçlerinde uygulanır; çok yazarlı dağıtım A10/C04 kapsamındadır. Ayrıntılar
[ajan kataloğu](agents-and-workspaces.md).

# A02 — Talimat derleyicisi ve skill'ler — 1 Kasım 2026

- `instructions.py` `instructions.md`, `project.md`, `rules.md` ve seçili
  `skills/<id>/SKILL.md` dosyalarını deterministik biçimde derler. Sıra profil →
  proje → seçili skill → kalıcı kurallar; görev metni ayrı kullanıcı mesajıdır.
- Skill frontmatter'ı `name`/`description`/`keywords` ile kapalı şemada
  doğrulanır. Seçim açıktır: `default_skills` veya görev bazlı `--skill`.
  Katalogdaki ilgisiz skill'ler modele gönderilmez; otomatik ilgi seçimi A09'a
  aittir.
- Boyut sınırları: profil 8.000, proje/kural 4.000, skill gövdesi 4.000, toplam
  skill 8.000 ve derlenmiş toplam `context.max_instruction_chars` (varsayılan
  16.000). Aşım sessizce kırpılmaz.
- `TaskDefinition.instruction` alanı derlenmiş metnin SHA-256 revizyonunu,
  kaynak hash'lerini ve seçili skill kimliklerini taşır. `tasks show` snapshot'ı
  gösterir; eski görevler dosya düzenlemesinden etkilenmez.
- **134 test geçti, 1 test atlandı** (Windows sembolik bağlantı yetkisi
  olmadığı için symlink testi skip). 16 yeni senaryo: birleştirme sırası, skill
  seçimi, frontmatter/gövde doğrulaması, boyut aşımı, UTF-8/symlink reddi,
  katalog proje/skill entegrasyonu, görev snapshot'ı, eski idempotency anahtarı
  uyumluluğu ve CLI akışları.
- `data/verify_provenance.py` 21 hedefte statik import/gölgeleme ve mutasyon
  kontrolü çalıştırdı; beş yeni hedef (`compile_instructions`,
  `resolve_skill_ids`, `load_skill`, `compile_texts`, `_profile_documents`)
  mutasyonla düştü. Kaynaklar byte düzeyinde geri yüklendi.
- `pip check` temiz. Testlerde gerçek model/ağ/kasa/tarayıcı kullanılmadı; canlı
  `data/ragents.db`, V1 ve kullanıcı profilleri değiştirilmedi.

A02 tamamlandığında workspace/dosya araçları (A03), sandbox (A04), dosya
yazma/komut (A05), bağımsız doğrulama (A06) ve otomatik skill seçimi (A09)
yoktu. Talimat metni kodla uygulanan araç izinlerinin yerine geçmez; ajanın
profil dosyalarını değiştirebileceği bir araç verilmemiştir. Ayrıntılar
[talimatlar ve skill'ler](instructions-and-skills.md).

# A03 — Çalışma alanı, okuma ve artifact — 1 Kasım 2026

- Her ajana kalıcı bir workspace atandı. Varsayılan `workspaces/<ajan-id>`
  `agents create` sırasında oluşturulur; özel `--workspace` yalnız mevcut dizin
  olarak kabul edilir. `agents/`, `data/`, `ragents.yaml`, `RAGENTS_HOME` ve
  başka ajan workspace'leriyle çakışma reddedilir.
- Workspace grant'i görev tanımına dondurulur. Sonradan çalışma alanı değişse
  bile kuyruktaki görev eski grant ile çalışır. Çalışma alanı silinmişse yeni
  görev kuyruğa girmez.
- `list_files`, `search_text`, `read_file` yalnız `agent.yaml` `tools` listesinde
  açıkça izinliyse modele verilir. Yol kaçışı, absolute/UNC/sürücü yolu, NUL,
  Windows ADS, cihaz adı, symlink ve junction reddedilir; hedefin workspace
  içinde kaldığı çözümleme sonrası doğrulanır.
- Okuma ve arama sınırları: liste 200 giriş/derinlik 3, arama 50 eşleşme/1.000
  dosya/1 MiB, okuma 64 KiB/200 satır; ayrıca `context.max_tool_output_chars`
  bağlam koruması uygulanır. Kırpma `truncated` alanıyla açıkça bildirilir.
- SQLite `user_version=3` ve `artifacts` tablosu eklendi. Çalışma öncesi/sonrası
  sınırlı workspace farkı taranır; yeni/değişmiş dosyalar göreli yol, boyut,
  SHA-256, ajan, görev ve çalışma kimliğiyle kaydedilir. `tasks show` ve MCP
  `get_task` artifact listesini döndürür.
- **170 çevrimdışı senaryo: 168 geçti, 2 atlandı** (Windows symlink yetkisi
  olmadığı için symlink testleri skip; junction testi ve symlink'li üst dizin
  testi geçti). Yeni senaryolar workspace atama/çakışma, yol kaçışı,
  symlink/junction, okuma/arama/liste sınırları, UTF-8/binary davranışı, tool
  izni, görev snapshot'ı, artifact kaydı, migration, `scripts/setup.py` platform
  seçimi, `start-worker.py`/`.sh`, `{python}` MCP yolu ve CLI/MCP çıktısını
  kapsar.
- macOS'ta `/var` gibi sistem üst dizinlerindeki symlink'lerin workspace kökünü
  yanlışlıkla reddetmemesi için kök kanonikleştirildi; kökün kendisi symlink
  veya junction ise reddedilmeye devam ediyor. Bu davranış Windows junction ve
  symlink'li üst dizin testiyle sınandı.
- `data/verify_provenance.py` 31 hedefte statik import/gölgeleme ve mutasyon
  kontrolü çalıştırdı; 10 yeni hedef (`_validate_relative`,
  `resolve_agent_workspace`, `_target`, `list_files`, `search_text`, `read_file`,
  `collect_artifacts`, `record_artifacts`, `build_tools`,
  `_assert_workspace_isolated`) mutasyonla düştü. Kaynaklar byte düzeyinde geri
  yüklendi.
- `pip check` temiz. Testlerde gerçek model/ağ/kasa/tarayıcı kullanılmadı; canlı
  `data/ragents.db`, V1 ve kullanıcı profilleri değiştirilmedi.

A03 kesitinde workspace salt okunurdu. Dosya yazma/patch ve komut A05'te,
gerçek sandbox ve TOCTOU sertleştirmesi A04'te eklendi; bağımsız doğrulama
A06'da tamamlandı. Artifact fark taraması en iyi çabadır; A05 yazma araçları
explicit `file_tool` kaydı yapar. Ayrıntılar
[çalışma alanı ve artifact'lar](workspaces-and-artifacts.md).

# A04 — Gerçek sandbox yürütme katmanı — 1 Kasım 2026

- `sandbox.py` ortak sözleşmeyi ekledi: workspace, yazma/ağ izni, duvar saati,
  bellek, süreç sayısı, çıktı sınırı, güvenli ortam allowlist'i ve iptal
  denetimi. `SandboxPolicy` workspace'i mevcut `Workspace` doğrulamasından
  geçirir; kök symlink/junction ve sürücü kökü reddedilir.
- Windows `AppContainer + Job Object` backend'i eklendi. Alt süreç AppContainer
  SID'i ile başlatılır; Python çalışma zamanına salt okunur ACL verilir. Ağ
  varsayılan kapalıdır. Job Object bellek, CPU süresi, aktif süreç ve
  `KILL_ON_JOB_CLOSE` sınırlarını uygular; zaman aşımı/iptal tüm süreç ağacını
  kapatır.
- macOS `/usr/bin/sandbox-exec` Seatbelt backend'i yazma ve ağ kurallarını
  uygular. Linux `bwrap` backend'i kökü salt okunur bağlar; ağ, PID, IPC ve UTS
  namespace'lerini ayırır. Backend yoksa çalıştırma açıkça reddedilir; sessiz
  izolasyonsuz çalışma yolu yoktur.
- `ragents sandbox status` ve `ragents sandbox run` eklendi. Komut argv listesi
  olarak çalışır; `shell=True` kullanılmaz. Kimlik bilgileri ve keyfi üst süreç
  ortamı sandbox'a taşınmaz.
- Windows'ta gerçek izolasyon testleri: kök dışına yazma/okuma reddi, yerel
  loopback ağ bağlantısının engellenmesi, zaman aşımında torun sürecin
  sonlandırılması, `max_processes=1` ile alt süreç reddi, çıktı sınırında
  sonlandırma, `OPENAI_API_KEY` sızıntısının olmaması, stdin ve `cancel()`
  davranışı, CLI üzerinden gerçek çalıştırma.
- macOS/Linux backend komut ve Seatbelt profili çevrimdışı test edildi; native
  izolasyon testleri bu Windows ortamında çalıştırılmadı. `.github` matrisi
  ilgili runner'larda çalıştırılmak üzere hazır; native sonuç C03 kapısına
  bağlıdır.
- **A04 kesitinde 189 çevrimdışı senaryo: 186 geçti, 3 atlandı.** Yeni dosya
  `tests/test_sandbox.py` 19 senaryo içerir; Windows AppContainer testleri
  gerçek alt süreç ve geçici workspace kullanır. Windows ortamındaki üç skip:
  iki symlink yetkisi ve bir POSIX native sandbox testi. macOS/Linux native
  testleri ilgili platform dışında skip edilir.
- `data/verify_provenance.py` 35 hedefte statik import/gölgeleme ve mutasyon
  kontrolü çalıştırdı; `Sandbox.run`, `validate_argv`, `seatbelt_profile` ve
  `LinuxBubblewrapBackend._command` mutasyonla düştü. Kaynaklar byte düzeyinde
  geri yüklendi.
- `pip check` temiz. Testlerde gerçek model/ağ/kasa/tarayıcı kullanılmadı;
  canlı `data/ragents.db`, V1 ve kullanıcı profilleri değiştirilmedi.
- Stdio MCP bağlantısı sandbox sayılmaz; harici araç sunucusunun yetkisi A05/A11
  kapsamında ayrıca değerlendirilecektir. Ayrıntılar [sandbox](sandbox.md).

# A05 — Dosya değiştirme ve komut — 1 Kasım 2026

- `TaskPermissions` eklendi: `readable_paths`, `writable_paths`, `commands`,
  `allow_network`, `allow_publish`, `command_timeout_seconds` ve
  `max_output_bytes`. Görev kuyruğa girerken bu izinler `WorkspaceGrant` içine
  kopyalanır ve snapshot olarak dondurulur. Yazma/komut araçları izinsiz
  tanımlandığında `RunRequest` ve `TaskDefinition` doğrulaması görevi reddeder.
- `Workspace` artık okuma ve yazma kapsamlarını ayrı uygular. `write_file` ve
  `apply_patch` yalnız `writable_paths` içinde çalışır; `..`, symlink/junction,
  korumalı dizin ve workspace dışı yollar reddedilir. Yazma atomik geçici dosya
  ve `os.replace` ile yapılır; içerik 256 KiB, yama kaynağı 1 MiB ile sınırlıdır.
- Dosya işlemleri ana süreçte değil, platform sandbox'ı içinde
  `python -m ragents.fileops` yardımcısıyla çalışır. Sandbox yalnız izinli alt
  dizinleri yazılabilir yapar; yardımcı yolu ve kapsamı yeniden doğrular.
- `write_file` ve `apply_patch` başarılı sonuçlarını `ArtifactDraft` olarak
  döndürür; `TaskService` bunları `producer=file_tool` ile upsert eder. Aynı
  dosyaya yapılan son yama nihai SHA-256'yı kaydeder. Diğer değişiklikler
  `workspace_scan` olarak kalır.
- `run_command` argv listesiyle çalışır; `shell=True` yoktur. Çalıştırılabilir
  adı `commands` listesiyle karşılaştırılır; `cwd` workspace içinde olmalıdır.
  `allow_network=false` varsayılandır. `allow_publish=false` iken `git push`,
  `npm publish`, `docker push`, `twine upload`, `gh release/pr create` gibi
  komutlar araç tarafından reddedilir.
- `SandboxPolicy` dizin bazlı `writable_paths` ve `cwd` taşır. Windows
  AppContainer yalnız izinli alt dizine ACL verir; Linux bubblewrap yalnız o
  dizinleri `--bind` eder; macOS Seatbelt profili yalnız o alt yolları yazmaya
  açar. `sandbox run --writable-path` ve `--cwd` CLI'ye eklendi.
- Windows'ta gerçek alt süreç testi: yalnız `src/` yazılabilirken `src/izinli.txt`
  oluşturuldu; `docs/yetkisiz.txt` ve kök `kok.txt` reddedildi. Linux/macOS
  komut üretiminde kökün salt okunur, yalnız izinli alt dizinin yazılabilir
  bağlandığı doğrulandı.
- **A05 kesitinde 203 çevrimdışı senaryo: 200 geçti, 3 atlandı.** Yeni
  `tests/test_file_tools.py` 12 senaryo içerir; `test_sandbox.py` dizin kapsamı
  ve CLI kapsamlı yazma testleriyle 21 senaryoya çıktı. Windows'taki üç skip değişmedi: iki
  symlink yetkisi ve bir POSIX native sandbox testi.
- `data/verify_provenance.py` 42 hedefte statik import/gölgeleme ve mutasyon
  kontrolü çalıştırdı; `Workspace.write_file`, `Workspace.apply_patch`,
  `ArtifactLog.record`, `fileops.apply_operation`, `validate_command_argv`,
  `is_publish_command` ve `SandboxPolicy.checked_writable_paths` mutasyonla
  düştü. Kaynaklar byte düzeyinde geri yüklendi.
- `pip check` temiz. Testlerde gerçek model/ağ/kasa/tarayıcı kullanılmadı;
  canlı `data/ragents.db`, V1 ve kullanıcı profilleri değiştirilmedi.
- Bilinen sınır: POSIX komut süreci kökü salt okunur görse de sistem dosyalarını
  okuyabilir; `readable_paths` yalnız dosya araçlarını daraltır. stdio MCP
  süreci bu sandbox'ın dışındadır. Ayrıntılar
  [dosya ve komut](tools-and-execution.md).

# A06 — Model cevabından bağımsız doğrulama — 1 Kasım 2026

- `verification.py` eklendi. `VerificationPlan`, görev tanımına dondurulan
  `file`, `structured_output`, `command` ve `browser` kontrollerini taşır.
  Plan en fazla 32 kontrol, şema 16 KiB, plan dosyası 64 KiB ile sınırlıdır.
- `file` kontrolü workspace'e göreli yolu, boyutu, SHA-256'yı ve isteğe bağlı
  metni doğrular; symlink/junction, kaçış ve korumalı yollar reddedilir.
  `structured_output` saf JSON'u yerel JSON şemasıyla doğrular; uzak `$ref`
  ağ erişimini önlemek için reddedilir.
- `command` kontrolü argv listesini platform sandbox'ında çalıştırır; çıkış
  kodu, stdout/stderr metni, zaman aşımı ve çıktı sınırı denetlenir. `browser`
  kontrolü Playwright JSON raporundaki `expected`, `unexpected`, `flaky` ve
  `skipped` sayılarını okur; model metnindeki `BROWSER PASS` ifadesine bakmaz.
- `TaskService` model çağrısı ve artifact taramasından sonra doğrulamayı
  çalıştırır. En az bir kontrol `failed` ise görev `failed` ve çalışma
  `verification_failed`; yalnız `error` varsa `verification_error` olur. Model
  sonucu ve doğrulama kanıtı saklanır; başarısız görev `tasks retry` ile
  yeniden sıraya alınabilir.
- SQLite `user_version=4` oldu; `verifications` tablosu çalışma başına kanıt
  kaydını tutar. `tasks show`, `tasks result`, MCP `get_task` ve `get_result`
  bu kayıtları döndürür. Ham komut çıktısı değil; çıkış kodu, süre, boyut,
  SHA-256 ve Playwright sayıları saklanır.
- CLI `tasks add --verify-plan` eklendi; MCP `submit_task` isteğe bağlı
  `verification` kabul eder. MCP bağlantıları workspace taşımadığı için MCP'de
  yalnız `structured_output` kullanılabilir; dosya/komut/tarayıcı kontrolleri
  workspace'li katalog görevlerinde tanımlanır.
- **A06 sonrası 216 çevrimdışı senaryo: 213 geçti, 3 atlandı.** Yeni
  `tests/test_verification.py` 12 senaryo, `test_mcp_server.py` 1 senaryo
  ekledi. Windows'taki üç skip değişmedi: iki symlink yetkisi ve bir POSIX
  native sandbox testi. Tarayıcı kontrolü sahte sandbox ve gerçek Playwright
  JSON biçimiyle çevrimdışı sınandı; native tarayıcı çalıştırması bu ortamda
  yapılmadı.
- `data/verify_provenance.py` 56 hedefe genişletildi; `Verifier.run`,
  `_file_check`, `_structured_output_check`, `_command_check`,
  `_browser_report`, `StructuredOutputCheck.validate_schema`,
  `_reject_remote_refs`, `CommandSpec.validate_argv`,
  `TaskStore.succeed`/`fail_verification`/`verification`/`_insert_verification`,
  `TaskService.verify` ve `Workspace.checked_path` mutasyonla düştü.
  Statik import/gölgeleme kontrolleri geçti; kaynaklar byte düzeyinde geri
  yüklendi.
- `pip check` temiz. Testlerde gerçek model/ağ/kasa/tarayıcı kullanılmadı;
  canlı `data/ragents.db`, V1 ve kullanıcı profilleri değiştirilmedi. Kullanım
  ve sınırlar [görev doğrulamada](task-verification.md).

# A07 — V1'e denk görev yönetimi — 1 Kasım 2026

- Görev doğruluk kaynağı SQLite olarak seçildi; Markdown yalnız içe/dışa
  aktarma görünümüdür. `TaskMetadata` başlık, açıklama, `-1000..1000` öncelik,
  etkinlik ve en fazla 32 bağımlılık taşır. Başlık boşlukları normalize edilir;
  bağımlılıklar sıralanır, böylece idempotency anahtarı sıradan etkilenmez.
- SQLite `user_version=5` oldu. `tasks` tablosuna metadata sütunları,
  `task_dependencies` ve `task_revisions` tabloları eklendi; v4 veritabanı
  açılışta başlık, revizyon ve ilk revizyon kaydını geriye dönük doldurur.
- Kuyruk sırası `priority DESC, created_at ASC, id ASC` oldu. Yalnız etkin,
  arşivsiz ve tüm bağımlılıkları `succeeded` olan görevler alınır. `claim`
  bağımlılık, etkinlik ve arşiv durumunu ayrıca denetler; `tasks run` da
  bağımlılığı tamamlanmamış görevi çalıştırmaz.
- Bağımlılık doğrulaması kendine bağımlılığı, eksik hedefi, 32'den fazla
  bağımlılığı ve döngüyü reddeder. `dependencies`, `blocked_by` ve `ready`
  sorguları CLI `tasks show` ile MCP `get_task` çıktısına eklendi.
- `TaskStore.edit` yalnız `queued`, `failed`, `cancelled` ve `interrupted`
  görevlerde çalışır; `running`, `succeeded` ve arşivli görevler reddedilir.
  Her gerçek değişiklik `definition_revision` değerini artırır ve önceki tanım
  `task_revisions` tablosuna yazılır; değişiklik yoksa revizyon artmaz.
- `archive`/`restore` eklendi. Yalnız terminal görevler arşivlenir; arşivli
  görev varsayılan listede ve kuyrukta görünmez, düzenlenemez, iptal edilemez,
  yeniden denenemez ve çalıştırılamaz. `tasks list` `--status`,
  `--include-archived` ve `--archived-only` filtrelerini kabul eder.
- `task_markdown.py` eklendi. `tasks export` en fazla 1000 görevi (arşivliler
  dahil) YAML ön bilgili bloklar olarak yazar. `tasks import` her blok için
  yeni görev oluşturur; başlık tekilliği, topolojik bağımlılık çözümü, döngü,
  eksik bağımlılık, bilinmeyen alan ve geçersiz doğrulama planı reddedilir.
  İçe aktarma atomik değildir; sonraki blok hata verirse önceki bloklar kalır.
- MCP `submit_task` isteğe bağlı `title`, `description`, `priority` ve
  `depends_on` kabul eder; `get_task` bağımlılık, `blocked_by` ve `ready`
  döndürür. Görev gönderme hâlâ `--allow-execute` gerektirir.
- **A07 sonrası 226 çevrimdışı senaryo: 223 geçti, 3 atlandı.** Yeni
  `tests/test_task_management.py` 9 senaryo, `test_mcp_server.py` 1 metadata
  senaryosu ekledi; `test_storage.py` ve `test_artifacts.py` sürüm 5'e
  güncellendi. Windows'taki üç skip değişmedi: iki symlink yetkisi ve bir POSIX
  native sandbox testi.
- `data/verify_provenance.py` 73 hedefe genişletildi; `TaskStore.enqueue`,
  `edit`, `archive`, `restore`, `revisions`, `queued`, `claim`,
  `_validate_dependencies`, `_blocked_by`, `_insert_revision`, `_migrate_tasks`,
  `TaskMetadata.validate_dependencies`, `_front_matter`, `_topological_order`,
  `import_markdown`, `export_markdown` ve `dispatch_tasks` mutasyonla düştü.
  Statik import/gölgeleme kontrolleri geçti; kaynaklar byte düzeyinde geri
  yüklendi.
- `pip check` temiz. Testlerde gerçek model/ağ/kasa/tarayıcı kullanılmadı;
  canlı `data/ragents.db`, V1 ve kullanıcı profilleri değiştirilmedi. Kullanım
  ve sınırlar [görev yönetiminde](task-management.md).
- Bilinen sınır: Markdown içe aktarma atomik değildir; başlıklar yalnız dosya
  içinde benzersizdir. Dışa aktarılan dosyayı geri içe aktarmak mevcut
  görevleri güncellemez, yenilerini oluşturur.

