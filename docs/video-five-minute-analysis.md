# Beş dakika hedefi: ölçülen darboğazlar ve gerekli değişiklikler

2026-10-27 tarihinde görünür Tarayıcı sekmesinden başlatılan Çin Seddi üretiminin analizi. Run: `ffe3cceb-7c4c-4b45-8a6f-9f491ae2aebc`. Ham ölçümler: `data/qa-video-speedup/china-wall-bottleneck-analysis.json`.

## Sonuç

Üretim 4839.756 saniyede (80 dakika 40 saniye) editör aşamasında başarısız oldu. Son hata: `Model üç denemede doğrulanabilir görev çıktısı üretmedi.` Remotion render başlamadı. Kaynak klipler, sesler ve görseller korunuyor. Bu analiz sırasında yeni üretim veya GPU işi başlatılmadı.

| Aşama | Ölçülen duvar saati |
|---|---:|
| Supervisor | yaklaşık 120 s |
| İçerik stratejisi | 18.177 s |
| Senaryo | 133.765 s |
| Seslendirme | 155.135 s |
| Görsel ve çekim planı | 342.889 s |
| Hareketli kaynaklar: gönderim, hazırlık, üretim, alma, doğrulama | 2370.478 s |
| Editör: örnekler, inceleme ve başarısız plan denemeleri | 1697.929 s |

## 1. Editörün büyük yanıtı tekrar üretmesi

`planned_edit.prepare_decision()` bütün kurgu kararını `EditDecisionV2` olarak tek istekte alıyor. Girdi yaklaşık 13.6 bin token: tam senaryo, bütün çekim promptları, gözlemler, kaynaklar ve büyük iç içe JSON şeması. Çıktı da gözlemleri ve uzun tasarım nesnelerini yeniden içeriyor.

`Evren.generate()` Pydantic/JSON hatasında bütün yanıtı en fazla üç kez istiyor. Sahneye özel düzeltme ancak bu temel doğrulama geçtikten sonra devreye giriyor. Dolayısıyla önceki yerel onarım yaklaşımı temel şema hatalarını kapsamamış.

| Deneme | Süre | Sonuç | Completion token |
|---|---:|---|---:|
| 1 | 656.310 s | validation_failed | 16384 |
| 2 | 298.840 s | validation_failed | 6409 |
| 3 | 221.729 s | validation_failed | 7353 |

Toplam 1176.879 saniye, yani 19 dakika 37 saniye; geçerli kurgu planı yok. İlk completion sayısı olası bir çıktı sınırına işaret ediyor, ancak `finish_reason`, reasoning token ayrıntısı ve güvenli doğrulama hata konumu kaydedilmediği için kesilme veya belirli alan hatası kesinleştirilemiyor. JSON şemasını yalnız prompt içinde vermek sağlayıcıda zorunlu şema uyumu uygulandığını kanıtlamaz.

Gerekli değişiklik: genel yaratıcı yönü bir kez al; ardından yalnız ilgili sahnenin kısa, kimlik tabanlı kararlarını üret. Global süreler ve hazır gözlemler model çıktısında yeniden yazılmasın. Doğrulama hatası alan/scene yoluyla kaydedilsin; bozuk tek sahne düzeltilsin, geçerli sahneler kalıcı saklansın. JSON kesilmesi ayrı bir hata sınıfı olsun. Çok büyük planı yeniden istemek yerine dar yanıt bütçeleri ve görev başına süre sınırı uygulansın. Sağlayıcının gerçek yapılandırılmış çıktı desteği varsa sözleşmesi doğrulanarak kullanılsın.

## 2. İlk üretimde ardışık görsel inceleme

13 ayrı `ClipPerception` çağrısı tek tek beklenmiş: toplam 357.603 saniye (5 dakika 58 saniye). Hiçbiri yeniden denenmemiş. En uzun tek inceleme 59.104 saniye. Önbellek yeniden kurguyu hızlandırır; ilk videodaki bu maliyeti kaldırmaz.

Gerekli değişiklik: küçük ve kimliği belirli inceleme grupları, sağlayıcı sınırlarına uygun sınırlı eşzamanlılık, kısa olgu çıktısı ve ayrı sahne uygunluk kararı. İptal, model bütçesi ve metrik yazımları eşzamanlı çalışmaya güvenli hâle getirilmeden yalnız thread eklenmemeli. Kalıcı GPU altyapısı seçilirse tamamlanan çekimler geldikçe inceleme sonraki çekimlerle örtüştürülebilir. Mevcut Kaggle son-dosya toplama yöntemi bunu sağlamıyor.

## 3. GPU: gerçek hesaplama maliyeti

13 klip toplam 1930.079 saniye (32 dakika 10 saniye) üretim harcamış. Profil duvar saati 1979.766 saniye; model hazırlığı ayrıca 286.720 saniye. Günlükte 16.65 GiB ağırlık kopyası 148.7 saniye, T5 ağırlık yüklemesi yaklaşık 51 saniye. Gerçek 13 prompt kodlaması bunun küçük bir parçası; `text_seconds` adı bütün hazırlığı topluyor ve yalnız metin kodlaması olarak yorumlanmamalı.

Çekimler GPU 0 üzerinde sırayla FP32 ve sequential CPU offload ile üretilmiş. Dört–beş saniyelik klipler yaklaşık 138–174 saniye sürmüş. Günlükte sekiz örnekleme adımı yaklaşık 68–87 saniye; son adım sonrasında bir sonraki çekime kadar yaklaşık 66–84 saniye daha var. Bu son bölüm çözümleme/dışa aktarma/araç ek yüklerini içeriyor; ayrı zamanlayıcı olmadan tamamını VAE veya encode'a atfetmek doğru değil.

