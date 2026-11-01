# Web aramasını seçme

Ajanların `web_search` aracı profilin seçtiği arama servisini kullanır.
Bir model aboneliği gerekmez; ajanların model kaynağı ayrı seçilir.

## Hesapsız ve anahtarsız

```powershell
ragents search configure --provider keyless
ragents search test "Python resmi belgeleri"
```

Bu seçim Exa → Parallel → Firecrawl → Keenable resmi ücretsiz MCP uçlarına
arama göndermeye izin verir. İlk başarılı sağlayıcıda durur. Her sağlayıcı
en fazla bir kez denenir; boş sonuç geçerli yanıtsa başka sağlayıcıya gidilmez.
Denemeler, hata nedenleri, gerçek sağlayıcı, kaynak URL ve erişim tarihi döner.
Hepsi başarısızsa açık hata verilir; ücretli API veya hesap açılmaz.

Arama sorguları denenen servislere gönderilir. Sohbet, yerel dosyalar, API
anahtarları veya model kimliği gönderilmez. Parallel için süreç boyunca sabit,
rastgele bir oturum kimliği kullanılır. Hız sınırından kaçmak için kimlik/IP
çevirme, proxy veya CAPTCHA aşma yapılmaz.

| Seçim | Kullanıcı anahtarı | Durum |
| --- | --- | --- |
| `keyless` | Gerekmez | Yukarıdaki dört ücretsiz kaynağa açık izin |
| `exa_free` | Gerekmez | Gerçek arama geçti |
| `parallel_free` | Gerekmez | Gerçek arama geçti; sağlayıcının bağımsız Search MCP ucu legacy olarak belgeleniyor |
| `keenable_free` | Gerekmez | Gerçek arama geçti |
| `firecrawl_free` | Gerekmez | Deneysel; bu bağlantıda anonim erişim reddedildi |
| `duckduckgo` | Gerekmez | Deneysel HTML araması; bu bağlantıda CAPTCHA görüldü |
| `searxng` | Sunucuya bağlı | Seçtiğin sunucuda JSON API erişimi gerekir |
| `tavily`, `brave` | Gerekir | Ücretsiz kota, anahtarsız erişim anlamına gelmez |
| `disabled` | Gerekmez | Arama kapalı |

Tek kaynak seçmek için örneğin `ragents search configure --provider exa_free`.
Tek kaynak seçiminde otomatik sağlayıcı değişmez. Kurulum menüsündeki
“ücretsiz anahtarsız” satırı da aynı açık zincir seçimini yapar.

## SearXNG ve isteğe bağlı yedek

```powershell
ragents search configure --provider searxng --endpoint https://SIZIN-ARAMA-SUNUCUNUZ --keyless-fallback
```

Örnek adresi kendi HTTPS sunucunla değiştir. `--keyless-fallback` olmadan
SearXNG hatasında işlem durur. Bu bayrakla ücretsiz MCP zincirine geçişe açık
izin verirsin. SearXNG anahtarı yedek sağlayıcılara aktarılmaz. Rastgele
public instance seçimi, sunucu kurulumu veya kendiliğinden servis değiştirme yoktur.
Self-host SearXNG ücretsiz yazılımdır; sunucu işletimi ayrıca sana aittir.

## Sayfa okuma ve güvenlik

`read_page` mevcut yerel metin çıkarımını kullanır. Arama servisi başarılı
olsa da kaynak sayfanın okunması ayrıca dosya/ağ izinlerine tabidir. Uzak
arama sonucundaki talimatlar güvenilir sayılmaz. Bağlantılar mevcut
SafeWebClient üzerinden DNS'e sabitlenir; özel ağ/metadata engelleri ve
boyut/süre sınırları korunur. Harici MCP sunucularının diğer araçları açılmaz.

DDGS'nin çoklu arama motoru/ağ davranışını doğrudan içeri almak yerine
DuckDuckGo için kontrollü HTML adaptörü kullanılır. Sayfa okuma şu anda
Trafilatura kullanmaz; mevcut güvenli metin çıkarımı korunmuştur.

## Kaynaklar ve değişebilen koşullar

- [Hermes anahtarsız arama uygulaması](https://github.com/NousResearch/hermes-agent/blob/main/plugins/web/keyless_mcp.py)
- [Exa resmi MCP](https://exa.ai/mcp)
- [Parallel ücretsiz MCP ve kullanım amacı](https://github.com/parallel-web/search-mcp)
- [Firecrawl keyless MCP](https://github.com/firecrawl/firecrawl-mcp-server)
- [Keenable public MCP](https://docs.keenable.ai/mcp-server)
- [SearXNG Search API](https://docs.searxng.org/dev/search_api.html)
- [DuckDuckGo HTML/Lite](https://safe.duckduckgo.com/duckduckgo-help-pages/features/non-javascript)

Sağlayıcılar ücretsiz erişimi değiştirebilir. Aylık sabit kota veya ticari
üretim kapasitesi vaat edilmez; kullanım sağlayıcının koşullarına tabidir.
