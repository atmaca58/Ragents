# Sürümleme

Kısa sürüm adları kullanılır. Her commit için sürüm yayımlanmaz; kullanıcıya
dağıtılacak değişiklikler bir araya geldiğinde yeni sürüm çıkarılır.

| Tür | Örnek | Kullanım |
| --- | --- | --- |
| Geliştirme | `0.2.0-dev.3` → `0.2.0-dev.4` | Kararlı kabul kapıları henüz tamamlanmamış paketler |
| Düzeltme | `0.2.0` → `0.2.1` | Geriye uyumlu hata düzeltmesi |
| Özellik | `0.2.1` → `0.3.0` | Yeni yetenekler; 0.x döneminde uyumluluk değişebilir |
| Ana sürüm | `1.0.0` → `2.0.0` | 1.0 sonrasında geriye uyumsuz değişiklik |

Python paketinde karşılık `0.2.0.dev3`, Git etiketi `v0.2.0-dev.3` olur.
Tarih sürüm adına eklenmez. Etiketler ve yayımlanmış paketler değiştirilmez;
aynı sürüm yeniden üretilip üzerine yüklenmez. Kabulden sonra değişen içerik
yeni sürüm gerektirir. Ön sürümler GitHub'da prerelease olarak yayımlanır.

Sürüm çıkarırken `src/ragents/__init__.py`, `pyproject.toml` ve Windows
kurucu varsayılanları birlikte güncellenir. `prepare_online_release.py`
uygulama sürümünden etiketi ve paket manifestini üretir; bootstrap içindeki
etiket ve manifest SHA-256 değerini aynı varlıklara bağlar.

Her sürümün kısa değişiklik listesi `CHANGELOG.md` içinde tutulur. Kurulum
belgeleri o sürümün sabit etiketini gösterir. Geliştirme ana dalı hazır sürüm
olarak sunulmaz. Ürün kabul durumu sürüm numarasından bağımsızdır.
