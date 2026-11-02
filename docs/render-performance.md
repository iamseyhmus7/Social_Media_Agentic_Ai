# Yerel Remotion performansı — 25 Ekim 2026

Kaggle yalnızca hareketli klipleri üretir. Kurgu kararlarını yapılandırılmış medya metin modeli verir; Remotion ve FFmpeg yerel medya worker'ında çalışır. Kaggle üzerinde montaj için başlatılan ek kodlar geri alındı.

## Kontrollü ölçüm

8 CPU / yaklaşık 7.7 GiB Docker ortamında, mevcut `shot-000.mp4` kullanıldı. Yeni görsel, ses veya GPU klibi üretilmedi. Testler eşzamanlı render olmadan sırayla çalıştı. Çıktı 1080×1920 / 30 FPS / H.264; kısa video testleri 12 karedir. Ölçümler başlık ve altyazı katmanları kapalı temel klip maliyetidir; tam üretimin süresi ayrıca ölçülür.

| Test | Süre |
|---|---:|
| Sistem FFmpeg, 30 kare sentetik görüntü, veryfast / 2 thread | 0.550 sn |
| Remotion FFmpeg, aynı videoyu 30 kare yeniden kodlama | 0.362 sn |
| Headless Shell, 12 gerçek kare, veryfast / tek sekme | 1.523 sn |
| Headless Shell, aynı kareler, medium / tek sekme | 1.754 sn |
| Headless Shell, aynı kareler, medium / iki sekme | 1.393 sn |
| Headless Shell, aynı veryfast testi Windows bağlı medya alanından | 1.521 sn |
| Sistem Chromium + zorlanmış swangle, medium / iki sekme | 5.290 sn |

Bu örnekte disk konumu veya medium önayarı tek başına büyük yavaşlığı açıklamıyor. Tam Chromium ile zorlanmış yazılım GPU yolunun birleşimi, CPU için uygun Headless Shell ve varsayılan GL yolundan pahalı. Önceki eşzamanlı denemelerin süreleri kontrollü hız karşılaştırması olarak kullanılmaz.

## Uygulanan düzeltme

- Headless Shell, sabit Remotion 4.0.538 paketinin `ensureBrowser` API'siyle Docker imajına önceden hazırlanır. İlk üretimde tarayıcı indirilmez.
- Renderer medya yollarını mutlaklaştırıp kendi paket dizininde çalışır. Böylece worker'ın özel üretim klasöründen başlatılması tarayıcı önbelleğini yanlış konumda aramasına neden olmaz.
- 2D kompozisyon için zorlanmış `swangle` kaldırıldı. Açıkça özel tarayıcı yolu yapılandırılmışsa tam Chromium desteği korunur.
- İki render sekmesi, bir OffthreadVideo çözümleme thread'i ve 256 MiB kare önbelleği kullanılır. H.264 CRF 21, veryfast; çözünürlük ve FPS korunur.
- `render-metrics.json`, bundle / tarayıcı / composition / render sürelerini ve işlenen/kodlanan kare sayılarını kaydeder.
- SIGTERM / SIGINT, Remotion iptal sinyaline aktarılır. Tarayıcı `finally` içinde kapatılır; worker init süreci alt süreçleri toplar.

Gerçek renderer iptal kontrolü geçti: 8 kare işlendikten sonra SIGTERM, **0.072 sn** kapanış ve **0 yeni tarayıcı süreci**. `scripts/check-remotion-cancel.py` yalnızca ayrı `cancel-check` çıktısında çalışır; üretim kaydını değiştirmez.

Tanılama aracı: `remotion/production/profile.mjs`. Var olan üretim klasörü ve rapor dosyası yolu alır; üretim API'lerini çağırmaz. Geçici Linux klasörünü yalnızca kendi oluşturduğu `mkdtemp` yolunda temizler. Kontrollü rapor, ilgili üretimin `render-profile-controlled.json` dosyasındadır.

