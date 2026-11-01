# R Agents geliştirme rehberi

Ürünü kullanmak için [README](README.md) ve [terminal rehberi](docs/terminal-quickstart.md)
yeterlidir. Bu sayfa kaynak koduna katkıda bulunanlar içindir.

## Yerel geliştirme

Python 3.12–3.14 ile depo kökünde:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\python -m pytest
```

Testler gerçek model hesabı veya ücretli çağrı gerektirmez.
Kullanıcı profillerini, kimlik bilgilerini ve yerel veritabanlarını commit etmeyin.
Örneklerde kişisel veya geliştirme makinesine özgü mutlak yollar kullanmayın.

## Kaynak düzeni

| Dizin | İçerik |
| --- | --- |
| `src/ragents/` | Uygulama kaynakları |
| `tests/` | Otomatik testler |
| `docs/` | Kullanım ve teknik belgeler |
| `examples/` | Kişisel veri içermeyen geliştirici örnekleri |
| `scripts/`, `packaging/` | Kurulum ve dağıtım araçları |

## Teknik başvuru

- [Repo çalışma kuralları](AGENTS.md)
- [Mimari](docs/architecture.md)
- [Ürün hedefi](docs/product-delivery.md)
- [Uygulama durumu ve açık kabul kapıları](docs/windows-product-progress.md)
- [Platform desteği](docs/platform-support.md)

Kaynak deposu testleri içerir; kullanıcıya kurulan uygulama paketi testleri
ve geliştirici örneklerini içermez. Mevcut sürüm geliştirme ön sürümüdür.
