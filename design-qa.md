# Sahne görsel QA

final result: passed

## Görsel kaynak ve son yönlendirme

- Kaynak: `docs/design-reference.png` (1487 × 1058).
- Kullanıcı sonradan agent alanının büyütülmesini/genişletilmesini ve beyaz arka planın değiştirilmesini istedi. Bu nedenle eski görseldeki küçük beyaz akış alanı artık hedef değildir; açık yönetim kabuğu, serif başlıklar, mor vurgu ve koyu önizleme korunur.
- Uygulama: `docs/qa/agent-workspace-viewport.png`, `docs/qa/agent-workspace-desktop.png` ve `docs/qa/agent-expanded.png`.
- Tam görünüm karşılaştırması: `docs/qa/comparison-final.jpg`.
- Odak karşılaştırması: `docs/qa/flow-comparison-final.jpg` (önceki kompakt akış ve güncel büyütülmüş çalışma alanı).
- CSS viewport 1487 × 1058, devicePixelRatio 1. Tarayıcı screenshot API'si scrollbar hariç 1472 × 1047 PNG döndürdü; karşılaştırmada üst/sol hizası korunarak 1487 × 1058 beyaz tuvale yerleştirildi. Kaynak ölçeklenmedi.
- Durum: oturum açılmamış, açıkça etiketli demo, 4/7 tamamlanmış agent ve 3/5 örnek görsel. Görseller üretim çıktısı olarak sunulmuyor.

## Karşılaştırma geçmişi

1. İlk karşılaştırma (`comparison-before.jpg`): [P2] ASCII font alt kümeleri eksikti; serif/sans fallback'leri hedef tipografiyi değiştiriyordu. [P2] Graph düğümleri küçük ve merkezden sapmıştı. Latin + Latin-ext font dosyaları eklendi, gerçek düğüm ölçüleri ve konumlar düzeltildi.
2. İkinci karşılaştırma (`comparison-after.jpg`): ilk düzeltmeler doğrulandı. Kullanıcı daha büyük agent alanı ve farklı arka plan talep etti.
3. Son görünüm: 570px yüksekliğinde (eski 370px) açık lila/noktalı tuval, 330 × 66px düğümler, daha geniş ana alan ve daraltılan önizleme. Genişlet modunda düğümler yaklaşık 363 × 73px. Mobilde tek sütun düğümler yaklaşık 317 × 63px; yatay taşma yok.

## Beş zorunlu yüzey

- Fontlar: yerel Playfair Display ve DM Sans; Türkçe/Latin karakterler, başlık satırları ve düğüm etiketleri kontrol edildi.
- Yerleşim: sidebar, konu formu, akış ve koyu önizleme sınırları karşılaştırıldı. Agent alanının büyümesiyle son projelerin aşağı kayması kullanıcının talebinin beklenen sonucudur.
- Renkler: beyaz yerine `#f7f5fb` tuval, `#d6cfe5` React Flow noktaları; mor aktif vurgu, yeşil tamamlanma ikonları ve nötr bekleyen düğümler. Durumlar erişilebilir adlarda metinle de belirtilir.
- Görseller: yerel demo fotoğraflar doğru oran ve kırpma ile yerleştirildi; hazır olmayan sahneler açıkça bekliyor. Statik görsel üzerinde sahte video oynatıcı yok.
- İçerik: Türkçe metinler, gerçek/demonstrasyon ayrımı, yayın öncesi onay ve kurulum eksikleri görünür. Ücretli üyelik veya sahte analiz metriği yok.

## Tarayıcı kontrolleri

- Agent alanını genişlet/küçült, yakınlaştırma/uzaklaştırma ve ekrana sığdırma çalıştı.
- Agent çıktıları sekmesi, etkinlik günlüğü ve modal kapatma çalıştı.
- Demo üretim butonu oturum açma modalını açtı; gerçek görev başlatmadı.
- Mobil menü, içerik araması ve boş sonuç durumu çalıştı.
- 390 × 844 mobil görünümde belge genişliği 375px (scrollbar hariç); yatay taşma yok.
- Konsol: çalışma zamanı exception görülmedi. Geliştirme sırasında HMR kaynaklı React Flow nodeTypes/ölçüm uyarıları görüldü; düğümler ve resize sonrası görünüm DOM ölçüleriyle doğrulandı.
- TypeScript kontrolü ve üretim derlemesi geçti. Hosting paketinin dört mevcut testi geçti. Son backend birim testlerinde dokuz test geçti; tam API paketinin son tekrarı sandbox soket kısıtı nedeniyle tamamlanamadı. Bu, görsel QA sonucundan ayrıdır.

## Sınırlar / takip

- P0/P1/P2 görsel veya etkileşim bulgusu kalmadı.
- [P3] Agent tuvalinin daha fazla dikey alan kaplaması nedeniyle küçük dizüstü ekranlarda akışın altına kaydırma gerekir; Genişlet kontrolü alternatif sunar.
- Canlı Evren, gerçek medya üretimi ve YouTube yükleme kabulü bu görsel testin kapsamı değildir; kimlik bilgileri ve modeller kurulmadan doğrulanmış sayılmaz.
