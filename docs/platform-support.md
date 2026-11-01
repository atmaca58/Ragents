# Windows, macOS ve Linux hedefleri

**Güncel ürün kapsamı:** İlk release Windows 11 x64 içindir. macOS/Linux
kodu ve test hedefleri korunur; native kabul tamamlanana kadar deneysel
olarak etiketlenir. Aşağıdaki üç platform matrisi sonraki genişleme hedefidir;
ilk Windows yayınının tamamlandığına dair kanıt değildir. Yeni profil kökü ve
takvim/işletim davranışları [güncel uygulama kaydındadır](windows-product-progress.md).

Üç işletim sistemi ürünün hedefidir. Aynı Python çekirdeği, ajan/bağlantı
şemaları, görev kuyruğu ve MCP sözleşmeleri kullanılır. Platforma özgü kurulum,
güvenli kimlik kasası, sandbox ve otomatik servis katmanları ayrı tutulur.
Bir hedefte aynı güvenlik özelliği sağlanamıyorsa işlem açıkça reddedilmeli;
sessizce daha geniş yetkiyle devam edilmemelidir.

> **Kanıt sınırı:** Gerçek yerel test kanıtı Windows / Python 3.14.7 içindir.
> macOS ve Linux için native kurulum, kasa ve servis testleri henüz
> çalıştırılmadı. CI matrisi hazırlanmıştır fakat bu çalışma alanında
> tetiklenmemiştir. Native testler geçmeden “macOS/Linux destekli” etiketi
> verilmez.

## Ön koşullar

| Platform | Gerekenler |
| --- | --- |
| Windows | Python 3.12–3.14, PyPI erişimi; isteğe bağlı `py` launcher ve PowerShell |
| macOS | Python 3.12–3.14 (python.org veya Homebrew), PyPI erişimi; `sandbox-exec` (genellikle sistemde); isteğe bağlı Xcode Command Line Tools |
| Linux | Python 3.12–3.14, `venv`/`ensurepip`, PyPI erişimi; sandbox için `bubblewrap`/`bwrap`; masaüstü kasa için Secret Service veya KWallet |

