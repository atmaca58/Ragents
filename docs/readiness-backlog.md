# R Agents V2 — Günlük kullanım ve ajan ekipleri görev listesi

**Güncel teslim kararı:** İlk tamamlanmış ürün Windows 11 x64'tür;
macOS/Linux deneysel kalır. Önceki üç platform şartını ilk yayında zorunlu
tutan ifadelerin yerini [ürün teslim sözleşmesi](product-delivery.md) alır.
Uygulanan yeni takvim, hafıza, kilit, profil ve MCP davranışları ile açık
ürün kapıları [uygulama kaydındadır](windows-product-progress.md).

Tarih: 1 Kasım 2026. Bu liste geliştirme planıdır; işaretlenmemiş özellikler
henüz uygulanmış sayılmaz. V1 karşılaştırması `agent-runtime/README.md` içindeki
ajan profili, görevler, scheduler, skill/hafıza ve MCP bölümlerine dayanır.

**Platform şartı:** Windows, macOS ve Linux birlikte hedeflenir. Kurulum,
workspace, kimlik kasası, sandbox ve servis davranışı üçünde de aynı ürün
sözleşmesini karşılamalıdır. Platform backend'leri farklı olabilir; yetki
garantileri sessizce düşürülemez. Mevcut gerçek test kanıtı Windows içindir;
diğer platformların native testleri C03 teslim kapısına dahildir.

## Hedef

Kullanıcı kendi ajanlarını ve ekiplerini oluşturabilsin; talimatlarını, model
kaynaklarını, çalışma alanlarını ve araç izinlerini seçebilsin. Tek seferlik
ve zamanlanmış görevler güvenilir biçimde çalışsın. Ajanlar gerektiğinde
kontrollü görev devri yapabilsin. Sonuç, doğrulama ve tüketim izlenebilsin.

İki teslim eşiği vardır:

1. **Günlük kullanım:** V1'deki ajan tanımlama, talimat/skill/hafıza, proje
   üzerinde çalışma, görev takvimi, doğrulama ve MCP yönetimi V2'de sağlanır.
2. **Ekip kullanımı:** Birden fazla ajan ortak görevi görev devri, ortak bütçe
   ve doğrulanmış ara çıktılarla tamamlayabilir.

Şirketlere çok kullanıcılı dağıtım, bu iki eşikten sonra ayrı bir yayına
hazırlık aşamasıdır. Ajanların aynı anda çalışması tek başına ekip iş birliği
anlamına gelmez.

## Mevcut temel — yeniden yazılmayacak

- [x] Pydantic AI native ajan motoru; harici Codex/OpenCode CLI zorunluluğu yok.
- [x] ChatGPT OAuth, Go, Zen, OpenRouter ve Ollama bağlantı uygulamaları.
  Her sağlayıcının canlı erişim doğrulaması tamamlanmış değil.
- [x] Kalıcı görev/çalışma/sonuç, idempotency, açık retry ve kesinti kurtarma.
- [x] FIFO worker, sınırlı eşzamanlılık, zaman aşımı, iptal ve kontrollü kapanış.
- [x] MCP araç bağlantıları, izin listesi, görevle ilgili araç seçimi ve çıktı sınırı.
- [x] Yönetim MCP'si: görev gönderme, durum/sonuç, iptal ve bağlantı seçimi.
- [x] Token/bağlam sınırları; otomatik model/araç hatası tekrarı kapalı.
- [x] Kurulum sihirbazı, özelleştirilmiş örnek ajan, doctor ve istemci dosyaları.

Son kayıtlı doğrulama 226 çevrimdışı senaryodur (223 geçti, 3 atlandı); gerçek görev kalitesi, temiz
makine kurulumu veya tüm sağlayıcıların canlı uyumluluğu için kanıt değildir.

## A — V1 gibi günlük kullanmak için

### A01 — Kalıcı ajan kataloğu ve yaşam döngüsü

- [x] Örnek YAML dosyalarından bağımsız, kalıcı ajan oluşturma/listeleme/
  güncelleme/devre dışı bırakma ve arşivleme işlemlerini ekle.
