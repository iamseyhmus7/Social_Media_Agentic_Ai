# Görsel ve hareket kalitesi — 5 Kasım 2026

Yeni üretimler varsayılan olarak `references_v1` ve `fastwan5b_v1` profillerini kaydeder. Eski ayar
görüntülerinde bu alanlar yoksa Schnell ve LTX 0.9.6 akışı sürer. Devam eden işler
ve mevcut kullanıcı medyası değiştirilmez. `.env` dosyasının üzerine yazılmamalıdır.

## Görseller ve kota

Normal üretimde yalnız Cloudflare FLUX.2 Klein 9B kullanılır (576×1024,
multipart). Lucid/Schnell adaptörleri eski kayıtların uyumluluğu içindir;
yeni akış model karşılaştırması veya otomatik görsel yeniden üretimi yapmaz.
Hazır dosyalar özetleriyle tekrar kullanılır. Studio kaynak kontrol paneli ve
ara görsel onayları kaldırılmıştır; bitmiş videonun yayın onayı korunur.

Ücretsiz bütçe yetersizse Openverse üzerinden CC0, public domain veya CC BY
lisans kaydı bulunan ilgili görseller aranır. NC/ND/SA veya eksik lisanslı
sonuçlar kullanılmaz. Kaynak, eser sahibi, lisans URL'si ve atıf kaydedilir.
İndirilen gerçek kareye göre yalnız hareket yönergesi uyarlanır; anlatım korunur.
Uygun kaynak bulunamazsa yanıltıcı/ilgisiz görsel kullanılmaz; hazır medya korunur.

Müzik Seçici, senaryodan duygu, tempo ve arama sorguları çıkarır. Openverse ve
ccMixter kataloglarını birlikte arar, uygun açık lisanslı enstrümantal adayları
sırasıyla dener. Uygun kayıt indirilemezse kurgu konuşma ve efektlerle devam eder.
Seçim ve dosya özeti kalıcıdır. Müzik ve konuşma ayrı normalize edilir, konuşma sinyaline bağlı
sidechain compression müziği kısar; müzikte kısa giriş/çıkış geçişi uygulanır.
Üçüncü taraf kaynakları paylaşım metinlerine ve ZIP'teki media-credits.txt
belgesine eklenir.

10.000 neuron, Cloudflare hesabının tüm modellerinin paylaştığı günlük havuzdur.
Kota 00.00 UTC / Türkiye saatiyle 03.00'te yenilenir. `cloudflare_budgets`, hesap
özetine ve UTC gününe göre atomik, muhafazakâr rezervasyon yapar. Başarısız veya
yanıtı kaybolan çağrının harcaması iade edilmiş varsayılmaz. Sağlayıcı günlük kota
reddinde havuz gün sonuna kadar kapatılır; açık lisanslı kaynaklara geçilir.
Yalnız istek hızı sınırlaması günlük kota tükenmesi olarak kaydedilmez.

Bu kayıt sağlayıcı bakiyesi değildir. Başka uygulamalardaki tüketimi kapsamaz;
bütçe API yanıtı bunu açıkça belirtir. Ücretsiz hedef için Workers Free hesabı kullanılmalıdır;
uygulama Cloudflare aboneliğini yükseltmez ve ücretli yedek sağlayıcı çağırmaz.

## Referanslar ve kullanıcı müdahaleleri

- `GET/POST /api/v1/projects/{id}/references`: özel referans kütüphanesi.
- `PATCH /api/v1/projects/{id}/references/{reference_id}`: sonraki üretimler için
  referansı etkinleştir/devre dışı bırak. Devam eden üretimin snapshot'ı değişmez.
- `POST /api/v1/projects/{id}/shots/{shot_id}/change`: `run_id`,
  `action: image|motion|pin`, `instructions`. Tamamlanmış videoda yeni sürüm açılır;
  yalnız hedef çekim üretilir. Ses ve diğer çekimler korunur. Son kullanıcı onayı
  yeni sürüm için tekrar gereklidir.
