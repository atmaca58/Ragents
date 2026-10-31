# R Agents V2 — Sürekli servis ve MCP

Bu aşama 1 Kasım 2026 tarihinde sürekli worker, araç MCP istemcisi ve V2 yönetim
MCP'sini ekler. Mevcut TaskStore, TaskService, native motor, sağlayıcı/OAuth
bağlantıları, token/bağlam politikaları ve saf `text_stats` aracı yeniden
kullanılır. V1'in salt okunur MCP başlangıç, açık yazma yetkisi ve ince sunucu
desenleri V2'ye uygulanır. V1 çalışma motoru, kişisel ajanlar, canlı DB ve OAuth
sunucusu kopyalanmaz; MCP protokolünü resmi SDK sağlar.

## 1. Sürekli worker

Komutları `C:\Projeler\Ajan\Ragents` dizininden çalıştırın:

```powershell
.\.venv\Scripts\ragents.exe worker --db data/ragents.db --concurrency 2 --poll-seconds 0.5 --shutdown-seconds 10
```

Worker kuyruk boşken bekler; yeni işleri FIFO sırasıyla alır. Kuyruk beklemesi
model çağrısı yapmaz. `--once` mevcut kuyruk boşalınca çıkmak içindir. Başlangıçta
süreç kilidi boşalmış eski `running` çalışmalar `interrupted` olur; kendiliğinden
yeniden çağrı yapılmaz. Mevcut kurtarma taraması en son 1.000 aktif kaydı kapsar.

Tek DB için tek supervisor kilidi tutulur; ikinci worker açılması reddedilir.
`--concurrency` 1–64 arasındadır ve supervisor'ın yürüttüğü işleri kapsar.
Elle `run` / `tasks run` çağrıları bağımsızdır; ortak limit istiyorsanız işleri
yalnız kuyruğa gönderin. Bu yerel süreç modelidir; dağıtık worker kümesi değildir.

Başka bir terminalden:

```powershell
.\.venv\Scripts\ragents.exe tasks --db data/ragents.db add --config examples/chatgpt-luna.yaml --key gorev-001 "Kısa görev"
.\.venv\Scripts\ragents.exe tasks --db data/ragents.db show GOREV_KIMLIGI
.\.venv\Scripts\ragents.exe tasks --db data/ragents.db cancel GOREV_KIMLIGI
.\.venv\Scripts\ragents.exe tasks --db data/ragents.db result CALISMA_KIMLIGI
```

Bekleyen görev doğrudan `cancelled` olur; çalışma/model çağrısı oluşturulmaz.
Aktif görevin iptal isteği çalışma kimliğine bağlı SQLite kaydıdır. TaskService
100 ms aralıkla kontrol eder ve async yürütmeyi iptal eder. Yeniden denenen yeni
çalışma eski iptal isteğini devralmaz. Sonuç kaydı ile iptal aynı anda gelirse
SQLite işlem sırası belirleyicidir: iptal önce kaydedilmişse sonuç yayımlanmaz.

Görevin `budget.timeout_seconds` sınırı sağlayıcıya bağlanmayı, ChatGPT hesap
kilidinde beklemeyi, MCP keşfini, araç çağrılarını ve model döngüsünü kapsar.
Aynı ChatGPT hesabı için model çağrıları asenkron kilitte sıraya girer; başka
hesap/sağlayıcı işleri event loop üzerinde ilerleyebilir. Kilitte bekleyen görev
de iptal edilebilir. MCP bağlantısının kendi zaman aşımı ayrıca uygulanır.

Ctrl+C / SIGTERM yeni iş almayı durdurur. Aktif işlere `--shutdown-seconds`
kadar bitirme süresi verilir, sonra kalan async işler iptal edilir. Bekleyen
işler kuyrukta kalır. Bu işbirlikçi async iptaldir; event loop'u bloke eden veya
iptali yutan üçüncü taraf koduna sert süreç izolasyonu sağlamaz. MCP stdio
süreçlerinin kapatılması/sonlandırılması SDK'ya aittir.

Başarısız iş diğer işleri durdurmaz. Hata ayrıntısı yerine güvenli hata kodu
DB'ye kaydedilir. Tekrar için `tasks retry GOREV_KIMLIGI` kullanılır. Worker
aktifse işi alır. İptal edilen uzak model/araç işleminin geri alındığı veya
ücret yazmadığı garanti edilmez. Kesinti sonrası açık retry, sonucun kaydından
önce uzakta gerçekleşmiş bir işlemi tekrarlayabilir; uzakta exactly-once yoktur.

Worker bir sürekli yerel süreçtir. Windows servisi/Task Scheduler otomatik
başlangıç kaydı bu aşamada yüklenmez. Yeniden başlatma, çalışma dizini, ortam
değişkenleri ve OAuth kasasına erişebilen kullanıcı hesabı süreç yöneticisinde
ayarlanmalıdır. Canlı kuyruğa worker başlatmak sıradaki gerçek işleri çalıştırır.

