# Native ajan servisi

Hedef platformlar Windows, macOS ve Linux'tur. Ortak kurucu ve worker/MCP
çekirdeği paylaşılır; sandbox ve OS servis katmanları ortak sözleşme altında
platform backend'leriyle geliştirilecektir. [Platform kapsamı](platform-support.md).

## Bağımlılık yönü

```text
CLI / Yönetim MCP → TaskStore → Worker → TaskService → application.run_task
                                                       ↓
                        Araç MCP ← ToolGateway ← NativeEngine → Pydantic AI
                                                       ↑
                                                  providers.py
                                                       ↓
                               Ollama / OpenRouter / Go / Zen / ChatGPT OAuth
```

`config.py` ajan ile bağlantıyı ayrı doğrular. `contracts.py` framework'e ait
model veya mesaj türlerini dışarı çıkarmaz. `application.py` bir görevi
yürütür; SDK nesnesi veya CLI süreci oluşturmaz. `providers.py` bağlantı
anahtarını çalışma anında çözer, HTTP istemcisinin ömrünü yönetir ve native
motoru kurar. `engines/native.py` model–araç döngüsünü ve sınırları uygular.
`auth.py` şifreli OAuth deposunu ve hesap kilidini, `chatgpt_login.py`
resmi Sign in with ChatGPT akışını yönetir.
`setup_cli.py` sağlayıcı/ajan seçim akışıdır; `setup_profile.py` yeni profil ve
worker/MCP istemci dosyalarını üretir. `diagnostics.py` yerel kimlik kontrolü
ile açıkça seçilen tek istekli, araçsız model testini ayırır. Mevcut config,
auth ve application servisleri yeniden kullanılır; ikinci motor/kuyruk yoktur.
[Kurulum rehberi](setup-and-customization.md) bu akışın kullanıcı arayüzüdür.
`catalog.py` kalıcı ajan profillerini `local-profile/agents/<id>/` altında
yönetir; `agents_cli.py` oluşturma/listeleme/güncelleme/devre dışı bırakma/
arşivleme yüzeyidir. `instructions.py` profil, proje, kural ve seçili skill
dosyalarını tek ve deterministik bir talimat metnine derler; seçim ve boyut
sınırlarını uygular. `workspace.py` ajanın çalışma alanını, göreli yol
doğrulamasını, symlink/junction reddini, okuma/yazma kapsamlarını, sınırlı dosya
araçlarını ve artifact fark taramasını yönetir; `tools.py` görev izinlerini
doğrular, `fileops.py` yazma/yamayı sandbox içinde uygular. `sandbox.py` ortak yürütme sözleşmesini, platform
backend seçimini, güvenli ortamı, çıktı/zaman aşımı ve sert iptali yönetir;
`sandbox_windows.py` AppContainer + Job Object, `sandbox_posix.py` macOS
Seatbelt ve Linux bubblewrap uygulamalarıdır. Backend yoksa çalıştırma
reddedilir; sandbox'sız yedek yol yoktur. Katalog ajanı görev kuyruğuna girerken bu metin mevcut
`ProjectConfig` biçimine yerleştirilir; görev tanımı o anki talimat snapshot'ını
workspace grant'ini ve profil kopyasını saklar. `storage.py` framework'ten
bağımsız SQLite görev/run/sonuç/artifact kayıtlarını, görev metadata'sını,
bağımlılık grafiğini ve tanım revizyonlarını; `task_markdown.py` yalnız
içe/dışa aktarma görünümünü; `task_service.py` başlatma, süreç kilidi, workspace
anlık görüntüsü, iptal/hata sonlandırma ve açık kurtarmayı yönetir.
`engines/context.py` geçmiş seçimi ve her istek öncesi bağlam korumasıdır.
`worker.py` kalıcı kuyruğu sürekli işler; `worker_cli.py` sinyal/kapanış sınırıdır.
`mcp_server.py` aynı depoyu kullanan yerel yönetim yüzeyi, `mcp_client.py` izin
seçimi ve SDK bağımsız araç sözleşmesi, `mcp_transport.py` resmi MCP SDK bağlantısı,
`engines/mcp_tools.py` Pydantic AI araç köprüsüdür. Protokol ve saf metin aracı
yeniden yazılmaz; mevcut SDK ve araç fonksiyonu kullanılır.

