<div align="center">

# R Agents

### Kendi modellerin. Kendi ajanların. Kendi bilgisayarın.

Terminalden kur. Model kaynağını bağla. Kullandığın yapay zekâdan ajanlarını yönet.

[![Windows 11 x64](https://img.shields.io/badge/Windows_11-x64-0078D4)](docs/terminal-quickstart.md)
[![Ön sürüm](https://img.shields.io/badge/durum-geliştirme_ön_sürümü-orange)](https://github.com/atmaca58/Ragents/releases)
[![Apache 2.0](https://img.shields.io/badge/lisans-Apache_2.0-blue)](LICENSE)

[Kurulum](#kurulum) · [İstemci bağlantısı](#istemcini-bağla) · [Kullanım rehberi](docs/terminal-quickstart.md) · [Sürümler](https://github.com/atmaca58/Ragents/releases)

</div>

---

R Agents, kendi model kaynağını kullanarak bilgisayarında ajanlar ve kontrollü
ajan ekipleri çalıştırmanı sağlar. Görevler, talimatlar ve sonuçlar yerel
profilinde tutulur. Yönetim için Codex, OpenCode veya Claude gibi MCP destekli
bir istemci kullanabilirsin.

**Ayrı bir ürün paneli gerekmez.** Kurulum ve izin onayları terminalde yapılır;
ajanın ne yapacağını bağlı yapay zekâ istemcisine anlatırsın.

> **Sürüm durumu:** R Agents geliştirme ön sürümüdür. Gerçek sağlayıcı,
> istemci ve uçtan uca kullanıcı kabulü henüz tamamlanmadı.
> Windows 11 x64 hedeflenir; macOS ve Linux deneyseldir.

## Kurulum

Windows 11 x64 üzerinde PowerShell'i aç ve çalıştır:

```powershell
irm https://raw.githubusercontent.com/atmaca58/Ragents/v0.2.0-dev.5/scripts/install.ps1 | iex
```

GitHub hesabı, yönetici yetkisi veya önceden kurulmuş Python/Git gerekmez.
Kurucu gerekli çalışma zamanlarını indirir; internet bağlantısı gerekir.

Kurulumun sonunda terminal sihirbazı açılır:

1. **Model kaynağını bağla.** Sağlayıcına göre resmi giriş veya API anahtarı kullan.
2. **Web aramasını seç.** Ücretsiz anahtarsız arama, Tavily, Brave, SearXNG veya “şimdilik bağlama”.
3. **Arka plan çalışmasını belirle.** Ajanların oturum açılışında başlatılmasını seç.
4. **İstemcini bağla.** Aşağıdaki komutlardan kullandığın istemciyi çalıştır.

Sağlayıcı ve arama numaralı listelerden seçilir. Model listesi sağlayıcıdan
alınır; model kimliğini ezberlemen gerekmez. Liste alınamazsa kurulum açık
hata verir. Kurulum sonunda seçilen sağlayıcı/model ve sonraki adım gösterilir.

## İstemcini bağla

Kullandığın istemciye ait **bir** komutu çalıştır:

| İstemci | Terminal komutu |
| --- | --- |
| Codex | `ragents connect codex --test` |
| OpenCode | `ragents connect opencode --test` |
| Claude Code | `ragents connect claude --test` |
| Claude Desktop | `ragents connect claude-desktop --test` |

Komut MCP kaydını ekler ve mevcut ayarların yedeğini alır. Ardından istemcini
yeniden aç ve gerekiyorsa bağlantı onayını tamamla. `--test`, yerel MCP
bağlantısını kontrol eder; model isteği göndermez.

**ChatGPT web** bağlantısı kendi HTTPS tünelini ve OAuth eşleştirmesini gerektirir.
Adımlar [bağlantı rehberinde](docs/terminal-quickstart.md#chatgpt-web-bağlantısı).

## İlk ajanını tarif et

Bağladığın yapay zekâ istemcisine şuna benzer bir istek yaz:

> Bir araştırma ajanı taslağı hazırla. Yalnız seçtiğim çalışma klasörünü okusun,
> kaynaklarıyla birlikte bir rapor üretsin. Modeli, araç izinlerini ve bütçeyi
> uygulamadan önce göster.

İstemci MCP üzerinden bir taslak oluşturur. İzinleri terminalde inceleyip onayla:

```powershell
ragents approvals list
ragents approvals show TALEP_KIMLIGI
ragents approvals approve TALEP_KIMLIGI
```

`TALEP_KIMLIGI` yerine listede görünen kimliği kullan. Onay sırasında gösterilen
işlem kodunu terminale yazarsın. Değişen veya süresi dolan taslak yeniden onay ister.

## Model kaynağı ve MCP bağlantısı

Bunlar iki ayrı seçimdir:

| Seçim | Ne işe yarar? |
| --- | --- |
| **Model sağlayıcısı** | Arka plandaki ajanların hangi modelle çalışacağını belirler. |
| **MCP istemcisi** | Ajanlarına talimat verdiğin ve sonuçlarını gördüğün uygulamadır. |

Örneğin OpenCode üzerinden yönetip ajanların model kaynağı olarak Ollama
kullanabilirsin. Bir istemciyi bağlamak, onun oturumunu veya aboneliğini
arka plan ajanlarına otomatik olarak aktarmaz.

Model bağlantıları: **ChatGPT OAuth, OpenRouter, OpenCode Go, OpenCode Zen ve Ollama**.
ChatGPT erişimi uygun hesap ve açık plan kullanım izni gerektirir.
API anahtarı kullanan servislerin kendi kullanım koşulları geçerlidir.
Doğrudan Anthropic model sağlayıcısı bu sürümde yoktur; Claude MCP istemcisi olarak bağlanabilir.

## Neler yapabilirsin?

- **Ajanlar ve ekipler:** Talimat, rol ve izinleri tanımla; kontrollü ekip akışları kur.
- **Kalıcı görevler:** Görevleri sıraya al, takvim oluştur, durumu ve sonuçları izle.
- **Dosya ve geliştirme:** İzinli klasörlerde dosya işlemleri, komutlar ve Git araçları kullan.
- **Araştırma ve tarayıcı:** Arama kaynağı bağla, sayfa oku, Playwright kanıtları üret.
- **Yerel kontrol:** Taslakları onayla, çalışmaları iptal et, profilini yedekle ve taşı.

Araçlar açık izinlerle çalışır. Bir özelliğin uygulanmış olması, gerçek
hesapla ürün kabulünün tamamlandığı anlamına gelmez.

## Ücretsiz ve anahtarsız web araması

Hesap açmadan sınırlı kullanım için:

```powershell
ragents search configure --provider keyless
ragents search test "Python resmi belgeleri"
```

Bu seçim **Exa → Parallel → Keenable** ücretsiz MCP uçlarını
hata durumunda sırayla denemeye izin verir. Yanıtta kullanılan sağlayıcı ve
denemeler görünür. Ücretli hesaba geçilmez; ücretsiz sınırlar garanti edilmez.
Exa, Parallel ve Keenable ile gerçek anahtarsız arama doğrulandı.

Kendi SearXNG sunucunu veya tek bir sağlayıcıyı da seçebilirsin.
[Arama seçenekleri ve gizlilik](docs/web-search.md).

## Günlük komutlar

```powershell
ragents connections list
ragents connections test primary
ragents service status
ragents service start
ragents service stop
```

Bağlantı kontrolü yerel ayarları inceler; modelin uzaktan yanıt verdiğini
kanıtlamaz. Canlı model kontrolü ayrıca seçilir ve hesap kotası tüketebilir.
Kota veya erişim hatasında başka ücretli sağlayıcıya otomatik geçilmez.

Uygulama ile kullanıcı verileri ayrı tutulur. Varsayılan profil:
`%LOCALAPPDATA%\RAgents\profiles\default`.
Kimlik bilgileri taşınabilir profil paketine dahil edilmez.

## Kaldırma

```powershell
ragents uninstall
```

Yerel onaydan sonra seçili profilin arka plan görevi, bu kuruluma ait yerel
MCP kayıtları, PATH girdisi ve uygulama dosyaları kaldırılır. Ajanların,
görev geçmişin ve kimlik bilgilerin kullanıcı profilinde korunur.
ChatGPT web hesabındaki bağlantıyı ve kendi tünelini ayrıca kaldırmalısın.


## Yardım ve katkı

[Kurulum ve kullanım](docs/terminal-quickstart.md) ·
[Sağlayıcı bağlantıları](docs/provider-integrations.md) ·
[Sorun bildir](https://github.com/atmaca58/Ragents/issues) ·
[Geliştirici rehberi](CONTRIBUTING.md)

Kaynak kod, testler ve geliştirme araçları katkıda bulunanlar içindir;
normal kurulum bunları uygulama paketine dahil etmez.

[Apache-2.0](LICENSE) · [Üçüncü taraf bildirimleri](NOTICE)