2026-10-25 tam Remotion ölçümü: 900 kare / 30 saniyelik gerçek Kaggle klipleri. Bundle 14.464 sn, tarayıcı 0.284 sn, kompozisyon 1.168 sn, render 54.381 sn, toplam 70.342 sn. Altyazı çözümleme, model kararı ve FFmpeg dahil editör aşaması 189.865 sn. Son video 1080×1920 / 30 FPS H.264/AAC, 30.1 sn, tam çözümleme ve teknik kontrolden geçti. Sonraki Yayıncı aşaması yaklaşık 126 sn sonra Evren zaman aşımıyla başarısız oldu; bu kayıtta paylaşım paketi ve uçtan uca kabul tamamlanmış sayılmaz.

2026-10-26: Dinamik kurgu ayrı sürüm olarak ekleniyor. Gerçek kelime zamanları ve kaynak ses özetleriyle doğrulanan altyazı önbelleği tutulur. Stüdyodaki yalnızca yeniden kurgu işlemi ses, görsel ve doğrulanmış hareketli klipleri yeni sürüme kopyalar; Kaggle işi veya yeni ses üretmez. Yayıncı yalnızca gerekli metin bağlamıyla metin modeline yönlendirilir. Yeni dinamik sürümün canlı süresi ve görsel kabulü ayrıca kaydedilecektir.


Dinamik kurgu karşılaştırması (2026-10-26): aynı kompozisyonun 6 karesi ayrı ve temiz render sürecinde boş zemin 0.702 sn, yalnız video 1.799 sn, kelime vurgulu video 1.174 sn ve güçlü açılış 1.695 sn sürdü. Bunlar kısa örneklerdir; tam video süresi olarak ölçeklenmez. İlk dinamik denemede aynı Node sürecindeki Webpack derlemesi 131.303 sn sürdü ve sonraki kareler yaklaşık 1 FPS ilerledi. Windows boş fiziksel belleği 334–550 MiB aralığında ölçüldü. Derleyici belleğinin render ile yarışmasını önlemek için derleme ayrı bir alt sürece taşındı; tam video karşılaştırması bekleniyor. Önceki yavaş denemenin ölçümü `render-metrics-inprocess.json`, kontrollü örnekler `dynamic-profile.json` dosyasındadır.

## Son tam kabul — ayrı derleyici süreci

2026-10-26: Webpack derlemesi `bundle.mjs` alt sürecine taşındı. Derleyici sonlanmadan Chromium başlatılmaz; compiler heap'i render sürecinde tutulmaz. İptal sinyali alt sürece aktarılır. Aynı üretimde yeniden deneme, doğrulanan `edit-plan.json` kararını ve hash ile doğrulanan ASR önbelleğini korur.

Kelime vurgulu 5. sürüm: 900 kare **75.943 sn**, toplam Remotion **107.750 sn**. Editör 131.287 sn; paketli onay durumuna 152.453 sn. Publisher metin modelinde tamamlandı.

Kullanıcının daha kapsamlı kurgu isteğiyle hazırlanan **editorial 6. sürüm**: üç kaynaklı açılış montajı, bölünmüş kadrajlar, hareketli tipografi, reveal/whip, anlatı başlıkları, özgün ses tasarımı ve kapanış. 900 kare **57.007 sn**, toplam Remotion **80.246 sn**. Editör 143.275 sn, paketli onay durumuna 156.553 sn. Yeni Kaggle işi yok. Bu değerler mevcut kliplerden yeniden kurgu içindir; yeni konu/GPU üretimi süresi değildir. Donanım, bellek baskısı ve ilk derleme süreyi değiştirir. Görsel ve teknik kayıt: [editorial kurgu kabulü](editorial-edit.md).

Ayrı derleyici süreçli iptal regresyonu da geçti: 55 kare sonrası SIGTERM, 0.039 sn kapanış, 0 yeni tarayıcı süreci. Tanılama kendi cancel-check klasöründe çalıştı; tamamlanmış kullanıcı videosu değişmedi.
