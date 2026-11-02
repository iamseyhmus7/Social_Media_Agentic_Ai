# Ana sayfa ve Agentic AI anlatımı · 21 Ekim 2026

- `/`: ziyaretçiye açık ürün tanıtımı; dashboard veya proje listesi gösterilmez.
- `/app`: oturum gerektirir. Anonim tarayıcıda `/login` yönlendirmesi doğrulandı.
- Giriş ve kayıt sonrası `/app`; çıkışta `/` açılır. Dört yönlendirme testi geçti.
- Yerel ve Docker web üretim derlemeleri başarılı.
- Masaüstünde ana sayfa, bölüm bağlantısı, agent diyagramı ve rol seçimi kontrol edildi.
- Akış anlatımı sekizinci adımda insan onayına ulaşıp durdu. Seslendirme seçimi anlatımı duraklatıp girdi/çıktı panelini güncelledi.
- Hareket azaltma tercihi açıkken otomatik oynatma kapalıydı; kullanıcı kontrollü oynatma çalıştı.
- 390 px genişlikte ana sayfa, menü ve diyagram kontrol edildi; sayfa genişliği 375 px ölçüldü, yatay taşma görülmedi. Diyagram kendi kaydırılabilir alanında okunabilir boyutta tutulur.
- Açıklama diyagramı canlı üretim değildir ve açıkça simülasyon olarak etiketlenir. Görsel/ses dalları bağımsız çıktı bağımlılıklarını gösterir; mevcut pilot medya görevlerini sırayla yürütür.

Görüntüler: `qa/landing-home-final.png`, `qa/landing-agentic-final.png`.