## 2. Ajanların araç MCP'sini kullanması

`examples/ollama-mcp.yaml` ayarı, mevcut saf metin aracını tekrar kullanan
`examples/tool-server.py` yerel MCP örneğine bağlanır. Keşfi model çağırmadan sınayın:

```powershell
.\.venv\Scripts\ragents.exe mcp tools --config examples/ollama-mcp.yaml --prompt "kelime say"
```

Bu komut izin verilen sunucu sürecini başlatır ve `tools/list` yapar; araç
çalıştırmaz, LLM çağırmaz. Gerçek bir görevi çalıştırmak için aynı YAML dosyasını
`tasks add` ile kuyruğa gönderin. Örnekteki Ollama modeli ayrıca kurulu olmalıdır;
`connections` ve `agent.connection` alanlarını ChatGPT/Go/Zen bağlantınızla da
değiştirebilirsiniz. MCP desteği sağlayıcıya özgü değildir.

Bağlantı ve izinler ayrı tanımlanır:

```yaml
mcp_servers:
  company-tools:
    transport: streamable-http
    url: https://tools.example.com/mcp
    bearer_env: COMPANY_MCP_TOKEN
    timeout_seconds: 20
agent:
  # Mevcut id/name/instructions/connection/budget alanlarına ek:
  mcp_tools:
    - server: company-tools
      name: search_mail
      keywords: [posta, mail]
    - server: company-tools
      name: calendar
      keywords: [takvim, calendar]
  tool_selection:
    max_tools: 4
    max_schema_chars: 8000
    max_description_chars: 600
```

Stdio bağlantısında `transport: stdio`, `command`, `args`, isteğe bağlı `cwd` ve
`env_vars: [COMPANY_MCP_TOKEN]` kullanılır. `args` argv listesidir; shell komutu
olarak çalıştırılmaz. SDK'nın temel sistem ortamı dışında yalnız `env_vars`
isimleriyle seçilen değerler iletilir. Anahtarı URL, args veya YAML içine
yazmayın; yalnız ortam değişkeninin adını yazın. `.env` otomatik yüklenmez.
Göreceli yollar worker'ın çalışma dizinine göredir; dağıtımda mutlak yol önerilir.

Uzak HTTP için HTTPS gerekir; düz HTTP yalnız loopback adreslerine açıktır.
URL içinde kullanıcı/parola, sorgu veya fragment kabul edilmez. Bearer ortamdan
çözülür. İstemci tarafı interaktif MCP OAuth/SSE bu aşamada yoktur. Stdio komutu
ve sunucusu güvenilen operatör ayarıdır; yerel araç süreci sandbox içinde değildir.

### Token tasarrufu ve izin davranışı

1. Ajanın `mcp_tools` listesi açık izin listesidir. Sunucudaki diğer araçlar
   çağrı noktasında da kapalıdır; model isim uydurarak bunlara erişemez.
2. Görev metnindeki Unicode sözcüklerle izin girdisindeki `keywords` eşleşir.
   Çok sözcüklü bir anahtardaki bütün sözcükler bulunmalıdır. Büyük/küçük harf
   normalize edilir; kök bulma, eşanlam veya semantik arama yapılmaz. Anahtarları
   kullanım diline göre ekleyin. `always: true` açıkça her görevde dahil eder.
3. Yalnız ilgili izinlerin sunucularına bağlantı açılır. Keşif yereldir; tüm
   katalog açıklamaları LLM bağlamına gönderilmez. Keşif sunucu başına en fazla
   100 sayfa/1.000 araçla sınırlıdır. Otomatik sampling/ek LLM çağrısı açılmaz.
4. İzin sırasına göre en fazla `max_tools` araç ve `max_schema_chars` şema
   karakteri seçilir. Büyük şema sığmazsa atlanır; açıklamalar ayrıca kesilir.
   Araç seçimi görev başında sabitlenir. Sığmayan aracı kullanmak için politikayı
   değiştirmek gerekir; başka araca/sağlayıcıya otomatik geçiş yapılmaz.
5. Modele araç adı `sunucu__arac` olarak sunulur. Sunucu kimliği en fazla 20,
   araç adı en fazla 40 karakter; araç adında harf/sayı/alt çizgi/tire kullanılır.
6. Argümanlar uzak çağrıdan önce JSON Schema ile doğrulanır; dış URL'ye `$ref`
   çözümü kapalıdır. Her MCP çağrısı zaman aşımına ve mevcut tool-call bütçesine
   tabidir. Native motor MCP çağrılarını sıralı yürütür. Otomatik araç/model
   hatası tekrarı yoktur; SDK istemcisi legacy protokol müzakeresi kullanır.
7. Büyük araç sonucu `context.max_tool_output_chars` ile işaretlenerek
   sınırlandırılır. Yapılandırılmış JSON sonuç tercih edilir; aksi halde metin
   blokları alınır. Görsel/ses/binary içerik modele taşınmaz.

