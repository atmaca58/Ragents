# Windows ürün teslimi

Kullanıcı onaylı hedef: Windows 11 x64, tek kullanıcı, MCP'den yapay zekâ
destekli kurulum/yönetim, bağımsız ajanlar ve kontrollü ekipler. Apache-2.0
ile açık GitHub yayını. Kişisel ajan göçü en son yapılır.

## Kabul sırası

1. Denetimdeki sekiz hata ve ortak ajan/workspace kilitleri.
2. Tek profil kökü, güvenli bağlantılar, taşınabilirlik ve yedek/geri dönüş.
3. Takvim, programatik işler, doğrulanmış hafıza ve kontrollü ekip bütçeleri.
4. Dosya/kod/Git/web/tarayıcı/artifact araçları; seçilebilir arama servisi.
5. Katalog/ekip yönetim MCP'si, yerel insan onayı, uzak MCP yetkilendirmesi.
6. Windows kurucu, terminal kurulumu/onayı, otomatik arka plan işletimi ve güncelleme.
7. Kullanıcının yerel Windows bilgisayarında kurulum ve gerçek istemci/sağlayıcı kabulü; sonra GitHub yayını.
8. Kullanıcının yayımlanan kurucuyla sıfırdan kurulumu; sonra özel ajan göçü.

Her madde kod, anlamlı regresyon, kullanım belgesi ve kabul kanıtıyla kapanır.
Sahte model testi gerçek sağlayıcı/kurulum kanıtı sayılmaz. Yayın kapısı için
en az 20 sürümlü senaryo, referans modelle üç tekrar ve önceden belirlenen
canlı bütçe gerekir. Kişisel veri, secret ve DB'ler yayın paketine girmez.

## Sabit ürün kararları

- Ürün kodu kullanıcı profilinden ayrıdır. Varsayılan profil
  `%LOCALAPPDATA%/RAgents/profiles/default`; açık kök ve `RAGENTS_HOME` desteklenir.
- Yönetici MCP istemcisi ile arka plandaki model kaynağı farklı bağlantılardır.
- Kurulum, ayarlar, MCP kaydı ve yerel onay CLI üzerinden yapılır; ürün web
  paneli yoktur. Sağlayıcının zorunlu OAuth ve istemcinin hesap onayı korunur.
- Kullanıcının son kararıyla VM/ISO hazırlanmaz. Yerel bilgisayar kabulü temiz
  Windows/VM kanıtı olarak raporlanmaz. Ek ücretli model test bütçesi 0 USD'dir.
- Uzak MCP kullanıcının HTTPS tüneli ve dar yetkili kimlik doğrulamayla çalışır.
- Arama seçimi Tavily, Brave, SearXNG veya şimdilik kapalı; ücretsiz/kotasız/
  anahtarsız ayrımları açıklanır. Sessiz ücretli geçiş yapılmaz.
- Windows ilk desteklenen ürün; macOS/Linux native kabulüne kadar deneyseldir.
- V1 ve kullanıcı ajanları geliştirme/test verisi değildir.

Bu belge hedef/kabul sözleşmesidir; tamamlanma veya canlı runtime kaydı değildir.

2 Kasım 2026 kullanıcı kararı: mevcut ürün kodu şimdi commit/push edilecek,
depo herkese açık yapılacak ve hesap gerektirmeyen tek komutluk geliştirme
kurulumu yayımlanacak. Bu, önceki yayın sırasının kullanıcı tarafından verilen
istisnasıdır; eksik ürün kabulü tamamlanmış veya kişisel geçiş yapılmış sayılmaz.
