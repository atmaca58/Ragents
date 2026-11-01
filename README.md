# R Agents

Windows 11 x64 için PowerShell'de tek komutla geliştirme sürümü kurulumu:

```powershell
irm https://raw.githubusercontent.com/atmaca58/Ragents/v0.2.0-dev.20261102.2/scripts/install.ps1 | iex
```

Python/Git/Chromium ayrıca kurulu olmak zorunda değildir; kurucu sabit
çalışma zamanlarını resmi kaynaklarından indirir ve hash'leri doğrular.
Yönetici yetkisi gerekmez. Kurulum sonunda terminalden model/arama seçimi
açılır. Bu bir geliştirme ön sürümüdür; gerçek hesap/istemci kabulü açık.
[Kurulum ve MCP bağlantısı](docs/terminal-quickstart.md).

Windows ürünleştirmesinin uygulanan davranışları, yeni profil/takvim/yedek
komutları ve açık teslim kapıları [güncel uygulama kaydında](docs/windows-product-progress.md).
İlk desteklenen ürün Windows 11 x64'tür; macOS/Linux native kabulüne kadar deneyseldir.

Lisans: [Apache-2.0](LICENSE). Bu geliştirme sürümü henüz Windows kurucusu ve
ürün kabul kapıları tamamlanmış bir release değildir.

**Ana ürün akışı terminaldir:** Windows EXE kurucusundan sonra `ragents init`,
ardından `ragents connect codex`, `ragents connect opencode` veya
`ragents connect claude`. Ayrı ürün web paneli yoktur; MCP kurulum taslakları
`ragents approvals` ile terminalden onaylanır. ChatGPT web için HTTPS tüneli ve
OAuth gerekir. [Terminal kurulum ve bağlantı rehberi](docs/terminal-quickstart.md).
Bu komutların çevrimdışı regresyonları var; gerçek istemci/hesap kabulü açık.

Kendi LLM kaynağınızı bağlayabileceğiniz, Python tabanlı bağımsız ajan sistemi.
Bu paket V2'nin **ilk çalışan native prototipidir** (`0.2.0.dev1`).
Codex/OpenCode kurulumu gerektirmez. Python komut satırı bu çekirdeğin ince
arayüzüdür; model çalıştırmak için harici bir ajan CLI'sı başlatılmaz.

**ChatGPT OAuth, OpenCode Go ve Zen bağlantıları eklendi.** Giriş komutları,
örnek ayarlar ve hesap/plan ayrımı için
[entegrasyon rehberini](docs/provider-integrations.md) okuyun.

**İlk üç adım tamamlandı:** Luna ile canlı ChatGPT doğrulaması, token/bağlam
yönetimi ve SQLite görev/çalışma kayıtları. Komutlar ve doğrulama sınırları
[uygulama raporunda](docs/first-three-steps.md).

**Sürekli worker ve MCP desteği hazır:** kalıcı kuyruk, eşzamanlılık sınırı,
zaman aşımı, başka istemciden iptal, izinli MCP araç seçimi ve V2 yönetim MCP'si.
Kurulum ve komutlar [servis ve MCP rehberinde](docs/service-and-mcp.md).

**Dışarıdan yönetim:** MCP üzerinden görev gönderme, durum/sonuç alma, iptal
ve görev başına kayıtlı model kaynağı seçimi hazır. Stdio ve yerel HTTP desteği,
Codex/diğer istemci ayarları ve ChatGPT tünel bağlantısı
[dış yönetim rehberinde](docs/external-management.md).

**Görev yönetimi hazır:** başlık, açıklama, öncelik, etkinlik, bağımlılık,
tanım revizyonu, arşivleme ve Markdown dışa/içe aktarma eklendi. SQLite
doğruluk kaynağıdır; kullanım [görev yönetiminde](docs/task-management.md).

**Birleşik kurulum hazır:** `scripts/setup.py` sağlayıcı/model seçimini,
örnek ajanı, bağlantı kontrolünü ve worker/MCP dosyalarını tek akışta oluşturur.
[Kurulum ve özelleştirme rehberi](docs/setup-and-customization.md).

V1 benzeri günlük kullanım ve ajan ekipleri için eksikler, bağımlılıklar ve
tamamlanma ölçütleri [geliştirme görev listesinde](docs/readiness-backlog.md).

Aşağıdaki hızlı komutlar Windows içindir; macOS/Linux'ta `.exe` yerine
`.venv/bin/ragents` kullanın.

```powershell
.\.venv\Scripts\ragents.exe auth login chatgpt
.\.venv\Scripts\ragents.exe run --config examples/chatgpt-luna.yaml "Merhaba."
```

