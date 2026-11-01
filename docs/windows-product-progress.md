# Windows ürün uygulaması — 1–2 Kasım 2026

## 2 Kasım: GitHub geliştirme yayını ve tek komut

Kullanıcı mevcut geliştirmeyi şimdi GitHub'a commit/push etmeyi, depoyu
herkese açık yapmayı ve hesap gerektirmeyen tek komutla kurulumu açıkça istedi.
Önceki kabul-sonrası-yayın sırası bu geliştirme yayını için değişti; ürünün
tam kabulü ve kişisel ajan geçişi yapılmış sayılmaz.

`scripts/install.ps1`, sabit `v0.2.0-dev.20261102.2` manifesti ve SHA-256 ile
uygulama/Python/Git/pip varlıklarını doğrular; bağımlılıklar PyPI'den, sabit
Playwright tarayıcısı resmi CDN'den gelir. Sistemde Python/Git/ajan istemcisi
gerekmez. Yalnız uygulama wheel'i, kendi launcher'larımız, bağımlılık kilidi,
manifest ve checksum yayımlanır; üçüncü taraf çalışma zamanları bu çevrimiçi
kurulum paketinde yeniden dağıtılmaz.

Windows PowerShell 5.1 ile ayrı geçici uygulama/profil kökünde gerçek indirme,
paket kurma, tarayıcı kurma, şema sağlığı ve etkin sürüm seçimi geçti. Yeni
kurulumun EXE'siyle MCP 25 aracı keşfetti; model isteği 0. Hash reddi ve arşiv
yol kaçışı regresyonları geçti. Kullanıcı PATH'i, gerçek istemci ayarı ve
varsayılan kullanıcı profili değiştirilmedi. Geçici kurulum testten sonra
kaldırılacak; bilgisayarda varsayılan ürün kurulumu bulunmadı.

Komut ve geliştirme sürümünün sınırları [terminal rehberindedir](terminal-quickstart.md).

Yayın sonucu: depo herkese açık yapıldı; `v0.2.0-dev.20261102.2` geliştirme
ön sürümünde beş kurulum varlığı yayımlandı. Windows PowerShell 5.1'in ham
`irm | iex` metnindeki BOM sorunu regresyonla düzeltilerek yeni etikette
yayımlandı; eski `.1` yayını taslağa alındı, etiket geçmişi değiştirilmedi.
Yeni betik GitHub'dan kimliksiz indirilip, tüm release varlıkları yine
kimliksiz alınarak geçici kökte kurulum/güncelleme/sağlık kontrolünü tamamladı.
Sonrasında geçici uygulama, profil ve istemci kaydı kaldırıldı. Varsayılan
uygulama dizini ve HKCU ürün kurulum kaydı yok; kullanıcı PATH'i değişmedi.

GitHub CI ilk koşusunda Python 3.12/3.13'ün `list` metodu sonrası annotation
çözümü ve Windows Git testinin `mingw64` varsayımı bulundu. Kaynakta deferred
annotation ve testte `ucrt64` desteği eklendi. İlgili depolama/Git/kurucu seti
14 testte, sabit yeni MinGit ile Git/takvim seti 5 testte geçti. Yeni CI koşusu
ayrı izlenir; önceki başarısız koşular yeşil diye sunulmaz. Yayımlanan kurulum
zaten kendi sabit Python 3.14 çalışma zamanını kullanır ve testten geçti.

Bu kayıt, onaylanan [ürün teslim sözleşmesinin](product-delivery.md) uygulanan
bölümünü ve henüz kapanmayan teslim kapılarını ayırır. Ürün henüz yayıma hazır
değildir. Kişisel ajanlar taşınmadı ve V1 değiştirilmedi.

## Güncel terminal akışı

Kurulum/yönetim için ürün web paneli kaldırıldı. Ana akış
`ragents init` → `ragents connect codex|opencode|claude|claude-desktop` →
MCP taslağı → `ragents approvals` ile yerel terminal onayıdır.
Sağlayıcının resmi OAuth sayfası ve istemcinin zorunlu hesap onayı korunur.
Kullanım [terminal rehberindedir](terminal-quickstart.md).

