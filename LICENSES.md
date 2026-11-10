# Üçüncü taraf bileşen ve model kayıtları

Bu dosya kaynak envanteridir. Dağıtım öncesi kullanılan sabit sürümün tam lisans metinleri, atıfları ve model kartları da saklanmalıdır. Bu projenin özgün koduna kullanıcı adına ayrıca bir lisans atanmadı.

| Bileşen | Kaynak | Lisans / not |
|---|---|---|
| React | https://github.com/facebook/react | MIT |
| FastAPI | https://github.com/fastapi/fastapi | MIT |
| LangGraph | https://github.com/langchain-ai/langgraph | MIT; LangSmith servisi zorunlu değil |
| Celery | https://github.com/celery/celery | BSD-3-Clause |
| Valkey | https://github.com/valkey-io/valkey | BSD-3-Clause |
| PostgreSQL | https://www.postgresql.org/about/licence/ | PostgreSQL License |
| SQLAlchemy / Alembic | https://github.com/sqlalchemy | MIT |
| Diffusers | https://github.com/huggingface/diffusers | Apache-2.0 |
| ComfyUI | https://github.com/Comfy-Org/ComfyUI | GPL-3.0; özel Kaggle çalışma paketinde, sabit revision ve lisans dosyası korunur |
| ComfyUI-GGUF | https://github.com/city96/ComfyUI-GGUF | Apache-2.0; sabit revision korunur |
| Wan2.2-I2V-A14B GGUF | https://huggingface.co/QuantStack/Wan2.2-I2V-A14B-GGUF | Wan2.2 ağırlıkları Apache-2.0; Q5_K_M dönüşümü, kaynak revision ve dosya özetleri kaydedilir |
| Cloudflare Klein 9B / Lucid Origin | https://developers.cloudflare.com/workers-ai/models/ | Barındırılmış servisler; sağlayıcı/model kullanım koşulları ve ortak kota geçerlidir |
| SSD-1B | https://huggingface.co/segmind/SSD-1B | Model kartında Apache-2.0; indirilen revizyonun kartını sakla |
| faster-whisper | https://github.com/SYSTRAN/faster-whisper | MIT; Whisper ağırlıkları ayrıca kaydedilmeli |
| FFmpeg | https://ffmpeg.org/legal.html | Derlemeye göre LGPL/GPL. Bu proje libx264 kullandığından GPL etkin derleme gerekir; nonfree derleme dağıtma |
| React Flow | https://github.com/xyflow/xyflow | MIT; Pro aboneliği yok, atıf görünür |
| Radix UI / shadcn yaklaşımı | https://github.com/radix-ui/primitives / https://github.com/shadcn-ui/ui | MIT; yerel Radix tabanlı bileşenler |
| TanStack Query | https://github.com/TanStack/query | MIT |
| Tailwind CSS | https://github.com/tailwindlabs/tailwindcss | MIT |
| Lucide | https://github.com/lucide-icons/lucide | ISC |
| DM Sans / Playfair Display | https://github.com/google/fonts | OFL; Fontsource paketleriyle yerel sunulur |
| Three.js / React Three Fiber | https://github.com/mrdoob/three.js / https://github.com/pmndrs/react-three-fiber | MIT; isteğe bağlı yerel 3D geometri |

Remotion renderındaki Playfair Display 700 Latin ve Latin Extended alt kümeleri dosyaya gömülüdür; Türkçe harfleri destekler ve font CDN bağlantısı gerektirmez. Lisans: `remotion/production/licenses/Playfair-Display-OFL.txt`.

Demo fotoğraflar ve tasarım referansı bu görüşmede görsel üretim aracıyla oluşturuldu. Bunlar uygulamanın gerçek üretim çıktısı değildir. Çalışma zamanında bu araca veya ücretli bir görsel API'ye bağımlılık yoktur.

Evren sağlayıcısı ve YouTube resmi servislerinin erişim, kota ve kullanım koşulları bu depodaki açık kaynak lisanslarından ayrıdır. Kullanıcının yüklediği müzik ve görseller için kullanım hakları kullanıcıya aittir.

Wan hız profili: LightX2V `Wan2.2-Lightning`, I2V A14B 4-step Seko V1 high/low LoRA
ağırlıkları Apache-2.0 lisanslıdır. Kaynak:
https://huggingface.co/lightx2v/Wan2.2-Lightning . Sabit revizyon ve dosya SHA-256
değerleri `backend/kaggle/wan_acceleration_lock.json` içinde kayıtlıdır.

FastWan 5B: FastVideo `FastWan2.2-TI2V-5B-FullAttn-Diffusers`, Apache-2.0.
Sabit kaynak revizyonu ve üç adımlı DMD ayarları
`backend/kaggle/fastwan_runtime_lock.json` içinde kayıtlıdır. Ağırlık adlarının
dönüşümü Hugging Face Diffusers'ın Apache-2.0 lisanslı
`scripts/convert_wan_to_diffusers.py` eşlemesinin tersidir; DMD örneklemesi
FastVideo'nun Apache-2.0 lisanslı Wan DMD aşamasını izler.

Platform logoları: Simple Icons (https://github.com/simple-icons/simple-icons), CC0. YouTube, Instagram ve TikTok adları ve logoları ilgili sahiplerinin ticari markalarıdır.

Ana sayfa etkileşimli demo klipleri: mevcut özgün konsept görsellerinden FFmpeg ile yerel olarak hazırlanmış sessiz H.264 MP4 dosyalarıdır. Üç örnek konu ve her konu için 12/9 saniyelik sürümler içerir; gerçek agent üretimi veya yayın sonucu değildir. Kaynak tanımlar `frontend/src/components/story-demo-examples.json`, üretim betiği `scripts/render_landing_demo.py`. Ek müzik, dış medya veya ücretli API kullanılmadı.

Openverse aramasından CC0, public domain ve CC BY kayıtları, ccMixter müzik
aramasından CC BY kayıtları kabul edilir. Kullanılan kaynağın lisansı, eser
sahibi, orijinal sayfası ve atıf bilgisi üretim kaydında, paylaşım metinlerinde
ve `media-credits.txt` içinde saklanır. Uygun müzik indirilemezse kurgu konuşma
ve efektlerle devam eder.

Ek stok fotoğraf kaynakları: [Pexels License](https://www.pexels.com/license/),
[Pixabay Content License](https://pixabay.com/service/license-summary/) ve
[Unsplash License](https://unsplash.com/license). Bunlar Creative Commons olarak
etiketlenmez; her görsel kendi sağlayıcı lisansı, fotoğrafçısı ve kaynak
bağlantısıyla kaydedilir. Unsplash API görselleri arayüzde doğrudan API görsel
bağlantısıyla gösterilir; seçimde indirme bildirimi ve kaynak atfı korunur.