## Kurulum

Windows, macOS ve Linux üzerinde Python 3.12–3.14 hedeflenir. Gerçek yerel
doğrulama Windows / Python 3.14.7 içindir; macOS/Linux native testleri henüz
çalıştırılmadı. [Platform kurulumları ve test matrisi](docs/platform-support.md).

macOS / Linux için:

```sh
python3 scripts/setup.py
.venv/bin/python local-profile/start-worker.py
```

Proje dizininde PowerShell ile:

```powershell
cd C:\RAgents-Kaynak
.\scripts\setup.ps1
.\.venv\Scripts\ragents.exe demo
```

Diğer bölümlerdeki PowerShell/`.exe` örnekleri Windows içindir. macOS/Linux
karşılıkları `.venv/bin/ragents`, `.venv/bin/python` ve
`local-profile/start-worker.py` biçimindedir; tam tablo
[platform desteğindedir](docs/platform-support.md).

Sandbox backend'ini kontrol edin ve izole bir komut çalıştırın:

```powershell
.\.venv\Scripts\ragents.exe sandbox status
.\.venv\Scripts\ragents.exe sandbox run --workspace C:\Projeler\Ornek -- python -c "print('merhaba')"
```

Ayrıntılar, platform gereksinimleri ve güvenlik sınırları
[sandbox rehberindedir](docs/sandbox.md).

Script Python ortamını/bağımlılıkları kurar ve ajan kurulum sihirbazını açar.
Model indirmez; gerçek model bağlantı testi açık seçim gerektirir ve token
tüketebilir. Yalnız bağımlılıklar için `-SkipConfigure` kullanın.
İlk kurulum PyPI erişimi gerektirir. Profil sonrası sürekli worker başlatma:

```powershell
.\local-profile\start-worker.ps1
```

