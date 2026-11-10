"""Versioned spoken opening requirement for new productions."""
from pydantic import model_validator
import re

INSTRUCTION = ('İlk 1–3 saniyede konuya bağlı bir hook kur: '
    'merak açığı, somut sonuç veya doğrulanabilir karşıtlık kullan. Selamlama ve '
    'genel konu tanıtımıyla başlama; yanıltıcı vaat veya uydurma bilgi ekleme. '
    'hook alanını en fazla 8 kelime yaz ve ilk sahnenin narration alanını bu hook ile başlat. '
    'Hook sonrası aynı soruyu açıklama; hemen somut bilgi veya örnekle ilerle. '
    'Görsel eylemi, okunabilir kısa yazıyı ve ses/anlatıcı vurgusunu aynı açılış vaadine bağla. '
    'İlk cümlede güçlü fiil ve somut risk/ödül/şaşırtıcı ayrıntı kullan; soyut klişe ve dolgu sözcüklerini çıkar. '
    'İlk karede tek odaklı eylem veya kritik ayrıntı göster; ilk sözcük bekletmeden duyulsun. '
    'Anlatıcı ilk kritik sözcüğü anlamlı vurgulasın; kısa ses vurgusu ve müzik girişini bu ana eşleştir, bağırma. '
    'Tempoyu bilgi ilerleyişiyle kur; seslendirmeyi hızlandırma veya her kareye efekt yığma. '
    'Son sahnede açılışı karşılayan yeni sonuç/uygulanabilir adım/keşif ver; '
    'yalnız önceki sahneleri özetleme, otomatik beğeni veya takip çağrısı ekleme.')

CLOSING_INSTRUCTION = (
    'Kullanıcının yeni videolar için kalıcı tercihi: Son anlatım paragrafını konuya özel, seslendirilecek '
    'tek bir etkileşim cümlesiyle bitir. Önce anlatının sonucunu ver; ardından o konuyla ilgili somut '
    'bir yorum sorusu veya paylaşma/kaydetme/takip/beğeni çağrısı seç. Dört eylemi arka arkaya sıralama. '
    'Örneği videonun kendi konusu, ikilemi, deneyimi veya yararlı bilgisine bağla; aynı hazır sloganı tekrarlama. '
    'Kısa ve doğal söyle; zorlayıcı dil, etkileşim garantisi ve clickbait kullanma. '
    'CTA son sahnenin narration metninde duyulmalı; yalnız cta alanına veya ekrana yazmak yeterli değildir. '
    'Son cümle cta alanında aynen yer alsın; ek seslendirme dosyası veya tekrar okuma üretme. '
    'Supervisor bu cümlenin konuya özgülüğünü, doğal üslubunu ve tek bir ana eylem istemesini değerlendirsin.')


def instruction_for(policy):
    if policy<2:return INSTRUCTION
    return INSTRUCTION.replace('otomatik beğeni veya takip çağrısı ekleme.',
        'ardından konuya özgü etkileşim kapanışını uygula.')+' '+CLOSING_INSTRUCTION


def closing_cta(narration):
    return re.split(r'(?<=[.!?])\s+',narration.strip())[-1]


def validate_closing(narration):
    cta=closing_cta(narration)
    if not re.search(r'\b(?:yorum\w*|paylaş\w*|beğen\w*|takip|kaydet\w*)\b',cta,re.IGNORECASE):
        raise ValueError('Son seslendirilen cümlede konuya özel yorum/paylaşım/kaydetme/takip/beğeni çağrısı bulunmalı.')
    return cta


def validate_engagement(script, policy=1):
    first=script['scenes'][0]['narration'].strip()
    hook=script['hook'].strip()
    if len(hook.split())>8 or not first.startswith(hook):
        raise ValueError('İlk narration, hook alanındaki en fazla 8 kelimelik girişle başlamalı.')
    if policy>=2:
        last=script['scenes'][-1]['narration'].strip()
        validate_closing(last)
        if not last.endswith(script['cta'].strip()):
            raise ValueError('CTA son narration içinde aynen seslendirilmelidir.')
    return script


def engaging_script(base, policy=1):
    class EngagementScript(base):
        @model_validator(mode='after')
        def opening(self):
            validate_engagement(self.model_dump(),policy)
            return self
    return EngagementScript
