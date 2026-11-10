# Kaggle üretim günlükleri

Worker, takip ettiği uzak işin **kayıtlı sürümüne ait sayısal oturumunu** çözer ve
canlı SSE günlüklerini sınırlı süreyle okur. Üretim durumu kontrol edilirken yeni
satırlar Docker worker loguna iş/üretim kimliğiyle yazılır:

```powershell
docker compose logs --since=10m -f worker
```

Özel kalıcı kopya: `data/media/<project>/<run>/kaggle/<job>/remote.log.jsonl`.
`remote-log-state.json` oturum kimliğini ve okuma konumunu tutar. Worker yeniden
başlarsa aynı satırlar tekrar basılmaz. Bunlar genel API yanıtına eklenmez;
anahtarlar, bearer değerleri, URL'ler ve terminal kontrol kodları ayıklanır.
Günlük bağlantısı kesilirse üretim yeniden gönderilmez veya durdurulmaz; sonraki
kontrolde aynı oturumdan devam edilir. Bir okumada en fazla 2 MiB işlenir.

Yeni Wan oturumları şu bilgileri standart çıktıya yazar:

- Girdi kontrolü, paketlerin SHA-256 doğrulaması ve kurulum aşamalarının süreleri.
- ComfyUI başlangıç kaydı ve çalışma motorunun satırları. `comfy.log` ayrıca
  notebook çıktısında en fazla yaklaşık 2 MiB tutulur ve sonuçla birlikte alınır.
- ComfyUI WebSocket'inden gerçek `executing` düğümü ve örnekleme `progress`
  değeri. Böylece `CLIPTextEncode` ile `KSamplerAdvanced` ayırt edilebilir.
- Her 30 saniyede kart başına GPU kullanımı/belleği, süreç CPU/RAM'i, swap ve I/O.
- Hatanın aşaması, istisna türü, sınırlı mesajı ve traceback; son manifestte aşama
  süreleri ve tanılama özeti. İstek doğrulama hatasının ComfyUI yanıtı da kaybolmaz.

Bu gözlem kodu modeli, örnekleme adımlarını veya kalite profilini değiştirmez.
Eski oturumlar `CUDA_VISIBLE_DEVICES=0` ile tek kart kullanıyordu. 6 Kasım hız
düzeltmesinden sonraki oturumlarda video GPU 0 üzerinde, metin kodlama varsa
GPU 1 üzerinde çalışır; tek kart varsa metin kodlama da GPU 0'ı kullanır.
İki T4'ün belleği birleştirilmez. Yüksek CPU/
düşük GPU, düşük boş RAM ve swap veya uzun model yükleme ancak gerçek ölçümle
darboğaz olarak yorumlanmalıdır.

Çalışmakta olan notebook'un kodu sonradan değişmez. Eski oturumun Kaggle'da
görünmeyen geçici ComfyUI günlüğü geriye dönük üretilemez. Yeni tanılamayı görmek
için çalışan işin tamamlanması veya standart iptal yoluyla kapanması gerekir.
Sonraki normal üretim güncel tanılama kodunu ve hazır model paketlerini kullanır.

## 6 Kasım hız düzeltmesi

Metin kodlama artık CPU'ya zorlanmaz. `SahneCachedText`, pozitif ve negatif metni
GPU'da kodlar; aynı oturumda kodlayıcı nesnesini ve elde edilen CPU tensorlarını
yeniden kullanır. Anahtar; motor sürümü, model kilidi, kodlayıcı dosyası ve tam
metni kapsar. Sonuçlar özel notebook çıktısındaki `conditioning/cond-<sha256>.pt`
dosyalarında atomik saklanır. Yalnız tamamlanıp alınabilen sonuçlar aynı üretimin
sonraki Kaggle girdilerine kopyalanır; farklı kullanıcı/üretim önbelleği paylaşılmaz.
Dosya boyutu ve SHA-256 kontrol edilir, yüklemede `weights_only=True` kullanılır.
Yeni prompt yeniden kodlanır; değişmeyen negatif prompt tekrar kullanılabilir.
Oturum sağlayıcı tarafından çıktıları kaydetmeden öldürülürse o oturumun geçici
önbelleğinin kurtarıldığı varsayılmaz.

Kodlayıcı, VAE ve o anda gereken uzman ağırlığı, doğrulanmış bağlı paketlerden
8 MiB tamponla yerel scratch alanına kopyalanır; çıkarım bağlı depolama dosyalarını
bellek eşlemesi üzerinden tekrar tekrar okumaz. Kopya SHA-256 doğrulaması sürer.
CPU metin kodlamasına yol açan `--lowvram` ve zorunlu agresif boşaltma ayarı
kaldırılmıştır; ComfyUI'nin normal bellek yönetimi kullanılır. `standard20`
profilinde model, çözünürlük, FPS, CFG ve 20 örnekleme adımı korunur.

`conditioning_encoded`, `conditioning_cache_hit` ve `model_staged` günlükleri
süreyi ayrı gösterir. `runtime_metrics` metin GPU'sunu, yerel depolamayı ve motor
sürümünü kaydeder. Bu değişikliklerin gerçek T4 hızlanması canlı klip tamamlanınca
ölçülür; yerel regresyon testleri performans kanıtı değildir.

## Dört adımlı hız profili

Yeni üretimlerin `WAN_SAMPLING_PROFILE` varsayılanı `lightning4_v1`'dir.
`standard20` eski profili seçer. Eski ayar görüntüleri alan eksikse standard20
kullanır; devam eden işler sessizce değiştirilmez. Genel Bakış'ta yeni video
başlatıldığında sunucudaki güncel profil üretimin ayar görüntüsüne kaydedilir.

LightX2V'nin native ComfyUI I2V Seko V1 iş akışındaki ayrı high/low LoRA'lar,
toplam 4 adım (2 + 2), CFG 1, shift 5, Euler/simple ve strength 1 kullanılır.
Revizyon ve beklenen SHA-256 değerleri `wan_acceleration_lock.json` içindedir.
Üç büyük base paketi korunur; yalnız ek özel CPU `lightning4` paketi iki LoRA'yı
hazırlar. GPU başlamadan hem base kilidi hem hızlandırma kilidi doğrulanır.

Hız profilinin kabul kaydı ve çekim imzaları standart profilden ayrıdır. Başka
profilin klibi bu profilin ölçümü olarak yeniden kullanılmaz. Görsel inceleme,
teknik klip denetimi ve insan onayı sürer. Dört adım, standart modelde yalnızca
adım sayısını azaltmak değildir; uygun distillation ağırlıkları olmadan bu profil
çalıştırılmaz. Gerçek T4 hızı ve görsel sonucu ayrıca kaydedilir.

## Gerçek giriş kadrajıyla görsel kontrol

Wan giriş görselini 480×832 merkez kırpmasıyla kullanır. Klip kontrolü de aynı
kadrajı referans alır; örneğin kare eski kaynaktaki kenar öğeleri dikey klipte
kaybolmuş kabul edilmez. İstekte açıkça istenen hareket/olay, kaynakta başlangıçta
bulunmadığı için tek başına tutarsızlık sayılmaz. Kaynak kimliği, mekân, anatomi,
titreme ve kamera hareketi hâlâ kontrol edilir.

Değerlendirme sürümü `wan-input-crop-and-action-v2` olarak kaydedilir. Yeniden
kullanılan bir klibin değerlendirme sürümü güncellendiğinde aynı klip incelenir;
eski bulgu geçmişte saklanır. Reddedilen kaynaklar normal stüdyo kontrolleriyle
kullanıcı tarafından incelenebilir veya ilgili çekim için değişiklik istenebilir.