`demo` sahte model kullanır, çıktıda `simulation: true` bulunur. Gerçek kalite
ve tüketim ölçümü değildir. PowerShell script kullanmadan eşdeğer kurulum:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.lock -e ".[dev]"
.\.venv\Scripts\python -m ragents demo
```

`pyproject.toml` doğrudan bağımlılıkların kaynağıdır. `requirements-dev.lock`
Windows geliştirme ortamında çözülen doğrudan ve geçişli bağımlılıkların sabit
sürümleridir; macOS/Linux kurucusu `pyproject.toml` kullanır. Lock hash
doğrulamalı veya tüm platformları kapsayan bir lock değildir.
Build backend sürüm aralığı `pyproject.toml` içindedir.

## Yerel model ile çalışma

Ollama'yı ayrı kurup servisinizde bulunan, araç kullanımı destekleyen modelin
kimliğini `examples/ollama.yaml` içinde belirtin. Örnekteki model indirilmez.

```powershell
.\.venv\Scripts\ragents.exe check --config examples/ollama.yaml
.\.venv\Scripts\ragents.exe run --config examples/ollama.yaml "Kısaca kendini tanıt."
```

`check` yalnız şemayı ve bağlantı referansını doğrular; modelin kurulu olduğunu,
sağlayıcının erişilebilir olduğunu veya anahtarın geçerliliğini kontrol etmez.
`run` gerçek sağlayıcı çağrısı yapar. Görev ve başarılı sonuç ürün verisi olarak
`data/ragents.db` dosyasında düz metin saklanır; `--db` ile başka yol seçilebilir.
OAuth/API anahtarlarının değerleri bu kayıtlara alınmaz. Python `run_task`
fonksiyonu geçici çalışmaya devam eder; CLI kalıcı görev servisini kullanır.
CLI'daki görev argümanı işletim sistemi süreç listesinde ve terminal geçmişinde
görülebilir; gizli görev içeriği için bu prototip arayüzü kullanılmamalıdır.

## OpenRouter

`examples/openrouter.yaml` dosyasındaki `vendor/model` yer tutucusunu hesabınızda
kullanabildiğiniz gerçek model kimliğiyle değiştirin. Anahtarı dosyaya yazmayın:

```powershell
# OPENROUTER_API_KEY ortam değişkenini kendi oturumunuzda tanımladıktan sonra:
.\.venv\Scripts\ragents.exe check --config examples/openrouter.yaml
.\.venv\Scripts\ragents.exe run --config examples/openrouter.yaml "Kısa bir çalışma planı çıkar."
```

Yalnız `api_key_env` ile belirtilen değişken okunur. Başka servislerin anahtarları
otomatik kullanılmaz. OpenRouter endpoint'i sabittir. Ollama için özel endpoint
ve isteğe bağlı anahtar desteklenir; bu adrese görev içeriği ve belirtilmişse
anahtar gönderilir. Yalnız güvendiğiniz adresleri kullanın.

Tek dosyada birden fazla `connections` girdisi tanımlayıp
`run --config ragents.yaml --connection router "Görev"` ile bağlantıyı
seçebilirsiniz. Ajan kimliği, talimatı ve araç izinleri değişmez.
Desteklenmeyen sağlayıcı/araç adı veya bilinmeyen alan reddedilir; otomatik
başka sağlayıcıya geçiş yoktur. ChatGPT/Luna canlı doğrulandı; diğer sağlayıcıların
canlı doğrulaması ayrıca yapılacaktır.

## Araçlar ve sınırlar

- Varsayılan örnek ajan araçsızdır. `tools: [text_stats]` ile yalnız metin
  sayma aracı açılır. Araç girdisi en fazla 8.000 karakterdir.
- Modele araçlar kendiliğinden verilmez. `write_file`, `apply_patch` ve
  `run_command` yalnız `agent.yaml` `tools` listesinde açıkça seçilirse ve görev
  grant'i izinli dizin/komutları tanımlıyorsa verilir. Komutlar argv listesiyle
  platform sandbox'ında çalışır; ağ ve yayın izni ayrıdır. MCP üzerinden verilen
  yetkiler açık araç izin listesiyle belirlenir.
- Git, arama, sayfa okuma ve yönetilen Playwright araçları açık araç izni
  ister. Tarayıcı doğrudan ağa çıkmaz; denetimli web geçidi kullanır.
- Görev izinleri kuyruğa girerken dondurulur: `readable_paths`, `writable_paths`,
  `commands`, `allow_network`, `allow_publish`. Yetkisiz dizin/komut reddedilir;
  model veya süreç çıktısı sınırsız yüklenmez.
- `request_limit`, `tool_calls_limit`, birikimli `input_tokens_limit`,
  `output_tokens_limit`, `total_tokens_limit` ve
  `timeout_seconds` uygulanır. SDK ve model doğrulama tekrarları sıfırdır.
- Geçmiş otomatik taşınmaz, boşta model çağrılmaz. Python sözleşmesinde açıkça
  verilen geçmişin eski turları sayıya/karaktere göre çıkarılır. Büyük görevler
  önceden reddedilir; uzun araç sonuçları işaretlenerek sınırlandırılır.
- Ollama/OpenRouter ve Go/Zen'de çıktı token sınırı model isteğine de iletilir.
  Her adımda kalan çıktı bütçesi kullanılır. ChatGPT plan yolu bu alanı kabul
  etmez; burada sonradan kullanım denetimi uygulanır. Token denetimi sağlayıcı
  kullanımına bağlıdır ve yanıt sonrasında aşımı tespit edebilir. Kesin parasal
  harcama sınırı yoktur; karakter sınırı tokenizer yerine geçmez.
- Sıfır/eksik token bildirimi ihtiyatlı olarak `null` gösterilir; maliyet
  hesaplanmadığından `cost_usd` her zaman `null` kalır. Demo kullanımı sentetiktir.
- Süre dolunca bekleyen async işlem iptal edilir; uzaktaki sağlayıcının üretimi
  durdurduğuna veya ücret yazmadığına dair garanti verilmez.

## Kalıcı görevler

```powershell
# Yalnız kaydet; model çağırmaz.
.\.venv\Scripts\ragents.exe tasks add --config examples/chatgpt-luna.yaml --key is-001 "Kısa görev"
.\.venv\Scripts\ragents.exe tasks list
.\.venv\Scripts\ragents.exe tasks run GOREV_KIMLIGI
.\.venv\Scripts\ragents.exe tasks show GOREV_KIMLIGI
.\.venv\Scripts\ragents.exe tasks result CALISMA_KIMLIGI

# Süreç kaybından sonra; model çağırmaz.
.\.venv\Scripts\ragents.exe tasks recover
.\.venv\Scripts\ragents.exe tasks retry GOREV_KIMLIGI
```

Görevler başlık, açıklama, öncelik, etkinlik ve bağımlılık taşır. Kuyruk
`priority DESC, created_at ASC` sırasıyla çalışır; bağımlılıkları tamamlanmamış
görev beklemede kalır. Sıradaki veya başarısız görev `tasks edit` ile
düzenlenebilir; her değişiklik tanım revizyonunu artırır. `tasks archive` ve
`tasks restore` görev geçmişini silmeden gizler. Markdown görünümü için
`tasks export`/`tasks import` kullanın:

```powershell
.\.venv\Scripts\ragents.exe tasks add --agent arastirmaci --title "Rapor" `
  --priority 5 --depends-on BASKA_GOREV "Raporu hazırla"
.\.venv\Scripts\ragents.exe tasks edit GOREV_KIMLIGI --priority 9
.\.venv\Scripts\ragents.exe tasks revisions GOREV_KIMLIGI
.\.venv\Scripts\ragents.exe tasks export --output gorevler.md
```

