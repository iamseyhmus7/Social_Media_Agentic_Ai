# Genel amaçlı otonom video üretimi — v3

Kullanıcı yalnızca konuyu yazar. MiMo Supervisor hedef kitle, ton, süre (30/45/60 saniye) ve yaratıcı yön belirler; LangGraph mevcut uzmanlara dinamik yönlenir. İçerik türleri birer hazır kurgu şablonu değildir. MiMo medya ve kalite görevlerinde, yapılandırılmış metin modeli strateji/senaryo/yayın metninde kullanılır.

## Çalışma zamanı

Kalıcı üretim araçları `orchestration.py`, `feedback.py` ve mevcut medya/Remotion modüllerindedir. Her video için Python veya JSX yazılmaz. Agent, Pydantic ile doğrulanan JSON üretir. Remotion 4.0.538 aynı yeniden kullanılabilir sahne bileşenlerini bu kararlara göre birleştirir. Kod veya sınırsız stil çalıştırılmaz.

`AGENT_PROTOCOL=structured_actions` mevcut Evren JSON sözleşmesi üzerinden modelin araç seçmesini sağlar. `native_tools` gerçek function-call yanıtı bekleyen alternatif protokoldür; geçit uyumu doğrulanmadan açılmamalıdır. Protokol otomatik ve sessiz değiştirilmez. Üretim başına 80 model turu, uzman görevi başına 12 araç turu vardır; ayarlar üretime kaydedilir. Araç etkileri ve tamamlanan aşamalar veritabanında kalıcıdır. Belirsiz Kaggle gönderimi tekrar gönderilmez.

Editör önce kaynakları inceler ve kurgu planını üretir, 540×960 sessiz önizleme render eder, gerçek önizleme karelerini MiMo ile değerlendirir. İncelenen plan ve önizlemenin dosya özetleri doğrulanmadan final render başlamaz. Final 1080×1920/30 FPS H.264, özgün hızdaki anlatım ve doğrulanan ses miksidir. Bağımsız kalite aşaması son videonun sahne ve geçiş örneklerini, desteklenen sözleşmede ilk sekiz saniyelik gerçek miks örneğini değerlendirir. Teknik tam çözümleme kontrolü korunur. Örnekleme tüm hareketi, tüm sesi veya tarihsel doğruluğu kanıtlamaz.

Kamera hareketi, iki kaynaklı yerleşim, tipografi, ışık, sınırlı parçacık ve mevcut bilgi grafikleri parametrelenebilir. Gerçek 3D, morf, otomatik nesne ayrıştırma ve kaynak katmanı olmadan paralaks desteklendiği iddia edilmez. Geçiş kaynak payları doğrulanır; v3 klibi geçiş için dondurmaz. Görsel ve ses önbellekleri değiştirilmiş girdilerde yeniden kullanılmaz.

## Geri bildirim

`POST /api/v1/projects/{id}/feedback` gövdesi: `run_id`, `prompt`, benzersiz `request_id`. Aynı istek kimliği aynı sonucu döndürür. Worker isteği değerlendirir; `GET /api/v1/projects/{id}/feedback` güncel durumları döndürür. Belirsiz istek `needs_clarification` olur; `POST .../feedback/{feedback_id}/answers` ile `answer` gönderilir. Açıklama beklenirken yeni video sürümü oluşturulmaz. İlk üretimde desteklenmeyen açık süre talebi `waiting_input` olur; `POST /api/v1/runs/{id}/answers` ile yanıtlanır.

Supervisor yalnız doğrudan etkilenen uzmanları seçer; kod veri bağımlılıklarını ekler. Kurgu geri bildirimi GPU işi başlatmaz. Yayın metni değişikliği videoyu yeniden render etmez. Ses ve senaryo değişiminde ölçülen süre yeniden değerlendirilir. Uygun kaynaklar sahiplik ve SHA-256 ile doğrulanarak yeni sürüme kopyalanır. Kaynak video değiştirilmez; yeni sürüm yeniden insan onayı gerektirir.

Otomatik onarım en fazla iki kurgu düzeltmesi, bir anlatım uzunluğu düzeltmesi ve bir medya onarım turu (en fazla üç çekim) içerir. Altyapı/kota hatası yaratıcı kalite hatası gibi yeniden üretim başlatmaz. Aktif, eski sürümlü veya yayın yüklemesi belirsiz kaynaklarda mevcut korumalar uygulanır.

## Dağıtım ve uyumluluk

Alembic `0003_agentic`, otomatik süre tercihini ve geri bildirim tablosunu ekler. PostgreSQL dağıtımında API açılışı migrasyonu uygular; mevcut yerel SQLite kurulumunda da API/worker başlatılmadan Alembic upgrade çalıştırılmalıdır. Yeni üretimler v3'tür. V1/v2 işler ve manifest v1 renderer'ı korunur. Bağımsız Remotion örnekleri üretim derlemesine alınmaz.

Tek kullanımlık `probe-dynamic.mjs` ve belirli eski üretim kimliklerini içeren `check-dynamic-edit.py` kaldırıldı. Genel render profili, iptal, altyazı ve regresyon kontrolleri korunur. Silme öncesi kaynak yedeği `.cache/source-backups/before-agentic-v3.zip` içindedir; gizli `.env` ve kullanıcı medyası bu arşive alınmaz.

## Son temizlik

Kullanıcının son talebiyle eski bağımsız Remotion videoları, örnek kodları, varlıkları ve yerel araçları kaldırıldı. Silinen kaynaklar `.cache/source-backups/retired-remotion-examples.zip` geri dönüş arşivinde saklanır; 28 Ekim 2026 genel temizliğinde kaynak ve veritabanı yedekleri korundu. Taşköprü uygulama projesinin varlıkları ayrı dosya özetleriyle korundu; `data` içindeki üretimler bu temizliğin dışında kaldı. Yeni üretimlerde aynı motor kullanılır; konuya özel yeni Python/JSX dosyaları oluşturulmaz.
