# Native ajan servisi

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
`storage.py` framework'ten bağımsız SQLite görev/run/sonuç kayıtlarını;
`task_service.py` başlatma, süreç kilidi, iptal/hata sonlandırma ve açık kurtarmayı
yönetir. `engines/context.py` geçmiş seçimi ve her istek öncesi bağlam korumasıdır.
`worker.py` kalıcı kuyruğu sürekli işler; `worker_cli.py` sinyal/kapanış sınırıdır.
`mcp_server.py` aynı depoyu kullanan yerel yönetim yüzeyi, `mcp_client.py` izin
seçimi ve SDK bağımsız araç sözleşmesi, `mcp_transport.py` resmi MCP SDK bağlantısı,
`engines/mcp_tools.py` Pydantic AI araç köprüsüdür. Protokol ve saf metin aracı
yeniden yazılmaz; mevcut SDK ve araç fonksiyonu kullanılır.

Görev kuyruğu ve çalışma/sonuç kayıtları SQLite'tadır. Tek supervisor, kendi
eşzamanlılık sınırıyla çalışır; manuel `run` ayrı süreçtir. `tasks add` ve MCP
`submit_task` yalnız sıraya alır. Worker ömrü sürekli süreç ömrüdür; işletim
sistemi otomatik başlangıç kaydı kurulmaz. Model metni doğrulanmış görev başarısı anlamına gelmez.
Framework iç yapısı kalıcı run şeması olarak kullanılmaz.

## ADR-001 — Prototip kararı

Pydantic AI 2.64.0 ile başlanmıştır. Yalnız OpenAI uyumlu sağlayıcı ekini
içeren slim paket ve MCP Python SDK kurulmuştur. LangGraph'a karşı hız/kalite/token üstünlüğü
iddiası yoktur. Ölçümlü karşılaştırma yapılmadan Faz 0 tamamlanmış sayılmaz.

## Sıradaki geliştirme

1. Aynı model, araç ve görevlerle karşılaştırma protokolü; ayrı ve açık model
   bütçesiyle ölçüm. Bu adımdaki sahte model testleri kalite benchmark'ı değildir.
2. Kullanıcı tarafından verilen workspace'te sınırlandırılmış okuma aracı,
   capability bildirimi ve bağımsız çıktı doğrulayıcısı; shell eklemeden başlama.
3. İşletim sistemi servis kurulumu, daha kapsamlı gözlemlenebilirlik ve kontrollü
   bağlantı havuzu/katalog önbelleği için ölçümler.
4. Stdio/loopback HTTP yönetim MCP'sini uygulama OAuth'u ve çok kullanıcılı
   ekip yetkileriyle genişletme. Görev başına bağlantı seçimi uygulanmıştır;
   [dış yönetim rehberi](external-management.md) mevcut bağlantıları açıklar.

[Sürekli servis ve MCP rehberi](service-and-mcp.md) tamamlanan worker, iptal,
araç izinleri/seçimi ve yönetim yüzeyinin davranışını açıklar. Sert sandbox,
takvim tabanlı scheduler ve çok ajan orkestrasyonu henüz uygulanmadı.

V1 veri kökü açılmaz; kişisel ajanlar kopyalanmaz. İlk örnek ajan bu paketin
`examples/` dosyalarındadır. Geri dönüş için eski runtime bağımsız kalır.

## Kaynaklar

- [Pydantic AI ajanları](https://pydantic.dev/docs/ai/core-concepts/agent/)
- [Pydantic AI test modelleri](https://pydantic.dev/docs/ai/guides/testing/)
- [OpenAI uyumlu sağlayıcılar](https://pydantic.dev/docs/ai/models/openai/)
- [Ollama API uyumluluğu](https://docs.ollama.com/api/openai-compatibility)
- [OpenRouter başlangıç](https://openrouter.ai/docs/quickstart)
