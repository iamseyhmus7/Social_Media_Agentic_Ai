# Otomatik kurgu görsel seçenekleri

Yeni renderlarda `reconstruction_label` boş üretilir. Otomatik renderer eski manifestteki etiketi de ekrana çizmez. Önceden oluşturulmuş MP4 dosyaları değişmez.

Tüm hareketler Remotion kare zamanına bağlıdır; rastgele zamanlayıcı, dış model/texture bağlantısı veya modelden gelen çalıştırılabilir kod yoktur. Yeni alanlar isteğe bağlıdır; eski sahneler mevcut varsayılanlarla açılır.

| Alan | Seçenekler |
|---|---|
| `design.camera.kind` | Mevcut hareketlere ek olarak `tilt_up`, `tilt_down`, `roll_left`, `roll_right`, `snap_zoom`, `arc` |
| `transition` | Mevcut geçişlere ek olarak `iris`, `diagonal_wipe`, `blur_dissolve`, `zoom_out`, `slide_up` |
| `design.typography` | `rise`, `words`, `characters`, `mask`, `blur_in`, `elastic`, `typewriter`, `flip`, `tracking` |
| `design.font_family` | Yerel DM Sans (`sans`) ve Playfair Display 700 (`serif`), Türkçe karakter desteği |
| `design.text_style` | `solid`, `outline`, `extruded`, `accent` |
| `design.template` | `none`, `editorial` (vurgu çizgisi), `glass` (cam başlık paneli), `blueprint` (teknik çizim ızgarası), `cinema` (üst/alt sinema çerçevesi) |
| `design.object_3d` | İsteğe bağlı Three.js `cube`, `sphere`, `torus`, `icosahedron`; `color`, `position`, `scale`, `speed`, `wireframe` |

Kamera üzerindeki `arc`, görüntü düzlemine uygulanan yumuşak yay hareketidir; kayıp görüntü derinliği üretmez. `object_3d` gerçek ışıklı geometri çizer; kişi, ürün veya tarihî yapı modeli oluşturmaz. 3D yalnız istenen sahnede açılır ve render süresini artırabilir. Yazı şablonları klibin `title` alanına uygulanır; aktif grafik kartıyla aynı anda klip başlığı gösterilmez. Altyazı zamanları ve anlatım hızı değişmez.

Kaynak kare rezervleri tüm yeni geçişlerde korunur. Parça cache anahtarları renderer kodunu ve manifesti içerdiği için eski efektlerle üretilen parçalar yeni görüntü için yanlışlıkla kullanılmaz.

Kontroller:

```powershell
node scripts/check-motion-design.mjs
.venv/Scripts/python.exe -m pytest backend/tests/test_motion_design_contract.py backend/tests/test_editorial_graphics.py -q --basetemp=.pytest-motion-design
```
