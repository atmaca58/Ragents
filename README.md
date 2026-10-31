# R Agents

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

**Birleşik kurulum hazır:** `scripts/setup.ps1` sağlayıcı/model seçimini,
örnek ajanı, bağlantı kontrolünü ve worker/MCP dosyalarını tek akışta oluşturur.
[Kurulum ve özelleştirme rehberi](docs/setup-and-customization.md).

```powershell
.\.venv\Scripts\ragents.exe auth login chatgpt
.\.venv\Scripts\ragents.exe run --config examples/chatgpt-luna.yaml "Merhaba."
```

## Kurulum

Python 3.12–3.14 hedeflenir. Bu başlangıç Windows / Python 3.14.7 üzerinde
doğrulandı; diğer Python sürümleri ve işletim sistemleri henüz test edilmedi.

Proje dizininde PowerShell ile:

```powershell
cd C:\Projeler\Ajan\Ragents
.\scripts\setup.ps1
.\.venv\Scripts\ragents.exe demo
```

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
bu geliştirme ortamında çözülen doğrudan ve geçişli bağımlılıkların sabit
sürümleridir; hash doğrulamalı veya tüm platformları kapsayan bir lock değildir.
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
- Yerleşik dosya, shell, tarayıcı veya sandbox yetkisi verilmez. MCP üzerinden
  verilen yetkiler açık araç izin listesiyle belirlenir.
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

`run --key is-001 ...` aynı içerikle tamamlanmış görevin sonucunu yeniden
model çağırmadan döndürür (`cached: true`). Dönen usage kayıtlı çalışmaya aittir.
Başarısız görevler kendiliğinden yeniden çalışmaz. Kurtarma aktif süreç kilidine
dokunmaz; `retry` yalnız sıraya alır. Aktif worker sıradaki görevi alır;
worker kullanılmıyorsa `tasks run` ile elle çalıştırılır.
Başarısız/kesilmiş çalışmanın bilinmeyen kısmi tüketimi `null` kalır.

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
| Arayüz | `setup`, `doctor`, `check`, `demo`, kalıcı `run`, `tasks`, `worker`, `mcp`, `auth` ve Python servisi |
| Kurulum | Sağlayıcı/model, özelleştirilmiş ajan, yerel/isteğe bağlı canlı kontrol, worker/MCP profil dosyaları |
| Kalıcı kayıtlar | SQLite görev/çalışma/sonuç, idempotency, açık kurtarma ve yeniden deneme |
| Sürekli servis | FIFO SQLite kuyruk, tek supervisor, sınırlı eşzamanlılık, iptal, kontrollü kapanış |
| MCP araçları | Stdio/Streamable HTTP istemcisi, açık izin ve anahtar kelime seçimi, şema/çıktı sınırı |
| MCP yönetimi | Stdio/loopback HTTP; salt okunur varsayılan, açık execute izni; görev başına bağlantı seçimi |
| Sandbox, hafıza, çok ajan, panel | Henüz uygulanmadı |
| Pydantic AI/LangGraph karşılaştırması | Henüz yapılmadı; seçim geçici |

[Mimari ve sonraki adım](docs/architecture.md) dosyası mevcut sınırları açıklar.
Tam ürün tasarımı üst projedeki
[R Agents V2 dokümanındadır](../agent-runtime/docs/R-Agents-v2.md).
V1 kodu, kişisel ajanlar ve canlı veritabanı bu pakete dahil değildir.
