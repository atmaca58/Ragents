# Terminalden kurulum ve MCP bağlantısı

Ürün terminalden kurulur ve yönetilir. R Agents için ayrı web paneli yoktur.
Ajan/ekip taslağını seçtiğiniz yapay zekâ istemcisi MCP ile hazırlar; izinleri
yerel terminalde görüp onaylarsınız. YAML veya kaynak kodu düzenlemek gerekmez.
Bu geliştirme sürümünün gerçek hesap/istemci ve kurulum kabulü henüz açık.

## Windows kurulumu

Herkese açık GitHub geliştirme sürümünü Windows 11 x64 PowerShell'de kurmak:

```powershell
irm https://raw.githubusercontent.com/atmaca58/Ragents/v0.2.0-dev.3/scripts/install.ps1 | iex
```

Komut yönetici yetkisi, sistem Python'u, Git veya GitHub hesabı gerektirmez.
Sabit sürüm manifesti ve uygulama varlıkları GitHub'dan; Python/MinGit/pip
resmi kaynaklarından, bağımlılıklar PyPI'den ve Chromium Playwright'ın resmi
dağıtımından indirilir. Manifest ve uygulama/Python/Git/pip indirmeleri
SHA-256 ile doğrulanır. Ağ gereklidir. Sessiz ücretli model çağrısı yapılmaz.

Varsayılan hedef `%LOCALAPPDATA%\Programs\RAgents`; profil ayrı tutulur.
Kurulum sonunda `ragents init` terminalde açılır. Model ve aramayı seçtikten
sonra aşağıdaki `ragents connect` komutlarından kullandığınız istemciyi seçin.
Tekrar kurulum aynı paket dosyalarını doğrular; mevcut profilin üzerine
yazmaz. Sonradan `ragents init` ile ertelenmiş kurulumu tamamlayabilirsiniz.

Kaynakla birlikte verilen Inno EXE yolu ayrıca geliştirme aşamasındadır:

Yayımlanan kurucunun SHA-256 değerini kontrol ettikten sonra PowerShell'de:

```powershell
Get-FileHash .\R-Agents-SURUM-windows-x64.exe -Algorithm SHA256
Start-Process -FilePath .\R-Agents-SURUM-windows-x64.exe -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -Wait
```

`SURUM` yerine indirilen dosyanın sürümü yazılır. Kurucu kullanıcı başına
çalışır; Python, Git veya bir ajan istemcisi kurulu olması gerekmez. Yeni bir
terminal açarak:

```powershell
ragents init
```

Terminal model kaynağını ve aramayı numaralı menüden seçtirir. Girişten sonra
sağlayıcının model listesi alınır ve numarayla seçim yapılır. Arka plan çalışması ayrıca sorulur. API anahtarı gerektiğinde görünmeyen girişle işletim sistemi kasasına
kaydedilir. ChatGPT seçildiğinde sağlayıcının resmi giriş/onay sayfası açılır.
Model listesi alınamazsa kurulum açık hata vererek durur; tahmini model kaydedilmez. Başka uygulamanın
oturumu alınmaz. Model erişimi yetersizse ücretli API'ye geçilmez.

PATH henüz yenilenmediyse aynı komutun varsayılan tam yolu:

```powershell
& "$env:LOCALAPPDATA\Programs\RAgents\ragents.exe" init
```

Kurulumda giriş ertelendiyse:

```powershell
ragents auth login chatgpt
ragents connections list
ragents connections test primary
```

Son komut yerel ayar/kimlik kontrolüdür; uzaktaki modelin çalıştığını
kanıtlamaz ve model isteği göndermez. `--live` ayrıca seçilirse tek araçsız
model isteği gönderir, hesap kotası tüketebilir. İlk kullanıcı kabulünde ek
ücret bütçesi 0 USD'dir; kota yetmezse test bekletilir.

## İstemciyi bağlama

Kullandığınız istemci için bir komut seçin:

```powershell
ragents connect codex --test
ragents connect opencode --test
ragents connect claude --test
ragents connect claude-desktop --test
```

