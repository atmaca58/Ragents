# R Agents — Kurulum ve özelleştirme

Yerel servis kurulum akışı tamamlandı: bağımlılıklar → sağlayıcı/model seçimi →
örnek ajan → yerel kimlik kontrolü → isteğe bağlı ChatGPT girişi ve tek model
isteğiyle bağlantı testi → worker/MCP dosyaları. Kurulum worker'ı kendiliğinden
başlatmaz; görev göndermek model ve araç kullanımına yol açabilir.

## Tek kurulum akışı

Windows PowerShell'de, Python 3.12–3.14 kurulu olmalıdır:

```powershell
cd C:\Projeler\Ajan\Ragents
.\scripts\setup.ps1
```

Script sanal ortamı/bağımlılıkları kurar ve Türkçe sihirbazı açar. Sağlayıcı
kimliği (`chatgpt`, `opencode_go`, `opencode_zen`, `openrouter`, `ollama`),
hesabınızda erişilebilir model kimliği, ajan kimliği/adı/talimatı sorulur.
Model erişimi hesaba göre değişir; kurulum model indirmez veya seçimi sessizce
başka modele yönlendirmez. Model kimliğini sağlayıcınızdan öğrenin.

- ChatGPT: R Agents hesap etiketi seçilir. Oturum yoksa tarayıcı girişini
  açabilirsiniz. Mevcut şifreli OAuth deposu kullanılır; Codex dosyaları okunmaz.
- Go/Zen/OpenRouter: anahtarın **ortam değişkeni adı** seçilir. Sihirbaza
  anahtarın kendisi yazılmaz. Varsayılanlar `OPENCODE_GO_API_KEY`,
  `OPENCODE_ZEN_API_KEY`, `OPENROUTER_API_KEY` olur.
- Ollama: çalışan OpenAI uyumlu API adresi seçilir; varsayılan
  `http://localhost:11434/v1`. Model ayrıca kurulu olmalıdır.

Eksik ortam değerini kendi güvenli terminal oturumunuzda tanımlayın ve ardından
`doctor` kullanın. `.env` otomatik yüklenmez. Worker ve MCP süreci de ihtiyaç
duyduğu ortamı miras almalıdır. Anahtar değeri YAML/JSON/TOML'ye yazılmaz.

Yerel kontrol kimliğin bulunup bulunmadığını gösterir; anahtarın/oturumun
sağlayıcıda geçerli olduğunu iddia etmez. Tek model isteğiyle gerçek erişim
testi ayrıca sorulur ve varsayılan cevap **hayırdır**. Test ücret/token
tüketebilir. Kurulumun normal beklemesi ve ayar üretimi model çağırmaz.

## Üretilen profil

Varsayılan dizin `Ragents/local-profile/`; `-ProfileDirectory` ile değişir:

```powershell
.\scripts\setup.ps1 -ProfileDirectory C:\Projeler\Ajan\Ragents\my-profile
```

| Dosya | Kullanım |
| --- | --- |
| `ragents.yaml` | Sağlayıcı/model, örnek ajan, talimat ve bütçeler |
| `start-worker.ps1` | Bu profilin kuyruğunu sürekli işleten worker |
| `mcp-client.json` | Genel stdio MCP istemci kaydı |
| `codex-mcp.toml` | Codex ayarlarına eklenecek MCP kaydı |

Tüm yollar mutlaktır; kuyruk `profil/data/ragents.db` olur. DB, worker/MCP
başlatıldığında oluşur. Mevcut projedeki `Ragents/data/ragents.db` kuyruğundan
ayrıdır. Mevcut profil dizininin üzerine yazılmaz; tekrar kurulum için yeni
dizin kullanın, mevcut ayarı değiştirmek için YAML'yi düzenleyin.

Kurulumdan sonra:

```powershell
# Ayrı terminalde sürekli açık kalır; Ctrl+C ile kontrollü kapanır.
.\local-profile\start-worker.ps1

# Başka terminalde, model çağırmadan kontrol:
.\.venv\Scripts\ragents.exe doctor --config local-profile/ragents.yaml
```

Codex TOML kaydını kendi `config.toml` dosyanızdaki diğer kayıtların yanına;
JSON kaydını kullanan istemcide ilgili MCP alanına ekleyin. Bu dosyalar
kullanıcı ayarlarınızı otomatik değiştirmez. İstemci, yönetim MCP'sini kendi
başlatır; worker ayrıca açık kalır. Oluşturulan MCP kaydı `--allow-execute`
içerir; yalnız okuma istiyorsanız bu argümanı çıkarın.
Görev/sonuç/iptal ve ChatGPT tünel bağlantısı için
[dış yönetim rehberini](external-management.md) kullanın.

