# Dosya değiştirme ve komut çalıştırma

A05 kapsamı. Bir ajan yalnız açıkça verilen dizinlerde dosya yazabilir, yama
uygulayabilir ve yalnız izinli çalıştırılabilirleri sandbox içinde çalıştırabilir.
Modelin "tamamlandı" demesi bu araçların izin sınırını değiştirmez; her çağrı
görev grant'i ve platform sandbox'ı tarafından ayrıca denetlenir.

## Araçlar

| Araç | Ne yapar | Ek izin |
| --- | --- | --- |
| `list_files`, `search_text`, `read_file` | Workspace içinde sınırlı okuma | `readable_paths` (boşsa tüm workspace) |
| `write_file` | İzinli dizinde UTF-8 dosya oluşturur/değiştirir | `writable_paths` |
| `apply_patch` | Dosyada tek eşleşen metni değiştirir | `writable_paths` |
| `run_command` | Argv listesini sandbox içinde çalıştırır | `commands`, isteğe bağlı `allow_network`/`allow_publish` |

Araçlar yalnız `agent.yaml` içindeki `tools` listesinde adı geçiyorsa modele
verilir. Örneğin:

```yaml
tools: [list_files, read_file, write_file, apply_patch, run_command]
permissions:
  readable_paths: [src, tests]
  writable_paths: [src]
  commands: [python, pytest]
  allow_network: false
  allow_publish: false
```

`permissions` alanı görev kuyruğa girerken `WorkspaceGrant` içine kopyalanır ve
görev tanımıyla dondurulur. Sonradan profil değiştirmek bekleyen görevin
izinlerini genişletmez.

## İzin alanları

| Alan | Varsayılan | Anlam |
| --- | --- | --- |
| `readable_paths` | boş | Göreli dizinler; boşsa tüm workspace okunabilir |
| `writable_paths` | boş | Göreli dizinler; boşsa yazma araçları kullanılamaz |
| `commands` | boş | Çıplak çalıştırılabilir adları; yol veya kabuk metni kabul edilmez |
| `allow_network` | `false` | `run_command` sandbox'ına ağ izni |
| `allow_publish` | `false` | `git push`, `npm publish`, `gh release` gibi dış etkiler |
| `command_timeout_seconds` | `60` | Komut başına üst süre; görev bütçesiyle ayrıca sınırlanır |
| `max_output_bytes` | `65536` | stdout ve stderr için ayrı çıktı sınırı |

Kurallar:

- Yollar workspace köküne göre görelidir; `..`, sürücü yolu, UNC ve Windows
  alternatif veri akışı reddedilir.
- `readable_paths` verilmişse `writable_paths` bu kapsamın içinde olmalıdır.
- İzin verilen dizinler görev kuyruğa girerken mevcut olmalıdır. Yanlış yazılmış
  bir dizin sessizce yok sayılmaz.
- `commands` yalnız çalıştırılabilir adıdır (`python`, `pytest`, `npm`).
  `python -c ...` çalıştırmak serbesttir; ancak bu, sandbox içinde sınırlı
  dosya/ağ/süreç yetkisiyle çalışır. Kabuk yorumu (`shell=True`) yoktur.
- `allow_publish=false` iken bilinen yayın komutları araç tarafından reddedilir:
  `git push`, `npm/pnpm/yarn/poetry/cargo/uv publish`, `docker push`,
  `twine upload`, `gh release`, `gh pr create/merge`, `gh repo create/fork`,
  `gh issue create` ve `gh api`.

## CLI

Ajan profiline varsayılan izinleri ekleyin:

```powershell
.\\.venv\\Scripts\\ragents.exe agents create --id gelistirici --name "Geliştirici" `
  --provider ollama --model qwen3:8b `
  --tool write_file --tool apply_patch --tool run_command `
  --writable-path src --allowed-command python --allowed-command pytest `
  --workspace C:\\Projeler\\OrnekProje
```

`agents update` mevcut listelere ekler; kaldırmak için `--remove-writable-path`
ve `--remove-command` kullanın. Ağ/yayın izni `--allow-network` /
`--no-allow-network` ve `--allow-publish` / `--no-allow-publish` ile yönetilir.

Görev bazında profili geçersiz kılın:

```powershell
.\\.venv\\Scripts\\ragents.exe tasks add --agent gelistirici `
  --writable-path src --allowed-command pytest `
  "src modülündeki hatayı düzelt ve testleri çalıştır"
```

`tasks add --writable-path` ve `--allowed-command` profil listesini **değiştirir**
(eklemez). Görev tanımı kuyruğa girerken snapshot alınır. `--config` ile
kullanılan tek dosyalı akışta workspace grant'i olmadığı için bu bayraklar
reddedilir.

## Dosya yazma ve yama

`write_file` ve `apply_patch` doğrudan ana süreçte dosya açmaz. İstek, platform
sandbox'ı içinde `python -m ragents.fileops` yardımcısına stdin üzerinden
JSON olarak verilir. Sandbox yalnız `writable_paths` dizinlerini yazılabilir
yapar; yardımcı ayrıca yolu, symlink/junction durumunu ve korumalı dizinleri
yeniden doğrular.

- `write_file(path, content, overwrite=false)`: en fazla 256 KiB UTF-8 içerik.
  Mevcut dosya varsayılan olarak ezilmez. Yazma aynı dizinde geçici dosya ve
  atomik `os.replace` ile yapılır.