Görev kuyruğu ve çalışma/sonuç kayıtları SQLite'tadır. Kuyruk öncelik ve
bağımlılık sırasına göre seçilir; yalnız etkin, arşivsiz ve tüm bağımlılıkları
tamamlanmış görevler alınır. Tek supervisor, kendi eşzamanlılık sınırıyla
çalışır; manuel `run` ayrı süreçtir. `tasks add` ve MCP `submit_task` yalnız
sıraya alır. Worker ömrü sürekli süreç ömrüdür; işletim sistemi otomatik
başlangıç kaydı kurulmaz. Model metni doğrulanmış görev başarısı anlamına gelmez.
Framework iç yapısı kalıcı run şeması olarak kullanılmaz.

## ADR-001 — Prototip kararı

Pydantic AI 2.64.0 ile başlanmıştır. Yalnız OpenAI uyumlu sağlayıcı ekini
içeren slim paket ve MCP Python SDK kurulmuştur. LangGraph'a karşı hız/kalite/token üstünlüğü
iddiası yoktur. Ölçümlü karşılaştırma yapılmadan Faz 0 tamamlanmış sayılmaz.

## Sıradaki geliştirme

1. Aynı model, araç ve görevlerle karşılaştırma protokolü; ayrı ve açık model
   bütçesiyle ölçüm. Bu adımdaki sahte model testleri kalite benchmark'ı değildir.
2. Kalıcı ajan kataloğu (A01), talimat derleyicisi (A02), workspace/dosya
   araçları (A03), gerçek sandbox (A04), sandbox içinde dosya yazma/yama ile
   argv tabanlı komut araçları (A05), model beyanından bağımsız görev
   doğrulaması (A06) ve V1'e denk görev yönetimi (A07) eklendi. Doğrulama planı
   görevle dondurulur; dosya, JSON şema, komut ve Playwright JSON kontrolleri
   çalışır. Görevler başlık, öncelik, bağımlılık, revizyon ve arşiv taşır;
   Markdown yalnız dışa/içe aktarma görünümüdür.
3. İşletim sistemi servis kurulumu, daha kapsamlı gözlemlenebilirlik ve kontrollü
   bağlantı havuzu/katalog önbelleği için ölçümler.
4. Stdio/loopback HTTP yönetim MCP'sini uygulama OAuth'u ve çok kullanıcılı
   ekip yetkileriyle genişletme. Görev başına bağlantı seçimi uygulanmıştır;
   [dış yönetim rehberi](external-management.md) mevcut bağlantıları açıklar.

[Sürekli servis ve MCP rehberi](service-and-mcp.md) tamamlanan worker, iptal,
araç izinleri/seçimi ve yönetim yüzeyinin davranışını açıklar.
[Sandbox rehberi](sandbox.md) platform backend'lerini ve izolasyon sınırlarını;
[dosya ve komut rehberi](tools-and-execution.md) görev izinlerini, yazma
araçlarını ve argv tabanlı komutları; [görev doğrulama](task-verification.md)
bağımsız kontrolleri ve kanıt kaydını; [görev yönetimi](task-management.md)
metadata, bağımlılık, revizyon ve Markdown görünümünü açıklar. Takvim tabanlı
scheduler ve çok ajan orkestrasyonu henüz uygulanmadı.

V1 veri kökü açılmaz; kişisel ajanlar kopyalanmaz. İlk örnek ajan bu paketin
`examples/` dosyalarındadır. Geri dönüş için eski runtime bağımsız kalır.

## Kaynaklar

- [Pydantic AI ajanları](https://pydantic.dev/docs/ai/core-concepts/agent/)
- [Pydantic AI test modelleri](https://pydantic.dev/docs/ai/guides/testing/)
- [OpenAI uyumlu sağlayıcılar](https://pydantic.dev/docs/ai/models/openai/)
- [Ollama API uyumluluğu](https://docs.ollama.com/api/openai-compatibility)
- [OpenRouter başlangıç](https://openrouter.ai/docs/quickstart)