VM/ISO hazırlanmayacak. Çevrimdışı kontrollerin ardından kullanıcının kendi
Windows bilgisayarında kurulum ve gerçek istemci/hesap testleri yapılacak.
Bu testler temiz makine/VM kanıtı olarak sunulmayacak. Ek ücretli model test
bütçesi 0 USD; kota tükenirse koşu durur. GitHub yayını ve kişisel geçiş yapılmadı.

Bu turda eklenen ve hedef regresyonları bulunan davranışlar:

- Merkezi model/arama bağlantıları, kasa referansları ve YAML gerektirmeyen
  `connections test`; varsayılan tanılama model isteği göndermez.
- MCP kurulum taslağı; profil revizyonu/hash/süreye bağlı tek kullanımlık onay.
  Gerçek terminal zorunlu; pipe/MCP onay veremez. Kesintiden sonra uygulama
  tekrar edilebilir; tamamlanma işareti olmadan yeni ajan çalıştırılamaz.
- Codex/OpenCode/Claude kullanıcı ayarlarına yedekli MCP kaydı, salt okunur
  seçenek ve model kullanmayan stdio el sıkışması. Dış istemci kabulü açık.
- Kontrollü DAG ekipleri, mevcut kuyrukta çocuklar, ortak bütçe rezervasyonu,
  kalıcı iptal ve zorunlu bağımsız final doğrulaması. Yerel onaylı tam eşit
  workspace paylaşımı aynı kanonik kilidi kullanır.
- Hash'li değişmez artifact deposu ve MCP'den sayfalı okuma. Ekip devri izinli
  artifact kimliklerinden sınırlı metin önizlemesi taşır; tam dosya devri açık.
- Git durum/diff/branch/worktree/commit, Tavily/Brave/SearXNG adaptörleri,
  DNS'e sabitlenmiş sayfa okuma ve ayrı AppContainer içinde ağsız Chromium.
  Playwright gerçek assertion/ekran görüntüsü testi native Windows'ta geçti.
- Uzak MCP OAuth: PKCE, resource/audience, kapsam kontrolü, terminalden ilk
  eşleştirme, kısa ömürlü erişim ve yenileme/iptal. Gerçek tünel kabulü açık.
- Sürümlü profil paketi; hash/allowlist, workspace eşleme önizlemesi, secret ve
  onayların dışarıda kalması, içe alınan ajan/takvimlerin kapalı başlaması.
- Task Scheduler supervisor, süreç ağacı temizliği, sınırlı yeniden başlatma;
  yedek/sağlık/etkin sürüm değiştirme ve başarısızlıkta uygulama/veri dönüşü.
- Sabit embedded Python/MinGit/Chromium ile allowlist kaynak paketi ve Inno EXE
  geliştirme paketi üretildi. Kullanıcının makinesine R Agents kurulmadı.

Şema `storage.SCHEMA_VERSION = 8`; aşağıdaki ilk uygulama kaydındaki v7 ve
252 test sayısı önceki tabandır. Son regresyon kanıtı ayrı güncellenir.

Güncel terminal regresyonu: **295 geçti / 3 atlandı**, 282,38 saniye.
Atlamalar iki Windows symlink yetki testi ve bir POSIX sandbox testidir.
`pip check` temiz. Ayrı staging paketinde embedded Python, sistem PATH'inde
yalnız System32 varken `--version`, sahte `demo` ve `init --help` geçti.
Bu kontroller kurucunun kullanıcı bilgisayarına kurulduğu anlamına gelmez.

Sonraki yetki düzeltmesinde `connect chatgpt --read-only` seçiminin supervisor
tarafından korunması eklendi; yetki alanı olmayan eski uzak ayarlar yazma
yetkisi kazanmaz. İlgili terminal, supervisor, MCP ve OAuth setinde **22 test
geçti**. Tam 295/3 koşusu bu son dar düzeltmeden önceki tabandır.

