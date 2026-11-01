# Kalıcı ajan kataloğu

Bu belge A01–A03 kapsamını anlatır: ajan profillerinin kalıcı saklanması,
oluşturma/güncelleme/arşivleme, talimat dosyaları, proje bilgisi, skill seçimi
ve çalışma alanı ataması. Talimat birleştirme ayrıntıları
[talimatlar ve skill'ler](instructions-and-skills.md); yol güvenliği, okuma
araçları ve artifact kaydı
[çalışma alanı ve artifact'lar](workspaces-and-artifacts.md) belgesindedir.
Komut örnekleri Windows PowerShell/`.exe` biçimindedir; macOS/Linux karşılıkları
[platform desteğindedir](platform-support.md).

## Dizin düzeni

Varsayılan kök `local-profile/`; her ajan kendi bağımsız dizininde yaşar:

```text
local-profile/
  agents/
    <ajan-id>/
      agent.yaml          # bağlantı, bütçe, izinler; ajanın kendi kendine yeterli profili
      instructions.md     # ajan talimatı (V1: SOUL)
      project.md          # isteğe bağlı proje bilgisi
      rules.md            # isteğe bağlı kalıcı kurallar
      skills/
        <skill-id>/
          SKILL.md        # isteğe bağlı, seçilebilir uzmanlık talimatı
  workspaces/
    <ajan-id>/            # varsayılan çalışma alanı
  data/
    ragents.db            # görev/çalışma/sonuç/artifact kayıtları
```

`agent.yaml` içinde `id` ile dizin adı aynı olmalıdır. Aynı kimlikle ikinci ajan
oluşturulamaz. Profil dosyaları sembolik bağlantı olamaz; katalog dizini dışına
çıkan yollar reddedilir.

Örnek `agent.yaml`:

```yaml
schema_version: 3
id: arastirmaci
name: Araştırmacı
status: active
connection: primary
connections:
  primary:
    provider: openrouter
    model: <model-kimliği>
    api_key_env: OPENROUTER_API_KEY
mcp_servers: {}
mcp_tools: []
tools: []
workspace: workspaces/arastirmaci
skills: []
default_skills: []
budget:
  request_limit: 4
  tool_calls_limit: 2
  output_tokens_limit: 1024
context:
  max_request_chars: 24000
  max_history_turns: 4
```

API anahtarı değeri YAML'ye yazılmaz; yalnız ortam değişkeni adı tutulur.
Bağlantılar ajan profiline ait olduğu için bir ajanın modelini değiştirmek diğer
ajanları etkilemez.

## Komutlar

```powershell
# Yeni ajan; model çağrısı yapmaz.
ragents agents create --id arastirmaci --name "Araştırmacı" `
  --connection primary --provider openrouter --model <model-kimliği> `
  --instructions "Türkçe, kısa ve açık yanıt ver."

# Mevcut ragents.yaml dosyasından bağlantı, talimat ve bütçe aktar.
ragents agents create --from-config local-profile/ragents.yaml

ragents agents list
ragents agents list --all
ragents agents show arastirmaci
ragents agents update arastirmaci --name "Kıdemli Araştırmacı"
ragents agents update arastirmaci --provider openrouter --model <yeni-model>
ragents agents update arastirmaci --add-tool text_stats --if-revision <revizyon>
ragents agents update arastirmaci --add-tool list_files --add-tool search_text --add-tool read_file
ragents agents update arastirmaci --workspace C:\Projeler\OrnekProje
ragents agents update arastirmaci --default-workspace
ragents agents update arastirmaci --project-file project.md
ragents agents update arastirmaci --add-skill arastirma --add-default-skill arastirma
ragents agents disable arastirmaci
ragents agents enable arastirmaci
ragents agents archive arastirmaci
ragents agents restore arastirmaci
```

`--root` varsayılan olarak `local-profile`; başka bir dizin için komutun başına
ekleyin:

```powershell
ragents agents --root C:\AjansProfilleri list
```

## Durumlar

| Durum | Yeni görev | Listede | Geçmiş |
| --- | --- | --- | --- |
| `active` | Alır | Görünür | Korunur |
| `disabled` | Almaz | Görünür | Korunur |
| `archived` | Almaz | Yalnız `--all` ile | Korunur |

`archive` dizini veya görev geçmişini silmez. `restore`, ajanı güvenli varsayılan
olan `disabled` durumuna getirir; yeniden görev alması için `enable` gerekir.
Devre dışı bırakma/arşivleme yalnız yeni görevleri engeller; daha önce kuyruğa
girmiş görevler kendi snapshot'larıyla çalışmaya devam eder.

## Çalışma alanı

Her ajanın `agent.yaml` içinde bir `workspace` yolu vardır. `agents create`
sırasında verilmezse `workspaces/<ajan-id>` oluşturulur; `--workspace` ile
verilen özel dizin önceden mevcut olmalıdır. Workspace; `agents/`, `data/`,
`ragents.yaml`, `RAGENTS_HOME` ve başka ajanların çalışma alanlarıyla
çakışamaz. Görev kuyruğa girerken workspace yolu da dondurulur.

Salt okunur `list_files`, `search_text` ve `read_file` araçları yalnız açık
`tools` izniyle kullanılabilir. Yol kaçışı, symlink/junction ve boyut sınırları
[çalışma alanı ve artifact'lar](workspaces-and-artifacts.md) belgesindedir.

## Talimatlar, proje ve skill'ler

`instructions.md` zorunlu; `project.md` ve `rules.md` isteğe bağlıdır. Metinler
şu sırayla birleştirilir:

1. `## Ajan profili` — `instructions.md`
2. `## Proje bilgisi` — `project.md` varsa
3. `## Seçili skill: <ad>` — seçili `SKILL.md` dosyaları
4. `## Kalıcı kurallar` — `rules.md` varsa

Görev metni ayrı kullanıcı mesajıdır; talimat metnine kopyalanmaz. Toplam
talimat `context.max_instruction_chars` ile sınırlıdır (varsayılan 16.000);
aşım sessizce kırpılmaz. Ayrıntılı sözleşme, skill frontmatter'ı, seçim kuralları
ve çakışma önceliği için [talimatlar ve skill'ler](instructions-and-skills.md)
belgesine bakın.

Revizyon, davranışı etkileyen içeriğin SHA-256 özetidir: `agent.yaml` (durum
alanı hariç), talimat/proje/kural dosyaları ve izinli skill dosyaları. `agents
show` bu revizyonu gösterir. `update --if-revision` eski revizyonla yazmayı
reddeder.

Görev kuyruğa girerken o anki derlenmiş talimat ve `InstructionSnapshot` görev
tanımına kopyalanır. Sonradan yapılan profil veya skill düzenlemesi kuyruktaki
veya çalışan görevi değiştirmez; `tasks show` snapshot'ı gösterir.

## Görev gönderme

```powershell
ragents tasks --root local-profile add --agent arastirmaci --key arastirma-1 "Kısa görev"
ragents tasks --root local-profile add --agent arastirmaci --skill dogrulama "Doğrulama görevi"
ragents tasks --root local-profile list
ragents tasks --root local-profile show <görev-id>
ragents run --root local-profile --agent arastirmaci --key arastirma-1 "Kısa görev"
```

`tasks add` yalnız kaydeder; model çağrısı yapmaz. `run` gerçek model isteği
gönderebilir. `--connection`, ajanın kendi bağlantılarından birini seçer.
`--db` verilmezse veritabanı `--root` altında `data/ragents.db` olur; bu,
`setup` ile üretilen profil kuyruğuyla aynı yoldur. Katalog dışı `--config`
kullanımında varsayılan yine çalışma dizinindeki `data/ragents.db` olur.

Workspace yolu ve okuma araçları görev kuyruğa girerken dondurulur. Ajanın
workspace'i sonradan değiştirilirse eski görev eski yolu kullanmaya devam eder.
Görev sırasında oluşan/değişen dosyalar `tasks show` çıktısındaki `artifacts`
listesinde görev, çalışma ve ajan kimliğiyle görünür. Ayrıntılar
[çalışma alanı ve artifact'lar](workspaces-and-artifacts.md) belgesindedir.

Mevcut tek dosyalı `--config examples/ollama.yaml` yolu korunur; katalog dışında
kalan bu kullanımda ajan durumu ve kalıcı kimlik yönetimi yoktur. Kataloğa geçmek
için `agents create --from-config` kullanın.

## Bu aşamanın sınırları

- Workspace okuma araçları salt okunurdur. A05 ile `write_file`, `apply_patch`
  ve `run_command` eklendi; bunlar görev grant'inde açık `writable_paths` ve
  `commands` ister. Dosya silme aracı yoktur; komutla silme yalnız sandbox
  yazma kapsamı içinde mümkündür.
- Gerçek işletim sistemi sandbox'ı ve sert süreç izolasyonu A04'te eklendi;
  CLI `sandbox run` ve A05 komut aracı bu katmanı kullanır.
- Otomatik skill seçimi yoktur; seçim açık veya `default_skills` ile yapılır
  (otomatik ilgi seçimi A09).
- Yönetim MCP'si henüz katalog ajanlarını listelemez; bu A11 kapsamındadır.
- Katalog, V1 `agent-runtime` dizinini veya veritabanını okumaz/değiştirmez.
