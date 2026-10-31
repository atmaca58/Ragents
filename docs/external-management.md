# R Agents — MCP ile dışarıdan yönetim

Yönetici istemci görev oluşturur, durumu sorgular, sonucu alır ve iptal eder.
Görevi aynı SQLite kuyruğundan bağımsız worker yürütür. İstemcinin kendi modeli
ile R Agents görevinin modeli ayrı seçilir: örneğin Codex, R Agents'a Luna veya
Ollama kullanan bir görev gönderebilir. MCP sunucusu ayrıca LLM çağırmaz.

## 1. Worker'ı başlat

```powershell
cd C:\Projeler\Ajan\Ragents
.\.venv\Scripts\ragents.exe worker --db C:\Projeler\Ajan\Ragents\data\ragents.db --concurrency 2
```

Worker açık kaldıkça yeni görevleri alır. Aynı veritabanında ikinci worker
başlatılmaz. Bu komut canlı kuyruktaki işleri de çalıştırır. ChatGPT kaynağı
için R Agents `auth login chatgpt` girişi; Ollama için kurulu ve çalışan model
gerekir. Worker, sağlayıcı ortam değişkenlerine ve OAuth kasasına erişebilen
kullanıcıyla çalışmalıdır.

## 2. Codex veya yerel MCP istemcisini bağla

[Codex ayar örneğini](../examples/codex-mcp.toml) kendi `config.toml` dosyanızdaki
diğer MCP kayıtlarının yanına ekleyin. Buradaki dosya otomatik olarak kullanıcı
ayarlarını değiştirmez. Genel `mcpServers` biçimini kullanan istemciler için
[JSON örneği](../examples/mcp-client.json) hazırdır. Kendi kurulumunuzda mutlak
yolları değiştirin. İstemci sunucu sürecini başlatır; worker ayrı açık kalır.
Codex stdio/HTTP ayarları [resmî MCP rehberindedir](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).

Sunucuyu elle başlatmak için:

```powershell
.\.venv\Scripts\ragents.exe mcp serve --db C:\Projeler\Ajan\Ragents\data\ragents.db --config C:\Projeler\Ajan\Ragents\examples\management.yaml --allow-execute
```

Bu stdio komutu JSON-RPC istemcisi bekler; terminale normal sohbet yazılmaz.
`--allow-execute` çıkarılırsa yalnız okuma araçları görünür. Birden fazla ajan
kaydetmek için `--config` tekrarlanır; ajan kimlikleri farklı olmalıdır.

## 3. MCP araçları

| Araç | Girdi | Davranış |
| --- | --- | --- |
| `list_agents` | yok | Ajanlar, varsayılan bağlantı ve seçilebilir bağlantı kimliği/sağlayıcı/model |
| `list_tasks` | `limit` (varsayılan 50, en fazla 1000) | Son görevler ve durumları |
| `get_task` | `task_id` | Görev durumu, çalışma kimlikleri, sağlayıcı/model ve kullanım kayıtları |
| `get_result` | `run_id` | Başarılı çalışmanın kalıcı sonucu ve kullanım bilgisi |
| `submit_task` | `agent_id`, `prompt`, `key`, isteğe bağlı `connection_id` | Görevi kuyruğa ekler |
| `cancel_task` | `task_id` | Bekleyeni iptal eder; çalışana iptal isteği kaydeder |
| `retry_task` | `task_id` | Başarısız/kesilmiş/iptal edilmiş işi yeniden sıraya alır |

Son üç araç açık `--allow-execute` izni gerektirir. Görev talimatı 1–32.000
karakter ve boşluk dışında içerik taşımalıdır; `key` boş olamaz ve en fazla
200 karakterdir. Aynı anahtar ve içerik aynı görevi döndürür. Bağlantı dahil
içerik değişirse aynı anahtar reddedilir; yeni görev için yeni anahtar kullanın.

Örnek [management.yaml](../examples/management.yaml), `assistant` ajanına
`luna` ve `local` bağlantılarını tanımlar. `connection_id` verilmezse `luna`
seçilir. Go/Zen/OpenRouter eklemek için mevcut sağlayıcı örneklerindeki bağlantı
girdilerini bu dosyanın `connections` bölümüne ekleyin. Sonra MCP sunucusunu
yeniden başlatın. Ajan talimatları, araç izinleri ve bütçesi aynı kalır.
İstemci keyfi model, endpoint, dosya yolu veya kimlik bilgisi gönderemez.