- Her ajanın sabit kimliği, profili, model bağlantıları ve izinleri olsun;
  çalışan görevler profil güncellemesinden etkilenmesin.
- **Tamamlanma:** İki farklı ajan servis yeniden başlatıldıktan sonra da
  listelenir ve ayrı görev alır; arşivleme geçmişi silmez.
- **Bağımlılık:** Mevcut config/TaskStore; ikinci görev deposu yazılmayacak.
- **Durum (1 Kasım 2026):** Uygulandı; kullanım [ajan kataloğunda](agents-and-workspaces.md),
  kanıtlar [doğrulamada](verification.md) kayıtlı.

### A02 — Talimat dosyaları ve talimat birleştirme

- [x] V1'deki SOUL/AGENTS/kurallar kullanımını karşılayan açık profil dosyaları
  ve tek bir talimat derleyicisi oluştur. İçerik dosyada mı YAML'de mi tutuluyor
  açık olsun; aynı talimat iki yerde bağımsız yönetilmesin.
- Profil, kalıcı kurallar, görev talimatı, ilgili skill ve proje bilgisinin
  nasıl birleştirildiğini ve çakışmaları belgele; bağlam boyutunu sınırla.
- **Tamamlanma:** İlgisiz bilgi yüklenmez; talimat revizyonu çalışmada izlenir;
  ajan kendi davranış/izin dosyalarını otomatik değiştiremez. Prompt kuralları
  kod tarafından uygulanan araç izinlerinin yerine geçmez.