## Mevcut kurulum / otomasyon

Bağımlılıklar zaten kuruluysa:

```powershell
.\.venv\Scripts\ragents.exe setup
```

Etkileşimsiz örnek (ChatGPT modeli mevcut hesabınızdan seçilir):

```powershell
.\.venv\Scripts\ragents.exe setup --non-interactive --provider chatgpt --model gpt-6-luna --directory local-profile --agent-id assistant --name "Asistan" --instructions "Türkçe ve kısa yanıt ver."
```

`--login`, mevcut ChatGPT tarayıcı girişini aynı akışta açar. `--oauth-account`
hesap etiketini seçer. `--verify` tek gerçek model testini açıkça etkinleştirir.
Diğer seçenekler: `--api-key-env`, Ollama için `--base-url`. API adresinde
kullanıcı/parola, sorgu veya fragment kabul edilmez. Anahtar değerlerini komut
argümanına yazmayın. Etkileşimsiz kullanım `--provider` ve `--model` gerektirir;
etkileşimli terminal bulunmazsa sihirbaz beklemek yerine açıklayıcı hata verir.

Yalnız bağımlılık kurulumu / geliştirme:

```powershell
.\scripts\setup.ps1 -SkipConfigure
.\scripts\setup.ps1 -SkipConfigure -RunTests
```

## Bağlantı kontrolü ve hata giderme

```powershell
# Yerel şema + seçili bağlantı kimliği; ağ/model isteği yok:
.\.venv\Scripts\ragents.exe doctor --config local-profile/ragents.yaml

# Tek gerçek model isteği; ücret/token tüketebilir:
.\.venv\Scripts\ragents.exe doctor --config local-profile/ragents.yaml --live

# Aynı ajan içinde başka kayıtlı bağlantıyı dene:
.\.venv\Scripts\ragents.exe doctor --config local-profile/ragents.yaml --connection alternatif --live
```

`credentials_ready` yerel kimlik koşulunu, `remote_validated` başarılı gerçek
model yanıtını gösterir. Ollama anahtarsız olabilir; `credentials_ready: true`
sunucunun açık olduğunu göstermez. Eksik kimlik veya başarısız testte doctor
çıkış kodu 1, geçersiz ayar/komutta 2 döner. `setup --verify` başarısız olursa
1 döner ve üretilmiş profil korunur; yeniden sihirbaz çalıştırmak yerine
kimliği/servisi düzeltip doctor'ı tekrar çalıştırın. Tarayıcı girişinde hata
olursa da profil korunur; standart `auth login chatgpt` komutu kullanılabilir.

Test, ajanınıza eklediğiniz MCP/yerleşik araçları çalıştırmaz, görev DB'sine
kayıt eklemez. Bir model isteği, sıfır araç çağrısı ve 20 saniye sınırı kullanır;
çıktı bütçesi 128, girdi bütçesi 1024 ve toplam bütçe 1152 tokendır. Mevcut
ChatGPT plan yolunda çıktı sınırı istek öncesinde uygulanamaz; kullanım yanıt
sonrasında denetlenir. Kesin parasal üst sınır veya kesilen isteğin uzakta
durdurulması garantisi yoktur. Başarısız istekte bilinmeyen kullanım `null`
kalır; ham sağlayıcı yanıtı/kimlik bilgisi çıktıya alınmaz.

Talimatı, modeli veya bütçeyi `ragents.yaml` üzerinden özelleştirin. Ajan
başlangıçta araçsızdır. Başka sağlayıcı eklemek için `connections` bölümüne
kayıt ekleyin; [entegrasyon rehberindeki](provider-integrations.md) örnekleri
kullanın. Değişiklikten sonra MCP sunucusunu yeniden başlatın. Kuyruktaki
görevler gönderildikleri andaki ayarı korur.

## Bu aşamanın sınırı

Yerel servis kurulum ve yönetim akışı hazırdır. Windows otomatik servis
kaydı, uygulama düzeyinde uzak MCP OAuth'u/ekip yetkileri, sandbox, çoklu ajan
iş birliği ve bağımsız görev çıktısı doğrulama henüz uygulanmadı. Bunlar
çalışan yerel çekirdeğin sonraki aşamalarıdır; üretim olgunluğu iddiası yoktur.
Yeni sihirbaz çevrimdışı testlerle doğrulanmıştır; bu aşamada gerçek sağlayıcı
isteği, tarayıcı girişi veya temiz makinede yeniden bağımlılık kurulumu yapılmadı.
