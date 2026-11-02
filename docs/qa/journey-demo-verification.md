# Etkileşimli ana sayfa demosu

Fotoğraf galerisi yerine üç sütunlu bir deneyim eklendi: örnek konu → agent aşamaları → oynatılabilir video ve demo onayı.

## Kapsam

- Üç hazır konu: keşif, merak, ilham.
- Yedi rolün görevleri, aşama çıktıları ve görsel örnekler.
- Yerel H.264 / 540 × 960 / 24 FPS, sessiz 12 saniyelik MP4 örnekler.
- Aynı örneğin 9 saniyelik kısa kurgu sürümü. Yeni kurgu önceki demo onayını kaldırır.
- Gerçek kişisel üretim için kayıt / çalışma alanı yönlendirmesi.
- Tanıtım demosu üretim API'sini çağırmaz, iş kuyruğuna görev eklemez ve yayın yapmaz.

## Doğrulama

- TypeScript ve Docker web üretim derlemesi başarılı.
- Tarayıcıda discovery-original.mp4: duration 12, videoWidth 540, videoHeight 960, readyState 4; oynatım 12 saniyeye ulaştı.
- Demo onayı verildi. Revizyon başlatıldığında onay düğmesi devre dışı, eski video kaldırılmış ve önceki onay iptal edilmişti.
- discovery-short.mp4: duration 9, readyState 4, v2 etiketi doğrulandı.
- Konu değişimi eski ilerlemeyi ve onayı sıfırladı.
- Mobil 390 pikselde yatay sayfa taşması yok. inspiration-original.mp4 doğru konuya bağlı olarak 12 saniye yüklendi.
- Kendi video CTA'sı kayıt formuna ulaştı; hesap oluşturma formu gönderilmedi.

Bu çalışma ana sayfadaki açıklamalı tanıtım deneyimidir; gerçek model tabanlı video üretiminin uçtan uca testi değildir. Örnek kliplerde ses izi bulunmaz; seslendirme aşaması metin taslağını gösterir.