Örnek araç çağrısı:

```json
{
  "agent_id": "assistant",
  "prompt": "Toplantı gündemi için üç kısa madde yaz.",
  "key": "gundem-001",
  "connection_id": "luna"
}
```

Dönen `task.id` ile `get_task` çağırın. `succeeded` olduğunda `runs` içindeki
başarılı çalışmanın `id` değerini `get_result(run_id)` için kullanın. Sık döngü
yerine 1–2 saniye arayla durum sorgulayın. Worker kapalıysa görev `queued`
kalır. Başarısız/iptal edilmiş çalışmada sonuç bulunmaması normaldir; hata kodu
`get_task` içindedir. Aktif iptal cevabı hemen `running` dönebilir; worker'ın
iptali işlemesini bekleyip durumu yeniden sorgulayın. Uzak işlemin geri alınması
garanti edilmez. Retry uzaktaki işlemi yeniden yapabilir.

İstemciye verilebilecek örnek talimat:

> R Agents'taki ajanları listele. assistant ajanına luna bağlantısıyla toplantı
> gündemi görevini gundem-001 anahtarıyla gönder. Görev kimliğini sakla; bitince
> durumdan çalışma kimliğini bulup sonucunu getir. İptal istersem aynı görev
> kimliğiyle cancel_task kullan.

## 4. ChatGPT / HTTP istemcisi

HTTP sunucusu aynı araçları **yalnız `127.0.0.1` üzerinde** sunar:

```powershell
.\.venv\Scripts\ragents.exe mcp serve --transport streamable-http --port 8765 --db C:\Projeler\Ajan\Ragents\data\ragents.db --config C:\Projeler\Ajan\Ragents\examples\management.yaml --allow-execute
```

Yerel adres `http://127.0.0.1:8765/mcp` olur. MCP SDK'nın Host/Origin koruması
açıktır; istek gövdesi 256 KiB ile sınırlıdır. Yerel uçta uygulama OAuth'u
yoktur; aynı kullanıcı/makinedeki yetkili istemciler için tasarlanmıştır.
Doğrudan internete açmayın. Bu sürüm ekip/tenant bazlı yetkilendirme sunmaz.

ChatGPT web yerel stdio yapılandırmasını doğrudan yüklemez. Özel MCP bağlantısı
için [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
kullanılabilir: Platform'da tüneli oluşturup `tunnel-client` hedefini bu yerel
HTTP adresine ayarlayın; ChatGPT'de özel MCP sunucusu eklerken bağlantı olarak
tüneli seçin. Tünel kimliği, runtime anahtarı ve ilgili Platform/ChatGPT erişim
izinleri hesabınızdan sağlanır. Kurulum parametrelerini mevcut `tunnel-client`
yardımı ve resmî rehberle doğrulayın. R Agents hesabınıza tünel kurmaz veya
anahtar üretmez.

ChatGPT özel MCP sunucuları okuma/yazma araçlarını ve streaming HTTP'yi
destekler; ekleme ve erişim adımları [resmî bağlantı rehberindedir](https://developers.openai.com/api/docs/guides/custom-mcp-server).
Bu projede ChatGPT arayüzünde gerçek bağlantı veya tünel testi yapılmadı.
HTTP MCP protokolü yerelde gerçek SDK istemcisiyle doğrulandı. ChatGPT'yi
yönetici olarak bağlamak ile worker'ın ChatGPT OAuth model kaynağını kullanması
iki ayrı bağlantıdır.

## Doğrulama

Çevrimdışı testler: MCP istemcisinden model bağlantısı seçimi; HTTP üzerinden
görev gönderme → worker → native motor → durum → kayıtlı sonuç; idempotent
tekrarın ek model isteği oluşturmaması; MCP üzerinden aktif iptal ve sonuç
yokluğu; varsayılan salt okunur araçlar; stdio alt süreç protokolü;
HTTP loopback CLI yapılandırması ve yabancı Host/Origin reddi.

Model sınırında FunctionModel kullanılır; gerçek sağlayıcı, OAuth kasası,
internet veya ücretli çağrı kullanılmaz. Canlı kuyruk değiştirilmez.
