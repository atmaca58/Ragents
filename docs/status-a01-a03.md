# R Agents V2 — A01–A03 sonrası durum raporu

Tarih: 1 Kasım 2026.

## Sonuç

**İlk üç görev (A01, A02, A03) uygulanmış ve çevrimdışı regresyon testleriyle
doğrulanmıştır.** Bu, görev listesindeki ilk geliştirme paketinin tamamlanmasıdır;
ilk üç büyük teslim aşamasının tamamlanması değildir. A04 ve A05 ayrıca
tamamlandı; A07–A13 ve ekip paketi henüz tamamlanmış görünmüyor.

R Agents artık kalıcı ajan profiliyle çalıştırılabilen, talimat/skill dosyaları
olan ve izinli proje dosyalarını okuyabilen bir native ajan servisidir.
V1'deki proje düzenleme, test çalıştırma, takvim ve hafıza işlevlerinin tamamına
veya ajanlar arası ekip orkestrasyonuna henüz ulaşmamıştır.

## Doğrulanan kapsam

| Görev | Durum | Mevcut davranış |
| --- | --- | --- |
| A01 — Kalıcı ajan kataloğu | Uygulanmış | Oluşturma, listeleme, profil/model güncelleme, disable/enable, archive/restore |
| A02 — Talimat sistemi | Uygulanmış | Ayrı talimat/proje/kural/skill dosyaları, deterministik derleme, boyut sınırları ve görev snapshot'ı |
| A03 — Workspace ve dosyalar | Uygulanmış | Workspace atama, izinli listeleme/arama/okuma, yol kontrolleri ve artifact kaydı |
| A04 — Gerçek sandbox | Uygulanmış | Windows AppContainer + Job Object; macOS Seatbelt ve Linux bubblewrap backend'leri; ağ/yazma/süreç/kaynak sınırı |
| A05 — Dosya ve komut | Uygulanmış | Sandbox içinde `write_file`/`apply_patch`, allowlist'li `run_command`, görev izinleri, açık artifact kaydı |
| A06 — Bağımsız doğrulama | Uygulanmış | Dosya, JSON şema, argv tabanlı komut ve Playwright JSON kontrolleri; görevle dondurulan plan ve kanıt kaydı |
| A07 — Görev yönetimi | Uygulanmış | Başlık, açıklama, öncelik, etkinlik, bağımlılık, tanım revizyonu, arşiv ve Markdown dışa/içe aktarma; SQLite doğruluk kaynağı |

Kaynakta `catalog.py`, `agents_cli.py`, `instructions.py`, `workspace.py`,
TaskStore/TaskService entegrasyonları ve MCP/CLI çıktıları incelendi.

### Ajanların yaşam döngüsü

- Her ajanın `local-profile/agents/<id>/agent.yaml` profili vardır.
- Model bağlantısı, bütçe ve araç izinleri ajana özeldir.
- Profil revizyonu tutulur; eski revizyonla güncelleme reddedilebilir.
- Devre dışı/arşivlenmiş ajan yeni görev alamaz. Arşivleme geçmişi silmez;
  restore güvenli varsayılan olarak disabled durumuna döndürür.
- Önceden kuyruğa giren görevler kendi snapshot'larıyla devam eder. Ajanı
  devre dışı bırakmak mevcut görevleri iptal etmez; bunun için görev iptali gerekir.

### Talimatların çalışma şekli

```text
instructions.md → project.md → seçili SKILL.md dosyaları → rules.md
                              + ayrı kullanıcı görev mesajı
```

- Davranış metni katalog YAML'sinde ikinci kez tutulmaz. Eski tek dosyalı
  `--config` yolu uyumluluk için ayrı olarak korunmuştur.
- Görevde açıkça seçilen skill'ler veya profilin `default_skills` listesi yüklenir.
  Otomatik görev ilgisi seçimi henüz yoktur.
- Talimat boyutu sınırı aşılırsa işlem reddedilir; sessiz kırpma yapılmaz.
- Görev kuyruğa girerken derlenmiş metin, kaynak hash'leri ve skill seçimi
  sabitlenir. Sonradan dosya düzenlemek eski görevi değiştirmez.
- Dosyalardaki kurallar model davranışını yönlendirir; araç ve workspace
  yetkilerini genişletemez. İzinler kod tarafından ayrıca uygulanır.
- `project.md` kalıcı proje bağlamıdır; otomatik öğrenme/hafıza güncellemesi değildir.

### Proje okuma ve artifact kaydı

- `list_files`, `search_text`, `read_file` yalnız ajan profilinde izinliyse açılır.
- Workspace dışında yol, Windows özel yolları, symlink/junction ve korumalı
  katalog/veri/kimlik dizinlerine erişim için kontroller vardır.
