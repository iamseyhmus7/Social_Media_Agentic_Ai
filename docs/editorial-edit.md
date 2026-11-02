# Profesyonel kurgu kabulü — 2026-10-26

Kullanıcı kelime vurgulu altyazı ve birkaç geçişten oluşan önceki yaklaşımı reddetti. `editorial` modu ayrı bir yönetilmiş kurgu olarak eklendi; eski `classic` ve `dynamic` sürümleri korunur.

- İlk 4.67 saniye: üç gerçek çekimden kısa açılış montajı; bölünmüş kadraj, maskeli görüntü açılması ve hareketli tipografi. Teaser çekimlerini Video Editörü doğrulanan JSON planında seçer.
- Gövde: senaryonun sahne sırası ve özgün ses süresi korunur. Her anlatı bölümü kendi başlığı ve kısa görsel vurgusuyla açılır. Maskeli reveal ve whip geçişi, genel/detay kadraj kesmeleri kullanılır.
- Son 2.53 saniye: özel kapanış tipografisi ve görsel ritim.
- Tam transkript ana görüntünün üzerine basılmaz. Türkçe SRT dosyası indirme paketinde korunur.
- Ayrı ve özgün bir ses tasarımı katmanı üretilir: düşük seviyeli atmosfer ve geçiş vurguları. Anlatım hızlandırılmaz veya kesilmez. Bu katman lisanslı stok müzik iddiası taşımaz; dış ses hizmeti veya indirme kullanmaz.

## Gerçek web kabulü

Proje `00eb0369-a9af-414c-a301-e6a57c4d991f`, üretim `9e239f8b-8176-46fa-ab63-ee217f7a72a6`, sürüm 6.

Webde **Stüdyo → Profesyonel sinematik kurgu → Yalnızca yeniden kurgula** kullanıldı. Yeni uzak iş sayısı **0**. Önceki sesler ve doğrulanmış yedi hareketli çekim yeni sürümün kendi medya kimliklerine kopyalandı. Dosya özetleri ve önceki videonun değişmediği doğrulandı.

- Render: 900 kare / **57.007 sn**. Derleme 14.201 sn; tarayıcı 0.160 sn; kompozisyon 8.779 sn; toplam Remotion 80.246 sn.
- Editör aşaması: **143.275 sn**. Editör başlangıcından paketli onay durumuna: **156.553 sn**. Bu bir yeniden kurgu ölçümüdür; Kaggle klip üretimi dahil değildir.
- Son video: **30.1 sn, 1080×1920, 30 FPS, H.264/AAC**. Tam çözümleme ve teknik kontrolde sorun bulunmadı.
- ZIP bütünlüğü ve `video.mp4`, `captions.srt`, `cover.png`, `publication.json` girdileri doğrulandı. Özgün ses tasarımı WAV süresi ve tepe sınırı doğrulandı.
- Durum `awaiting_approval`; gerçek kullanıcı onayı veya paylaşım yapılmadı. Estetik tercih kullanıcı incelemesine açıktır.

İzole SQLite regresyonları: **87 passed, 4 skipped**. API imajında bulunmayan medya kütüphaneleri atlanır; worker ortamında ses tasarımı ve PCM altyazı kontrolleri ayrıca **2 passed**. Frontend TypeScript ve üretim derlemesi geçti.

Görsel kayıtlar üretimin `qa/` klasöründedir. `preview-intro.mp4` ilk sekiz saniyelik gerçek video kesitidir. `acceptance-report.json` kaynak, paket ve zaman kontrolünü içerir.
