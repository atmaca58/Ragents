# Talimatlar, proje bilgisi ve skill'ler

Bu belge A02 kapsamını anlatır: ajan davranışının dosya tabanlı tanımı, tek
talimat derleyicisi, skill seçimi, boyut sınırları ve görev snapshot'ı.
Komut örnekleri Windows PowerShell/`.exe` biçimindedir; macOS/Linux karşılıkları
[platform desteğindedir](platform-support.md).

## Tek kaynak: dosyalar

Ajan davranışı YAML içine gömülmez. `agent.yaml` yalnız meta veri, bağlantı,
bütçe ve izinleri tutar; talimat metinleri ayrı dosyalardadır. Aynı talimat iki
yerde bağımsız yönetilmez. Bu kural katalog profilleri içindir; tek dosyalı
`--config` uyumluluk yolu kendi `agent.instructions` alanını kullanmaya devam
eder.

| Dosya | Rol | V1 karşılığı |
| --- | --- | --- |
| `instructions.md` | Ajan profili/kişiliği; zorunlu | `SOUL.md` |
| `project.md` | Proje bilgisi; opsiyonel | `proje.md` |
| `rules.md` | Kalıcı kurallar; opsiyonel | `kurallar.md` |
| `skills/<id>/SKILL.md` | Seçilebilir uzmanlık talimatı | skill dosyaları |

```text
local-profile/agents/<id>/
  agent.yaml
  instructions.md
  project.md
  rules.md
  skills/
    arastirma/
      SKILL.md
```

`agent.yaml` içinde yalnız skill seçim listeleri bulunur:

```yaml
skills:
  - arastirma
  - dogrulama
default_skills:
  - arastirma
```

- `skills`, izin verilen katalogdur.
- `default_skills`, bunun alt kümesidir ve görev özel seçim yapmazsa yüklenir.
- Boş `default_skills` hiçbir skill'in otomatik yüklenmemesi demektir.
- Skill dosyası oluşturulmadan `--add-skill` kullanılamaz.

## Birleştirme sırası

Derleyici metni deterministik olarak şu sırayla üretir:

1. `## Ajan profili` — `instructions.md`
2. `## Proje bilgisi` — `project.md`
3. `## Seçili skill: <ad>` — her seçili `SKILL.md`
4. `## Kalıcı kurallar` — `rules.md`

Görev metni (`prompt`) ayrı kullanıcı mesajıdır; talimat metnine kopyalanmaz.
Böylece görev talimatı iki kez modele gönderilmez.

### Çakışma önceliği

- Kodla uygulanan araç izinleri, MCP izinleri, bütçe ve workspace sınırları
  **her metinden üstündür**. Skill veya kural metni yeni araç açamaz.
- Metin içinde çakışma varsa kalıcı kurallar profil/proje/skill metninden
  üstündür.
- Görev istemi görevin kapsamını belirler; izinleri genişletemez.

## Skill dosyası

```markdown
---
name: Kaynaklı araştırma
description: Kaynak toplama ve doğrulama adımları
keywords: [araştırma, kaynak]
---

1. Kaynakları topla.
2. Her iddiayı kaynakla eşleştir.
```

- Skill kimliği dizin adıdır: `[a-z0-9][a-z0-9-]{0,31}`.
- Frontmatter opsiyoneldir; varsa yalnız `name`, `description`, `keywords`
  alanları kabul edilir. Bilinmeyen alan yazım hatası sayılır ve reddedilir.
- `name` verilmezse dizin kimliği kullanılır.
- Gövde boş olamaz.
- Skill dosyaları sembolik bağlantı olamaz ve ajan dizini dışına çıkamaz.

## Seçim kuralları

```powershell
# Skill dosyasını profile bağla
ragents agents update arastirmaci --add-skill arastirma

# Görev seçim yapmazsa yüklenecek skill
ragents agents update arastirmaci --add-default-skill arastirma

# Tek görev için açık seçim; varsayılanların yerine geçer
ragents tasks --root local-profile add --agent arastirmaci `
  --skill dogrulama "Görevi doğrula"

ragents run --root local-profile --agent arastirmaci `
  --skill arastirma "Görevi araştır"
```

- Açık `--skill` seçimi `default_skills` yerine geçer; eklemeli değildir.
- Seçilen her skill hem `skills` kataloğunda hem diskte bulunmalıdır.
- Otomatik ilgi/anahtar kelime seçimi A09'a aittir; bu aşamada katalogdaki tüm
  skill'ler modele gönderilmez.

## Boyut sınırları

| Bölüm | Sınır |
| --- | --- |
| `instructions.md` | 8.000 karakter |
| `project.md` | 4.000 karakter |
| `rules.md` | 4.000 karakter |
| Her skill gövdesi | 4.000 karakter |
| Toplam skill metni | 8.000 karakter |
| Derlenmiş toplam | `context.max_instruction_chars` (varsayılan 16.000) |

Sınır aşımı sessizce kırpılmaz; hangi bölümün aştığını söyleyen Türkçe hata
verilir. Görev kuyruğa girmez veya profil güncellemesi yazılmaz.

## Revizyon ve görev snapshot'ı

- Katalog revizyonu, `agent.yaml` (durum hariç), `instructions.md`,
  `project.md`, `rules.md` ve izinli skill dosyalarının içerik özetidir.
  `agents show` bu revizyonu gösterir.
- Görev kuyruğa girerken derlenmiş metin ve `InstructionSnapshot` görev tanımına
  kopyalanır. Snapshot; metin revizyonu, toplam karakter, kaynak dosya hash'leri
  ve seçili skill kimliklerini taşır.
- `tasks show`, görevin talimat snapshot'ını gösterir.
- Görev kuyruğa girdikten sonra dosya düzenlenirse eski görev değişmez; yeni
  görev yeni metni kullanır.
- Aynı idempotency anahtarı, farklı derlenmiş metinle kullanılamaz. Snapshot
  meta verisi anahtar karşılaştırmasını tek başına değiştirmez.

## Kendini değiştirme koruması

- Bu aşamada ajana profil dosyalarına yazan bir araç verilmez.
- Derleyici yalnız okuma yapar; `instructions.md`, `project.md`, `rules.md` ve
  `SKILL.md` dosyalarını değiştirmez.
- Talimat metni araç listesini değiştiremez; araçlar `agent.yaml` içindeki
  `tools` ve `mcp_tools` izinlerinden gelir.
- Workspace okuma araçları katalog `agents/`, `data/` ile kimlik dizinlerini
  okuyamaz. A05 yazma araçları da bu korumalı yolları ve workspace dışını
  reddeder; profil dosyalarını değiştiren bir araç yoktur.

## A02 sınırları

- Otomatik skill seçimi (A09) yoktur.
- Workspace ataması ve salt okunur dosya araçları A03'te eklenmiştir; ayrıntılar
  [çalışma alanı ve artifact'larda](workspaces-and-artifacts.md).
- A02 kesitinde gerçek sandbox yoktu; A04 ayrı sandbox katmanını, A05 ise
  izinli dosya yazma/yama ve argv tabanlı komut araçlarını ekledi. Ayrıntılar
  [dosya ve komut](tools-and-execution.md) belgesindedir. Bağımsız doğrulama
  (A06) [görev doğrulamada](task-verification.md) açıklanır.
- Yönetim MCP'sinden katalog/skill düzenleme (A11) yoktur.
