# Sahne · Agent Destekli Video Üretim Stüdyosu

FastAPI + React/TypeScript ile çok kullanıcılı yerel pilot. Supervisor ve yedi uzman rol; Evren, Cloudflare referans görselleri, ElevenLabs anlatımı, Kaggle I2V ve Remotion–FFmpeg ile dikey video hazırlar. YouTube'a yayın **güncel sürümün kullanıcı onayını** gerektirir. Agent tanımları `shared/agents.json` dosyasında ortaktır; eski üretimler önceki yedi rollü akışı korur.

## Otonom video üretimi

Yeni üretimlerde yalnızca konu yazmak yeterlidir. MiMo Supervisor süreyi ve yaratıcı yönü belirler, mevcut uzmanlara dinamik görev verir. Video Editörü doğrulanmış JSON ile Remotion bileşenlerini seçer; sahne kararları ile render paralel ilerler. Render sonrası yalnız teknik kontroller yapılır; video tekrar modele gönderilmeden kullanıcıya sunulur. Stüdyoda doğal dille geri bildirim verilir; gerekli agentlar yeni sürümü üretir. Belirsiz geri bildirimde önce kısa açıklama sorusu sorulur. Her video için yeni Python/JSX yazılmaz. [Mimari ve sınırlar](docs/agentic-video.md).

## Otomatik Kaggle ve Remotion akışı

Sunucudaki `.env` dosyasına `KAGGLE_USERNAME` ve `KAGGLE_API_TOKEN` ekle; `VIDEO_PROVIDER=kaggle`, `EDITOR_PROVIDER=remotion` kullan. Token tarayıcıya veya agent bağlamına verilmez. Docker worker Node 22, Chromium ve eşleşen Remotion 4.0.538 paketlerini içerir. Üretimi `/app` üzerinden başlatmak yeterlidir; Kaggle'da hücre çalıştırma veya dosya taşıma gerekmez.

İlk iş LTX-Video 2B distilled 0.9.6 ve bağımlılıklarını özel bir CPU kernel çıktısına hazırlar. Sonraki özel T4 işleri yalnızca kendi referans görselleri ve doğrulanan hareket manifestiyle çalışır; modeli kernel kaynağından kullanır. Modeli eğitmek veya kişisel Hugging Face deposuna yüklemek gerekmez. İlk profil 480×832/24 FPS, en fazla beş saniyelik çekimler ve sekiz örnekleme adımıdır. Model FP32 çalışır. Ayrı metin kodlaması mevcut GPU'lar, sınırlandırılmış CPU belleği ve gerekirse geçici disk boşaltma ile tamamlanır; ardından kodlayıcı serbest bırakılır ve video için kademeli CPU offload kullanılır. Sekiz adımlı checkpoint çizelgesi Diffusers 0.35.2'nin I2V çağrısıyla uyumlu zamanlayıcı üzerinden uygulanır.

Bağlı model dosyaları, bellek eşlemesiyle oluşabilecek yavaş küçük okumaları azaltmak için 8 MiB tamponlarla geçici yerel alana kopyalanır. Disk kapasitesi ve kopya boyutları denetlenir; bu önbellek notebook çıktılarına dahil edilmez. Her yeni GPU oturumunun model yükleme süresi vardır; canlı hız ve kalite sonuçları [kabul kaydında](docs/kaggle-acceptance.md) ayrı tutulur.

`waiting_remote` durumunda worker kilidi bırakılır. Uzak iş kimliği, sürümü, girdi özeti ve denemeleri veritabanında saklanır; belirsiz gönderim otomatik yinelenmez. Hesap başına tek uzak iş çalışır. İptal edilen uzak iş sağlayıcıda sona erene kadar hesap yuvasını korur; geç gelen sonuçlar montaja alınmaz. Başarılı çekimler korunur ve eksik çekimler en fazla bir kez tekrar üretilir. Kota veya hata durumunda ücretli sağlayıcıya ya da sessiz fotoğraf montajına geçilmez.

Gerçek anlatım hedef süreden ±2 saniye sapabilir ve 30–60 saniye içinde olmalıdır. Kabul edilen üst sınır en fazla 0,5 saniye aşılırsa, gereken hız değişimi %1’i geçmemek koşuluyla ses yerelde perde korunarak uyarlanır; kelimeler kesilmez ve ElevenLabs yeniden çağrılmaz. Daha büyük uyumsuzluklar sınırlı metin/ses düzeltme akışına gider; süre doğrulanmadan GPU işi başlamaz. Video Editörü doğrulanan JSON kararları verir. Remotion görüntü, başlık ve altyazıları işler; FFmpeg anlatımı ve isteğe bağlı müziği karıştırır. Yeni Remotion üretimlerinde çıktı varsayılan 1080×1920/60 FPS (REMOTION_OUTPUT_FPS=30 ile 30 FPS) H.264/AAC olarak özel medya alanına yazılır ve tamamen çözümlenerek denetlenir.

