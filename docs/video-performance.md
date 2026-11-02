# Video yürütme ve performans sözleşmesi

Yeni v3 üretimler `VIDEO_EXECUTION_POLICY=planned_v1` kullanır. Supervisor, yaratıcı brief ile birlikte bağımlılıkları doğrulanmış `ExecutionPlan` üretir. Normal ilerlemede kod hazır görevi bu plana göre çalıştırır. Kalite hatası, süre sorunu ve kullanıcı geri bildirimi yaratıcı model kararlarına geri döner. DeepSeek metin rollerinde, MiMo Supervisor ve medya rollerinde kullanılmaya devam eder. Planlama verisi çalıştırılabilir kaynak koda dönüşmez.

Eski kayıtların ayar snapshot'ında politika yoksa `legacy` kabul edilir. Devam eden uzak işin hazırlanmış `run.py`, manifest, engine ve profil kimliği değiştirilmez. Yeni görevlerde profil çekim planıyla birlikte dondurulur. Kullanıcının konu, geri bildirim ve yayın onayı API'leri değişmez.

## Kurgu

`perception-cache/`, proje kapsamında klip SHA-256, inceleme şeması/prompt sürümü ve model kimliğiyle anahtarlanır. Örnek karelerde görülen olgular saklanır; senaryoya uygunluk kararı yeni senaryoyla metin üzerinden yeniden verilir. Bu gözlemler kesintisiz hareket veya ses doğrulaması sayılmaz.

MiMo `EditDecisionV2` ile çekim sırasını, kaynak başlangıcını, süre ağırlıklarını ve tasarımı seçer. Derleyici ölçülen anlatım sürelerini kümülatif 30 FPS bütçelerine dönüştürür; kaynak ve geçiş ek kare sınırlarına uyar. Süre sorunu yalnız ilgili sahnede, grafik/ses zamanlama sorunu yalnız o sahnenin işaretlerinde en fazla iki kez düzeltilir. Derlenmiş `AutoEditPlan` mevcut renderer sözleşmesini korur. Kaynak yetersizse dondurma, döngü veya anlatım hızlandırması yapılmaz.

## Render

Kod önbelleği kaynak dosyaları ve package lock özetine bağlıdır. Docker'da `REMOTION_BUNDLE_CACHE=/app/data/remotion-code-cache` ile yeniden başlatmalar arasında korunur. Önce boş public diziniyle yalnız kod derlenir; her üretimin servis dizini bu koddan ve kendi özel `render-inputs/` dosyalarından hazırlanır. Ortak önbelleğe kullanıcı medyası girmez. Render paralelliği ikidir.

Önizleme, final ile aynı bileşen ve manifestten 1080×1920 kritik kareleri üretir. Açılış, bitiş, çekim ortaları, geçiş sınırları, grafik ve altyazı sayfası değişimleri kapsanır. İnceleme makbuzu manifest, renderer, kaynak dosyaları ve üretilen karelerin SHA-256 değerlerine bağlanır. Değişiklikte final durur ve yeni inceleme gerekir. Doğrulanmış video girdisi desteği varsa MiMo en fazla üç adet iki saniyelik hareket kesiti isteyebilir. Örneklerin dışındaki hareket ve ses için doğrulama iddiası yapılmaz.

## Kaggle profilleri

`legacy_fp32`, mevcut FP32 / 480×832 / 24 FPS / sekiz adımlı sequential offload profilidir. `dual_fp32_model_v1`, tek Kaggle işi içinde GPU başına ayrı süreç ve model offload kullanır. Ağırlık hazırlığı ve T5 kodlaması iş başına bir kez yapılır. Süreçler çekimleri bağımsız üretir; ana süreç sonucu birleştirir. Bellek veya süreç hatasında tamamlanan klipler korunur ve yalnız eksikler güvenli profille tamamlanır.