Gerçek paket EXE kontrolü, yönlendirilmiş Windows çıktısında `→` karakterinin
CP1254 hatasına yol açtığını buldu. CLI stdout/stderr UTF-8 olarak sabitlendi;
terminal, istemci kaydı, supervisor, MCP ve CLI setinde **22 test geçti**.
Üretim importu/mutasyon kontrolü toplam **20 farklı hedefte** geçti; dosyalar
her mutasyondan sonra byte düzeyinde geri yüklendi.

Son staging (`terminal-4`) EXE'siyle, PATH yalnız System32 iken ayrı geçici
profilde `init --non-interactive`, `connections test primary` ve geçici Codex
ayarında `connect codex --test` geçti. MCP 25 aracı keşfetti; model isteği
sayısı 0. Kullanıcının gerçek istemci ayarı değiştirilmedi; bu, Codex
uygulamasıyla uçtan uca kabul değildir. UTF-8 çıktısı paket EXE'sinde de geçti.

Güncel geliştirme kurucusu `dist/terminal-current/R-Agents-0.2.0.dev1-windows-x64.exe`
olarak derlendi (214.445.391 byte). SHA-256:
`339a0dd5a75d343bdf794a841d78b775e83237fda0d631c6dd74e0c6e85a51f0`.
Yanında checksum dosyası vardır. Bu imzasız geliştirme adayı kurulmadı,
kabul edilmiş release veya GitHub yayını değildir. Önceki `terminal-preview`
paketi son düzeltmeleri içermez; kullanıcı kurulumu için kullanılmamalıdır.

## Uygulanan davranışlar

- Endpoint userinfo/query/fragment reddi ortak bağlantı şemasında.
- Büyük dosyanın ilerleyen satırlarını sınırlı taramayla okuma.
- Doğrulama başarısızlığında açık run durumu ve CLI hata çıkış kodu.
- Snapshot sırasında kaydedilen iptalden sonra runner başlatmama.
- Sandbox çağrısına özgü iptal kontrolü, başlangıç kapısı ve thread temizliğini bekleme.
- Her Windows yürütmesinde yeni AppContainer kimliği; çalışma sonrası kendi ACL/profile temizliği.
- POSIX ana süreç çıkmış olsa da süreç grubunu temizleme; macOS native kanıtı hâlâ yok.
- Markdown'da başlıktan bağımsız `ref` ve bağımlılık kimlikleri; eski başlıklı import korunur.
- Manuel/worker ortak ajan ve kanonik workspace kilitleri; meşgul proje ardındaki bağımsız işin seçilmesi.
- Ortak kullanıcı profil kökü, açık profil bağlamının kimlik deposuna taşınması.
- Şema v7: kalıcı tek seferlik/cron takvimi ve hafıza revizyonları; saat dilimi, tek slot telafisi ve kesinti sonrası idempotency.
- Kapalı kayıtlı `runtime_health` ve `workspace_inventory` işleri; sıfır model isteği.
- Katalog ajanlarını MCP'den canlı keşif, workspace/talimat/doğrulama snapshot'ıyla görev atama.
- MCP'den programatik görev ve takvim; çalıştırma araçları hâlâ açık `--allow-execute` ister.
- Kaynak/revizyonlu talimat snapshot'ı korunarak anahtar sözcüklü ilgili skill seçimi.
- Bağımsız doğrulanmış çalışmadan hafıza adayı; yerel açık onay, revizyon,
  düzeltmede onayı kaldırma, arşiv ve anahtar sözcükle seçici yükleme.
  MCP adayı yazabilir fakat onay veremez; `--allow-write` çalıştırma yetkisi değildir.
- SQLite backup API ile WAL dahil tutarlı görev DB yedeği; mevcut DB üzerine yazmadan geri yükleme.
- Apache-2.0 lisans metni ve NOTICE; üçüncü taraf dağıtım bildirimleri yayın kapısında ayrıca üretilecek.

## Kullanıcı profili ve uyumluluk