SQLite doğruluk kaynağıdır; Markdown yalnız dışa/içe aktarma görünümüdür.
Alanlar, bağımlılık kuralları ve sınırlar
[görev yönetiminde](docs/task-management.md) açıklanır.

`run --key is-001 ...` aynı içerikle tamamlanmış görevin sonucunu yeniden
model çağırmadan döndürür (`cached: true`). Dönen usage kayıtlı çalışmaya aittir.
Başarısız görevler kendiliğinden yeniden çalışmaz. Kurtarma aktif süreç kilidine
dokunmaz; `retry` yalnız sıraya alır. Aktif worker sıradaki görevi alır;
worker kullanılmıyorsa `tasks run` ile elle çalıştırılır.
Başarısız/kesilmiş çalışmanın bilinmeyen kısmi tüketimi `null` kalır.

Görevin gerçekten tamamlandığını model beyanından bağımsız denetlemek için
`--verify-plan` kullanın:

```powershell
.\.venv\Scripts\ragents.exe tasks add --agent arastirmaci `
  --verify-plan dogrulama.yaml "Raporu hazırla"
```

Plan; dosya, JSON şema, argv tabanlı test komutu ve Playwright JSON raporu
kontrollerini içerebilir. Başarısız kontrol görevi `failed` yapar; model
sonucu ve kanıt `tasks show` / `tasks result` çıktısında kalır. Biçim, kodlar
ve sınırlar [görev doğrulamada](docs/task-verification.md) açıklanır.

## Kalıcı ajan kataloğu

`agents` komutları ajan profillerini `local-profile/agents/<id>/` altında saklar;
her ajanın talimatı, bağlantısı ve izinleri kendi dizinindedir. Katalog, görev
kuyruğuna girerken o anki profili görev tanımına kopyalar; sonraki profil
düzenlemesi çalışan görevi değiştirmez.

```powershell
.\.venv\Scripts\ragents.exe agents create --id arastirmaci --name "Araştırmacı" `
  --provider ollama --model qwen3:8b --instructions "Türkçe yanıt ver." `
  --project "Proje kısa bilgisi." --workspace C:\Projeler\OrnekProje
.\.venv\Scripts\ragents.exe agents update arastirmaci `
  --add-skill arastirma --add-default-skill arastirma `
  --add-tool list_files --add-tool search_text --add-tool read_file
.\.venv\Scripts\ragents.exe agents list

# Yazma ve sınırlı komut izinleri (isteğe bağlı).
.\.venv\Scripts\ragents.exe agents update arastirmaci `
  --add-tool write_file --add-tool apply_patch --add-tool run_command `
  --writable-path src --allowed-command python --allowed-command pytest
.\.venv\Scripts\ragents.exe tasks add --agent arastirmaci `
  --writable-path src --allowed-command pytest "Hataları düzelt ve testleri çalıştır"
.\.venv\Scripts\ragents.exe tasks --root local-profile show <görev-id>
.\.venv\Scripts\ragents.exe tasks --root local-profile list
```

