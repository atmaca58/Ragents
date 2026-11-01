# Gerçek sandbox yürütme katmanı

A04 kapsamı. Bu katman, model çağrılarını araç/süreç yürütmesinden ayırır ve
komutları platformun gerçek izolasyon mekanizmalarıyla çalıştırır. Bir platformda
gerekli yetenek yoksa çalıştırma **açıkça reddedilir**; sandbox olmadan sessizce
devam edilmez.

## Ortak sözleşme

`SandboxPolicy` aşağıdaki sınırları taşır:

| Alan | Varsayılan | Anlam |
| --- | --- | --- |
| `workspace` | zorunlu | Kanonik, var olan çalışma dizini; kök symlink/junction olamaz |
| `writable` | `false` | Workspace kökünün tamamına yazma izni |
| `writable_paths` | boş | Yalnız bu göreli dizinlere yazma; `writable=true` ise kök geçerlidir |
| `cwd` | workspace kökü | Sandbox alt sürecinin çalışma dizini; workspace içinde olmalı |
| `network` | `false` | Ağ erişimi; kapalıyken backend ağ izolasyonu uygular |
| `timeout_seconds` | 30 | Duvar saati sınırı; aşılırsa süreç ağacı sonlandırılır |
| `max_memory_mb` | 1024 | Süreç/job bellek sınırı (backend'e göre) |
| `max_processes` | 8 | Windows Job Object aktif süreç sınırı |
| `max_output_bytes` | 65.536 | stdout ve stderr için ayrı çıktı sınırı |
| `env` | boş | Açıkça verilen güvenli ortam değişkenleri |
| `env_allowlist` | `LANG`, `LC_*`, `TZ` | Üst süreçten taşınabilen değişkenler |

Kurallar:

- Komut **argv listesi** olarak çalıştırılır; `shell=True` veya kabuk yorumu
  yoktur. Boş, NUL içeren veya aşırı uzun argümanlar reddedilir.
- `PATH` üst süreçten miras alınmaz; Python çalışma zamanı ve sistem
  dizinlerinden yeniden kurulur.
- `OPENAI_API_KEY`, OAuth tokenı ve benzeri kimlik bilgileri otomatik olarak
  sandbox ortamına taşınmaz. `HOME`, `TEMP`, `TMP`, `USERPROFILE` ve
  `LOCALAPPDATA` geçici sandbox dizinine yönlendirilir.
- Çıktı sınırı aşılırsa süreç ağacı sonlandırılır ve `output_truncated=true`
  döner. Ham model/sağlayıcı çıktısı sınırsız yüklenmez.
- `timeout` aşılırsa `timed_out=true`; `cancel()` çağrılırsa `cancelled=true`
  döner. Her iki durumda da alt süreçler ve torunları sonlandırılır.
- Workspace kökü `Workspace` doğrulamasından geçer: mutlak yol, var olan dizin,
  sürücü kökü değil, kök symlink/junction değil. `sandbox run` için workspace
  olarak ajan profili, `data/` veya kimlik dizini vermeyin; bunlar A03/A05
  korumalı yollarıdır.
- `writable_paths` verilmişse dizinler mevcut olmalıdır; kök salt okunur kalır ve
  yalnız bu alt dizinler yazılabilir. A05 görev grant'i bu alanı kullanır.

## Backend matrisi

| Platform | Backend | Dosya sistemi | Ağ | Süreç | Kaynak | Sert iptal | Okuma izolasyonu |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Windows | AppContainer + Job Object | Yazma: workspace/geçici; okuma: izinli ACL yolları | Varsayılan kapalı; `internetClient` yalnız açık izinle | Job Object süreç ağacı | Bellek, CPU süresi, süreç sayısı | `TerminateJobObject` | Evet |
| macOS | `sandbox-exec` Seatbelt | Yazma: workspace (izinliyse)/geçici | `(deny network*)` | Yeni oturum/process group | RLIMIT_CPU (en iyi çaba) | Process group `SIGKILL` | Hayır; okuma açık |
| Linux | bubblewrap (`bwrap`) | Kök salt okunur; workspace/geçici yazılabilir | `--unshare-net` | PID/IPC/UTS namespace | RLIMIT_AS/CPU (en iyi çaba) | Process group + `--die-with-parent` | Hayır; kök salt okunur |

### Windows — AppContainer + Job Object

- Her çalıştırmada rastgele ve yalnız o yürütmeye ait `RagentsRun-*`
  AppContainer profili/SID oluşturulur. Backend yeniden kullanılsa da kimlik
  yeniden kullanılmaz. Önceki görevin ACL hakları sonraki göreve aktarılmaz.
- Python çalışma zamanı, sanal ortam ve R Agents kaynak dizinine AppContainer
  SID'i için **salt okunur** ACL verilir. Workspace kökü `writable=true` ise
  `(OI)(CI)(M)`, aksi halde `(OI)(CI)(RX)` alır; `writable_paths` verilmişse
  yalnız o alt dizinler `(OI)(CI)(M)` alır. Geçici dizin ayrıca yazılabilir.
- AppContainer varsayılan olarak ağ erişimine sahip değildir. `network=true`
  yalnız `internetClient` yeteneğini ekler; loopback erişimi ayrıca Windows
  loopback muafiyeti gerektirebilir.
- Alt süreç `CREATE_SUSPENDED` başlatılır, Job Object'e atanır ve sonra devam
  ettirilir. Job Object `KILL_ON_JOB_CLOSE`, aktif süreç, bellek ve CPU süresi
  sınırlarını uygular. Zaman aşımı/iptal `TerminateJobObject` ile tüm ağacı
  kapatır.
- Yalnız `.exe`/`.com` doğrudan başlatılır. Python betikleri için
  `python betik.py` kullanın; `.bat`/`.cmd` kabuk yorumu bu katmanda yoktur.
- Windows venv `python.exe` launcher'ı taban Python'u ayrı süreç olarak
  başlatabilir. `max_processes=1` gibi çok düşük sınırlarda venv Python'u
  başlamayabilir; bu durumda taban Python yolunu kullanın veya sınırı en az 2
  yapın.
- Python kurulumu kullanıcı tarafından okunamıyorsa veya ACL değiştirilemiyorsa
  backend çalıştırmayı reddeder. Bu durumda Python'u kullanıcı dizinine kurun
  veya yönetici ACL izni verin.
- Süreç ağacı kapandıktan sonra yalnız o çalışmanın SID'ine verilen ACL'ler
  ve AppContainer profili kaldırılır. Temizlik tamamlanmazsa çalışma hata verir.
  Eski sürümden kalan ortak profil bu sürümde kullanılmaz; kullanıcıya ait
  önceki ACL'ler genel bir temizlik işlemiyle değiştirilmez.

### macOS — Seatbelt

- `/usr/bin/sandbox-exec` kullanılır. Profil `(allow default)` üzerine
  `(deny network*)` ve `(deny file-write*)` ekler; yalnız geçici dizin,
  `writable=true` ise workspace kökü ve `writable_paths` alt dizinleri yazılabilir.
- Okuma izolasyonu yoktur; macOS süreçleri sistem kütüphanelerini ve kullanıcı
  dosyalarını okuyabilir. Bu nedenle `read_isolation=false` bildirilir.
- `sandbox-exec` Apple tarafından eski/deprecated sayılır. Gelecekte kaldırılırsa
  backend açıkça kullanılamaz olur; alternatif bir Seatbelt API'si uygulanana
  kadar izolasyonsuz çalıştırma yapılmaz.
- Süreç sayısı üst sınırı yoktur; bellek/CPU RLIMIT ile en iyi çaba uygulanır.
  Süreç ağacı yeni oturum/process group ile sonlandırılır.

### Linux — bubblewrap

- `bwrap` kurulu olmalıdır (`apt install bubblewrap`). User namespace kapalıysa
  veya bwrap çalışamıyorsa çalıştırma reddedilir.
- Kök `--ro-bind / /` ile salt okunur bağlanır; `--unshare-net`,
  `--unshare-pid`, `--unshare-ipc`, `--unshare-uts`, `--die-with-parent` ve
  `--new-session` kullanılır. Workspace kökü `writable=true` ise `--bind`,
  aksi halde `--ro-bind` edilir; `writable_paths` verilmişse yalnız o dizinler
  ayrıca `--bind` edilir. Geçici dizin `/sandbox-tmp` altına bağlanır.
- Okuma izolasyonu yoktur; kök salt okunur olduğu için yazma sınırı vardır.
  `read_isolation=false` bildirilir.
- Bellek/CPU RLIMIT ile en iyi çaba sınırlandırılır; süreç sayısı üst sınırı
  yoktur (PID namespace ayrımı vardır).

## CLI

```powershell
# Windows
.\.venv\Scripts\ragents.exe sandbox status
.\.venv\Scripts\ragents.exe sandbox run --workspace C:\Projeler\Ornek -- python -c "print('merhaba')"
.\.venv\Scripts\ragents.exe sandbox run --workspace C:\Projeler\Ornek --writable --timeout 60 -- python betik.py
.\.venv\Scripts\ragents.exe sandbox run --workspace C:\Projeler\Ornek --writable-path src --cwd src -- python -m pytest -q
```

```sh
# macOS / Linux
.venv/bin/ragents sandbox status
.venv/bin/ragents sandbox run --workspace /projeler/ornek -- python -c "print('merhaba')"
.venv/bin/ragents sandbox run --workspace /projeler/ornek --writable --timeout 60 -- python betik.py
.venv/bin/ragents sandbox run --workspace /projeler/ornek --writable-path src --cwd src -- python -m pytest -q
```

`status` yalnız rapor üretir; süreç çalıştırmaz. `run` her zaman seçili
platform backend'ini kullanır. `--allow-network`, `--writable` ve
`--writable-path` varsayılan olarak kapalıdır; hepsi açık kullanıcı kararıdır.
`--writable-path` birden çok kez kullanılabilir; `--writable` verilirse kökün
tamamı yazılabilir olur.

JSON sonucu `exit_code`, `stdout`, `stderr`, `timed_out`, `cancelled`,
`output_truncated`, `backend`, `workspace`, `writable_paths` ve `writable`
alanlarını içerir. Zaman aşımı veya çıktı sınırı ayrı bir hata kodu değil,
sonuç alanıdır; CLI yine JSON döndürür.

## stdio MCP sınırı

Stdio MCP sunucusu ayrı bir alt süreçtir ve bu sandbox backend'inin içinde
değildir. `mcp_transport.py` yalnız açıkça listelenen ortam değişkenlerini
geçirir; yine de harici araç sunucusunun kendi yetkisi ayrıca değerlendirilir.
A04/A05 kapsamında stdio MCP bağlantısı tek başına sandbox sayılmaz. A11'de
araç sunucusu için ayrı politika ve izin modeli ele alınacaktır.

## Kanıt ve sınır

Windows'ta gerçek AppContainer + Job Object testleri çalıştırıldı:

- Kök dışına yazma ve okuma reddedildi.
- Yerel loopback dinleyicisine ağ bağlantısı kurulamadı.
- Zaman aşımında torun süreç de sonlandırıldı; işaret dosyası oluşmadı.
- `max_processes=1` ile yeni alt süreç reddedildi.
- Çıktı sınırı aşıldığında süreç sonlandırıldı ve çıktı kırpıldı.
- Üst süreçteki `OPENAI_API_KEY` sandbox ortamına taşınmadı.
- `sandbox run` CLI'si gerçek süreçle çalıştı.

macOS ve Linux backend'leri ile komut/profile üretimi çevrimdışı testlerle
doğrulandı; native macOS/Linux izolasyon testleri bu çalışma ortamında
çalıştırılmadı. `.github/workflows/compatibility.yml` bu testleri ilgili
runner'larda çalıştıracak şekilde hazırlanmıştır. Native sonuçlar alınmadan
macOS/Linux için "doğrulanmış" etiketi kullanılmaz; bu C03 kapısına bağlıdır.

## Kapsam dışı

- Dosya yazma/patch ve task bazlı izinler A05'te eklendi; ayrıntılar
  [dosya ve komut](tools-and-execution.md) belgesindedir.
- Bağımsız çıktı doğrulaması ve tarayıcı kanıtı A06'da eklendi; A05 yalnız komut
  çalıştırır, sonucu başarı saymaz.
- Otomatik servis/başlangıç A12'ye aittir.
- Ağ allowlist'i, alan adı bazlı filtre ve uzak MCP kimlik doğrulaması bu
  görevin kapsamı dışındadır.