Komut ilgili kullanıcı ayarına `r_agents` stdio MCP kaydını ekler. Mevcut
ayarları korur ve değişen dosyanın özgün kopyasını yedekler. Farklı bir
`r_agents` kaydı varsa üzerine yazmaz; önce `--show`, sonra gerekiyorsa
`--replace` kullanılır. OpenCode JSONC yorumları yedekte korunur, yeni dosya
JSON olarak yazılır. Özel ayar yolu `--config DOSYA` ile seçilebilir.

`--test` gerçek MCP sunucusuyla el sıkışma/yetenek keşfidir; model kullanmaz.
Seçilen dış istemcinin uçtan uca kabulü anlamına gelmez. İstemciyi yeniden
açıp zorunlu bağlantı/güven onayını tamamlayın. Yalnız okuma için `--read-only`
kullanın. Normal bağlantı taslak/görev yönetimini açar; içerik onayı yine
terminalde verilir.

Kayıt biçimleri [Codex](https://developers.openai.com/codex/mcp),
[OpenCode](https://opencode.ai/docs/mcp-servers/) ve
[Claude Code](https://code.claude.com/docs/en/mcp) belgelerine dayanır.

## Yapay zekâyla ajan veya ekip kurma

Bağladığınız istemciye örneğin “Bu klasör için araştırmacı, geliştirici ve
bağımsız doğrulayıcıdan oluşan bir ekip taslağı hazırla; izinleri ve bütçeyi
göster” diyebilirsiniz. MCP taslağı onay talebi olarak kaydeder. Ardından:

```powershell
ragents approvals list
ragents approvals show TALEP_KIMLIGI
ragents approvals approve TALEP_KIMLIGI
```

Son komut gerçek terminalde önizlemeyi gösterir ve işlem hash'inin ilk 12
karakterini yazmanızı ister. Görülen işlem bir kez uygulanır. Değişen veya
süresi dolan taslak yeniden onay ister. MCP'den `confirm=true` göndermek ya da
pipe ile onay metni iletmek insan onayı sayılmaz.

## ChatGPT web bağlantısı

Web istemcisi yerel stdio sürecini başlatamaz. Kullanıcının HTTPS tüneli yalnız
OAuth korumalı MCP portunu (`127.0.0.1:8765`) yönlendirmelidir:

```powershell
ragents connect chatgpt --public-url https://SIZIN-TUNEL-ADRESINIZ
```

Çıktıdaki `serve` komutunu çalıştırın; seçilen profil ve yetkiler komuta dahil
edilir. ChatGPT hesabınızın MCP/app ekleme alanında çıktıdaki `/mcp` URL'sini
ekleyip OAuth akışını başlatın. Hesap bu bağlantıyı desteklemiyorsa gerçek
kabul tamamlanmış sayılmaz. İlk bağlantı talebi yerel terminalde onaylanır:

```powershell
ragents approvals connections
ragents approvals approve-connection BAGLANTI_KIMLIGI
```

ChatGPT hesabındaki zorunlu bağlantı onayı hesap arayüzünde kalır. Ürün
kurulumu/yönetimi için ayrı frontend gerekmez. Kimliksiz loopback HTTP
sunucusunu tünelle genel internete açmayın. `connect chatgpt --test` desteklenmez;
uzak istemci kabulü gerçek hesap/OAuth/tünel kanıtı gerektirir.

## Arka plan ve profil seçimi

```powershell
ragents service install
ragents service start
ragents service status
ragents service stop
ragents search status
ragents search configure --provider disabled
```

Varsayılan profil `%LOCALAPPDATA%\RAgents\profiles\default` olur. Başka profil
için komut grubunda `--root` kullanın; örneğin
`ragents connect codex --root C:\RAgents-Profil` ve
`ragents approvals --root C:\RAgents-Profil list`. Ortak varsayılanı
`RAGENTS_HOME` ile de belirleyebilirsiniz. Arka plan Task Scheduler ile kullanıcı
oturumunda çalışır; kişisel ajan taşıma ürün kabulü ve yayından sonra yapılır.
