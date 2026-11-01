# Çalışma alanı, sınırlı okuma ve artifact'lar

Bu belge A03 kapsamını anlatır: ajanın çalışma alanı (workspace), dosya
araçları, yol güvenliği ve görevle ilişkili artifact kaydı. A03 kesitinde ajan
proje dosyalarını değiştiremiyordu; gerçek sandbox A04'te, izinli yazma/yama ve
argv tabanlı komut araçları A05'te eklendi. Ayrıntılar
[dosya ve komut](tools-and-execution.md) belgesindedir. Komut örnekleri Windows
PowerShell/`.exe` biçimindedir; macOS/Linux karşılıkları
[platform desteğindedir](platform-support.md).

## 1. Workspace ataması

Her katalog ajanının bir çalışma alanı vardır. Varsayılan yol katalog köküne
göredir:

```text
local-profile/
  agents/<ajan-id>/          # profil, talimat ve skill dosyaları
  workspaces/<ajan-id>/      # varsayılan çalışma alanı; create sırasında oluşturulur
  data/ragents.db
```

```powershell
# Varsayılan workspace ile ajan oluştur
ragents agents create --id arastirmaci --name "Araştırmacı" `
  --provider ollama --model qwen3:8b

# Mevcut bir proje dizinini açıkça ata
ragents agents create --id gelistirici --name "Geliştirici" `
  --provider ollama --model qwen3:8b `
  --workspace C:\Projeler\OrnekProje

# Var olan ajanın workspace'ini değiştir
ragents agents update gelistirici --workspace C:\Projeler\BaskaProje

# Varsayılan workspaces/<ajan-id> yoluna dön
ragents agents update gelistirici --default-workspace
```

- `--workspace` ile verilen özel dizin **önceden var olmalıdır**; güvenlik için
  otomatik oluşturulmaz.
- Yalnız varsayılan `workspaces/<ajan-id>` dizini `agents create` sırasında
  oluşturulur.
- Workspace yolu `agent.yaml` içinde `workspace` alanında saklanır. Göreli
  değerler katalog köküne göre, mutlak değerler doğrudan çözümlenir.
- `agents show` ve `agents list`, çözümlenmiş yolu ve dizinin hazır olup
  olmadığını (`workspace_ready`) gösterir.
- Görev kuyruğa girerken workspace yolu görev tanımına dondurulur. Sonradan
  yapılan `agents update --workspace` kuyruktaki görevi değiştirmez.
- Workspace dizini silinirse ajan yeni görev alamaz; açık hata verilir.
- Workspace grant'i idempotency fingerprint'ine dahildir. A03 öncesinde aynı
  anahtarla kaydedilmiş katalog görevi, yeni grant nedeniyle farklı içerik
  sayılır; yeni bir anahtar kullanılmalıdır.

### Yasak konumlar

Workspace aşağıdaki konumlarla çakışamaz:

- `local-profile/agents/` (ajan profilleri ve skill dosyaları)
- `local-profile/data/` (görev veritabanı ve kilitler)
- `local-profile/ragents.yaml`
- `RAGENTS_HOME` altındaki OAuth/kimlik dizini
- Başka bir ajanın workspace'i veya onun üst/alt dizini
- Sürücü kökü (`C:\` gibi)

Bu kontroller `agents create`, `agents update` ve görev kuyruğa girerken
uygulanır. A10'daki ortak workspace desteği geldiğinde workspace çakışması
bilinçli olarak ayrı bir eşzamanlılık politikasıyla gevşetilecektir.

## 2. Okuma araçları

Workspace erişimi tek başına modele araç vermez. Araçlar mevcut `tools`
izin listesine açıkça eklenir. Tek dosyalı `--config` uyumluluk yolunda
workspace grant'i olmadığı için bu araçlar seçilirse görev açık hata verir.

```powershell
ragents agents update arastirmaci `
  --add-tool list_files --add-tool search_text --add-tool read_file
```

| Araç | Parametreler | Sınır |
| --- | --- | --- |
| `list_files` | `path="."`, `depth=1`, `max_entries=100` | 200 giriş, derinlik 3 |
| `search_text` | `query`, `path="."`, `case_sensitive=false`, `max_results=50` | 50 eşleşme, 1.000 dosya, dosya başına 1 MiB |
| `read_file` | `path`, `start_line=1`, `max_lines=200` | 64 KiB, 200 satır, satır başına 400 karakter |

- `search_text` birebir metin arar; düzenli ifade (regex) çalıştırmaz.
- `read_file` yalnız UTF-8 metin okur. NUL baytı içeren ikili dosyalar reddedilir.
- `list_files` ve `search_text` symlink/junction girdilerini takip etmez.
- `.git`, `.hg`, `.svn`, `.venv`, `node_modules` ve `__pycache__` dizinleri
  arama ve artifact taramasında atlanır. Bu dizinlerdeki tek bir dosya yine
  açık göreli yolla `read_file` ile okunabilir.
- Sonuçlarda `truncated: true` varsa sınır nedeniyle daha fazla girdi
  döndürülmemiştir. Sessiz kırpma yerine bu alan kullanılır.
