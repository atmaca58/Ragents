# İlk üç geliştirme adımı

Tarih: 1 Kasım 2026. Kapsam: ChatGPT/Luna canlı doğrulama, token/bağlam yönetimi,
kalıcı görev ve çalışma kayıtları. Arka plan worker ve MCP yürütme servisi sonraki aşamadır.
Komut örnekleri Windows PowerShell/`.exe` biçimindedir; güncel platform
karşılıkları [platform desteğindedir](platform-support.md).

## 1. ChatGPT bağlantısı

Kullanıcının daha önce verdiği R Agents OAuth izniyle `gpt-6-luna` çalıştırıldı.
Mevcut ChatGPT/Codex uygulamasının kimlik dosyaları kullanılmadı. İki ayrı kısa
canlı çağrının her birinde 1 istek, 38 giriş ve 9 çıkış tokenı bildirildi.
İkinci çağrı, yeni bağlam koruması ve kalıcı kayıt akışını da kapsadı.

Kalıcı canlı kayıt:

- Görev: `060431e881cf49ccb30a8fac75f99a8d`
- Çalışma: `9337fa1a11af427abfbd708e9d98c38a`
- Model: `gpt-6-luna`; araç çağrısı: 0; sonuç: bağlantı başarılı.
- Aynı içerik/anahtarla ikinci çalıştırma aynı run kimliğini ve `cached: true`
  döndürdü. Yeni sağlayıcı çağrısı yapılmadı. Dönen usage önceki çalışmaya aittir.

```powershell
cd C:\RAgents-Kaynak
.\.venv\Scripts\ragents.exe auth status chatgpt
.\.venv\Scripts\ragents.exe run --config examples/chatgpt-luna.yaml --key benim-denemem "Yalnızca merhaba yaz."
```

Oturum yenilemek için gerçek token süresi zorla değiştirilmedi. SDK'nın OAuth
yenileme yolu ve şifreli kayıt desteği devam ediyor; canlı zorunlu yenileme,
uzak izin iptali ve kota tükenmesi ayrıca doğrulanmış değildir. Go/Zen ve diğer
bağlantıların canlı denemeleri kullanıcının isteğiyle ertelendi.

