# Çin Seddi siyah sahne incelemesi

30 Ekim 2026. Rust deneyleri kaldırılırken üretimle ilgili bağımsız hata bulguları korundu.

Üretim: `ffe3cceb-7c4c-4b45-8a6f-9f491ae2aebc`. Final video korunmuş, teknik kontrolden geçememiştir.

`blackdetect=d=0.6:pix_th=0.1` 17,666667–19,366667 saniye arasında 1,7 saniyelik karanlık bölüm tespit eder. Bu, `shot-004.mp4` segmentidir (478–580. kareler).

Kaynak klip koyu mavi degrade üzerinde ince bir mercan çizgisinden oluşur. Çıkarılan karelerde eksik segment veya render boşluğu görülmedi. Kaynak aynı eşikte uyarı üretmezken hem sessiz `visual-edit.mp4` hem sesli `video.mp4` aynı aralıkta uyarı verir. Finaldeki koyu katmanlar görüntüyü daha da karartmaktadır.

Tanısal `pix_th=0.02` taramasında siyah aralık yoktur; üretim kalite eşiği değiştirilmedi. MiMo kaynak gözleminde de bu klip `uncertain` ve “kareler statik ve boş, eksik içerik riski yüksek” olarak işaretlenmiştir. Teknik eşik yanında görsel içerik zayıflığı da vardır.

Uygun müdahale, ilgili segmentte ışık/kontrast katmanlarını düzeltip yalnız etkilenen render parçalarını yenilemektir. Görsel anlatım yetersiz kalırsa yalnız bu kaynak değiştirilmelidir. Bu incelemede üretim planı, kaynakları ve final video değiştirilmedi.

Kanıtlar: `data/qa-video-speedup/black-scene-20261030/threshold-comparison.json`, `final-18.5.png`, `shot-004.mp4-1.8.png`.