`KAGGLE_MOTION_PROFILE=certified_auto`, geçerli ölçüm belgesi bulunana kadar güvenli profili seçer. Belge engine kaynak özetine bağlıdır; iki sabit seed için her iki profilin toplam dört kısa klibi doğrulanmalı ve aynı iş yükünde duvar saati kazancı en az %20 olmalıdır. Motor değişirse eski belge adayı etkinleştiremez. FP16'ya, daha az adıma veya daha düşük kaliteye otomatik geçilmez.

Tek bileşen kontrolü `python -m scripts.check_video_gpu` ile aynı dayanıklı iş kaydı üzerinden sürdürülür; yeniden çağırmak yeni Kaggle işi oluşturmaz. `data/qa-video-speedup/gpu-job.json` bu kimliği saklar. Çıktıların görsel incelemesi tamamlandıktan sonra `--visual-checked` ölçüm belgesini kaydeder. Bu komut üretim grafiğini çağırmaz, model runtime hazırlamaz ve en fazla dört adet iki saniyelik klip üretir. Mevcut hesap kilidini kullanır.

## Ölçüm ve geri alma

Model istekleri `_model_metrics` içinde rol, model, şema, deneme, girdi boyutu, medya boyutu, süre, HTTP durumu ve varsa token kullanımını kaydeder. Doğrulama tekrarları `validation_failed` ile ayrılır. İstek/yanıt içerikleri ve kimlik bilgileri metriğe yazılmaz. Render metriği bundle anahtarı, cache hit, aşama süreleri ve kare sayısını içerir.

Geri alma için yeni üretimlerde `VIDEO_EXECUTION_POLICY=legacy` ve `KAGGLE_MOTION_PROFILE=legacy_fp32` seçilebilir. Var olan üretim snapshot'ları değiştirilmez. Kalite kontrolü, final 1080×1920/30 FPS, özgün anlatım hızı ve kullanıcının yayın onayı korunur.

İlk yerel sentetik kontrolde üç kare için soğuk bundle 48.011 saniye, sıcak bundle hazırlığı 0.793 saniye ölçüldü; sıcak kullanım Webpack çalıştırmadı. Bu sınırlı ölçüm toplam video süresi veya GPU hızlanması garantisi değildir. Bileşen raporları `data/qa-video-speedup/` altında tutulur.

2026-10-27 kabul sonucu: dört kısa GPU dosyası çözümlendi ve hareket örnekleri incelendi. Adayın GPU 1 süreci `exit_-9` ile kapandı; birleşik sonuç manifestinde yalnız bir aday klibi kaldı. Bu nedenle aday kabul edilmedi ve `legacy_fp32` etkin kaldı. 197.280 ve 105.444 saniyelik profil sürelerinden hesaplanan oran, başarısız aday için üretim hızlanması kanıtı değildir. Yeni motor, dışa aktarımı atomik dosya adı ve ayrı klip makbuzuyla kaydeder; süreç kapanışında tamamlanan klip ana süreç tarafından geri kazanılır. Bu son dayanıklılık değişikliği için ek GPU işi başlatılmadı; yerel sözleşmeyle doğrulandı.

Son yerel kontrol 180 başarılı, 1 atlanan backend testi içerir. Gerçek kullanıcı üretim grafiği için yeni bir uçtan uca test başlatılmadı. Son renderer kontrolünde altı örnek kare ve 21 karelik sentetik geçiş kesiti üretildi; çözünürlük/FPS ve tam çözümleme kontrol edildi. Yük altındaki bu kontrolde sıcak bundle hazırlığı 1.308 saniyeydi ve Webpack çalışmadı.

Dağıtımda mevcut eski editör işi kesilmedi: yeni worker örneği release imajıyla başlatıldı, önceki worker'a yalnız elindeki görevi bitirip çıkması için Celery warm shutdown gönderildi. Ortak işletim sistemi/SQL kilidi ağır işleri tek tek yürütmeye devam eder. Eski worker'ın otomatik yeniden başlaması kapatıldı. Yeni üretimler `planned_v1`, devam eden eski üretim kendi `legacy` snapshot'ıyla çalışır. Eski örnek durduktan sonra normal Compose ölçek düzenine geçmeden önce yeni worker'da aktif üretim olmadığı kontrol edilmelidir.