- `POST /api/v1/runs/{id}/media-review`: `shot_id`, `asset_id`, `accept: true`.
  Kabul dosya özeti, girdi imzası ve güncel sürüme bağlıdır.
- `GET /api/v1/media/image-budget`: yaklaşık uygulama rezervasyonları.

PNG/JPEG/WEBP, en fazla 12 MB ve 16 MP kabul edilir; dört etkin referans sınırı
vardır. Referanslar sahiplik, CSRF ve dosya özetiyle korunur. Referans türü
karakter/mekândır; reklam, ürün ve logo özellikleri bu geliştirmeye dahil değildir.

## Wan paketi ve GPU kabulü

`wan_runtime_lock.json` kaynak Git/Hugging Face revision'larını sabitler. İlk
kurulum üç özel **CPU** notebook'u hazırlar: core (ComfyUI, bağımlılıklar, T5, VAE),
high ve low (ayrı Q5_K_M uzman dosyaları). Çift ağırlık notebook çıktı diskine tek
paket olarak sığdırılmaz. GPU işi bu üç salt okunur kaynağı kullanır; paket
dosyalarının boyut ve SHA-256 özetleri, Python ABI'si ve kaynak kilidi kontrol edilir.
Core bağımlılıkları CPU aşamasında wheel olarak çözülür ve özetlenir; GPU aşaması
internetsiz kurulumu bu paketlerden yapar.

Standart profil: video için tek GPU, 480×832, 24 FPS, en fazla 5 saniye, 20 örnekleme adımı,
10. adımda uzman değişimi. Q5 ağırlıklar FP16 hesaplamayla açılır. High ve low
ayrı Comfy API grafikleriyle çalışır; aralarında yalnız CPU conditioning/latent
korunur, modeller boşaltılır. Yerel API yalnız notebook içinde 127.0.0.1'e bağlanır;
notebook halka açık sunucuya veya tünele dönüştürülmez.

Wan Q5 için varsayılan hız profili `lightning4_v1`, sabit LightX2V I2V Seko V1 high/low
LoRA'larıyla toplam dört adım (2+2), CFG 1 ve shift 5 kullanır. Eski ayar
görüntüleri `standard20` olarak korunur. Yalnız ek bir özel CPU paketi hızlandırma
ağırlıklarını hazırlar; üç büyük paket yeniden indirilmez. Teknik ve görsel kabul
kontrolleri devam eder. Ayrıntılar: [Kaggle hız profili](kaggle-logging.md).

24 GiB host RAM, 14 GiB geçici disk ve en az 14 GiB GPU belleği ön kontrolü vardır.
Bu alt sınırlar çalışabilirlik/kalite garantisi değildir. Dosyaların boyutu VRAM
ihtiyacına eşit değildir. İki T4 belleği birleştirilmez.

Wan Q5 ile ilk gerçek videonun ilk çekimi tek başına gönderilir. Teknik çözümleme ve gerçek
kare incelemesinden geçerse aynı klip korunur; kalan çekimler ancak bundan sonra
gönderilir. Onay kaydı hesap ve paket kilidine bağlıdır; kullanıcı medyası hesaplar
arasında paylaşılmaz. Kaynak/örnekleme hatasında iş otomatik tekrarlanmaz, kalan
GPU işleri durur. Başarılı kısmi çıktılar tekrar kullanılabilir. FastWan ile yeni
paralel kurgu üretimlerinde açılış sahnesi ayrı bir Kaggle işi olarak gönderilir.

Klip incelemesi başlangıç/son örneklerini ve ortadaki beş ardışık kareyi kullanır;
tüm hareketin doğrulandığı iddia edilmez. Kaynak resim hatası görsel aşamasına,
hareket hatası yalnız klibe yönlenir. Otomatik düzeltme en fazla üç çekimde,
her medya aşaması/çekim için bir ek denemeyle sınırlıdır.

## Dağıtım ve kabul durumu