Varsayılan kök `%LOCALAPPDATA%/RAgents/profiles/default` olur. `RAGENTS_HOME`
ve komuttaki açık `--root` seçimi desteklenir. Açık kök > işlem profil bağlamı
> ortam > varsayılan sırası uygulanır. `setup --directory` profil seçimi,
üretilen worker/MCP başlatıcılarına da taşınır. Göreli yollar bağımlı olunan
mevcut çalışma dizinine göre değil, açık seçimin kanonik yoluna sabitlenir.

Eski `local-profile`, `data/ragents.db` veya `~/.ragents` kendiliğinden okunup
taşınmaz. Mevcut kullanıcılar eski profili açık `--root` ile seçmeli; eski
kimlik konumu farklıysa yeni profilde giriş yapmalıdır. `--config` korunur;
aynı kimlikte katalog ajanı varsa katalog doğruluk kaynağıdır.

Windows ilk ürün hedefidir. POSIX kaynakları korunur fakat macOS/Linux
deneyseldir; Windows'ta sahte platform testi native kabul kanıtı değildir.

## Komutlar

```powershell
# Profil durumunu DB oluşturmadan oku
ragents profile --root C:\RAgents-Profil status

# Görev DB'sinin tutarlı yedeği; çıktı dosyası yeni olmalıdır
ragents profile --root C:\RAgents-Profil backup --output C:\Yedekler\gorevler.db
ragents profile restore --backup C:\Yedekler\gorevler.db --output C:\Deneme\data\ragents.db

# Model kullanmayan görev; yalnız kaydet
ragents tasks --root C:\RAgents-Profil add --config ornek.yaml --handler runtime_health --disabled "Sağlık özeti"
ragents schedules --root C:\RAgents-Profil add --task GOREV_KIMLIGI --cron "0 9 * * *" --timezone Europe/Istanbul
ragents schedules --root C:\RAgents-Profil list

# Hafıza adayını gösterdikten sonra yalnız görülen revizyonu onayla
ragents memory --root C:\RAgents-Profil list --agent analist
ragents memory --root C:\RAgents-Profil show KAYIT_KIMLIGI
ragents memory --root C:\RAgents-Profil approve KAYIT_KIMLIGI --revision 1
```

Takvim şablonu devre dışı, arşivsiz, sırada bir görev olmalıdır. Tanım ve
metadata takvime kopyalanır; şablonu sonradan düzenlemek takvimi değiştirmez.
Worker zamanı gelen işleri aynı kuyruğa ekler. `--once` gelecekteki slotu
beklemez. `catch_up=true` uzun kesintide son slotu bir kez telafi eder;
`--no-catch-up` bir dakikadan eski slotu atlar. Başarısız işler kör tekrar
edilmez. Takvimi kapatmak önceden kuyruğa girmiş görevleri iptal etmez.

DB yedeği görev metinleri/sonuçları gibi hassas kullanıcı verisi içerir.
Kimlik kasası, ajan dosyaları ve workspace bu komutun kapsamına girmez;
bu, henüz tam taşınabilir profil paketi değildir. Geri yükleme yalnız yeni
DB'ye yapılır; daha yeni şema reddedilir. Aktif çalışmanın yedekteki durumu
worker kurtarmasında kesilmiş olarak ele alınır, otomatik yeniden yürütülmez.

## Açık teslim kapıları

- MCP'den mevcut ajan/talimat/skill güncelleme taslağı ve onaylı uygulama.
- Ekipte büyük/binary artifact'ın salt okunur giriş alanına tam aktarımı;
  ölçülen tüketim ile aktif rezervasyonun raporda açık ayrılması.
- Genel komut yayın izninin yerine doğrulanmış commit/artifact hash'ine bağlı
  ayrı yerel yayın onayı; mevcut `allow_publish` tek başına yeterli olmamalı.
- Supervisor durum/durdurma ve güncelleme sonrası yeniden kayıt/başlatma;
  güncelleme kesintisinden açık kurtarma ve tam profil tutarlılığı denetimi.
- Uzak kapsam keşfi/iptal ergonomisi ve gerçek ChatGPT OAuth/tünel kabulü.
  Kimliksiz loopback HTTP genel internete açılmamalıdır.
