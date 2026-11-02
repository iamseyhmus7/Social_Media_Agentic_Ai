# Remotion üretim motoru

Otomatik video düzenleyicinin yeniden kullanılabilir bileşenleri ve render araçları `production/` içindedir. Docker medya worker’ı, Video Editörü Agentı’nın doğrulanmış JSON kararlarını burada çalıştırır; her video için Python veya JSX yazılmaz.

Yeni üretimlerde MiMo kaynakları inceler, sahne tasarımı ve zaman çizelgesini seçer, önizlemeyi değerlendirir ve final render aracını kullanır. FFmpeg özgün hızdaki seslendirmeyi karıştırır. Sabit sürüm: Remotion 4.0.538; final çıktı 1080×1920/30 FPS H.264/AAC.

Eski bağımsız Kapadokya, Mert, Fetih, tohum, mesaj ve deney videoları kullanıcının isteğiyle kaynakları ve yerel araç önbellekleriyle birlikte kaldırılmıştır. Kaldırılan kaynak ve medya örneklerinin doğrulanmış arşivi `.cache/source-backups/retired-remotion-examples.zip` içindedir. Üretim renderer’ı, eski uygulama sürümlerinin uyumluluk yolları ve uygulamanın Taşköprü projesi korunur.

Mimari: [Otonom video üretimi](../docs/agentic-video.md).