Ana sayfadaki örnekler ve etkileşimli demo önceden hazırlanmıştır; gerçek Kaggle üretimi olarak sunulmaz. Gerçek üretim kayıtlı çalışma alanından başlatılır. Teknik kontrol içerik doğruluğu/estetik onayı değildir; son video kullanıcı incelemesini bekler.

## Mevcut durum

İçerikler ekranında satırdaki çöp kutusu tek içerik siler; kutucuklarla birden çok içerik seçilip **Seçilenleri sil** kullanılabilir. Son onay seçilen başlıkları gösterir. Kalıcı silme tüm yerel sürümleri ve medyayı kaldırır; YouTube'daki yayınları silmez. Çalışan üretimler, kapanmamış Kaggle işleri ve devam eden/belirsiz yüklemeler silinemez.

- Çalışan React arayüzü: genel bakış, agent akışı, sahne stüdyosu, kütüphane, takvim, marka/kanal/kullanıcı ayarları.
- FastAPI: Argon2 parolalar, HttpOnly oturum, CSRF, kullanıcı sahiplik kontrolleri, özel medya erişimi, sürüm/onay/yayın kayıtları, SSE.
- LangGraph: doğrulanan görev çıktıları, kalıcı aşama kayıtları, aşamaya göre sınırlı düzeltme turları, iptal/yeniden deneme/kota bekleme.
- SQLite + yerel worker geliştirme modu; PostgreSQL + Valkey + Celery Linux dağıtımı.
- Gerçek medya adaptörleri vardır; Whisper ağırlıkları ve Evren/Cloudflare/ElevenLabs bilgileri ayrıca kurulmalıdır. Demo görseller gerçek üretim sonucu değildir.
- Canlı Evren, YouTube, GPU ve Docker uçtan uca kabulü kimlik bilgileri, model kurulumu ve çalışan Docker motoru olmadan doğrulanmış sayılmaz.

## Önerilen çalışma: Docker

Web sayfaları: `/` ürün tanıtımı, `/register` kayıt, `/login` giriş, `/app` oturum gerektiren çalışma alanıdır. Giriş ve kayıt sonrası `/app` açılır; çıkış ana sayfaya döndürür. Ziyaretçilere proje listesi veya örnek dashboard gösterilmez.

Docker Desktop Linux motorunu aç. `.env` yerel gizli ayar dosyasıdır; mevcut dosyanı `.env.example` ile ezme.

```powershell
docker compose up --build -d
docker compose ps
docker compose exec api python -m backend.app.cli doctor
docker compose exec api python -m backend.app.cli create-admin --email yonetici@example.com --name "Yönetici"
```