- `context.max_tool_output_chars` ayrıca model bağlamına giren araç sonucunu
  sınırlar; bu iki sınır birbirinin yerine geçmez.

### Yol güvenliği

- Yalnız workspace köküne göre göreli yollar kabul edilir.
- Absolute yol, sürücü harfi, UNC yolu, `..`, NUL, Windows ADS (`dosya:akış`)
  ve `NUL`/`CON` gibi cihaz adları reddedilir.
- Workspace kökü kanonikleştirilir; macOS `/var` gibi üst dizin symlink'leri
  çözümlenir. Kökün kendisi symlink/junction ise reddedilir; workspace içindeki
  her yol bileşeni ayrıca denetlenir ve çözümlenen hedefin kök içinde kaldığı
  doğrulanır.
- Korumalı dizinlere veya kimlik dosyalarına çözülen yollar reddedilir.
- Yol hatası model çağrısını durdurur ve çalışma `workspace` hata koduyla
  başarısız olur; dışarıdaki içerik modele döndürülmez.

Bu kontroller uygulama düzeyindedir. İşletim sistemi düzeyinde yarış (TOCTOU)
sertleştirmesi, süreç izolasyonu ve kaynak sınırları A04 kapsamındadır.

## 3. Artifact kaydı

Artifact, bir görev çalışırken workspace içinde oluşan veya değişen düzenli
dosyadır. A03 kesitinde ajanın kendi yazma aracı yoktu; A05 ile `write_file` ve
`apply_patch` başarılı sonuçlarını açıkça `file_tool` üreticisiyle kaydeder.
Fark taraması MCP/dış süreç kaynaklı değişiklikleri ve testlerdeki sahte
üreticiyi `workspace_scan` olarak izlemeye devam eder.

Akış:

1. Görev başlamadan önce workspace'in sınırlı bir dosya özeti alınır
   (göreli yol, boyut, değişiklik zamanı).
2. Çalışma başarıyla bitince yeni veya değişmiş dosyalar hesaplanır.
3. Her dosya için göreli yol, boyut ve mümkünse SHA-256 özeti kaydedilir.
4. Kayıt `artifacts` tablosunda `task_id`, `run_id`, `agent_id` ve
   `producer="workspace_scan"` ile tutulur.

```text
artifacts
  id, task_id, run_id, agent_id, path,
  sha256, size_bytes, producer, created_at
```

- `path` her zaman workspace'e göre göreli ve POSIX biçimindedir; mutlak yol
  veritabanına yazılmaz.
- Aynı çalışmada aynı yol için tek kayıt tutulur.
- 32 MiB'den büyük dosyalarda `sha256` `null` olabilir; yol ve boyut yine
  kaydedilir.
- Tarama en fazla 20.000 dosya, 5.000 dizin ve çalışma başına 200 artifact ile
  sınırlıdır.
- Silinen dosyalar artifact sayılmaz.
- Fark taraması “en iyi çaba”dır; çok büyük workspace'lerde veya aynı
  boyut/zaman damgasıyla değişen dosyalarda eksik kalabilir. Aynı workspace'te
  eşzamanlı görevler artifact farkını karıştırabilir; bu eşzamanlılık A10'a
  aittir. A05 yazma araçları explicit `file_tool` kaydı yapar; fark taraması
  diğer değişiklikler için yedek yoldur.

Görev çıktısında:

```powershell
ragents tasks show GOREV_KIMLIGI
```

`artifacts` listesi yol, boyut, SHA-256, ajan ve çalışma kimliğini gösterir;
`workspace` alanı görevin dondurulmuş grant'ini, `instruction` alanı talimat
snapshot'ını gösterir. Yönetim MCP'sindeki `get_task` da aynı artifact listesini
döndürür.

## 4. A03 sınırları ve A05 sonrası durum

- A03 kesitinde ajan workspace'e yazamıyor, dosya silemiyor, patch
  uygulayamıyor veya komut çalıştıramıyordu.
- A04 gerçek sandbox'ı, süreç/ağ izolasyonunu ve sert iptali ekledi. A05 ise
  `write_file`, `apply_patch` ve `run_command` araçlarını görev bazlı
  `writable_paths`/`commands` izinleriyle ekledi. Ayrıntılar
  [dosya ve komut](tools-and-execution.md) belgesindedir.
- Yazma araçları başarılı sonucu `producer=file_tool` ile açıkça kaydeder;
  fark taraması diğer değişiklikleri `producer=workspace_scan` olarak ekler.
- Bağımsız çıktı doğrulaması A06'da eklendi; bir komutun çalışması veya modelin
  "tamamlandı" demesi görevin doğrulanmış başarısı değildir. Plan ve kanıt
  kaydı [görev doğrulamada](task-verification.md) açıklanır.
- Workspace'ler arası paylaşım ve eşzamanlılık A10'a aittir.
- Katalog, V1 `agent-runtime` dizinini veya veritabanını okumaz/değiştirmez.