Workspace verilmezse `local-profile/workspaces/<ajan-id>/` otomatik oluşturulur;
özel `--workspace` dizini önceden mevcut olmalıdır. Dosya araçları yalnız
`agent.yaml` içindeki açık `tools` listesiyle modele verilir; ajan workspace
dışına çıkamaz, symlink/junction ve kimlik dizinleri reddedilir. Görev sırasında oluşan/değişen dosyalar `tasks show` çıktısındaki
`artifacts` listesinde izlenir. Ayrıntılar:
[çalışma alanı ve artifact'lar](docs/workspaces-and-artifacts.md) ve
[dosya/komut izinleri](docs/tools-and-execution.md).

`--add-skill` kullanmadan önce `local-profile/agents/<id>/skills/<skill-id>/SKILL.md`
dosyasını oluşturun. `--db` verilmezse katalog komutları veritabanını `--root`
altında `data/ragents.db` olarak kullanır; `setup` ile üretilen profil kuyruğuyla
aynı dosyadır. Mevcut `ragents.yaml` dosyasından geçiş için
`agents create --from-config local-profile/ragents.yaml` kullanın. Talimat
birleştirme sırası, skill dosya biçimi ve sınırlar için
[talimatlar ve skill'ler](docs/instructions-and-skills.md); katalog yaşam
döngüsü için [ajan kataloğu](docs/agents-and-workspaces.md) belgesine bakın.

## Sürekli servis

```powershell
# Birinci terminal: sürekli çalışır; Ctrl+C ile kontrollü kapanır.
.\.venv\Scripts\ragents.exe worker --concurrency 2 --shutdown-seconds 10

# İkinci terminal: kaydet, izle, gerektiğinde iptal et.
.\.venv\Scripts\ragents.exe tasks add --config examples/chatgpt-luna.yaml --key is-002 "Kısa görev"
.\.venv\Scripts\ragents.exe tasks show GOREV_KIMLIGI
.\.venv\Scripts\ragents.exe tasks cancel GOREV_KIMLIGI

# Model çağırmadan yerel örnek MCP sunucusunda araç keşfi:
.\.venv\Scripts\ragents.exe mcp tools --config examples/ollama-mcp.yaml --prompt "kelime say"
```

Tek veritabanına tek worker supervisor bağlanır; limit onun yürüttüğü işler
içindir. Elle `run`/`tasks run` kullanımı bu worker limitine dahil değildir.
Worker başlangıçta sahipsiz çalışmaları kesilmiş olarak işaretler; yeniden
denemek açık bir `retry` gerektirir. Aynı ChatGPT hesabının çağrıları asenkron
hesap kilidinde sıraya girer. Windows otomatik başlangıç kaydı ayrıca kurulabilir;
bu komut terminal/süreç yaşadığı sürece çalışan yerel servistir.

## Geliştirme ve durum

```powershell
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m pip check
```

Testlerde gerçek model erişimi, DNS, sistem kasası ve tarayıcı kapatılır.
TestModel/FunctionModel ve bellek içi HTTP transport kullanılır. Gerçek model, anahtar veya eski
ajan ortamına ihtiyaç yoktur. Windows asyncio'nun kendi yerel socketpair
işlemi, Codex'in kısıtlı çalıştırma ortamında ek çalıştırma izni gerektirebilir.

| Katman | İlk adım |
| --- | --- |
| Ayarlar ve ürün sözleşmeleri | Kapalı Pydantic şeması, bağımsız ajan/bağlantı |
| Native motor | Pydantic AI 2.64.0, tek ajan, araç döngüsü, sınırlar |
| Sağlayıcılar | Ollama/OpenRouter, Go/Zen Chat Completions ve Responses; ChatGPT OAuth Responses |
| Arayüz | `setup`, `doctor`, `check`, `demo`, kalıcı `run`, `tasks`, `agents`, `sandbox`, `worker`, `mcp`, `auth` ve Python servisi |
| Kurulum | Sağlayıcı/model, özelleştirilmiş ajan, yerel/isteğe bağlı canlı kontrol, worker/MCP profil dosyaları |
| Kalıcı kayıtlar | SQLite görev/çalışma/sonuç, idempotency, açık kurtarma ve yeniden deneme |
| Kalıcı ajan kataloğu | Ajan başına profil, talimat/proje/kural dosyaları, seçilebilir skill, durum ve içerik revizyonu |
| Çalışma alanı | Ajan başına workspace, izinli okuma/yazma dizinleri, yol sınırları ve artifact kaydı |
| Sandbox | Windows AppContainer + Job Object, macOS Seatbelt, Linux bubblewrap; ağ/yazma/süreç/kaynak sınırı |
| Dosya ve komut | `write_file`, `apply_patch`, argv tabanlı `run_command`; yayın izni ayrı, çıktı sınırlı |
| Sürekli servis | FIFO SQLite kuyruk, tek supervisor, sınırlı eşzamanlılık, iptal, kontrollü kapanış |
| MCP araçları | Stdio/Streamable HTTP istemcisi, açık izin ve anahtar kelime seçimi, şema/çıktı sınırı |
| MCP yönetimi | Stdio/loopback HTTP; salt okunur varsayılan, açık execute izni; görev başına bağlantı seçimi |
| Hafıza, ajan ekipleri, panel | Henüz uygulanmadı |
| Pydantic AI/LangGraph karşılaştırması | Henüz yapılmadı; seçim geçici |

[Mimari ve sonraki adım](docs/architecture.md) dosyası mevcut sınırları açıklar.
Tam ürün tasarımı üst projedeki
[R Agents V2 dokümanındadır](../agent-runtime/docs/R-Agents-v2.md).
V1 kodu, kişisel ajanlar ve canlı veritabanı bu pakete dahil değildir.