`RunResult.tools.selected` ve `schema_chars` seçimin boyutunu gösterir. Seçilen
MCP şemalarının karakterleri mevcut bağlam boyutu korumasına da katılır. Bu
tokenizer veya tam HTTP yükünün kesin ölçümü değildir; yerleşik araçların
şemaları ve sağlayıcı ekleri bu ölçümün dışında kalabilir. Mevcut token sınırları
sağlayıcı kullanım raporuna bağlıdır. Keşif her görevde yapılır; görevler arası
kalıcı katalog önbelleği ve bağlantı havuzu bu aşamada yoktur.

## 3. V2'yi başka ajandan yönetme

V2 yönetim MCP'si de aynı TaskStore'u kullanır; yeni bir çalışma motoru yoktur.
Yerel MCP istemcinizde şu komutu stdio sunucusu olarak tanımlayın:

```powershell
C:\Projeler\Ajan\Ragents\.venv\Scripts\ragents.exe mcp serve --db C:\Projeler\Ajan\Ragents\data\ragents.db --config C:\Projeler\Ajan\Ragents\examples\chatgpt-luna.yaml
```

Varsayılan araçlar: `list_agents`, `list_tasks`, `get_task`, `get_result`.
Ajanlar `--config` ile açıkça kaydedilir; birden fazla örnek ajan için bu argüman
tekrar edilir. MCP istemcisi keyfi ayar dosyası yolu veya ajan spec'i gönderemez.

Görev gönderme/iptal/yeniden deneme için sunucu komutuna **`--allow-execute`**
ekleyin. Böylece `submit_task(agent_id, prompt, key)`, `cancel_task(task_id)` ve
`retry_task(task_id)` görünür. `key` zorunludur, aynı içerikle tekrar gönderim
aynı görevi döndürür. Farklı içerikle aynı anahtar reddedilir. `submit_task`
modeli MCP isteğinde çalıştırmaz; yalnız sıraya alır. Aynı DB'de ayrı çalışan
worker işi alır; durum/sonuç sonradan sorgulanır. Worker yoksa iş sırada bekler.
Çalıştırma izni, kayıtlı ajanların model ve araç yetkilerini kullanma iznidir.

Yönetim yüzeyi sonradan **stdio ve loopback Streamable HTTP** olarak genişletildi.
`submit_task` isteğe bağlı `connection_id` ile kayıtlı model kaynağını seçer;
`list_agents` kullanılabilir bağlantıları gösterir. Güncel komutlar, istemci
ayarları ve ChatGPT tünel yolu [dış yönetim rehberindedir](external-management.md).
Uygulama OAuth'u ve çok kullanıcılı ekip yetkilendirmesi henüz yoktur.

## Veri ve uyumluluk

- Şema sürümü 1'den 2'ye veri silmeden yükselir; yalnız iptal tablosu ve kuyruk
  indeksi eklenir. Önceki ayarlara eklenen varsayılan MCP alanları eski
  idempotency anahtarlarını bozmaz. Görev tanımı enqueue anındaki ayarın kopyasıdır.
- Görev talimatı, ayar ve sonuç ürün verisi olarak V2 DB'de düz metindir.
  Çözülen ortam anahtarları ve OAuth tokenları DB'ye/çalışma metadatasına alınmaz.
- Başarısız/iptal edilmiş isteğin bilinmeyen kısmi tüketimi `null` kalır.
  Başarılı yanıt gelmiş, iptal de önce kaydedilmişse bilinen usage saklanabilir.
- V1 kodu/veritabanı değiştirilmez. V1 araçlarına ihtiyaç olursa normal MCP
  bağlantısı ayrıca tanımlanabilir; bu sürüm onları varsayılan olarak başlatmaz.

## Doğrulama kaynakları

Çevrimdışı pytest; geçici SQLite, gerçek stdio alt süreçleri, MCP SDK bellek içi
istemcisi ve Streamable HTTP ASGI transportuyla çalışır. Model tarafı sahte
FunctionModel'dir. Bu aşamada canlı ChatGPT/Go/Zen isteği yapılmadı.
Toplam **80 test** geçti; 12 yeni test dosyasının üretim kodunu gerçekten
çağırdığı statik kontrol ve 12 mutasyonla doğrulandı. Ayrıntılar
[doğrulama kaydında](verification.md).

- [Resmi MCP Python SDK istemcisi](https://py.sdk.modelcontextprotocol.io/client/)
- [Resmi MCP transportları](https://py.sdk.modelcontextprotocol.io/client/transports/)
- [Pydantic AI araçları](https://pydantic.dev/docs/ai/tools/functions/)

Windows/Python 3.14.7 üzerinde doğrulanmıştır. İşletim sistemi otomatik başlangıç,
dağıtık worker, sert sandbox ve uzak yönetim OAuth'u bu kapsamda değildir.
