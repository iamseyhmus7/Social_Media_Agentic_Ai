# Yerel render kaynak ölçümü — 30 Ekim 2026

Mevcut Çin Seddi parçası: 181 kare (6,03 saniye), 1080×1920, 30 FPS, H.264, CRF 21, veryfast, paralellik 2. Bir ısınma ve üç ölçüm; sıcak bundle. Model/GPU üretimi başlatılmadı.

| Süreç | Medyan tepe PSS (MiB) | Medyan örneklenen CPU süresi (s) |
|---|---:|---:|
| Node.js | 127,1 | 3,82 |
| Chromium | 964,5 | 38,30 |
| FFmpeg | 423,4 | 11,14 |
| Remotion compositor | 209,0 | 1,20 |

Medyan render: 12,721 saniye. Medyan renderer toplamı: 15,442 saniye. Medyan aynı anda toplam tepe PSS: yaklaşık 1723 MiB. CPU süreleri çekirdekler arasında toplanır; duvar saati değildir.

Tüm ölçüm çıktıları aynı SHA256 değerinde; çözünürlük/FPS/kare sayısı doğrulandı. Kaynak manifest, aralık ve video hashleri değişmedi. Başlangıç kaydındaki 37 üretim varlığının gerçek dosya SHA256 değerleri tekrar doğrulandı; değişiklik yok.

Sonuç: Bu örnekte bellek ve CPU yükünün çoğu Chromium ve FFmpeg tarafında. Node kontrol katmanını Rust ile değiştirmek bu maliyetleri ortadan kaldırmaz. Rust A/B testi yapılmadı; hız kazancı iddia edilmiyor.

Sınırlar: Tek sahne, sıcak önbellek ve mevcut donanım. 0,5 saniye örnekleme kısa ömürlü süreçleri kaçırabilir; CPU değerleri alt sınırdır. PSS paylaşılan belleği orantılar; kategori zirveleri farklı anlarda oluşur, toplanmamalıdır. Uzak Kaggle GPU kullanımı ölçülmedi. İlk eksik Chromium örneklemesi sonuçlardan dışlandı.

Araç: `scripts/profile_render_resources.py`. Esas ham rapor `data/qa-video-speedup/resource-profile-20261030-v2/report.json` ve her tekrarın `samples.json` / `render-metrics.json` dosyalarındadır. Üretim render'ı aynı anda başlarsa araç kendi ölçümünü keser. Üretim akışı ve renderer kodu değiştirilmedi.
