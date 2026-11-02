## 30 Ekim 2026 — .env değişikliği sonrası bağlantı

API container yeniden oluşturulduğunda iç IP değişebilir. Nginx başlangıçta eski IP’yi çözümlemişse API sağlıklı olduğu hâlde web üzerinden 502 alınır. Doğrulanan düzeltme:

```powershell
docker compose up -d --no-deps --force-recreate api worker beat
docker compose exec -T web nginx -s reload
```

30 Ekim’de Nginx yeniden yüklendikten sonra web üzerinden sağlık ve oturum uçları HTTP 200 döndü. Bu kontrol, değiştirilen harici sağlayıcı API anahtarının geçerliliğini ayrıca doğrulamaz.

# Docker doğrulaması · 21 Ekim 2026

## Güncel canlı medya kabulü

- `.env`: metin modeli `deepseek-v4.1-flash`, medya modeli `mimo-v2.6-pro`.
- Görsel sağlayıcısı Cloudflare FLUX.1 Schnell; ses sağlayıcısı ElevenLabs, otomatik API ses keşfi.
- Cloudflare ile gerçek 1024×1024 PNG üretildi ve görsel olarak incelendi.
- ElevenLabs hazır ses havuzundan agent'ın seçtiği Liam sesiyle 8,36 saniyelik Türkçe WAV üretildi; seçim/gerekçe QA veritabanında kayıtlı.
- Canlı testte kütüphane sesi için 402 `payment_required` alındı. Ücretsiz API modunda yalnızca hazır sesler seçilecek şekilde filtre eklendi; ücretli plana geçilmedi.
- MiMo, metni verilmeden Türkçe kayıttaki `mavi` ve `yirmi yedi` kontrol değerlerini çıkardı; sessizlik kontrolünde konuşma bildirmedi. `EVREN_AUDIO_INPUT_VERIFIED=true` açıldı; video girdi bayrağı kapalı.
- Whisper small ağırlıkları indirildi ve CPU/int8 yüklemesi doğrulandı. PyAV decoder uyumsuzluğu FFmpeg ile 16 kHz PCM girişi kullanılarak giderildi; örnek kayıttan dört zamanlı altyazı parçası çıkarıldı.
- Medya worker ortamında 62 backend testi geçti. Fixture testleri SQLite kullanır; bu sonuç PostgreSQL üzerinde tam pytest paketi sonucu değildir.
- API/worker/beat güncel kodla yeniden oluşturuldu ve başlatıldı. PostgreSQL, Valkey ve API sağlıklı; API ve Nginx üzerinden sağlık kontrolü 200.
- Gerçek HTTP/oturum/CSRF, PostgreSQL ve Celery üzerinden video kabul testi tamamlandı: üç görsel, 38,17 saniye, 1080×1920 video, kalite kontrolü başarılı, durum `awaiting_approval`. Ses seçim gerekçesi ve gerçek MiMo ses değerlendirmesi kayıtlarda mevcut.
- Celery prefork altında Whisper çıkarımı kilit beklemesine girdiği için worker `--pool=solo --concurrency=1` kullanıyor. Kontrollü yeniden başlatmadan sonra aynı üretim kaldığı yerden sürdürüldü; ses ve görseller yeniden üretilmedi. Solo modunda altyazı ve montaj tamamlandı.
- Üç karelik video önizlemesi görsel olarak incelendi; Türkçe altyazılar görünür. Türkçe ses MiMo ve Whisper ile otomatik doğrulandı; kullanıcı tarafından dinleme onayı verilmiş sayılmadı. Test hesabı pasifleştirildi; yayın veya kullanıcı onayı yapılmadı.
- Kabul testi tamamlandıktan sonra kullanıcının isteğiyle manuel test betikleri, QA raporları, örnek medya ve geçici test hesabı/projesi kaldırıldı. Yukarıdaki sonuçlar doğrulama geçmişidir; sonraki video denemeleri web arayüzünden yapılır. Üretim kodu, regresyon testleri ve Whisper model önbelleği korundu.

## Önceki kurulum kayıtları

- Altı servis başlatıldı: postgres, valkey, api, worker, beat, web.
- API, PostgreSQL bağlantısını SELECT 1 ile doğruladı; kuyruk modu Celery.
- Nginx üzerinden web ve `/api/v1/health`: HTTP 200.
- Yerel backend testleri: 20 geçti. Bu sonuç SQLite test fixture'ına aittir; PostgreSQL üzerinde tam test paketi sonucu olarak yorumlanmamalıdır.
- React üretim derlemesi başarılı; dört statik sunucu/paketleme testi geçti.
- Evren canlı bağlantısı ve Pydantic şemasına uygun JSON çıktısı doğrulandı.
- FFmpeg/ffprobe Docker imajında mevcut.
- Piper ses dosyası ve SSD-1B/Whisper model ağırlıkları henüz indirilmedi; uçtan uca video üretimi doğrulanmadı.
- Web kayıt akışı eklendi: `/register`. İlk hesap atomik olarak yönetici, sonrakiler üye olur. Kullanıcı kendi parolasını web formunda belirler.
- Güncel testler: yerel backend paketinde 23 başarılı test; PostgreSQL üzerinde üç kayıt/oturum/rol testi başarılı. Testler ayrı şemalarda çalıştı; gerçek kullanıcı hesabı oluşturulmadı.
- Kayıt ve ana sayfa masaüstünde ve 390 px genişlikte görsel olarak kontrol edildi; yatay taşma görülmedi.

Kullanım adresi: http://localhost:8080. PostgreSQL ve Valkey verileri named volume'larda; medya ve modeller `data` klasöründe kalır. Eski SQLite dosyası korundu ve Docker uygulamasında kullanılmıyor.

Temizlik: Python önbellekleri, eski geçici pytest veri klasörleri ve boş kök scripts klasörü kaldırıldı. `.env`, mevcut medya, tasarım kaynakları, testler ve geliştirme ortamı korundu. Docker dışındaki projelerin imajlarına veya volume'larına müdahale edilmedi.
