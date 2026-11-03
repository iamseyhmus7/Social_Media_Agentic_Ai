# Remotion kurgu araçları ve çıkış saati

Yeni üretimler varsayılan olarak 1080×1920 / 60 FPS çıkar. `REMOTION_OUTPUT_FPS=30`
ile 30 FPS seçilebilir. Ayar üretim başlarken yapılandırma kopyasına alınır;
bu alanı taşımayan eski üretimler 30 FPS kalır.

Agent kararları ve manifestteki `fps`, kesimler, kaynak başlangıçları, grafikler,
ses efektleri ve parça sınırları **30 FPS kurgu zaman tabanındadır**.
`output_fps` ayrı bir çıkış alanıdır. `timeline.jsx` kare saatini kesirli kurgu
karelerine çevirir, Sequence ve medya kesimlerini çıkış saatine taşır.
60 FPS animasyonlar ara konumlarda hesaplanır; sesin hızı değişmez.
`output-clock.mjs` kapsayıcı parça aralıklarını boşluk veya tekrar olmadan çevirir.
Parça önbelleği çıkış FPS değerini içerir; doğrulama gerçek kare sayısını kontrol eder.

`SceneDesign` alanları supervisor ve edit uzmanlarına `SCENE_CAPABILITIES`
üzerinden iletilir. Paket kurmak tek başına seçim yapmaz; LLM sahneye göre seçer:

| Alan | Seçenekler / uygulama |
|---|---|
| transition | Mevcut geçişlere ek `wipe`, `flip`, `clock_wipe`; resmî presentations |
| effects | `color_grade`, `glow`, `vignette`; @remotion/media Video üzerinde gerçek piksel efektleri |
| effect_strength | 0–1, varsayılan 0.35 |
| motion_blur | Dört örnekli, yalnız kaynak görüntü/kamera; yazı ve altyazı keskin kalır |
| lottie_asset | `none`, `pulse_ring`, `flow_arrow`; özgün yerel vektör animasyonları |
| annotation | `none`, `underline`, `circle`, `highlight`; klip başlığını vurgular |
| annotation_text | Başlığın içinden kısa bir kelime/ifade; boşsa ilk kelime vurgulanır |

Uzak Lottie URL'si, modelin ürettiği kod veya keyfi efekt adı kabul edilmez.
Lottie sembolik anlatım içindir; belge veya doğrulanmış olay görüntüsü sayılmaz.
Araçlar isteğe bağlıdır; sahne başına zorunlu efekt sayısı yoktur. Özellikle
motion blur ve piksel efektleri render maliyetini artırır.
Aynı segmentte motion blur ve piksel efektleri birlikte kullanılmaz; agent içerik
için uygun olanı seçer veya farklı segmentlere uygular. Bu sürümde birlikte
kullanımları Linux renderında zaman aşımına yol açtığı için sözleşme bunu engeller.
24/30 FPS kaynak
60 FPS çıkışta yeni hareket ayrıntısı kazanmaz; grafik ve kamera hareketleri akıcılaşır.

Üretim paketleri 4.0.538 sürümüne sabitlidir. Eski geçişler ve stiller korunur.
