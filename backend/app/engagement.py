"""Versioned spoken opening requirement for new productions."""
from pydantic import model_validator

INSTRUCTION = ('Her videonun ilk 1–3 saniyesi güçlü, konuyla bağlantılı bir hook olmalı: '
    'merak açığı, somut sonuç veya şaşırtıcı ama doğrulanabilir karşıtlık kullan. Selamlama ve '
    'genel konu tanıtımıyla başlama; yanıltıcı vaat veya uydurma bilgi ekleme. '
    'hook alanını en fazla 8 kelime yaz ve ilk sahnenin narration alanını bu hook ile başlat. '
    'Son sahnede anlamlı bir sonuç yaz; otomatik beğeni veya takip çağrısı ekleme.')


def validate_engagement(script):
    first=script['scenes'][0]['narration'].strip()
    hook=script['hook'].strip()
    if len(hook.split())>8 or not first.startswith(hook):
        raise ValueError('İlk narration, hook alanındaki en fazla 8 kelimelik girişle başlamalı.')
    return script


def engaging_script(base):
    class EngagementScript(base):
        @model_validator(mode='after')
        def opening(self):
            validate_engagement(self.model_dump())
            return self
    return EngagementScript