Web uygulaması: [http://localhost:8080](http://localhost:8080). **Hesap oluştur** bağlantısından veya `/register` adresinden kayıt olabilirsin. İlk hesap, sunucuda atomik kontrolle yönetici; sonraki hesaplar üye olur. Kayıt sonrası oturum otomatik açılır. En az 12 karakterlik parola gerekir. `ALLOW_REGISTRATION=false` yeni kayıtları kapatır. Bu akış yerel pilot içindir; e-posta doğrulaması veya parola sıfırlama servisi içermez. CLI ile hesap oluşturmak alternatif yöntemdir; yönetici ayrıca Ayarlar → Kullanıcı yönetimi üzerinden kullanıcı ekleyebilir.

Bu çalışma şekli PostgreSQL 17, Valkey, FastAPI, tek Celery medya worker'ı, Celery Beat ve Nginx/React kullanır. PostgreSQL ve Valkey portları host'a açılmaz. Veritabanı ve kuyruk Docker named volume'larında, medya ve model önbelleği `data` içinde korunur. API başlamadan Alembic şemayı kurar; worker ve web API sağlık kontrolünü bekler. API/Beat temel imajı, worker ise FFmpeg ve CPU PyTorch içeren medya imajını kullanır. GPU profili ayrıca doğrulanmalıdır.

Medya worker'ı `--pool=solo --concurrency=1` ile tek ağır işi ana süreçte çalıştırır.
Canlı kabulde prefork alt sürecindeki Whisper çözümlemesi kilitte beklediği için bu
yerel pilotta fork kullanılmaz. Veritabanı lease'i ve dosya kilidi korunur. Whisper
önce indirilmiş small modelini kullanır; ses FFmpeg ile 16 kHz PCM'e çevrilerek
PyAV decoder sürüm uyumsuzluklarından kaçınılır.

```powershell
docker compose exec api python -m backend.app.cli check-evren
docker compose logs --tail=50 api worker beat
docker compose stop
```

Docker worker Türkçe karakterleri destekleyen DejaVu Sans fontunu, FFmpeg ve ffprobe araçlarını içerir; Windows font yolu gerekmez. ElevenLabs sesi üretir; FFmpeg/ffprobe sesi dönüştürür, süresini ölçer ve montajı denetler. Whisper ağırlıkları, yerel görsel sağlayıcı seçilirse ayrıca SSD-1B ilk kullanımda indirilir; paket kurulması model ağırlıklarının kurulduğu anlamına gelmez. Google OAuth istemcisinin izinli dönüş adresi Docker için `http://localhost:8080/api/v1/youtube/callback` olmalıdır.

PostgreSQL ile testler, her test için ayrı rastgele şema oluşturup sonunda kaldırır; uygulamanın `public` şemasını kullanmaz:

```powershell
docker compose exec api sh -c 'TEST_DATABASE_URL="$DATABASE_URL" python -m pytest backend/tests -q -p no:cacheprovider'
```

Eski `data/sahne.db` SQLite dosyası yedek olarak korunur; Docker bunu kullanmaz. `docker compose down -v` veritabanı volume'larını siler; normal durdurma için `docker compose stop` kullan.

### Mevcut Docker kurulumunu güncelleme

Mevcut `.env`, veritabanı ve `data` dizinini koru. Güncellemeden önce PostgreSQL yedeği al; ardından uygulama servislerini güncelle:

```powershell
git pull --ff-only
docker compose up -d --build api worker beat web
docker compose ps
docker compose exec api python -m backend.app.cli doctor
```

Bu işlem uygulama imajlarını yeniler; PostgreSQL/Valkey verilerini silmez. Normal yükseltmede `docker compose down -v` kullanma. Bağımlılıklar değiştiğinde yalnız kaynak dosyalarını kopyalamak yeterli değildir; ilgili imaj yeniden oluşturulmalıdır. Yerel SQLite geliştirme kayıtları Docker’ın PostgreSQL veritabanına otomatik taşınmaz; aynı e-posta ile açılan hesaplar bu iki ortamda ayrı kayıtlardır.

## Yerel geliştirme (Windows, Python 3.12, Node 22)

Komutları proje kökünde çalıştır:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
# Yalnız .env henüz yoksa örnek ayarları kopyala.
if (!(Test-Path .env)) { Copy-Item .env.example .env }
.venv/Scripts/python.exe -m backend.app.cli init-db
.venv/Scripts/python.exe -m backend.app.cli create-admin --email yonetici@example.com --name "Yönetici"
```

CLI parolayı gizli ister. Varsayılan veya depoya yazılmış yönetici parolası yoktur. Ayrı terminallerde:

```powershell
.venv/Scripts/python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

```powershell
.venv/Scripts/python.exe -m backend.app.worker
```

```powershell
cd frontend
npm.cmd ci --no-audit --no-fund
npm.cmd run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

Tarayıcı: http://127.0.0.1:5173. `/api` isteklerini Vite backend'e iletir. `.env` içindeki `APP_ORIGIN` tarayıcıdaki adresle aynı olmalı; `127.0.0.1` kullanırsan `APP_ORIGIN=http://127.0.0.1:5173` ayarla. Oturum açmadan açıkça etiketli örnek veriler gösterilir; demo kontrolleri gerçek iş başlatmaz.

## Evren

Tüm üretim agentlarının yanıt bekleme süresi `EVREN_RESPONSE_TIMEOUT_SECONDS=1800`
ile ayarlanır (120–7200 saniye). Eski 120/300 saniyelik aşama sınırları kullanılmaz. Bağlantı
kurma sınırı 15 saniyedir. Yanıt bekleme ve bağlantı zaman aşımı arayüzde ayrı
açıklanır. Zaman aşımında tamamlanan aşamalar korunur; aynı üretimde
**Yeniden dene** ile devam edilir.

`.env` içinde gerçek değerleri yalnızca yerelde doldur:

```dotenv
EVREN_API_KEY=...
EVREN_BASE_URL=...
EVREN_MODEL=...
```

Evren'in gerçek API sözleşmesini kontrol et. **OpenAI Chat Completions uyumluluğu doğrulanırsa**:

```dotenv
EVREN_PROTOCOL=openai_chat
EVREN_CONTRACT_VERIFIED=true
EVREN_COMPLETIONS_PATH=/chat/completions
```

Örnek: base URL `/v1` ile bitiyorsa path yalnızca `/chat/completions` olur. Başka protokol kullanılıyorsa `backend/app/providers.py` içindeki tek adaptör değiştirilmelidir. API anahtarının tek başına URL ve model kimliğini belirlemesi varsayılmaz. Model cevabı üç denemede (ilk + iki düzeltme) Pydantic şemasına uymalıdır. HTTP 429/402 işi `waiting_quota` durumuna alır; kota açılınca kullanıcı yeniden dener. Ücretli sağlayıcıya otomatik geçiş yoktur.

`RSS_FEEDS` yönetici tarafından seçilmiş RSS URL'leri içerir; `YOUTUBE_API_KEY` opsiyonel resmi arama erişimidir. Kaynak alınamazsa model konsept üretir, güncel trend iddiası yapılmaz. Kaynak tarihi ve alınma zamanı çıktıda saklanır.

## Yerel medya kurulumu

### Cloudflare görsel + ElevenLabs ses (yerel model indirmeden)

Cloudflare paneli → Workers AI → Use REST API → Create a Workers AI API Token.
Token ve Account ID değerlerini al. Elle token oluşturulursa Workers AI Read/Edit
yetkilerini yalnızca ilgili hesaba ver. ElevenLabs Developers → API Keys bölümünden
Text to Speech yetkili anahtar oluştur; kullanabildiğin sesin Voice ID değerini seç.
Anahtarları sohbet, ekran görüntüsü veya frontend kodunda paylaşma.

Mevcut `.env` dosyana aşağıdaki alanları ekle; dosyayı `.env.example` ile ezme:

```dotenv
IMAGE_PROVIDER=cloudflare
CLOUDFLARE_ACCOUNT_ID=
CLOUDFLARE_API_TOKEN=
CLOUDFLARE_IMAGE_STEPS=4
TTS_PROVIDER=elevenlabs
ELEVENLABS_API_KEY=
ELEVENLABS_VOICE_ID=
ELEVENLABS_MODEL=eleven_v4
ELEVENLABS_VOICE_SOURCE=api
ELEVENLABS_PREVIEW_CHECKS=3
```

Cloudflare `@cf/black-forest-labs/flux-1-schnell` modelini çağırır. Bu endpoint
boyut seçeneği sunmadığı için gelen görselin boyutu korunur; montaj dikey kadraja
uyarlar. ElevenLabs MP3 çıktısı FFmpeg ile mono PCM WAV'a dönüştürülür ve süre/
sessizlik kontrolünden geçer. Cloudflare seçildiğinde yerel SSD-1B yüklenmez.
Altyazı için mevcut yerel Whisper modeli hâlâ gereklidir.

Kod ve `.env` değişikliklerini Docker'a almak için:

```powershell
docker compose up -d --build api worker beat
docker compose exec api python -m backend.app.cli doctor
```

`doctor` yalnızca yapılandırma varlığını kontrol eder, canlı API kabul testi değildir.
Anahtarlar girildikten sonra kısa bir üretimle doğrula. HTTP 402/429 işi kota bekleme
durumuna alır; otomatik başka sağlayıcıya geçilmez. Ağ hatası veya geçersiz anahtar
üretimi durdurur. Yeniden deneme yeni API tüketimine yol açabilir. ElevenLabs ücretsiz
planının ticari yayın lisansı olmadığını dikkate al.

Kaynaklar: [Cloudflare REST kurulumu](https://developers.cloudflare.com/workers-ai/get-started/rest-api/),
[ElevenLabs TTS](https://elevenlabs.io/docs/api-reference/text-to-speech/convert).

### Agent ile otomatik ses keşfi ve seçimi

Varsayılan `ELEVENLABS_VOICE_SOURCE=api` modunda ses kimliği/profili elle tanımlanmaz.
Anahtarda **Metinden Sese → Erişim** ve **Sesler → Okumak** izinleri gerekir.
Varsayılan `ELEVENLABS_FREE_VOICES_ONLY=true` akışı `/v2/voices` üzerinden hesabın
hazır (`premade`) seslerini araştırır. MiMo başlık/açıklama, kullanım alanı ve varsa
Türkçe doğrulamasına göre üç aday seçer. Bu seslerin Türkçe ana dilli olduğu
varsayılmaz; Türkçe deneme kayıtları dinlenerek değerlendirilir. API kullanıcı
sayısı sağlamıyorsa sayı gösterilmez veya uydurulmaz.
`ELEVENLABS_FREE_VOICES_ONLY=false` seçilirse `/v1/shared-voices?language=tr&sort=cloned_by_count`
üzerinden Türkçe kütüphanesi araştırılır; `free_users_allowed=true`, normal kredi
oranı ve kullanıcı sayıları dikkate alınır. Voice Library API erişimi ücretli plan gerektirir.
Ücretli ses satın alınmaz veya hesaba eklenmez. Sağlayıcının ücretsiz kullanım
etiketi tek başına API erişim garantisi değildir; gerçek ses üretimiyle doğrulanır.

Üç anlatıcı aynı senaryonun ilk 20 kelimesini `eleven_v4` ile seslendirir.
Text to Dialogue HTTP endpoint'i tek anlatıcılı girdilerle kullanılır; v4 için
yalnızca desteklenen stability/similarity ayarları gönderilir. Bu örnekler kredi
tüketir ve başarılı kayıtlar yeniden denemede tekrar üretilmez.
`ELEVENLABS_PREVIEW_CHECKS=3` varsayılanıyla üç, 4 seçilirse dört örnek karşılaştırılır.
Evren istek başına en fazla iki ses kabul ettiğinden üç WAV kaydı, her turda tam
senaryo ile `mimo-v2.6-pro` modeline ikili karşılaştırmalarla gönderilir: ilk iki
adayın kazananı üçüncüyle karşılaştırılır. Tamamlanan turlar da saklanır. Model
her ses için Türkçe telaffuz/anlaşılabilirlik, senaryoya uygunluk ve gerekçe döndürür;
son anlatıcıyı model seçer. Kayıtları işleyemediğini bildirdiği ses seçilemez.
Agent'ın seçtiği ses tüm videoda korunur. Çıktılardaki **Türkçe ses adayları**
bölümü adayları, kullanıcı sayılarını, gerçek örnekleri ve seçim gerekçesini gösterir.

Rol bazında metin modeli seçimi:

```dotenv
EVREN_MODEL=deepseek-v4.1-flash
EVREN_MEDIA_MODEL=mimo-v2.6-pro
EVREN_SUPERVISOR_MODEL=mimo-v2.6-pro
EVREN_MEDIA_MODEL2=qwen3-vl-30b
EVREN_AUDIO_INPUT_VERIFIED=false
EVREN_VIDEO_INPUT_VERIFIED=false
```

Bu örnekte Supervisor MiMo, strateji ve senaryo DeepSeek kullanır. Seslendirme, Görsel
Tasarımcı, Video Üretim Agentı, Video Editörü ve Kalite kontrolü MiMo’ya; örneklenmiş
karelerin görsel incelemesi Qwen’e yönlendirilir. Supervisor modeli belirtilmezse
`EVREN_MODEL`, algı modeli belirtilmezse medya/metin modeli kullanılır. Rol modeli
yapılandırmayla seçilir. Görselleri Cloudflare, hareketli çekimleri Kaggle, montajı
Remotion/FFmpeg araçları üretir; model yönlendirmesi bu araçları kendiliğinden
multimodal agent'a dönüştürmez. Adaptör `image_url`, `input_audio` ve `video_url`
girdilerini destekler. Xiaomi MiMo dokümanının bir girdiyi desteklemesi, Evren
geçidinin aynı sözleşmeyi desteklediğini tek başına doğrulamaz.

Ses sözleşmesi canlı testle doğrulanıp `EVREN_AUDIO_INPUT_VERIFIED=true` yapıldığında,
senaryodan üretilen aday kayıtları WAV/Base64 olarak MiMo'ya gönderilir. Model duyduğu kısa ifadeyi,
uygunluğu ve gerekçeyi raporlar; işleyemediğini bildirdiği adaylar seçilmez. Hiçbir
aday dinlenemiyorsa iş açıklamayla durur. Bu bayrak kapalıyken sistem dinlediğini
iddia etmez; kayıt açıkça açıklama/teknik ölçüm değerlendirmesi olarak etiketlenir.
Doğrulama bayraklarını yalnızca canlı API kabulünden sonra etkinleştir. Karşılaştırmalı
akış bu doğrulama olmadan başlamaz. Eski hesap-listesi/önizleme akışı yalnızca
uyumluluk için `ELEVENLABS_CASTING_ENABLED=false` ile kullanılabilir.

Seçim, değerlendirme yöntemi ve gerekçesi `_voice_plan` ve etkinlik günlüğünde
saklanır; ses baytları veya anahtarlar çıktıya yazılmaz. Aynı videoda ve yeniden
denemede aynı ses korunur. Kalite revizyonunda seçim yeniden değerlendirilir.
Manuel profiller eski kurulumlar için `VOICE_SOURCE=profiles`, tek ses ise
`VOICE_SOURCE=single` modunda isteğe bağlıdır; varsayılan API modunda gerekmez.

GPU/FFmpeg işleri için WSL2/Linux önerilir. Temel Python API'si Windows'ta da çalışır.

```bash
sudo apt-get update
sudo apt-get install ffmpeg libsndfile1 fonts-dejavu-core
pip install -r backend/requirements-media.txt
```

Windows'ta FFmpeg/ffprobe kur ve SUBTITLE_FONT_FILE için Türkçe destekleyen yerel font dosyası seç; örneğin C:/Windows/Fonts/arialbd.ttf, SUBTITLE_FONT=Arial.

Yerel görsel sağlayıcı seçilirse ilk üretim [SSD-1B](https://huggingface.co/segmind/SSD-1B) ağırlıklarını indirir; Cloudflare modunda bu indirme yapılmaz. İlk altyazı üretimi Whisper small ağırlıklarını indirir. İndirme için internet ve yeterli disk gerekir. 4 GB GTX 1650'de sıralı CPU offload denenir; CUDA bellek hatasında CPU'ya geçilir. Model indirme ve gerçek donanım ölçümü yapılmadan hız sözü verilmez.

Kaynak çözünürlüğü ve kare hızı seçilen sağlayıcıya bağlıdır; Kaggle’ın başlangıç profili 480×832/24 FPS’tir. Yeni Remotion üretimleri varsayılan 1080×1920/60 FPS H.264/AAC çıkar; `REMOTION_OUTPUT_FPS=30` ile 30 FPS seçilir. Bu ayarı taşımayan eski üretimler 30 FPS kalır. Çıkışı büyütmek doğal 1080p ayrıntı veya kaynakta olmayan hareket ayrıntısı oluşturmaz. Gerçek WAV süreleri montajı belirler. 30–60 saniye sınırı, ses/siyah sahne ve altyazı uzunluğu kontrolleri uygulanır. Altyazı zamanları ASR tahminidir; son kullanıcı incelemesi zorunludur. Marka adı, rengi ve yüklenen logo kapakta ve videoda kullanılır. İlk üretim öncesi lisanslı müzik dosyası arayüzden veya API üzerinden eklenebilir.

## YouTube

Google Cloud Console'da YouTube Data API etkinleştir, OAuth web istemcisinde `.env` içindeki redirect URI'yi aynen tanımla. Gerekirse OAuth test kullanıcılarını ekle. `YOUTUBE_CLIENT_ID` ve `YOUTUBE_CLIENT_SECRET` sunucuda tutulur.

```powershell
.venv/Scripts/python.exe -m backend.app.cli generate-key
```

Üretilen değeri `TOKEN_ENCRYPTION_KEY` olarak `.env` içine koy. Anahtarı veritabanından ayrı yedekle; kaybedilirse kanal bağlantıları yeniden kurulmalıdır. Kullanıcı Ayarlar'dan kendi hesabını bağlar. Refresh token Fernet ile şifrelenir; uygulama loglarına token/code yazılmaması için sunucu `--no-access-log` ile çalıştırılır.

Onay video, altyazı, kapak hash'leri ve paylaşım metninin sürümüne bağlıdır. Yayın zamanı saat dilimi içermelidir; arayüz İstanbul saatini UTC'ye dönüştürür. Planlanan yayın en az 15 dakika ileride olmalı. Yükleme oturumu video baytlarından **önce** saklanır; kesinti sonrası aynı oturum sorgulanır. Sonucu belirsiz veya süresi dolmuş oturum otomatik yeni videoya dönüşmez. Kanalı kontrol edip sorunu çözmeden yeniden yayın başlatma. Planlanmış/yayınlanmış veya belirsiz yüklemesi olan proje yerinde revize edilmez; yeni proje oluştur.

## PostgreSQL / Valkey / Celery (Docker Linux)

Docker motoru çalışır durumda olmalı. `.env` içine güçlü bir `POSTGRES_PASSWORD` ekle; bağlantı URL'sinde kullanılacağından harf/rakam tercih et. `data` klasörü konteyner UID 10001 tarafından yazılabilir olmalı. Uygulama yalnızca yerel bilgisayara bağlanır:

```bash
docker compose up --build -d
docker compose exec api python -m backend.app.cli create-admin --email yonetici@example.com
```

Arayüz: http://localhost:8080. NVIDIA WSL2 desteği hazırsa `docker compose -f compose.yaml -f compose.gpu.yaml up --build -d`. Bu komutlar büyük medya bağımlılıkları indirir. Çok kullanıcılı **yerel pilot** içindir; internet yayını/HTTPS kapsam dışıdır.

Alembic ilk şemayı kurar. Sonraki şema değişikliklerinde açık migration eklenmeli; `create_all` mevcut sütunları dönüştürmez. SQLite verilerini PostgreSQL'e otomatik taşımak bu sürümde yoktur. Tüm worker'lar aynı `MEDIA_ROOT` dosya sistemini paylaşmalıdır; OS kilidi ve veritabanı lease'i sistem genelinde tek ağır iş sağlar. Başlangıçta kullanıcı başına bir aktif üretim vardır. Tamamlanan aşamalar DB'de kalır; kesintiye uğrayan iş açıkça yeniden denenir.

## Testler

```powershell
.venv/Scripts/python.exe -m pytest backend/tests -q
cd frontend
npm.cmd run build
npm.cmd run test:sites
```

Testler geçici veritabanı ve kullanıcılarla çalışır. Sağlayıcı/medya mock testleri canlı model kabulü değildir. Canlı kabul sırası: Evren/Cloudflare/ElevenLabs yapılandır → Whisper kur → örnek üret → sesi/altyazıyı incele → kendi YouTube test kanalında onaylı yayın dene. Gerçek hesaplara test sırasında yayın yapılmaz.

## Maliyet ve lisanslar

Üretim maliyeti seçilen sağlayıcıların kotasına, planına ve kullanımına bağlıdır. Cloudflare ve ElevenLabs çağrıları kota/kredi tüketebilir; ücretsiz kullanım ticari yayın izni anlamına gelmez. Elektrik, internet, disk ve donanım maliyetleri de vardır; Evren'in kalıcı ücretsiz hizmet ve kota koşulları ayrıca doğrulanmalıdır. YouTube ve Evren dış servislerdir. Yazılımın açık kaynak olması ağırlıkların ve medya çıktılarının lisanslarını aynı yapmaz. Kaynaklar ve dağıtım notları: [LICENSES.md](LICENSES.md).

Mimari: [docs/architecture.md](docs/architecture.md). Seçilen görsel hedef: [docs/design-reference.png](docs/design-reference.png).


## Senaryo kalite akışı (editorial policy 2)

Yeni üretimlerde supervisor, `editorial_direction` içinde ana soru, önem, neden-sonuç odağı,
sonuç hedefi, kapanış biçimi, sahne sayısı ve kaynak gereksinimini belirler. `critical_questions`
ile olayın açıklanması gereken sorularını, `attention_allocation` ile hangi bölüme daha
fazla zaman ayrılacağını tanımlar. Başlangıç planı 5–8 sahne önerir; süreler eşit
bölünmez. Kritik neden-sonuç açıklaması daha uzun, bağlantı ve kapanış daha kısa olabilir.
Anlatı sahnesi ile teknik çekim aynı şey değildir; bir sahne birden çok kısa klibe ayrılabilir. Uzmanların genel
sahne önerileri supervisor planına dayanır; uzman farklı bir sayı önerirse kabulünü supervisor değerlendirir. Önceki üretimlerin kaydedilmiş ayarları korunur.

Yazar yalnız anlatım paragraflarını üretir. Supervisor editörü metni yeniden yazmadan altı
ölçütle değerlendirir ve açık `approve/revise/cancel` kararı verir. Küçük üslup ve ifade farkları
onayı engellemez; büyük/kritik sapma bildirildiğinde onay verilemez. Alıntı kopyalamak zorunlu
değildir; paragraf indeksleri kod tarafından gerçek anlatım metnine bağlanır. Bir düzeltme turundan
sonra da reddedilirse süreç durur. Supervisor farklı sahne sayısını kabul ederse ortak plan da kabul edilen sayıya güncellenir.
Görsel aşama yalnız görsel alanları döndürür; kabul edilmiş
anlatım kodla birleştirilir. Taslaklar, kararlar ve görsel metadata ayrı kontrol noktalarıdır;
servis kesintisinden sonra tamamlanmış çağrılar tekrarlanmaz. Plan/bağlam değişirse kayıt geçersizleşir.

Dış kaynak araştırması varsayılan olarak kapalıdır (`STORY_RESEARCH_ENABLED=false`).
Bu modda yazar ve editör LLM bilgisiyle çalışır; dış doğrulama yapıldığı iddia edilmez,
kaynak yokluğu tek başına üretimi durdurmaz ve kaynak/alıntı üretilmez.
İsteğe bağlı kaynak modunu açmak için `STORY_RESEARCH_ENABLED=true` ve
`STORY_RESEARCH_USER_AGENT` yapılandırılmalıdır:
açıklayıcı bot adı/sürümü ve işletmecinin paylaşılabilir gerçek iletişim URL'si veya adresi.
İstemci kimliği yalnız Wikimedia HTTPS API isteklerinde kullanılır. Hesap e-postası otomatik
kullanılmaz. Kaynak metni alınamazsa süreç kaynak doğrulanmış gibi ilerlemez. Araştırma,
Wikipedia makale metnini getirir; bu bağımsız tarihsel doğrulama değildir. Kaynak kimliği ve
alıntının gerçekten metinde bulunması kodla, iddiayla anlam uyumu editör modeliyle kontrol edilir.

Yeni üretimler arayüzden tam akış olarak başlatılır; ayrı “yalnız senaryo” seçeneği yoktur.
Önceden `script_ready` durumunda bırakılmış üretimler **Yeniden dene** ile aynı kayıttan
medya aşamasına devam edebilir. Hata sonrası da tamamlanan geçerli aşamalar korunur;
plan veya girdi değiştiğinde ilgili kayıt yeniden değerlendirilir. Arayüz metin yazımı,
Supervisor metin incelemesi, görsel plan hazırlığı ve görsel inceleme durumlarını ayırır.

Editoryal akışta anlatım onayından sonra görsel yönergeler de supervisor LLM tarafından
incelenir. Miktar, ölçek, eylem ve zaman çelişkilerinde yalnız hedef sahnelerin görsel
alanları bir kez düzeltilir ve tekrar incelenir; onaylı anlatım korunur. Bu, medya
üretiminden önceki senaryo denetimidir. Görsel üretimi veya render sonrası model
incelemesi değildir. Her sonuç kontrol noktasına kaydedilir. `cta` alanı ayrı slogan
üretmez; onaylı son sahnenin anlatımını yansıtır. Dış kaynak modu kapalıyken bu inceleme
LLM bilgisine dayanan tutarlılık kontrolüdür; dış doğrulama yapıldığı iddia edilmez.

## Hedefli video düzenleme

Stüdyodaki geri bildirimi Supervisor mevcut video ve kurgu katmanlarıyla birlikte değerlendirir.
Örneğin “ilk iki sahnedeki 3D cisimleri kaldır” isteği kurgu katmanına aitse Video Editörü’ne
iletilir; kaynak görseller ve ses yeniden üretilmez. Kaynak resmin içeriği değişecekse Görsel
Tasarımcı, kaynak hareket değişecekse Video Üretim Agentı görevlendirilir. Geçerli medya ve
imzası eşleşen render parçaları yeniden kullanılır; düzenleme kapsamı dışındaki sahneler korunur.

## Remotion kurgu ve render

`@remotion/transitions`, `@remotion/effects`, `@remotion/motion-blur`, `@remotion/lottie`
ve `@remotion/rough-notation` paketleri 4.0.538 sürümünde kullanılır. Editör model sahneye göre
geçiş, renk/glow/vignette, kamera hareketi, yerel Lottie animasyonu ve metin vurgusu seçer;
her sahneye efekt eklemek zorunlu değildir. Motion blur yalnız görüntü/kameraya uygulanır;
yazı ve altyazı keskin kalır. Bu sürümde piksel efektleri ile motion blur aynı segmentte
birlikte kullanılamaz; farklı segmentlerde kullanılabilir. Lottie varlıkları kayıtlı yerel
animasyonlarla sınırlıdır.

Kurgu kararlarının zaman tabanı 30 FPS’tir; renderer bunları seçilen 30/60 FPS çıkışa çevirir.
60 FPS, grafik ve kamera animasyonlarını akıcılaştırır; düşük FPS kaynak videoya yeni hareket
ayrıntısı eklemez. Render sonrası teknik kontroller çözümleme, süre, kare hızı, siyah görüntü,
sessizlik ve altyazı sınırlarını denetler. İçerik ve estetik için son kullanıcı incelemesi gerekir.
Ayrıntılar: [Remotion kurgu araçları](docs/remotion-editing.md).

Geçici `.test` çıktıları, medya, önbellekler ve gizli `.env` dosyası Git dışında tutulur;
`backend/tests` altındaki kaynak testler sürüm kontrolüne dahildir.