- `apply_patch(path, old_text, new_text, replace_all=false, expected_sha256=...)`:
  `old_text` dosyada tam olarak bir kez geçmelidir; birden çok eşleşme
  reddedilir. `expected_sha256` verilirse dosya önce o sürümle eşleşmelidir.
  Kaynak dosya en fazla 1 MiB, sonuç en fazla 256 KiB olabilir. CRLF dosyalarda
  eşleşme için normalize edilmiş metin denenir; bu durumda dosya LF ile yazılır
  ve sonuç `normalized_newlines=true` döner.
- İkili dosyalar, UTF-8 olmayan dosyalar ve workspace dışına çıkan yollar
  reddedilir.
- Her başarılı yazma/yama sonucu `path`, `size_bytes`, `sha256` ve yama için
  `replacements` döner. `write_file` ayrıca `created` döner.

### Artifact kaydı

Yazma araçları başarılı olduklarında son dosya sürümünü açıkça artifact olarak
kaydeder. Görev servisi bu kaydı `producer=file_tool` ile upsert eder; böylece
aynı dosyaya yapılan son yama nihai SHA-256'yı verir. Görev sonunda çalışma
alanı fark taraması da çalışır; araç tarafından kaydedilmemiş diğer değişiklikler
`producer=workspace_scan` olarak eklenir. Başarısız görevde artifact kaydı
yapılmaz.

## Komut çalıştırma

`run_command(argv, cwd=".", timeout_seconds=None)`:

1. `argv` boş olmayan metinlerden oluşan bir liste olmalıdır; NUL ve aşırı uzun
   argümanlar reddedilir.
2. İlk öğe yalnız çalıştırılabilir adı olabilir; `/` veya `\\` içeren yol
   reddedilir. Ad, `commands` listesiyle büyük/küçük harf duyarsız karşılaştırılır;
   Windows'ta `.exe` eki normalize edilir.
3. `cwd` workspace içinde, okunabilir kapsamda ve mevcut bir dizin olmalıdır.
4. Yayın sınıflandırması `allow_publish` kapalıyken komutu reddeder.
5. Sandbox politikası: `network=allow_network`, yazma yalnız `writable_paths`,
   süre `min(command_timeout_seconds, timeout_seconds)`, çıktı
   `max_output_bytes`. Süre aşımı, iptal ve çıktı sınırı süreç ağacını
   sonlandırır.
6. Sonuç `exit_code`, `stdout`, `stderr`, `timed_out`, `cancelled`,
   `output_truncated`, `network_allowed`, `writable` ve `backend` alanlarını
   içerir. Çıktı sınırsız yüklenmez.

Örnek:

```python
run_command(["pytest", "-q"], cwd=".")
run_command(["python", "-m", "compileall", "src"], cwd=".")
```

`git push` gibi bir komut `allow_publish=true` olmadan çalışmaz. Ağ kapalıyken
`pip install`, `npm install` ve uzak `git fetch` gibi komutlar başarısız olur;
bu, sandbox'ın beklenen davranışıdır.

## Güvenlik sınırları

- **Dosya araçları:** Okuma/yazma kapsamı araç katmanında uygulanır; yazma
  ayrıca sandbox içinde çalışır. Symlink/junction ve `..` reddi korunur.
- **Komut süreci:** Windows AppContainer yalnız ACL verilen yolları okur;
  macOS/Linux'ta kök salt okunur olsa da süreç sistem dosyalarını okuyabilir.
  `readable_paths` komut sürecinin okuma görünümünü POSIX'te daraltmaz; bu
  sınır yalnız dosya araçları içindir ve `sandbox status` bunu bildirir.
- **Geçici dizin:** Sandbox her çalıştırmada workspace dışında ayrı bir geçici
  dizin oluşturur ve yalnız onu yazılabilir yapar. Bu, keyfi kök dışı yazma
  izni değildir.
- **Windows ACL yaşam döngüsü:** Her yürütme ayrı AppContainer kimliği kullanır;
  kendi izinleri ve profili süreç temizliğinden sonra kaldırılır. Eski ortak
  kimlik sonraki yürütmelerde kullanılmaz.
- **stdio MCP:** Harici MCP sunucusu ayrı bir süreçtir; bu sandbox'ın kapsamında
  değildir. Kendi yetkisi A11 kapsamında ayrıca değerlendirilir.
- **TOCTOU:** Yol doğrulaması ile atomik yazma arasında kalan yarışlar için
  sandbox yazma kapsamı ikinci savunma hattıdır; yine de aynı kullanıcı
  hesabında kötü niyetli eşzamanlı süreçlere karşı tam garanti verilmez.

## Doğrulama

- `tests/test_file_tools.py` izin reddi, sandbox içinde yazma/yama, artifact
  kaydı, komut allowlist'i, yayın engeli, çıktı sınırı ve CLI izinlerini kapsar.
- `tests/test_sandbox.py` Windows'ta yalnız izinli alt dizine yazmayı; Linux ve
  macOS komut üretiminde dizin bazlı bağlamayı doğrular.
- Modelin bitirdiğini söylemesi görev başarısı değildir. Dosya, JSON şema,
  test komutu ve Playwright raporu kontrolleri [görev doğrulamada](task-verification.md)
  ayrı çalışır; başarısız kontrol görevi `failed` yapar.
- `.github/workflows/compatibility.yml` macOS/Linux native testlerini ilgili
  runner'larda çalıştırır. Native sonuç alınmadan o platformlar için "doğrulanmış"
  denmez; bu C03 kapısına bağlıdır.