Alembic `0004_visual_quality` referans ve kota tablolarını ekler. Dağıtımda API ve
worker birlikte güncellenmeli ve migration uygulanmalıdır. Kod değişikliği kendi
kendine üretim hesabında video başlatmaz.

Yerel sözleşme testleri gerçek görsel/video modelinin canlı kabulü sayılmaz.
T4 üzerinde ilk gerçek çekimin görsel kalitesi ve uçtan uca belgesel/hikâye
üretimleri ayrıca gözlenmelidir; ölçülmemiş hız veya Higgsfield eşitliği vaat edilmez.

5 Kasım yerel doğrulaması: yeni kaynak medya testlerinde 17 başarılı; son Wan
paketleme/iş akışı kontrollerinde 2 başarılı; geniş backend koşusunda 388 başarılı,
2 atlanan test. Önceden HEAD kopyasında da aynı biçimde başarısız olduğu doğrulanan
4 test bu koşudan ayrı tutuldu: engagement yönergesinin eski sözcük beklentisi,
Remotion geçiş kaydı uyumsuzluğu, Supervisor model seçimi testinin ortam ayarına
bağımlılığı ve brief yönergesinin eski sözcük beklentisi. Bunlar bu değişiklikte
değiştirilmedi. Frontend derlemesi, 4 Sites ve 8 yönlendirme/geri bildirim testi
başarılı. Test raporları `output/quality-final-20261105.xml` ve
`output/quality-sources-20261105.xml` altında. Tarayıcı aracı yerel önizlemeye
erişemedi; görsel arayüz QA'sı tamamlanmış sayılmadı. Canlı sağlayıcı/GPU kabulü
bu ilk yerel doğrulamada yapılmadı; testler dış sağlayıcı kotası tüketmedi.

5 Kasım dağıtımı: Kullanıcının Docker güncelleme izniyle API, worker, beat ve web
yeniden oluşturuldu. Postgres/Valkey konteynerleri, named volume'lar ve medya
korundu. Migration `0004_visual_quality` uygulandı; API sağlıklı, Celery worker
hazır ve beat çalışıyor. Worker/API kaynak dosya özetleri yerel kodla eşleşti;
profil `references_v1` / `wan22_q5_v1`. Önceki imajlar
`before-wan-20261105` etiketinde, veritabanı yedeği
`output/docker-wan-acceptance-20261105/database-before.dump` altında tutuluyor.

Kaynaklar: [Cloudflare](https://developers.cloudflare.com/workers-ai/platform/pricing/),
[Klein](https://developers.cloudflare.com/workers-ai/models/flux-2-klein-9b/),
[ComfyUI Wan](https://docs.comfy.org/tutorials/video/wan/wan2_2),
[QuantStack](https://huggingface.co/QuantStack/Wan2.2-I2V-A14B-GGUF).

## Toplu açık lisanslı kaynak seçimi

Görsel başına metin modeliyle aday sıralama kaldırıldı. Kod lisans, boyut ve konu
ipuçlarıyla adayları sıralar; en fazla dört çekim için ikişer indirilebilir aday
toplar. Kare seçimi ve hareket yönergeleri tek görsel model çağrısında hazırlanır.
Bu çağrının yanıt sınırı 180 saniyedir. Aday dosyaları, dosya özetleri ve seçim
sonuçları çekim bazında saklanır; yeniden deneme indirmeleri tekrarlamaz.
Openverse istek sınırı/servis hatası, görsel bulunamamasıyla karıştırılmaz.

Seçim, sahnenin somut olayı ve tüm senaryo bağlamıyla yapılır. `suitable=false`
sonucu ilgisiz adayları eler; kalan sorgular sınırlı olarak denenir. Uygun kare
bulunamadığında yanlış fotoğrafı seçmek yerine açık hata verilir. Eski v1 seçimleri
yeni uygunluk önbelleğine taşınmaz. Sahiplik kontrollü çekim düzeltmesi birden fazla
çekimi aynı işlemde yeniler; tamamlanmış sesler ve diğer kaynaklar korunur.