Anlatım 46.72 saniye; kaynaklar frame yuvarlamaları ve geçiş paylarıyla 56.208 saniye üretilmiş. Fazladan yaklaşık %20 kaynak süre maliyeti var. Gereken geçiş payları çekimden önce seçilirse gereksiz pay azaltılabilir; bu tek başına beş dakika sağlamaz.

İdeal iki GPU yalnız mevcut 1930 saniyelik işi kusursuz bölerse yaklaşık 965 saniye (16 dakika 5 saniye) eder. Hazırlık ve diğer agentlar buna dahil değildir. Bu bir iyimser hesap, ölçülmüş paralel üretim sonucu değildir. Daha önceki iki GPU adayında alt süreç `exit_-9` ile sonlanmıştır; host RAM eksikliği henüz kanıtlanmamıştır. İki GPU sürecinin CPU RSS, GPU allocated/reserved, bellek başına tepe değerleri ve çıkış nedenleri ayrı izlenmelidir.

Diffusers belgeleri sequential offload'un alt modülleri sürekli CPU/GPU arasında taşıdığı için çok yavaş olabildiğini, model offload'un ise daha fazla GPU belleği istediğini açıklıyor. Bu nedenle yalnız ikinci GPU'yu açmak bu profili beş dakikaya indirmez:
https://huggingface.co/docs/diffusers/v0.35.1/en/optimization/memory

Gerekli değişiklik: beş dakika hedefi için sıfırdan notebook hazırlığı kritik yoldan çıkarılmalı; model bellekte hazır olmalı, yeterli bellekte uygun hassasiyet/çekirdekler kullanılmalı ve çekimler gerçekten paralel çalışmalı. FP16/BF16/quantization kalite ve donanım uyumluluğu ölçülmeden etkinleştirilmemeli. Yeni ücretli donanım veya servis bu analiz kapsamında açılmadı.

## 4. Diğer agentlar

Senaryo 125.345 saniyelik model çağrısı, çekim planı 157.857 saniyelik model çağrısı içeriyor. Tekrarlanan ortak stil/continuity metinlerini her çekim nesnesinde uzun uzun yazdırmak çıktı hacmini büyütüyor. MiMo ortak yaratıcı tanımları bir kez seçebilir; çekimler kısa farkları ve kimlikleri döndürür, araç girdileri ortak tanımlarla derlenir.

Ses aşamasında iki karşılaştırmalı dinleme 105.793 saniye. Aynı kullanıcı/marka için önceden doğrulanmış anlatıcı seçimi yeni senaryoda yeniden eleme gerekmiyorsa yeniden kullanılabilir. Bu, yeni ve farklı ses ihtiyacında yapılan dinlemeyi kaldırmak anlamına gelmez. Görsel üretim de 13 istek boyunca seri ilerliyor; sağlayıcı kota/kapasitesi ölçülerek sınırlı paralellik değerlendirilmeli. Ses süresi nihai zamanlamayı belirlese de görsel içerik hazırlığının tamamı ses bitimine bağımlı olmak zorunda değil.

## 5. Beş dakika için iki üretim tercihi

1. Her çekimin sıfırdan AI hareketli klip olması korunacaksa, modelin hazır tutulduğu ve ölçülmüş yeterli paralel kapasitesi olan GPU altyapısı gerekir. Mevcut ücretsiz Kaggle/T4/FP32 akışıyla 300 saniye üst sınırı desteklenmiyor. Sıcak GPU bile tek başına yeterli kabul edilmemeli; model çağrıları ve editör de aşağıdaki bütçelere yaklaşmalı.
2. İçeriğe uygun karma üretimde agent her sahnenin gerçekten AI klip gerektirip gerektirmediğini seçebilir. Ölçek, harita, diyagram, tipografi gibi anlatımlar doğrudan Remotion animasyonlarıyla; gerçek özne hareketi gerekenler AI kliplerle üretilebilir. Bu bir sabit video şablonu değildir. Fakat her sahnenin AI video olmasıyla aynı üretim tercihi de değildir; kalite/hareket gereksinimi gizlice değiştirilmemelidir. Gerekli genel grafik bileşenleri ve sahne sözleşmeleri geliştirilmeden mevcut renderer bunların hepsini yapıyormuş gibi sunulmamalı.

Önerilen sıra: editörün tüm-plan tekrarını kaldırma ve tanılamayı tamamlama → görsel/ses/model çağrılarındaki seri beklemeleri azaltma → GPU için sıcak altyapı veya içerik uyumlu karma üretim seçimi → aynı referanslarla uçtan uca ölçüm. Remotion bundle önbelleği faydalı, ancak bu test render'a ulaşmadığı için toplam süredeki temel sorunu çözmemiştir.

Örnek 300 saniyelik duvar saati bütçesi: yaratıcı plan/senaryo 30 s; ses ve kaynaklar eşzamanlı 150 s; kurgu/inceleme 45 s; final render/teknik kontrol 60 s; aktarım payı 15 s. Bunlar kabul hedefleridir, elde edilmiş sonuç veya garanti değildir. Kuyruk, sağlayıcı gecikmesi ve soğuk başlangıç bu hedefi aşarsa açıkça raporlanmalı; daha uzun bekleme hızlandırma sayılmamalıdır.
