# ChatGPT OAuth, OpenCode Go ve Zen

Tarih: 1 Kasım 2026. Bu entegrasyonlar harici ajan CLI'sı başlatmaz. Komut
örnekleri Windows PowerShell/`.exe` biçimindedir; macOS/Linux karşılıkları
[platform desteğindedir](platform-support.md).

| Bağlantı | Kimlik | Native model yolu |
| --- | --- | --- |
| `chatgpt` | Tarayıcıda R Agents'a verilen OAuth izni | OpenAI Responses, kullanıcının uygun ChatGPT planı |
| `opencode_go` | Go hesabından alınan API anahtarı | OpenCode Go OpenAI uyumlu gateway |
| `opencode_zen` | OpenCode Console/Zen API anahtarı | OpenCode OpenAI uyumlu gateway |

## ChatGPT nasıl çalışır?

1. `ragents auth login chatgpt` komutu tarayıcıda resmi OpenAI girişini açar.
2. Uygulama adı **R Agents** olarak gösterilir. Kullanıcı giriş ve ChatGPT
   planını kullandırma izinlerini inceler. Bunlar ayrı izinlerdir.
3. Uygulama, kuruluma ait kalıcı `ext_agent_host_id`, yeni state/nonce ve PKCE
   kullanır. İlk giriş dinamik istemci kaydı oluşturur; sonraki giriş kayıtlı
   `client_id` ile devam eder. Callback `127.0.0.1:1455/auth/callback` adresidir.
4. `chatgpt.tokens.use.direct` izni verilmişse seçilen model üzerinden çalışılır.
   İzin verilmemişse giriş kaydedilir fakat çıkarım yapılmaz. Sonraki açık
   `login` komutu plan iznini tekrar isteyebilir.
5. Pydantic AI'ın resmi akışı token değişimi/doğrulama ve yenilemeyi yürütür.
   R Agents dönen tokenları kendi deposunda saklar; yenilenen tokenlar da yazılır.
6. Model çağrısı `https://api.openai.com/v1/responses` adresine OAuth bearer ile
   gider. `stream: true`, `store: false` kullanılır. Ajan/araç döngüsü R Agents'tadır.

ChatGPT sohbet geçmişi bu izinle alınmaz. Codex/OpenCode/Hermes'in kayıtlı
oturumları okunmaz veya kopyalanmaz. OpenAI API anahtarı bu bağlantıda kabul
edilmez; hata veya kota dolması otomatik başka bir faturaya yönlendirilmez.

```powershell
cd C:\RAgents-Kaynak
.\.venv\Scripts\ragents.exe auth login chatgpt
.\.venv\Scripts\ragents.exe auth status chatgpt
.\.venv\Scripts\ragents.exe check --config examples/chatgpt.yaml
.\.venv\Scripts\ragents.exe run --config examples/chatgpt.yaml "Kısa bir çalışma planı çıkar."
```

`examples/chatgpt.yaml` içindeki model örnektir; seçilen hesap ve planın
desteklediği model kullanılmalıdır. Birden fazla hesap için `login chatgpt
--account is` ve bağlantıda `oauth_account: is` kullanılır. Etiket hesabın
e-posta adresi değildir; tarayıcıda doğru hesabı seçmek kullanıcıya aittir.
Etikete yeniden giriş mevcut yerel oturumu değiştirir.

`auth status` yerel kaydın ve verilen scope'un durumunu gösterir. Ağ çağrısı,
token yenileme, kota veya uzak hesap geçerliliği kontrolü yapmaz.
`auth logout chatgpt` yerel şifreli kaydı kaldırır. Uzak yetkiyi iptal etmez;
kalıcı iptal ChatGPT hesap ayarlarından yapılır. Host ID sonraki giriş için korunur.

### Kimlik deposu ve eşzamanlılık

OAuth tokenları `~/.ragents/auth/` altına Fernet ile şifrelenmiş olarak atomik
yazılır. Kısa şifreleme anahtarı Windows Credential Manager, macOS Keychain veya
desteklenen Linux sistem kasasında tutulur. Büyük OAuth tokenları Windows
kasasının tek kayıt boyutuna bağlı kalmaz. Güvenli kasa bulunmazsa düz metne
geçilmez; giriş durur. Başsız Linux kurulumu için bu sürümde güvenli kasa
erişimi sağlanmalıdır. Depo kökü `RAGENTS_HOME` ile değiştirilebilir; kök
değiştirmek mevcut şifreli kayıtları otomatik taşımaz.

Her hesap etiketi için süreçler arası kilit, giriş/yenileme/çalıştırma boyunca
tutulur. Aynı etiketle ikinci işlem açık hata verir; tek kullanımlık refresh
tokenı iki worker aynı anda tüketmez. Bu, ilk sürümde aynı OAuth hesabıyla
paralel run yerine sıralı çalışma demektir. Yenileme SDK seviyesinde yürür;
bir 401 sonrası en fazla bir yenileme/yeniden gönderim olabilir. Genel SDK
istek tekrarları kapalıdır. Bu kimlik yenileme adımı LLM doğrulama tekrarı değildir.