- **Bağımlılık:** A01.
- **Durum (1 Kasım 2026):** Uygulandı; sözleşme [talimatlar ve skill'lerde](instructions-and-skills.md),
  kanıtlar [doğrulamada](verification.md) kayıtlı.

### A03 — Çalışma alanı, dosya okuma ve çıktı dosyaları

- [x] Ajana açık bir workspace ata; listeleme, hedefli arama ve sınırlı dosya
  okuma araçlarıyla başla. Üretilen dosyalara görevle ilişkili artifact kaydı ekle.
- Kök dışına kaçışları, symlink/junction yollarını ve çıktı boyutlarını denetle.
- **Tamamlanma:** Ajan izinli projeyi okuyabilir; başka ajan/proje/kimlik
  dosyalarını okuyamaz. Artifact'in yolu, üreticisi ve görev kimliği izlenir.
- **Bağımlılık:** A01–A02.
- **Durum (1 Kasım 2026):** Uygulandı; sözleşme
  [çalışma alanı ve artifact'larda](workspaces-and-artifacts.md), kanıtlar
  [doğrulamada](verification.md) kayıtlı.

### A04 — Gerçek sandbox yürütme katmanı

- [x] Windows, macOS ve Linux için ortak sandbox sözleşmesi ve uygun backend'ler seç;
  dosya sistemi, süreç, ağ ve kaynak sınırlarını her hedefte prototiple kanıtla.
- [x] Kimlik bilgilerini sandbox ortamına gereksiz taşımadan model erişimi ile
  araç yürütmesini ayır; alt süreçleri ve sert iptali yönet.
- **Tamamlanma:** Kök dışına yazma, yasak ağ erişimi ve süre aşımındaki alt
  süreçler gerçek izolasyon testleriyle engellenir. Stdio MCP bağlantısı tek
  başına sandbox sayılmaz; harici araç sunucusunun yetkisi ayrıca değerlendirilir.
- **Bağımlılık:** A03. Backend kararları üç platformun uygulama kanıtıyla
  verilecek. Desteklenmeyen yetenek açıkça reddedilecek; izolasyonsuz devam yok.
- **Durum (1 Kasım 2026):** Uygulandı. Windows AppContainer + Job Object
  gerçek izolasyon testleriyle doğrulandı; macOS Seatbelt ve Linux bubblewrap
  backend'leri ile ortak sözleşme hazır. Native macOS/Linux testleri C03
  kapısında çalıştırılacak. Ayrıntılar [sandbox](sandbox.md) ve
  [doğrulama](verification.md) belgelerinde.

### A05 — Dosya değiştirme ve komut çalıştırma

- [x] Sandbox içinde sınırlı dosya yazma/patch ve argv tabanlı komut araçları ekle.
- [x] Göreve göre okunabilir/yazılabilir dizinleri ve komut yetkilerini açık tanımla;
  dış sisteme yayınlama/push gibi etkileri ayrı izinle yönet.
- **Tamamlanma:** Örnek proje dosyası düzenlenir ve test komutu çalışır;
  yetkisiz dizin/komut reddedilir. Model veya süreç çıktıları sınırsız yüklenmez.
- **Bağımlılık:** A04.
- **Durum (1 Kasım 2026):** Uygulandı. `write_file`, `apply_patch` ve
  `run_command` araçları; görev bazlı okuma/yazma dizinleri, komut allowlist'i,
  ağ/yayın izni, sandbox içi dosya yardımcısı ve açık artifact kaydı eklendi.
  Ayrıntılar [dosya ve komut](tools-and-execution.md) ile
  [doğrulama](verification.md) belgelerinde.

### A06 — Model cevabından bağımsız görev doğrulaması

- [x] Dosya, yapılandırılmış çıktı ve test komutu doğrulayıcıları ekle.
  Tarayıcı gerektiren işlerde gerçek test çıktısını değerlendir.
- [x] Model yürütmesinin bitmesi ile görevin doğrulanmış başarısını ayır;
  doğrulama kanıtını ve hata nedenini kaydet.
- **Tamamlanma:** Model "tamamlandı" dese bile eksik dosya veya başarısız
  test görevi başarılı yapmaz. `BROWSER PASS` metni tek başına kanıt sayılmaz.
- **Bağımlılık:** A03; komut/tarayıcı doğrulaması için A05.
- **Durum (1 Kasım 2026):** Uygulandı. `verification.py` dosya, JSON şema,
  argv tabanlı komut ve Playwright JSON raporu kontrollerini çalıştırır;
  plan görevle dondurulur. Başarısız doğrulama görevi `failed` yapar, model
  sonucunu ve kanıtı saklar. Kullanım [görev doğrulamada](task-verification.md),
  kanıtlar [doğrulamada](verification.md) kayıtlıdır.

### A07 — V1'e denk görev yönetimi

- [x] Başlık, açıklama, öncelik, etkinlik, bağımlılıklar, doğrulama ve tanım
  revizyonunu ekle; görev düzenleme/iptal/arşivleme işlemlerini tamamla.
- [x] Görev tanımının kaynağını seç: DB veya Markdown. Diğeri içe/dışa aktarma
  görünümü olsun; iki bağımsız doğruluk kaynağı oluşturma.
- **Tamamlanma:** Öncelik ve bağımlılıkla görev seçilir; döngüsel bağımlılık
  reddedilir. Çalışan tanım değiştirilemez; geçmiş ve revizyon korunur.
- **Bağımlılık:** A01 ve A06; mevcut basit FIFO davranışı korunarak genişletilir.
- **Durum (1 Kasım 2026):** Uygulandı. SQLite doğruluk kaynağıdır; başlık,
  açıklama, öncelik, etkinlik, bağımlılık, doğrulama ve tanım revizyonu
  eklendi. Kuyruk öncelik ve hazır bağımlılıklara göre seçilir; döngü, kendine
  bağımlılık ve eksik hedef reddedilir. `edit`, `cancel`, `archive`, `restore`,
  `revisions` ve Markdown `export`/`import` yüzeyleri eklendi. Kullanım
  [görev yönetiminde](task-management.md), kanıtlar [doğrulamada](verification.md)
  kayıtlıdır.

### A08 — Zamanlanmış görevler ve programatik servisler

- [ ] Tek seferlik zaman ve cron/saat dilimi desteği ekle. LLM gerektirmeyen
  programatik işleri model çağırmadan çalıştıran kayıtlı handler yapısı tanımla.
- Kaçırılan takvim, tekrar, yeniden başlatma ve çift tetikleme politikasını belirle.
- **Tamamlanma:** Europe/Istanbul günlük görevi yeniden başlatmada kaybolmaz;
  aynı zaman dilimi slotu iki kez çalışmaz. Zamanı gelmeyen iş LLM çağırmaz;
  başarısızlık sınırsız retry üretmez.
- **Bağımlılık:** A07.

### A09 — Seçici skill ve kalıcı proje hafızası

- [ ] Göreve göre ilgili skill'leri ve kısa proje/ders kayıtlarını seçerek yükle.
- Hafızayı kaynak ve revizyonla tut; doğrulanmamış model iddiasını otomatik
  kalıcı bilgiye çevirmeme, tekrarları ayıklama ve düzeltme/silme akışını ekle.
- **Tamamlanma:** Sonraki ilgili görev doğrulanmış bilgiyi kullanır;
  ilgisiz geçmiş ve tüm skill kataloğu modele gönderilmez. Talimat dosyaları
  model tarafından hafıza güncellemesi bahanesiyle değiştirilmez.
- **Bağımlılık:** A02 ve A06.

### A10 — Ajan ve ortak workspace eşzamanlılığı

- [ ] Worker limitine ek olarak ajan ve workspace kilitlerini uygula;
  manuel yürütme ve kuyruk yürütmesinin aynı kaynakta çakışmasını engelle.
- **Tamamlanma:** Aynı projede iki yazıcı iş çakışmaz; bağımsız projeler
  paralel ilerler. İptal/çökme sonrası kilit kurtarma güvenli çalışır.
- **Bağımlılık:** A03–A05; A08 ve ekip pilotundan önce tamamlanmalı.

### A11 — MCP'den tam ajan ve görev yönetimi

- [ ] Ajan profili/durumu, oluşturma/güncelleme/arşivleme, görev düzenleme,
  takvim, doğrulama kanıtı ve kullanım özetini mevcut yönetim MCP'sine ekle.
- Yazma, ajan yönetimi ve çalıştırma yetkilerini ayır; istemciden keyfi dosya
  yolu/komut/spec kabul etmek yerine kapalı şema ve doğrulanmış işlemler kullan.
- **Tamamlanma:** Kullanıcı izinli MCP istemcisinden ajan oluşturur, görev
  atar, takvimini değiştirir ve doğrulanmış sonucu alır; yetkisiz işlem reddedilir.
- **Bağımlılık:** A01, A06–A09. Mevcut MCP ve TaskStore yeniden kullanılacak.

### A12 — Terminalden bağımsız servis ve işletim araçları

- [ ] Windows, macOS ve Linux için kur/başlat/durdur/durum/kaldır akışını; seçilen kullanıcı
  hesabıyla otomatik başlangıç, kontrollü yeniden başlama ve log sınırlarını ekle.
- Kuyruk/worker sağlık kontrolü, son hata, yedekleme ve geri yükleme ekle.
- Windows süreç yöneticisi, macOS launchd ve Linux systemd kullanıcı servisi
  gibi platform katmanlarını ortak yaşam döngüsü sözleşmesinin altında tut.
- **Tamamlanma:** Makine yeniden açıldığında servis çalışır; OAuth kasası ve
  anahtar ortamına doğru kullanıcıyla erişir. Çökme sonrası belirsiz işler
  otomatik tekrar yürütülmez; yedekten geçici ortamda geri dönüş denenir.
- **Bağımlılık:** Mevcut worker; takvim gözetimi için A08.

### A13 — V1 benzeri günlük kullanım pilotu

- [ ] Kişisel veriler içermeyen örneklerle araştırmacı ve geliştirici ajanı kur;
  talimat, skill, hafıza, takvim, MCP, proje düzenleme ve doğrulama akışlarını dene.
- Kullanıcı tarafından seçilecek gerçek geçiş için önce salt okunur V1 envanteri
  ve eşleme raporu çıkar. Gerekli verileri ayrı özel profile aktaracak yöntemi
  tasarla; kişisel ajanları açık kaynak örneklerine kopyalama.
- **Tamamlanma:** Örnek ajanlar bağımsız çalışır; kesinti/iptal/yeniden başlatma
  kanıtları kaydedilir. V1 canlı DB'si ve dış ürün projeleri değişmeden kalır.
- **Bağımlılık:** A01–A12.

## B — Ajanların ekip olarak çalışması için

### B01 — Ekip tanımı ve ortak bütçe

- [ ] Ekip üyeleri, roller, sorumluluklar ve izinli görev devri ilişkilerini
  tanımla; ajan başına model seçimini koru.
- Ekibe toplam istek/token/süre, paralellik ve görev devri sayısı sınırı koy;
  çocuk işler parent görev/ekip kimliğiyle izlenebilsin.
- **Tamamlanma:** Her üyeye ayrı bütçe tanımlayarak toplam sınır aşılamaz;
  yeni iş başlatmadan bütçe kontrol edilir. Sağlayıcı raporlaması ve ChatGPT
  çıktı sınırının mevcut teknik kısıtları kullanıcıya doğru gösterilir.
- **Bağımlılık:** A01–A02, A07, A10.

### B02 — Belirli akışlarla görev devri

- [ ] Önce araştırmacı → üretici → doğrulayıcı gibi tanımlı akışları uygula.
  Serbest biçimli ajanlar arası sohbeti varsayılan yapma.
- Başlangıç/çıkış koşulları, bağımlılıklar ve azami devir/iyileştirme turunu tanımla.
- **Tamamlanma:** Ortak iş üç rol arasında ilerler; aynı aşama kesinti sonrası
  gereksiz tekrar çağrılmaz, döngüsel görev devri sınırda durur.
- **Bağımlılık:** B01, A06–A07.

### B03 — Ajanlar arasında sınırlı bilgi ve artifact aktarımı

- [ ] Görev devrinde tam sohbet geçmişi yerine yapılandırılmış görev özeti,
  gerekli kanıtlar ve izinli artifact referansları aktar.
- Paylaşılan ve özel hafızayı ayır; görev/ekip dışı bilgiye erişimi denetle.
- **Tamamlanma:** İkinci ajan gerekli ara çıktıyla çalışır; başka ajanın
  kimlik bilgisi veya ilgisiz geçmişi bağlama girmez. Aktarım boyutu ölçülür.
- **Bağımlılık:** B02, A03 ve A09.

### B04 — Ekip iptali, hata yönetimi ve final doğrulama

- [ ] Ana görev iptalinin çocuklara yayılmasını; bir üye başarısız olduğunda
  durdurma/yeniden deneme ve kısmi sonuç politikasını uygula.
- Sonucu birleştir; model değerlendirmesine ek olarak A06 doğrulamasını çalıştır.
- **Tamamlanma:** Başarısız çocuk işi ana görevden gizlenmez; iptalden sonra yeni
  çocuk başlamaz. Ekip sonucu ve toplam tüketimi MCP üzerinden görüntülenir.
- **Bağımlılık:** B02–B03 ve A11.

## C — Yayına hazırlık ve tüketim doğrulaması

### C01 — Kalite, hız ve token ölçüm paketi

- [ ] Tek ajan/ekip için aynı görev ve model koşullarında başarı, doğrulama,
  gecikme, istek, girdi/çıktı ve bağlam aktarım boyutunu ölç.
- Önce çevrimdışı regresyon setini kur; ücretli ölçümleri açık bütçeyle ayrı çalıştır.
- **Tamamlanma:** Boşta LLM çağrısı ve gizli tekrar yok; ekibin tek ajana göre
  faydası ve ek tüketimi raporlanır. Bilinmeyen kullanım sıfır yazılmaz.
- **Bağımlılık:** Temel ölçümler A06 ile başlayabilir; ekip ölçümleri B04 sonrası.

### C02 — Gerçek sağlayıcı ve yönetici istemci doğrulaması

- [ ] ChatGPT/Luna, Go, Zen, Ollama/OpenRouter için küçük, açık bütçeli uyumluluk
  kontrolleri; token bildirimi, araç çağrısı, süre aşımı ve auth hata senaryoları hazırla.
- Codex yerel MCP ve ChatGPT tünel/uygun uzak bağlantıyı gerçek istemcide dene.
- **Tamamlanma:** Desteklenen/gerçekte denenmiş özellik matrisi yayımlanır;
  ChatGPT'yi yönetici olarak kullanma ile ChatGPT'yi model kaynağı olarak kullanma
  ayrı doğrulanır. Denenmeyen sağlayıcıya doğrulandı etiketi konmaz.
- **Bağımlılık:** A11 ve C01; kullanıcı hesapları ve ilgili servis erişimleri.

### C03 — Kurulum, yükseltme ve temiz paket

- [ ] Temiz Windows, macOS ve Linux ortamlarında kurulum → ajan → servis → MCP → görev → sonuç
  akışını doğrula; şema yükseltmesi, geri dönüş ve kaldırmayı belgeleyip dene.
- Açık kaynak pakete yalnız örnek ajanlar koy; kişisel profilleri, görevleri,
  kimlik bilgilerini ve araştırma verilerini dışarıda tut.
- **Tamamlanma:** Yeni kullanıcı rehberle ilk görevini tamamlar; yükseltme
  mevcut geçmişi korur. Desteklenen Python/OS sürümleri gerçek testlere dayanır.
- Üç OS × Python 3.12/3.13/3.14 matrisi geçmeli; native symlink/yol, süreç
  iptali ve uygun güvenli kimlik kasası senaryolarının kanıtı ayrıca kaydedilmeli.
- **Bağımlılık:** A12–A13, B04 ve C02.

### C04 — Şirket/çok kullanıcı dağıtımı — ayrı teslim

- [ ] Kullanıcı/ekip izolasyonu, kaynak ve artifact erişimi, uygulama OAuth'u,
  uzak MCP kimlik doğrulaması, işlem denetim izi ve ekip kotaları ekle.
- **Tamamlanma:** Bir şirketin/kullanıcının görevleri ve kimliği diğerine
  açılamaz; yönetici işlemleri kayıtlıdır. Loopback HTTP bu hedefin yerine geçmez.
- **Bağımlılık:** B04, C01–C03. Kişisel yerel kullanımı başlatmak için ön koşul değil.

## Uygulama sırası ve teslim kapıları

1. **İlk paket (tamamlandı):** A01 → A02 → A03. Ajan profilleri ve gerçek proje okuma.
2. **Çalışma paketi:** A04–A06 (tamamlandı) → A07, ardından A10.
3. **Günlük kullanım paketi:** A08–A12 → A13. V1 benzeri kullanım eşiği.
4. **Ekip paketi:** B01 → B02 → B03 → B04. Kontrollü ekip eşiği.
5. **Yerel sürüm teslimi:** C01–C03. C01 ölçümleri ilk paketlerden itibaren toplanır.
6. **Şirket dağıtımı:** C04 ve ona uygun kurulum/istemci pilotu.

Her görev ancak üretim kodu, gerekli anlamlı çevrimdışı test, kullanım
belgesi ve belirtilen kabul kanıtı hazır olduğunda tamamlandı işaretlenir.
Bu dosya V1'in `gorevler.md` biçiminde çalıştırılabilir görev tanımı değildir;
canlı runtime durumları buraya elle yazılmaz.

## Bu listeye başlangıçta eklenmeyecek işler

Web paneli, tüm Google konektörleri, dağıtık worker kümesi, sınırsız otonom
ajan sohbeti ve framework değişimi günlük kullanımın ön koşulu değildir.
Pydantic AI kararı ölçümde somut bir engel görülmedikçe korunur. Havuzlama ve
önbellek ihtiyaçları C01 ölçümlerine göre seçilir; mevcut kod gereksiz yazılmaz.

## İlgili belgeler

- [Mevcut mimari](architecture.md)
- [Kurulum ve özelleştirme](setup-and-customization.md)
- [Dışarıdan MCP yönetimi](external-management.md)
- [Doğrulama kayıtları](verification.md)
- [V1 kullanım referansı](../../agent-runtime/README.md)
