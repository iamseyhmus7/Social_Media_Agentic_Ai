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

Platform logoları: Simple Icons (https://github.com/simple-icons/simple-icons), CC0. YouTube, Instagram ve TikTok adları ve logoları ilgili sahiplerinin ticari markalarıdır.

Ana sayfa etkileşimli demo klipleri: mevcut özgün konsept görsellerinden FFmpeg ile yerel olarak hazırlanmış sessiz H.264 MP4 dosyalarıdır. Üç örnek konu ve her konu için 12/9 saniyelik sürümler içerir; gerçek agent üretimi veya yayın sonucu değildir. Kaynak tanımlar `frontend/src/components/story-demo-examples.json`, üretim betiği `scripts/render_landing_demo.py`. Ek müzik, dış medya veya ücretli API kullanılmadı.
