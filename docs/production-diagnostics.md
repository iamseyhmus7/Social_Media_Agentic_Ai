# Üretim doğrulama hataları

Pydantic `ValidationError` hataları `pipeline.execute` sınırında ayrı yakalanır.
Eksik Python paketi hatalarıyla aynı mesaj altında gösterilmez.

Her hata için 12 karakterli bir takip numarası oluşturulur. Aynı numara:

- Arayüzde üretimin hata mesajında ve etkinlik günlüğünde yer alır.
- Üretim kaydının `outputs._diagnostics` listesine yazılır (son 20 kayıt).
- Worker loguna `production_failure` başlıklı yapılandırılmış JSON olarak yazılır.

Kayıt şema adını, aşamayı, alan yolunu, hata türünü, varsa sayısal sınırları ve
uygulama dosyası/fonksiyon/satır konumlarını içerir. Girdi değerleri, sağlayıcı
yanıtı, traceback yerel değişkenleri ve özel validator mesajları yazılmaz.
Örneğin `string_too_long` için `max_length` sınırı gösterilir; metnin kendisi gösterilmez.

Üretim ve önceki başarılı aşamalar korunur. Yeniden deneme aynı kaydı kullanır;
hata günlüğü tek başına bir çıktıyı onaylamaz veya doğrulamayı atlatmaz.

Eski hatalarda ayrıntı kaydedilmediyse bu bilgi sonradan geri getirilemez.
Yeni loglamanın çalışan worker tarafından yüklenmesi gerekir; aktif model/medya
işi sırasında worker zorla kapatılmamalıdır. Docker güncellemesi gerekmez.