- Listeleme, arama, dosya okuma ve modele taşınan çıktı sınırlıdır.
- Dosya değişiklikleri görev öncesi/sonrası sınırlı taramayla artifact olarak
  kaydedilebilir; `tasks show` ve MCP `get_task` bu kayıtları gösterebilir.
- Artifact kaydı ajana dosya yazma aracı verildiği anlamına gelmez. Fark taraması
  en iyi çabadır; dosyanın doğru üretildiğini veya kesin olarak ajan tarafından
  değiştirildiğini tek başına kanıtlamaz.
- Bu katman gerçek işletim sistemi sandbox'ı değildir. Yarış durumlarına karşı
  sertleştirme ve süreç/ağ izolasyonu A04 kapsamındadır.

## Bugün kullanılabilen akış

CLI'den kalıcı ajan oluşturma/yönetme → talimat ve skill seçimi → kendi
workspace'inde sınırlı okuma → görev kuyruğu → worker → kalıcı sonuç.

Mevcut model bağlantıları, token/bağlam sınırları, iptal ve kalıcı sonuç
altyapısı korunmuştur. Her sağlayıcının gerçek hesapla canlı doğrulamasının
tamamlandığı anlamına gelmez.

**MCP entegrasyonu sınırı:** Yönetim MCP'si hâlâ açık `--config` kayıtlarını
kullanıyor. `agents/` kataloğunu keşfedip katalog ajanlarını yönetme/görev atama
akışı A11'de tamamlanacak. CLI'de ajan oluşturmak onu mevcut MCP listesine
kendiliğinden eklemiyor. Artifact'in MCP'de görülebilmesi bu eksik entegrasyonu
tamamlamıyor.

## Henüz hazır olmayanlar

| İhtiyaç | Görev |
| --- | --- |
| Cron/zamanlı görev ve programatik servisler | A08 |
| Otomatik ilgili skill seçimi ve doğrulanmış kalıcı ders/hafıza | A09 |
| Ajan/ortak workspace yürütme kilitleri | A10 |
| Katalog ve gelişmiş görev yönetiminin MCP'ye bağlanması | A11 |
| Windows/macOS/Linux otomatik servis kurulumu ve işletim araçları | A12 |
| V1 benzeri günlük kullanım pilotu | A13 |
| Ekip rolleri, görev devri, ortak bütçe ve ekip doğrulaması | B01–B04 |

## Bu incelemede çalıştırılan kontroller

```powershell
.\.venv\Scripts\python -m pytest -q -ra -o addopts=
.\.venv\Scripts\python -m pip check
```

- **168 test geçti, 2 test atlandı; toplam 170 senaryo.** Bu sayı A03
  kesitinin tarihsel kaydıdır; A04–A07 testleri eklendikten sonra güncel
  tam paket **223 geçti, 3 atlandı (226 senaryo)** olmuştur.
- Atlananlar: talimat dosyası ve workspace symlink testleri; Windows sembolik
  bağlantı yetkisi yok. Windows junction ve symlink'li üst dizin testleri geçti.
- Bağımlılık kontrolü: `No broken requirements found.`
- Testler geçici veritabanları ve sahte modeller kullanır; gerçek LLM isteği
  veya kişisel OAuth oturumu kullanılmadı. V1/canlı veritabanı değiştirilmedi.
- macOS/Linux native testleri ve gerçek kasa/servis kanıtı henüz yoktur;
  ayrıntılar [platform desteğinde](platform-support.md).
- Bu rapor aktif worker'ın işletim durumunu, gerçek görev kalitesini, temiz
  makine kurulumunu veya sağlayıcıların canlı erişimini doğrulamaz.
- A01–A03 kaynak incelemesinin yanında platform kurucu/launcher dosyaları ve
  macOS symlink'li üst dizin düzeltmesi uygulandı; canlı DB ve V1 değişmedi.

## Sonraki geliştirme

Sırada **A08**: takvim/zamanlanmış görevler ve programatik servisler; ardından
A10 eşzamanlılık kuralları, hafıza, MCP katalog entegrasyonu ve servis pilotu.
Ekip iş birliği bu temel üzerinde B01–B04 ile tamamlanacak.

Kullanım: [ajan kataloğu](agents-and-workspaces.md),
[talimatlar ve skill'ler](instructions-and-skills.md),
[workspace ve artifact'lar](workspaces-and-artifacts.md),
[görev doğrulama](task-verification.md),
[görev yönetimi](task-management.md).
Plan: [görev listesi](readiness-backlog.md).