- Son koddan yeni release adayı, tam paket içerik denetimi, üçüncü taraf/GPL
  kaynak ve bildirimlerinin tamamlanması, SBOM ve Windows paketleme CI kapısı.
- Kullanıcının yerel Windows bilgisayarında EXE kurulumu, gerçek Codex/ChatGPT,
  sağlayıcı/arama hesabı ve sürümlü 20 senaryonun üç tekrarı. Native geliştirme
  testi bunların yerine geçmez; VM yapılmayacak.
- Kabul edilmiş aynı hash'li dosyanın GitHub yayını; ardından yayımlanan
  kurucuyla sıfırdan kurulum ve en son kişisel ajan geçişi.

Bu eksikler tamamlanmadan ürün için “hazır” veya “kurucu tamam” denmez.

Hafıza için başarılı model sonucu yeterli değildir: aynı ajanın `passed`
doğrulama kaydı gerekir ve aday ayrıca yerel kullanıcı onayı bekler. JSON
şema doğrulaması olgusal doğruluğu tek başına kanıtlamaz; onaylayan kullanıcı
iddia ile kaynağı birlikte incelemelidir. Metin değişikliği yeni revizyon ve
yeni onay gerektirir. Görev başına en fazla sekiz kayıt/3000 karakter seçilir;
kalıcı kural dosyaları hafıza işlemiyle değiştirilmez.

## Doğrulama

Güncel tam regresyon: **252 geçti / 3 atlandı, 255 senaryo** (203,30 saniye).
İlk ara koşu 239/3 idi; son sayı hafıza ve son profil/MCP testlerini kapsar.
Editable paket standart build izolasyonuyla yeniden kuruldu; `pip check` temiz.

`scripts/check_product_provenance.py`, hedef regresyonların üretim importlarını,
gölgeleme olmadığını ve üretim fonksiyonu bozulunca testin düştüğünü kontrol
eder. **15 hedefte kontrol geçti.** Her mutasyonun ardından dosya byte
düzeyinde geri yüklenir. Gerçek model, kullanıcı kasası, temiz Windows kurucu
ve uzak istemci/tünel kabulü yapılmadı.


## 0.2.0-dev.3 — terminal deneyimi ve sürümleme

- Sağlayıcı/arama için numaralı menüler; sağlayıcıdan model listesi ve açık listeleme hatası.
- Kurulum sonu özeti; kişisel geliştirme yolları çıkarılmış MCP örnekleri.
- Ürün README'si ve ayrı CONTRIBUTING rehberi.
- `ragents uninstall`: seçili profilin supervisor kaydı, bu kuruluma ait
  yerel MCP kayıtları, PATH ve uygulama dosyaları. Profil ve kimlik bilgileri
  korunur. ChatGPT hesap bağlantısı ve kullanıcı tüneli ayrıca kaldırılır.
- Özel istemci ayar yolları yeni bağlantılarda envantere yazılır. Eski
  özel yollar otomatik keşfedilemez; değiştirilmiş/yabancı MCP kaydı korunur
  ve kaldırma açık hata ile durur.
- [Sürümleme politikası](versioning.md): `0.2.0-dev.N`, kararlı sürümde
  semantik sürümleme. Paket ve Git etiketleri değişmez.
- Temiz staging, bağımsız Python/Git/Chromium indirmeleriyle geçici kurulum
  geçti. Kurulu sürüm `0.2.0.dev3`; gerçek yerel stdio MCP el sıkışması
  25 araç keşfetti, model isteği 0. Yeni kaldırma komutu uygulamayı ve test
  MCP kaydını sildi, profilin korunduğu doğrulandı. Sonra yalnız test verileri temizlendi.
- Wheel içinde yalnız uygulama namespace'i ve paket metadatası bulundu.
- Model listesi testi sahte sağlayıcı kataloğuyla gerçek seçim fonksiyonunu
  çalıştırır; gerçek hesap/plan erişimi kabulü değildir.