Luna model kimliği [resmi model belgesinden](https://developers.openai.com/api/docs/models/gpt-6-luna)
doğrulandı. Hesap bazındaki erişim sonucu canlı çağrıyla sınandı; API fiyatından
ChatGPT plan tüketimi için dolar maliyeti türetilmez.

## 2. Token ve bağlam yönetimi

Yeni ayarlar örneği:

```yaml
agent:
  # id, name, instructions ve connection da gereklidir.
  budget:
    request_limit: 4
    tool_calls_limit: 2
    input_tokens_limit: 16384
    output_tokens_limit: 1024
    total_tokens_limit: 18432
    timeout_seconds: 60
  context:
    max_request_chars: 24000
    max_history_turns: 4
    max_tool_output_chars: 2000
```

Girdi, çıktı ve toplam token sınırları run boyunca birikimli uygulanır.
Sağlayıcının bildirdiği kullanım esas alınır; token sayma endpoint'ine her
istekten önce ek bir ağ çağrısı yapılmaz. Bu nedenle bir yanıt, limit aşıldığının
öğrenilmesinden önce üretilmiş olabilir. Bunlar kesin parasal harcama tavanı değildir.

Çıktı tavanını destekleyen bağlantılarda her isteğin `max_tokens` değeri,
önceki yanıtlardan sonra kalan çıktı/toplam bütçeye düşürülür. Sonraki isteğin
girdi tüketimi önceden bilinmez. ChatGPT plan yolu `max_output_tokens` kabul
etmediğinden bu alan gönderilmez; tüketim sonrası denetim ve sonraki isteği
durdurma uygulanır. Bu kısıtın [resmi açıklaması](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations).

Bağlam politikası:

- Görev ve talimatlar kesilmez. Görev tek başına sığmıyorsa model çağrısı yapılmaz.
- Geçmiş otomatik eklenmez. Python `RunRequest.history` alanına açıkça verilen
  kullanıcı/ajan turları içinden en yenileri tutulur; önce tur sayısı, sonra
  karakter bütçesi uygulanır. Eski turlar bütün olarak çıkarılır.
- Araç döngüsünde her model isteğinden önce bağlam yeniden kontrol edilir.
  Güncel döngünün araç çağrı/yanıt eşleşmeleri silinmez; sığmazsa çalışma durur.
- Uzun araç sonuçları belirgin bir `araç çıktısı kısaltıldı` işaretiyle sınırlanır.
  Büyük JSON sonuçları bu durumda sınırlı metin olarak gönderilir. Tam araç sonucu
  gerektiren görevlerde uygun sınır seçilmelidir.
- Karakter sayacı, SDK mesajlarının JSON gösterimi ve talimatları kapsar.
  Bu bir tokenizer veya tüm HTTP gövdesinin ölçümü değildir; araç şemaları ve
  sağlayıcının eklediği tokenlar bu yerel sayaçta yer almaz.
- Ek LLM özetleme çağrısı, otomatik sağlayıcı değişimi veya boşta çalışma yoktur.

Sonuçtaki `context` alanı çıkarılan tur, kısaltılan araç sonucu ve en büyük
gönderim öncesi karakter sayısını gösterir. Mevcut CLI görev başına yeni bağlam
kullanır; geçmiş aktarma Python sözleşmesinde desteklenir. Kalıcı sonuçlar
sonraki göreve kendiliğinden bağlam olarak eklenmez.

## 3. Kalıcı görev ve çalışma kayıtları

CLI `run` artık varsayılan olarak çalışma dizinine göre `data/ragents.db`
dosyasını kullanır. Komutları `Ragents/` içinden çalıştırın veya mutlak `--db`
yolu verin. Eski `agent-runtime/data/agents.db` açılmaz. Python `run_task`
fonksiyonu geçici çalışmaya devam eder; kalıcılık `TaskStore`/`TaskService`
katmanına aittir. `demo`, `check` ve `auth` görev veritabanı oluşturmaz.

| Tablo | İçerik |
| --- | --- |
| `tasks` | Sabit ayar anlık görüntüsü, görev metni, bağlantı seçimi, durum, tekrar anahtarı |
| `runs` | Her girişimin durumu, sağlayıcı/model, zamanlar, süre, kullanım, güvenli hata kodu |
| `results` | Başarıyla tamamlanan çalışmanın ürün sonucu ve bağlam raporu |

OAuth/API anahtarlarının değerleri veritabanına alınmaz; anahtar ortam değişkeninin
adı ayarlarda bulunabilir. Ham sağlayıcı hatası çalışma metadatasına yazılmaz.
Görev metni, ajan talimatları ve başarılı sonuç **ürün verisi olarak düz metin
SQLite'ta tutulur**; telemetri değildir ve otomatik şifrelenmez. Dosya erişimi ve
yedeklerini buna göre yönetin. OAuth deposunun şifrelemesi ayrıdır.

Durum akışı:

```text
queued → running → succeeded
                 → failed
                 → cancelled   (aynı süreçte async iptal / Ctrl+C)
                 → interrupted (süreç kaybından sonra açık recover)

failed / cancelled / interrupted → queued (açık retry)
```

Görev başlatma ve sonuç yazımı SQLite transaction'larıyla atomiktir. Aynı göreve
iki başlatma isteğinde yalnız bir çalışma oluşturulur. Model çağrısı boyunca
SQLite transaction'ı tutulmaz. Süreçler arası dosya kilidi, `recover` komutunun
hâlen çalışan işe dokunmasını önler. Yerel disk/kilit modeli kullanılır; çok
makineli dağıtık worker garantisi verilmez.

```powershell
# Yalnız kaydet; ağ veya hesap erişimi gerekmez.
.\.venv\Scripts\ragents.exe tasks add --config examples/chatgpt-luna.yaml --key is-001 "Kısa bir görev"
.\.venv\Scripts\ragents.exe tasks list

# add çıktısındaki kimlikle çalıştır ve kayıtları oku.
.\.venv\Scripts\ragents.exe tasks run GOREV_KIMLIGI
.\.venv\Scripts\ragents.exe tasks show GOREV_KIMLIGI
.\.venv\Scripts\ragents.exe tasks result CALISMA_KIMLIGI

# Süreç kapandıysa; bunlar model çağırmaz.
.\.venv\Scripts\ragents.exe tasks recover
.\.venv\Scripts\ragents.exe tasks retry GOREV_KIMLIGI
# Ardından ayrıca tasks run çalıştırılır.

# Başka veritabanı seçimi (tasks grubunda alt komuttan önce):
.\.venv\Scripts\ragents.exe tasks --db C:\RAgents-Kaynak\data\baska.db list
```

`--key` aynı ayar/görev/bağlantı içeriğini tekrar eklemez. Aynı anahtarla farklı
içerik reddedilir. Başarılı görev tekrar istendiğinde sonuç yerelden okunur;
başarısız görevde yeniden model çağrısı için önce `retry` gerekir. Yeni bir
çalışma isteniyorsa yeni anahtar kullanılır veya anahtar verilmez.

Bu koruma görev kimliği bazındadır. Sağlayıcı yanıtı geldikten sonra süreç
sonucu kaydetmeden kapanırsa, açık yeniden deneme yeniden tüketim oluşturabilir;
uzak model çağrısı için exactly-once garantisi yoktur. Başarısız/kesilmiş
çalışmaların bu sürümde kısmi tüketimi toplanmaz: `usage: null` bilinmiyor
demektir, tüketim sıfır kabul edilmez. Maliyet `cost_usd: null` kalır.

`recover` çağrı başına en yeni 1000 aktif kaydı inceler; daha büyük kuyrukta
ek çağrılar gerekir. Başlangıçta otomatik recover veya otomatik retry yapılmaz.
Şema sürümü SQLite `user_version=1`; daha yeni şema açılmak istendiğinde durur.

## Doğrulama ve sonraki adım

49 çevrimdışı test: giriş/toplam/çıktı bütçeleri, kalan çıktı tavanı, büyük
görev/geçmiş/araç sonucu, SQLite yeniden açma, eşzamanlı başlatma, tekrar
anahtarı, sonuç kaydı, iptal/zaman aşımı, kurtarma ve CLI akışları.
Canlı çağrılar otomatik testlerden ayrı, yalnız Luna ile yapıldı.

Sonraki aşama: sürekli worker, kuyruk işleme, kontrollü eşzamanlılık ve uzaktan
iptal. Ardından mevcut MCP araç bağlantısı ve dış istemcilere MCP yönetimi.
