# Görev yönetimi

Görevlerin doğruluk kaynağı SQLite veritabanıdır. `tasks` komutları aynı kaydı
yönetir; Markdown yalnız okunabilir dışa aktarma ve elle hazırlanan planları içe
aktarma görünümüdür. Dışa aktarılan dosyayı düzenleyip içe aktarmak mevcut
görevleri güncellemez, yeni görevler oluşturur.

## Görev alanları

Her görev şu alanları taşır:

- `title`: kısa başlık; verilmezse görev metninin ilk satırı kullanılır.
- `description`: isteğe bağlı açıklama.
- `priority`: `-1000..1000`; büyük değer önce çalışır, eşitlikte eski görev önce.
- `enabled`: devre dışı görev kuyrukta bekler ama worker almaz.
- `depends_on`: tamamlanmış olması gereken görev kimlikleri.
- `verification`: görevle dondurulan bağımsız doğrulama planı (A06).
- `definition_revision`: her tanım değişikliğinde artan sürüm.
- `archived_at`: arşivlenmiş görevler varsayılan listede ve kuyrukta görünmez.

`agent`, `connection` ve workspace izinleri görev kuyruğa girerken dondurulur.
Bunları değiştirmek için yeni görev oluşturun; çalışan görevin tanımı hiçbir
zaman değiştirilemez.

## Görev ekleme

```powershell
.\.venv\Scripts\ragents.exe tasks add --agent arastirmaci `
  --title "Rapor" --description "Haftalık özet" --priority 5 `
  "Raporu hazırla"

.\.venv\Scripts\ragents.exe tasks add --agent arastirmaci `
  --depends-on GOREV_KIMLIGI --priority 3 "Raporu gözden geçir"
```

`--disabled` görevi devre dışı kaydeder. `--key` aynı içerikle tekrar eklemeyi
önler; aynı anahtar farklı başlık, öncelik, bağımlılık veya tanımla
kullanılamaz.

## Kuyruk seçimi ve bağımlılıklar

Worker yalnız şu koşulları sağlayan görevleri alır:

1. `status = queued`, `enabled = 1` ve arşivlenmemiş.
2. Tüm bağımlılıkları `succeeded` durumunda.

Sıra `priority DESC, created_at ASC, id ASC` biçimindedir. Bağımlılığı
tamamlanmamış görev kuyrukta kalır; `tasks run` ile de zorla çalıştırılamaz.
Bağımlılık grafiği döngü oluşturamaz; kendine bağımlılık ve var olmayan görev
kimliği reddedilir. Bir görev en fazla 32 bağımlılık taşır.

## Düzenleme ve revizyonlar

```powershell
.\.venv\Scripts\ragents.exe tasks edit GOREV_KIMLIGI `
  --title "Yeni başlık" --priority 9 --enable
.\.venv\Scripts\ragents.exe tasks edit GOREV_KIMLIGI `
  --depends-on BASKA_GOREV --clear-verification
.\.venv\Scripts\ragents.exe tasks revisions GOREV_KIMLIGI
```

- `queued`, `failed`, `cancelled` ve `interrupted` görevler düzenlenebilir.
- `running` ve `succeeded` görevler düzenlenemez; arşivlenmiş görev önce geri
  yüklenmelidir.
- Her değişiklik `definition_revision` değerini artırır ve önceki tanım
  `task_revisions` tablosunda saklanır. Değişiklik yoksa revizyon artmaz.
- `--depends-on` bağımlılık listesini **değiştirir**, eklemez. Tümünü kaldırmak
  için `--clear-dependencies` kullanın.
- `--verify-plan` planı değiştirir; `--clear-verification` kaldırır.
- Düzenleme görevi otomatik yeniden sıraya almaz; başarısız görev için ayrıca
  `tasks retry` gerekir.

## İptal, arşiv ve geri yükleme

```powershell
.\.venv\Scripts\ragents.exe tasks cancel GOREV_KIMLIGI
.\.venv\Scripts\ragents.exe tasks archive GOREV_KIMLIGI
.\.venv\Scripts\ragents.exe tasks list --archived-only
.\.venv\Scripts\ragents.exe tasks restore GOREV_KIMLIGI
```

- `cancel` sıradaki görevi hemen `cancelled` yapar; çalışan göreve işbirliğine
  dayalı iptal isteği gönderir.
- Yalnız terminal durumdaki (`succeeded`, `failed`, `cancelled`, `interrupted`)
  görevler arşivlenir. Sıradaki/çalışan görev önce iptal edilmelidir.
- Arşivlenmiş görev varsayılan `tasks list` çıktısında ve kuyrukta görünmez;
  düzenlenemez, iptal edilemez ve yeniden denenemez. `restore` bunu geri alır.

## Markdown dışa aktarma

```powershell
.\.venv\Scripts\ragents.exe tasks export --output gorevler.md
```

Dosya, en eski görev önce olacak biçimde en fazla 1000 görevi (arşivlenmişler
dahil) içerir. Her blok YAML ön bilgisi ve görev metninden oluşur:

```markdown
<!-- ragents:task:start -->
---
title: Temel
agent: arastirmaci
connection: primary
description: İlk adım
priority: 3
enabled: true
depends_on: []
---
Temel analizi yaz.
<!-- ragents:task:end -->
```

## Markdown içe aktarma

```powershell
.\.venv\Scripts\ragents.exe tasks import --root local-profile --file gorevler.md
```

İçe aktarma:

- Her blok için **yeni** görev oluşturur; mevcut görevleri kimlikle eşleştirmez.
- Başlıklar dosya içinde benzersiz olmalıdır; bağımlılıklar başlıkla çözülür.
- Bağımlılıklar aynı dosyada bulunmalıdır; döngü, yinelenen başlık, bilinmeyen
  alan ve geçersiz doğrulama planı reddedilir.
- Ajan profilleri önce doğrulanır. Yine de içe aktarma tek işlemde atomik
  değildir; sonraki blok hata verirse önceki bloklar eklenmiş kalabilir.
- Durum, çalışma geçmişi, artifact ve sonuçlar aktarılmaz; yalnız tanım ve
  metadata aktarılır.

## MCP

`submit_task` isteğe bağlı `title`, `description`, `priority` ve `depends_on`
alanlarını kabul eder. `get_task` görev metadata'sını, bağımlılıkları,
`blocked_by` listesini ve `ready` durumunu döndürür. MCP bağlantılarında
workspace olmadığı için dosya/komut/tarayıcı doğrulaması hâlâ yalnız CLI ile
tanımlanır.

## Sınırlar

- Bağımlılıklar aynı veritabanındaki görevlerle sınırlıdır; başka DB'ye veya
  ajana çapraz bağlantı kurulmaz.
- Görev silinmez; arşivleme geri alınabilir bir gizleme işlemidir.
- Tanım revizyonları ham görev metnini ve snapshot ayarlarını saklar; bunlar
  kullanıcı verisidir, telemetriye yazılmaz.
- Markdown dışa aktarma sıralama/bağımlılık görünümüdür; iki yönlü eşitleme
  aracı değildir.