- Önceki CI'da Windows Git test fixture'ı tüm DLL'leri taşımıyordu;
  `*.dll` kullanacak şekilde düzeltildi. Önceki macOS/Linux sandbox hataları
  açık; deneysel platformlar tam destek olarak sunulmaz.
- İlk tam test koşusunda Windows süreç sınırı testi Python codec erişim
  hatası verdi; tek başına tekrar geçti. Eşzamanlı başka native test olmadan
  yapılan son seri koşu: **306 geçti, 3 atlandı**, 268,85 saniye.

Bu paket geliştirme ön sürümüdür; ürün hazır kapısı, gerçek hesap/istemci/
arama kabulü ve 20 × 3 senaryo tamamlanmış değildir. Canlı ücretli model
çağrısı yapılmadı. Kendi bilgisayarındaki kabul, temiz VM kabulü diye sunulmaz.


## 0.2.0-dev.4 — resmi anahtarsız arama

- Hermes örneği ve sağlayıcıların kendi belgeleri üzerinden Exa, Parallel,
  Firecrawl ve Keenable resmi ücretsiz MCP uçları doğrulandı. Hermes kodu
  veya başka uygulamanın kimliği/anahtarı alınmadı; sabit arama araçları
  mevcut SafeWebClient üzerinden çağrılır.
- `keyless` seçimi bu dört servis arasında açıkça izin verilmiş bir arama
  zinciridir. Varsayılan `disabled` korunur. Tek sağlayıcı seçimi değişmez;
  SearXNG ve diğer mevcut kaynaklarda ek zincir yalnız `--keyless-fallback`
  ile açılır. Ücretli anahtarlara/hizmetlere geçiş yoktur.
- `ragents search test`, numaralı kurulum seçimi, kaynak URL/erişim tarihi,
  gerçek sağlayıcı ve deneme/hata kayıtları eklendi. Bir sağlayıcı en fazla
  bir kez denenir; geçerli boş sonuç başka sağlayıcıyı tetiklemez.
- Yerel veri veya model kimliği gönderilmez. Ücretsiz uçlara birincil kaynak
  anahtarı aktarılmaz. DNS sabitleme, özel ağ/metadata, yanıt boyutu ve süre
  kontrolleri korunur. Public MCP'nin yalnız sabit arama aracı çağrılır.
- Canlı, anahtarsız ve araç dışında model kullanmayan kontrol: Exa, Parallel,
  Keenable ikişer kaynak sonuç döndürdü. Firecrawl açıkça anonim erişimi
  reddetti; DuckDuckGo CAPTCHA/erişim sınırına takıldı. Bu ikisi deneysel.
- 38 arama/terminal/web/izin testi ve 12 MCP/motor testi: toplam 50 geçti.
  Bu sürümde bütün native test seti yeniden koşulmadı; önceki seri yerel
  taban 306 geçti/3 atlandı. Önceki GitHub Windows Git native testi hâlâ
  başarısız; bütün CI yeşil veya ürün kabulü tamamlandı denmiyor.
- Mevcut `read_page` korunur; Trafilatura veya ağ davranışı farklı DDGS
  bağımlılığı eklenmedi. Ayrıntılar [arama rehberinde](web-search.md).

Kotalar/fiyatlar koda gömülmedi. Sağlayıcıların ücretsiz erişimi, kullanım
amacı ve koşulları değişebilir. Bu hâlâ ürün kabul kapıları açık bir ön sürüm.


## 0.2.0-dev.5 — deneysel arama seçeneklerini kaldırma

Kullanıcı talebiyle DuckDuckGo ve Firecrawl kaynak kodu/sağlayıcı şeması,
menü ve ücretsiz zincirden çıkarıldı. Zincir yalnız Exa → Parallel → Keenable.
Geçmiş sürüm kayıtları tarihsel kanıt olarak korunur; güncel ürün rehberi
kaldırılmış sağlayıcıları seçenek olarak sunmaz. Eski profilde kaldırılmış
bir kaynak seçilmişse `ragents search configure --provider keyless` ile değiştirilir.
