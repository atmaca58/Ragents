# Görev doğrulama

Görev doğrulama, modelin “tamamlandı” demesini görev başarısı saymaz. Görev
kuyruğa girerken dondurulan bağımsız kontroller çalışır; dosya, JSON çıktısı,
test komutu ve tarayıcı raporu ayrı ayrı değerlendirilir. Kontroller geçmezse
görev `failed` olur, model çıktısı yine de incelenebilir.

## Plan dosyası

`tasks add` komutuna `--verify-plan` ile YAML veya JSON planı verilir. Plan,
görev tanımıyla birlikte saklanır; sonradan dosyayı değiştirmek eski görevi
etkilemez.

```yaml
checks:
  - type: file
    path: src/rapor.txt
    contains: "sonuç"
    min_bytes: 1

  - type: structured_output
    schema:
      type: object
      required: [summary, tests]
      properties:
        summary: {type: string}
        tests:
          type: object
          required: [passed]
          properties:
            passed: {type: integer, minimum: 1}
      additionalProperties: false

  - type: command
    argv: [python, -m, pytest, -q]
    cwd: .
    stdout_contains: ["passed"]

  - type: browser
    argv: [npx, playwright, test, --reporter=json]
```

```powershell
ragents tasks add --agent gelistirici --verify-plan dogrulama.yaml "Raporu hazırla"
ragents tasks show GOREV_KIMLIGI
ragents tasks result CALISMA_KIMLIGI
```

`tasks show` çıktısında `verification_plan` dondurulmuş planı, `verifications`
ise her çalışmanın kanıt kaydını gösterir. `tasks result` ve yönetim MCP'sindeki
`get_result` ilgili çalışmanın doğrulama kaydını döndürür.

## Kontrol türleri

### `file`

Workspace'e göre göreli bir dosyayı doğrular. `path` zorunludur; `sha256`,
`min_bytes`, `max_bytes` ve `contains` isteğe bağlıdır. Yol kaçışı, symlink,
junction ve korumalı katalog/veri dizinleri reddedilir.

- `sha256` için üst sınır 32 MiB'dir.
- `contains` için dosya en fazla 1 MiB olabilir ve UTF-8 olmalıdır.
- Dosya yoksa `file_missing`, hash uyuşmazsa `file_hash_mismatch` kaydedilir.

### `structured_output`

Modelin nihai metnini JSON olarak ayrıştırır ve yerel JSON şemasıyla doğrular.
Çıktı saf JSON olmalıdır; markdown kod bloğu kabul edilmez. Şema en fazla
16 KiB olabilir ve yalnız yerel `$ref` (`#/...`) kullanabilir; uzak `$ref`
ağ erişimini önlemek için reddedilir.

Geçersiz JSON `output_not_json`, şema uyuşmazlığı `schema_mismatch` olarak
kaydedilir. Hata kanıtında şema yolu ve hata sayısı bulunur; ham model çıktısı
telemetriye yazılmaz.

### `command`

`argv` listesi sandbox içinde çalıştırılır; `shell=True` yoktur. `cwd`
workspace içinde olmalıdır. `expected_exit_code` varsayılanı `0`'dır;
`stdout_contains` ve `stderr_contains` isteğe bağlıdır.

- Çalıştırılabilir adı yalnız çıplak ad olarak verilir (`python`, `pytest`);
  yol veya kabuk metni kullanılamaz.
- Komut, görev grant'indeki yazılabilir dizinleri ve ağ iznini kullanır.
- `allow_publish=false` iken `git push`, `npm publish`, `docker push`,
  `twine upload`, `gh release/pr create` gibi yayın komutları reddedilir.
- Zaman aşımı, görev komut süresi ve isteğe bağlı `timeout_seconds` değerinin
  küçüğüdür. Çıktı `max_output_bytes` ile sınırlıdır.
- Çıkış kodu uyuşmazsa `command_exit_code`, çıktı sınırına ulaşırsa
  `output_truncated` kaydedilir.

### `browser`

Playwright'ın JSON raporlayıcısını kullanır:

```powershell
npx playwright test --reporter=json
```

Raporun `stats` alanında `expected`, `unexpected`, `flaky` ve `skipped`
sayıları okunur. Geçerli sayılmak için `expected >= min_expected` (varsayılan
`1`) ve `unexpected = flaky = skipped = 0` olmalıdır. Model metnindeki
`BROWSER PASS` ifadesi tek başına kanıt değildir; yalnız gerçek komut çıktısı
değerlendirilir. Rapor JSON değilse `browser_output_not_json`, istatistik
eksik/geçersizse ilgili `browser_*` kodu kaydedilir.

## Sonuç durumları

Her kontrol `passed`, `failed` veya `error` durumundadır:

- `passed`: kontrol çalıştı ve koşul sağlandı.
- `failed`: kontrol çalıştı, koşul sağlanmadı (eksik dosya, başarısız test,
  şema uyuşmazlığı gibi).
- `error`: kontrol güvenilir biçimde çalıştırılamadı (geçersiz yol, sandbox
  yok, çıktı kesildi, UTF-8 olmayan dosya gibi).

En az bir `failed` varsa görev doğrulaması `failed`; yalnız `error` varsa
`error` olur. Görev her iki durumda da `failed` statüsüne geçer. Çalışma
kaydındaki `error_code` sırasıyla `verification_failed` veya
`verification_error` olur. Model sonucu ve doğrulama kanıtı saklanır; başarısız
görev `tasks retry` ile yeniden sıraya alınabilir.

## Sınırlar ve güvenlik

- Plan en fazla 32 kontrol içerebilir; plan dosyası en fazla 64 KiB'dir.
- Dosya kontrolleri workspace dışına çıkamaz; komutlar platform sandbox'ında
  çalışır ve ağ varsayılan olarak kapalıdır.
- Doğrulama komutları modele verilen `run_command` aracından ayrıdır; yine de
  aynı sandbox, yazma kapsamı, ağ izni ve yayın sınıflandırması uygulanır.
- Kanıt kaydı ham komut çıktısını saklamaz; çıkış kodu, süre, çıktı boyutu,
  SHA-256 ve Playwright sayıları gibi sınırlı alanları saklar.
- Tarayıcı komutunun gerçek Playwright kurulumuyla bu geliştirme ortamında
  çalıştırıldığı iddia edilmez. Çevrimdışı testler sahte sandbox ve gerçek
  Playwright JSON biçimiyle yapılmıştır; native tarayıcı kanıtı ayrıca
  gereklidir.

## MCP

`submit_task` isteğe bağlı `verification` nesnesi kabul eder. Mevcut MCP
bağlantıları workspace taşımadığı için MCP üzerinden yalnız
`structured_output` kontrolleri kullanılabilir; dosya/komut/tarayıcı
kontrolleri workspace'li katalog görevlerinde CLI ile tanımlanır. `get_task`
görevdeki tüm doğrulama kayıtlarını, `get_result` ilgili çalışmanın kaydını
döndürür.