### Kullanım sınırı

ChatGPT plan yolunda `max_output_tokens` desteklenmediği için istek gövdesine
eklenmez. R Agents'ın `output_tokens_limit` denetimi burada kullanım sonucu
geldikten sonra uygulanır; önceden uygulanmış kesin token/harcama tavanı değildir.
İstek/araç sınırları ve zaman aşımı devam eder. Kullanıcının ChatGPT'de uygulama
için belirlediği plan limitleri ayrıca geçerlidir.

Resmi OSS/yerel kullanım akışı uygulanmıştır. Gelecekte ücretli veya uzaktan
barındırılan dağıtım sunulursa ilgili OpenAI partner süreci ayrıca ele alınmalıdır.

## Hermes'ten öğrenilen yaklaşım

İncelenen Hermes `auth.py` dosyası provider çözümleme ile auth akışlarını ayırır;
`auth_codex.py` OAuth oturumunu Codex CLI oturumundan ayrı tuttuğunu açıklar.
Bu, refresh-token yenilemelerinin uygulamalar arasında çakışmaması için önemlidir.
Hermes ürününde güncel Sign in with ChatGPT desteği de resmi partner listesinde
yer alır. Eski Codex auth yolu ile yeni uygulamaya özel resmi plan kullanım yolu
aynı protokol kabul edilmemiştir. R Agents yeni resmi OSS akışını kullanır;
Hermes kaynak kodu veya kimliği kopyalanmamıştır.

## Go ve Zen

API anahtarlarını ilgili OpenCode hesabından alın ve yalnız adı belirtilen
ortam değişkeninde tanımlayın. Kod başka servisin anahtarını aramaz.

```powershell
# OPENCODE_GO_API_KEY ve/veya OPENCODE_ZEN_API_KEY tanımlandıktan sonra:
.\.venv\Scripts\ragents.exe check --config examples/opencode-go.yaml
.\.venv\Scripts\ragents.exe run --config examples/opencode-go.yaml "Kısa bir çalışma planı çıkar."
.\.venv\Scripts\ragents.exe run --config examples/opencode-zen.yaml "Kısa bir çalışma planı çıkar."
# Zen'de Responses protokolü kullanan örnek bağlantı:
.\.venv\Scripts\ragents.exe run --config examples/opencode-zen.yaml --connection zen-responses "Merhaba."
```

Güncel resmi belgelerdeki endpoint'ler sabittir:

- Go: `https://opencode.ai/inference/go/openai/v1`
- Zen/Console: `https://opencode.ai/inference/openai/v1`

Eski `zen/v1` adresleri varsayılan yapılmadı. `api: chat_completions` veya
`api: responses` modelin resmi tabloda belirtilen protokolüne göre seçilir.
Model adından protokol tahmin edilmez. Bu sürüm OpenCode'un Anthropic Messages,
Google veya System One protokollerini kullanan modellerini desteklemez;
bu modellerin her iki OpenAI protokolünde de çalıştığı varsayılmamalıdır.
Örneklerdeki model kimlikleri hesabınızda erişilebilir olmalıdır.

## Doğrulama sınırı

Testler geçici depolar, sahte kasa/OAuth akışı ve bellek içi HTTP transport
kullanır. Go/Zen için uygulama servisi → gateway isteği → yanıt ayrıştırma
doğrulanır. ChatGPT için OAuth kayıt saklama/izin ayrımı, kilit ve Responses
istek şekli test edilir. Kullanıcının tamamladığı girişten sonra sistem kasasıyla
kayıtlı oturum okunarak `gpt-6-luna` üzerinde iki kısa canlı çağrı başarılı oldu.
Yeni kalıcı kayıt ve aynı anahtarla çağrıyı yinelememe akışı da doğrulandı.
Tarayıcı girişini kullanıcı tamamladı; bu geliştirme çalışmasında yeniden giriş
başlatılmadı. Canlı zorunlu token yenileme/kota hataları ve Go/Zen çağrıları
henüz doğrulanmadı. Ayrıntılar [ilk üç adım raporunda](first-three-steps.md).

## Kaynaklar

- [OpenAI: ChatGPT plan usage](https://developers.openai.com/siwc/token-sharing-open-source)
- [OpenAI: önizleme sınırları](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations)
- [ChatGPT: desteklenen uygulamalar](https://learn.chatgpt.com/docs/sign-in-with-chatgpt)
- [Pydantic AI: ChatGPT provider](https://pydantic.dev/docs/ai/models/openai-chatgpt/)
- [Hermes auth çözümleme](https://github.com/NousResearch/hermes-agent/blob/main/hermes_cli/auth.py)
- [Hermes ayrı Codex oturumu](https://github.com/NousResearch/hermes-agent/blob/main/hermes_cli/auth_codex.py)
- [OpenCode Go API](https://opencode.ai/v2/docs/console/go/)
- [OpenCode model/protokol tablosu](https://opencode.ai/v2/docs/console/models/)