- Python sürümü `python --version` veya `python3 --version` ile doğrulanır.
  Sistemdeki eski Python (özellikle macOS/Linux'ta 3.9) yeterli değildir.
- Kaynak ağacından kurulum için `git` gerekir; PyPI paketinden kurulumda
  gerekmez.
- Windows'ta uzun yol desteği etkin değilse kısa bir proje/workspace yolu seçin;
  uygulama yol uzunluğunu 512 karakterle sınırlar.
- `python3-venv` eksikse Debian/Ubuntu'da `sudo apt install python3-venv`
  gerekebilir. Bu, proje dizinine kurulum yapılmasını engellemez.
- Sanal ortamı aktive etmek zorunlu değildir; komutlar doğrudan venv
  yorumlayıcısıyla çalıştırılabilir.
- Türkçe çıktı ve dosya adları için UTF-8 kullanın. Windows PowerShell 5.1'de
  `$env:PYTHONUTF8 = "1"` ayarlanabilir; POSIX'te UTF-8 locale (`LANG`) seçili
  olmalıdır. Testler `PYTHONUTF8=1` ile çalıştırılır.

## Kurulum

Komutlar `Ragents` dizininden verilir. Üç platformda da aynı ortak kurucu
`scripts/setup.py` kullanılır; PowerShell ve POSIX kabuk dosyaları yalnızca ince
sarmalayıcılardır.

Windows:

```powershell
python scripts/setup.py
# Alternatif PowerShell sarmalayıcısı:
.\scripts\setup.ps1

# Yalnız bağımlılıkları kur:
python scripts/setup.py --skip-configure
```

macOS / Linux:

```sh
python3 scripts/setup.py
# Alternatif POSIX sarmalayıcısı:
sh scripts/setup.sh

# Yalnız bağımlılıkları kur:
python3 scripts/setup.py --skip-configure
```

- Windows venv yorumlayıcısı `.venv/Scripts/python.exe`, macOS/Linux
  yorumlayıcısı `.venv/bin/python` olur.
- `--run-tests` çevrimdışı testleri çalıştırır; `--profile-directory` yeni
  profil dizinini seçer. PowerShell karşılıkları `-RunTests`,
  `-SkipConfigure` ve `-ProfileDirectory` seçenekleridir.
- Windows kurucusu mevcut `requirements-dev.lock` dosyasını kullanır. macOS ve
  Linux kurucuları bağımlılıkları `pyproject.toml` üzerinden çözer. Lock dosyası
  hash doğrulamalı veya bütün platformları kapsayan bir lock değildir; platform
  başına kilit ve gerçek temiz kurulum kanıtı C03 kapsamındadır.
- Kurulum dizininde boşluk veya Türkçe karakter olabilir; komutlar argv listesi
  ve tırnaklı kabuk değişkenleriyle çalıştırılmalıdır.
- Windows'ta PowerShell yürütme politikası `setup.ps1` dosyasını engellerse
  `python scripts/setup.py` doğrudan kullanılabilir.
- Daha önce başka bir işletim sistemi için oluşturulmuş `.venv` taşınmamalıdır;
  yeni platformda `.venv` yeniden oluşturulmalıdır.

## Komut yolu sözleşmesi

Aşağıdaki tablo, diğer rehberlerdeki Windows PowerShell örneklerinin POSIX
karşılığını verir. Windows'ta `.exe` uzantısı yalnız Windows içindir; macOS ve
Linux'ta kullanılmaz.

| İşlem | Windows | macOS / Linux |
| --- | --- | --- |
| CLI | `.\.venv\Scripts\ragents.exe` | `.venv/bin/ragents` |
| Python | `.\.venv\Scripts\python.exe` | `.venv/bin/python` |
| Test | `.\.venv\Scripts\python.exe -m pytest` | `.venv/bin/python -m pytest` |
| Modül olarak CLI | `.\.venv\Scripts\python.exe -m ragents` | `.venv/bin/python -m ragents` |
| Profil worker'ı | `.\local-profile\start-worker.ps1` | `.venv/bin/python local-profile/start-worker.py` |
| POSIX shell worker | — | `sh local-profile/start-worker.sh` |

Windows venv yolu `.venv\Scripts\`, POSIX venv yolu `.venv/bin/` altındadır.
`python -m ragents` biçimi özellikle PATH ve `.exe` farkından bağımsızdır.
Rehberlerdeki PowerShell blokları Windows içindir; aynı komut macOS/Linux'ta bu
tabloya göre çalıştırılır.

## Worker ve MCP

Her yeni profil üç başlatıcı içerir:

| Dosya | Kullanım |
| --- | --- |
| `start-worker.py` | Üç platform için ortak Python başlatıcı |
| `start-worker.ps1` | Windows PowerShell |
| `start-worker.sh` | macOS/Linux POSIX shell |

```powershell
# Windows
.\.venv\Scripts\python.exe local-profile/start-worker.py --once
.\local-profile\start-worker.ps1
```

```sh
# macOS / Linux
.venv/bin/python local-profile/start-worker.py --once
sh local-profile/start-worker.sh
```

- Kurulum worker'ı otomatik açmaz. `--once` mevcut kuyruk boşalınca çıkar.
- Başlatıcılar işletim sistemi servisi değildir; otomatik başlangıç A12
  kapsamındadır.
- `start-worker.py`, kurulu venv yorumlayıcısıyla çalıştırılmalıdır. Profil
  dizinine taşınırsa Python paketinin hâlâ kurulu olduğu venv kullanılmalıdır.
- `start-worker.sh` POSIX'te yürütme bitiyle üretilir. Depodaki `.sh` dosyaları
  `.gitattributes` ile LF satır sonu kullanır; Windows'ta oluşturulan profil
  dosyası POSIX'e taşınırsa `chmod +x` veya `sh dosya.sh` gerekebilir.
- Üretilen MCP JSON/TOML dosyaları kurulumun gerçek Python yolunu kullanır;
  sabit Windows yolu içermez. Profil, venv veya proje taşındığında mutlak
  yolların güncellenmesi gerekir. `examples/mcp-client.json` ve
  `examples/codex-mcp.toml` eski Windows kurulum örnekleridir; taşınabilir
  kurulumda `scripts/setup.py` tarafından üretilen dosyalar kullanılmalıdır.
- Yerel Python MCP sunucusu için `command: "{python}"`, çalışan R Agents
  yorumlayıcısına çözülür. Yalnız bu tam komut değeri desteklenir; args/env
  içinde genel metin ikamesi yapılmaz. `examples/ollama-mcp.yaml` bu yolu
  kullanır; örnekteki göreli args yolu için çalışma dizini hâlâ `Ragents`
  olmalıdır.

## Kimlik kasası

ChatGPT kimlik bilgileri keyring katmanı üzerinden güvenli işletim sistemi
kasası gerektirir:

| Platform | Beklenen kasa |
| --- | --- |
| Windows | Windows Credential Manager |
| macOS | Keychain |
| Linux | Secret Service (GNOME Keyring vb.) veya KWallet |

- Headless Linux'ta kasa oturumu yoksa ChatGPT OAuth akışı açık hata verir;
  düz metne otomatik dönüş yapılmaz. Gerekirse Secret Service/GNOME Keyring
  paketlerini kurup kullanıcı oturumunda `gnome-keyring-daemon` çalıştırın;
  aksi halde API anahtarı kullanan sağlayıcıları seçin.
- Ollama ve yalnız API anahtarı kullanan bağlantılar ChatGPT kasası gerektirmez;
  anahtar ortam değişkeninden okunur.
- OAuth tokenları ve anahtar değerleri YAML, JSON, TOML veya SQLite ürün
  kayıtlarına yazılmaz. Yalnız ortam değişkeni adı/hesap etiketi saklanır.
- macOS Keychain ve Linux kasa erişimi ilk kullanımda kullanıcı onayı
  isteyebilir; worker/MCP süreci doğru kullanıcı oturumunda çalışmalıdır.

## Workspace ve dosya yolu davranışı

- Workspace kökü çözümlenmiş/canonical yoldur. Kökün kendisi symlink veya
  junction ise reddedilir. macOS'ta `/var` gibi sistem üst dizinlerinde bulunan
  symlink'ler çözümlenir; workspace kökü kanonik hedefe sabitlenir.
- Workspace **içindeki** symlink ve junction bileşenleri takip edilmez; hedef
  kök dışına çıkıyorsa veya korumalı bir dizine çözülüyorsa reddedilir.
- `agents/`, `data/`, `ragents.yaml` ve `RAGENTS_HOME` korumalıdır. Varsayılan
  kimlik kökü Windows/macOS/Linux'ta `~/.ragents` altındadır; `RAGENTS_HOME`
  ile değiştirilebilir.
- Taşınabilir ad politikası üç OS'te aynıdır: Windows sürücü/UNC yolları, ADS
  (`dosya:akış`), `NUL`/`CON` gibi cihaz adları ve sondaki nokta/boşluk
  reddedilir. POSIX'te geçerli olsa bile `:` içeren adlar ve sondaki nokta/boşluk
  kabul edilmez; proje dosyalarınızı taşınabilir adlandırın.
- Windows varsayılan olarak büyük/küçük harfe duyarsızdır; macOS genellikle
  duyarsız, Linux duyarlıdır. Aynı ada yalnız harf büyüklüğüyle bağlı iki dosya
  oluşturmayın.
- Bu okuma katmanı tek başına sandbox değildir. A04 ile eklenen gerçek
  yürütme sandbox'ı Windows AppContainer + Job Object, macOS Seatbelt ve Linux
  bubblewrap backend'lerini kullanır; ayrıntılar [sandbox](sandbox.md)
  belgesindedir. Desteklenmeyen backend'de komut çalıştırma reddedilir.

## Platform kabul kontrol listesi

Her yeni platform/backend için en az şu kontroller kanıtlanmalıdır:

1. `scripts/setup.py --skip-configure --run-tests` temiz venv'de geçer.
2. Yeni profil oluşturulur; `start-worker.py --once` ve o platformun yerel
   başlatıcısı boş geçici DB ile çalışır.
3. `examples/ollama-mcp.yaml` içindeki `{python}` yolu gerçek MCP alt sürecini
   başlatır; araç çağrısı ve çıktı sınırı çalışır.
4. Workspace kökü kanonikleştirilir; iç symlink/junction reddedilir, kök dışına
   çıkış ve korumalı dizin okuması başarısız olur.
5. ChatGPT için gerçek OS kasasına yazma/okuma ve kasa yokken açık hata
   senaryosu denenir; anahtar/token günlüğe veya DB'ye yazılmaz.
6. Görev kuyruğu, iptal, worker yeniden başlatma ve sonuç okuma akışı gerçek
   süreçlerle tekrarlanır.
7. Servis/otomatik başlangıç varsa A12 kapsamında ayrıca kaldırma ve geri yükleme
   denenir; yoksa manuel başlatıcı olduğu açıkça belirtilir.
8. `sandbox status` seçili backend'i ve yetenekleri raporlar; `sandbox run` ile
   kök dışına yazma, ağ erişimi, zaman aşımı ve alt süreç sonlandırma gerçek
   izolasyon testleriyle doğrulanır. Backend yoksa çalıştırma reddedilir.

Bu liste C03 temiz makine matrisinin ve A04/A12 kabul kanıtlarının temelidir.

## Test matrisi ve kanıt

`.github/workflows/compatibility.yml`, depo kökünde
Windows/macOS/Ubuntu × Python 3.12/3.13/3.14 için dokuz iş çalıştıracak şekilde
hazırlandı. Workflow bu çalışma alanında veya uzakta henüz tetiklenmedi; gerçek
CI kanıtı sayılmaz. Üst depo altında kullanılacaksa workflow yolu ve çalışma
dizini o depoya göre uyarlanmalıdır.

Yerel çevrimdışı doğrulama:

```powershell
# Windows
.\.venv\Scripts\python.exe -m pytest -o addopts= -q
.\.venv\Scripts\python.exe -m pip check
```

```sh
# macOS / Linux
.venv/bin/python -m pytest -o addopts= -q
.venv/bin/python -m pip check
```

CI adımı `python scripts/setup.py --skip-configure --run-tests` kullanır.
Testler gerçek model, kimlik kasası veya hesap gerektirmez. POSIX runner'da
`start-worker.sh` gerçekten çalıştırılır; Windows'ta Python başlatıcısı gerçek
alt süreç ve geçici DB ile sınanır.

| Alan | Mevcut kanıt |
| --- | --- |
| Windows / Python 3.14.7 | Gerçek yerel çevrimdışı testler: 213 geçti, 3 atlandı (216 senaryo; 1 POSIX native skip) |
| macOS/Linux kurucu yol ve komut seçimi | Windows'ta kontrollü platform girdileriyle test |
| Ortak Python worker ve MCP örneği | Windows'ta gerçek süreç testleri |
| Windows sandbox | AppContainer + Job Object gerçek yazma/ağ/süreç/kaynak testleri; yalnız izinli alt dizine yazma |
| Windows dosya/komut araçları | Sandbox içinde `write_file`/`apply_patch`, allowlist'li `run_command`, artifact kaydı ve çıktı sınırı |
| macOS/Linux sandbox backend'i | Komut/profile ve backend sözleşmesi test edildi; native izolasyon henüz çalıştırılmadı |
| macOS/Linux native kurulum ve testler | Henüz çalıştırılmadı |
| Gerçek OS kasası ve otomatik servis | Üç platform için ayrı kabul kanıtı gerekiyor |

Native testler geçmeden macOS/Linux için doğrulanmış tam destek iddiası
yapılmaz. CPU mimarisi, Linux dağıtımı ve sürüm kapsamı da gerçek sonuçlarla
belirlenecek. A04, A12 ve C03 görevlerinin kabul ölçütleri buna göre güncellendi.

## Sık karşılaşılan sorunlar

| Belirti | Kontrol |
| --- | --- |
| `No module named venv` / `ensurepip` yok | Linux'ta `python3-venv` paketini kurun |
| `python` bulunamadı | macOS/Linux'ta `python3`, Windows'ta `py -3` veya Python yolunu deneyin |
| PowerShell `setup.ps1` çalışmıyor | Yürütme politikasını gevşetmek yerine `python scripts/setup.py` kullanın |
| ChatGPT girişi kasa hatası | Masaüstü oturumunda Keychain/Secret Service/KWallet erişimini doğrulayın |
| Worker açılmıyor | Profil worker'ını kurulu `.venv` yorumlayıcısıyla çalıştırın |
| MCP sunucusu başlamıyor | `{python}` yolunu ve göreli `args` için çalışma dizinini kontrol edin |
| Profil başka makinede açılmıyor | Mutlak venv/DB/MCP yollarını ve OS'e özgü `.venv` yolunu yenileyin |
| Türkçe karakterler bozuk görünüyor | `PYTHONUTF8=1` ve UTF-8 terminal/locale kullanın |
| `sandbox status` backend'i kullanılamıyor diyor | Linux'ta `bwrap`, macOS'ta `sandbox-exec`, Windows'ta AppContainer/ACL iznini kontrol edin |
| Sandbox'ta Python başlamıyor | Windows'ta Python kurulumuna AppContainer salt okunur ACL izni verilemiyor olabilir; kullanıcı dizinine kurun |
| Sandbox'ta ağ beklenmedik şekilde açık/kapalı | `sandbox run` varsayılanı kapalıdır; `--allow-network` açık karardır. Windows loopback ayrıca muafiyet gerektirir |
| `run_command` "izinli değil" diyor | Ajan profilinde veya görev grant'inde `commands` listesine çalıştırılabilir adını ekleyin; yol değil ad kullanın |
| Push/yayın komutu reddedildi | `allow_publish` varsayılan kapalıdır; yalnız açık kararla `--allow-publish` kullanın |
| Dosya yazma "yazılabilir dizinlerin dışında" diyor | Görev grant'inde `writable_paths` içine göreli dizini ekleyin; dizin mevcut olmalı |

## Kapsam dışı ve sıradaki adımlar

- Dosya yazma/patch ve komutun modele araç olarak açılması A05'te eklendi;
  izinler ve platform sınırları [dosya ve komut](tools-and-execution.md)
  belgesindedir.
- Otomatik servis/başlangıç (Windows servisi, launchd, systemd kullanıcı
  servisi) A12'ye aittir; mevcut `start-worker` dosyaları manuel başlatıcıdır.
- Temiz makine kurulumu, yükseltme, geri dönüş ve kaldırma C03'e aittir.
- macOS/Linux native testleri ve gerçek kasa/servis kanıtı tamamlanmadan üç
  platform için eşit destek iddiası yapılmaz.
