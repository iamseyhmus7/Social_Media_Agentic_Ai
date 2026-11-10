"""Remote media adapters; credentials and provider response bodies stay private."""
import base64
import binascii
import io
import json
import re

import httpx
from PIL import Image, UnidentifiedImageError

from .config import settings
from .providers import ProviderError, QuotaExceeded, TransientProviderError


def supports_voice_speed(cfg):
    # Verified TTS VoiceSettings contract; dialogue/v4 does not use that payload.
    return cfg.tts_provider == 'elevenlabs' and cfg.elevenlabs_model in (
        'eleven_multilingual_v2', 'eleven_turbo_v2_5', 'eleven_flash_v2_5')


class VoiceAccessDenied(ProviderError):
    """This specific voice is unavailable; never an account-wide auth failure."""


def request_media(url, headers, payload, check_cancel, *, transport=None, params=None, method='POST', files=None):
    check_cancel()
    try:
        with httpx.Client(timeout=httpx.Timeout(120, connect=15), transport=transport) as client:
            body = {'data':payload, 'files':files} if files is not None else {'json':payload}
            with client.stream(method, url, headers=headers, params=params, **body) as response:
                error_status = None
                if response.status_code in (500,502,503,504):
                    raise TransientProviderError(f'Medya hizmeti bekleniyor (HTTP {response.status_code}).',
                        http_status=response.status_code, retry_after=response.headers.get('retry-after'),
                        request_id=response.headers.get('request-id'))
                if response.status_code >= 400:
                    # Inspect only a small error envelope; never expose raw bodies.
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk[:max(0, 8192 - len(body))])
                        if len(body) >= 8192:
                            break
                    try:
                        detail = json.loads(body).get('detail', {})
                        error_status = detail.get('status') if isinstance(detail, dict) else None
                    except (ValueError, AttributeError):
                        pass
                    if url.startswith('https://api.cloudflare.com/') and response.status_code==429:
                        try:
                            quota = any(str(e.get('code'))=='4006' or 'daily' in e.get('message','').lower()
                                for e in json.loads(body).get('errors',[]))
                        except (ValueError,AttributeError,TypeError):
                            quota = False
                        if not quota:
                            raise TransientProviderError('Cloudflare istek hızı sınırına ulaşıldı; günlük kota dolduğu doğrulanmadı.',
                                http_status=429,retry_after=response.headers.get('retry-after'))
                    if error_status in ('detected_unusual_activity', 'unusual_activity_detected'):
                        raise ProviderError('ElevenLabs ücretsiz kullanım güvenlik denetimi isteği reddetti. Hesap/panel üzerinden sağlayıcının erişim uyarısını çöz; otomatik yeniden deneme yapılmadı.')
                    elevenlabs = url.startswith('https://api.elevenlabs.io/')
                    tts = elevenlabs and ('/text-to-speech/' in url or url.endswith('/text-to-dialogue'))
                    if elevenlabs and error_status == 'quota_exceeded':
                        raise QuotaExceeded('ElevenLabs karakter kotası doldu (quota_exceeded). Hesabın kotasını kontrol edip aynı üretimi yeniden dene.')
                    if elevenlabs and error_status in ('missing_permissions', 'insufficient_permissions'):
                        permission = 'Metinden Sese → Erişim' if tts else 'Sesler → Okumak'
                        raise ProviderError(f'ElevenLabs anahtarında {permission} izni eksik (HTTP {response.status_code}, {error_status}). Anahtarı sağlayıcı panelinden güncelle.')
                    if elevenlabs and error_status in ('invalid_api_key', 'invalid_authorization_header', 'unauthorized'):
                        raise ProviderError(f'ElevenLabs API anahtarı reddedildi (HTTP {response.status_code}, {error_status}). Anahtarın geçerliliğini kontrol et.')
                    if tts and error_status in ('voice_not_found', 'voice_not_allowed', 'voice_access_denied', 'payment_required'):
                        raise VoiceAccessDenied(f'ElevenLabs bu ses için API erişimi vermedi (HTTP {response.status_code}, {error_status}).')
                if response.status_code in (402, 429):
                    suffix = f' ({error_status})' if error_status in ('quota_exceeded', 'too_many_concurrent_requests', 'rate_limit_exceeded', 'payment_required') else ''
                    raise QuotaExceeded(f'Medya sağlayıcısı kotası veya erişim sınırı doldu (HTTP {response.status_code}){suffix}. Kotayı kontrol edip yeniden dene.')
                if response.status_code >= 400:
                    raise ProviderError(f'Medya API isteği başarısız (HTTP {response.status_code}). API anahtarını, izinleri ve model erişimini kontrol et.')
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    check_cancel()
                    size += len(chunk)
                    if size > 25 * 1024 * 1024:
                        raise ProviderError('Medya API yanıtı 25 MB sınırını aştı.')
                    chunks.append(chunk)
                return b''.join(chunks)
    except httpx.RequestError:
        raise TransientProviderError('Medya sağlayıcısına bağlanılamadı veya yanıt zaman aşımına uğradı.') from None


def cloudflare_image(prompt, target, check_cancel, *, transport=None, model=None, references=(), seed=None):
    import json
    cfg = settings()
    if not cfg.cloudflare_api_token or not re.fullmatch(r'[a-fA-F0-9]{32}', cfg.cloudflare_account_id):
        raise ProviderError('Cloudflare için CLOUDFLARE_ACCOUNT_ID ve CLOUDFLARE_API_TOKEN ayarlanmalı.')
    selected = model or cfg.cloudflare_image_model
    models = {'schnell':'@cf/black-forest-labs/flux-1-schnell',
              'klein':'@cf/black-forest-labs/flux-2-klein-9b', 'lucid':'@cf/leonardo/lucid-origin'}
    if selected not in models or (references and selected != 'klein') or len(references)>4:
        raise ProviderError('Görsel modeli veya referans desteği geçersiz; referanslar yalnız Klein ile kullanılabilir.')
    if selected == 'schnell' and not 1 <= cfg.cloudflare_image_steps <= 8:
        raise ProviderError('CLOUDFLARE_IMAGE_STEPS 1–8 arasında olmalı.')
    payload = {'prompt':prompt[:2048]}
    files = None
    sizes = []
    if selected != 'schnell':
        payload.update(width=576, height=1024)
    if seed is not None and selected != 'schnell':
        payload['seed'] = seed
    steps = cfg.cloudflare_image_steps if selected == 'schnell' else 25
    if selected == 'lucid':
        payload.update(num_steps=25, guidance=4.5)
    elif selected == 'schnell':
        payload['steps'] = steps
    else:
        # Force multipart even for a text-only request; JSON is not supported.
        files = {k:(None,str(v)) for k,v in payload.items()}
        payload = {}
        for index, path in enumerate(references):
            with Image.open(path) as source:
                reference = source.convert('RGB')
                reference.thumbnail((511,511))
                sizes.append(reference.size)
                buffer = io.BytesIO()
                reference.save(buffer,format='PNG')
            files[f'input_image_{index}'] = (f'reference-{index}.png',buffer.getvalue(),'image/png')
    reservation = None
    if cfg.visual_policy == 'references_v1':
        from .image_budget import reserve, estimate
        check_cancel()
        reservation = reserve(estimate(selected,576 if selected!='schnell' else 1024,1024,steps,sizes))
    try:
        raw = request_media(
        f'https://api.cloudflare.com/client/v4/accounts/{cfg.cloudflare_account_id}/ai/run/{models[selected]}',
        {'Authorization': f'Bearer {cfg.cloudflare_api_token}'},
        payload, check_cancel, transport=transport, **({'files':files} if files is not None else {}))
    except QuotaExceeded:
        if reservation:
            from .image_budget import block
            block(reservation)
        raise QuotaExceeded('Cloudflare hesabının ortak kotası/erişim sınırı doldu. Model değiştirmek yeni kota sağlamaz. Günlük kota Türkiye saatiyle 03.00’te yenilenir; hazır görseller korundu.') from None
    try:
        result = json.loads(raw)
        if result.get('success') is False:
            if any(error.get('code')==4006 for error in result.get('errors',[]) if isinstance(error,dict)):
                if reservation:
                    from .image_budget import block
                    block(reservation)
                raise QuotaExceeded('Cloudflare ortak günlük kotası doldu; diğer modeller de aynı kotayı kullanır. Yenilenme Türkiye saatiyle 03.00.')
            raise ProviderError('Cloudflare görsel üretimini reddetti. Workers AI panelindeki kota ve erişimi kontrol et.')
        image_bytes = base64.b64decode(result['result']['image'], validate=True)
        with Image.open(io.BytesIO(image_bytes)) as generated:
            generated.load()
            check_cancel()
            # Cloudflare Schnell does not expose width/height. Preserve its image;
            # the existing montage handles scaling/cropping into the vertical frame.
            generated.convert('RGB').save(target, format='PNG')
            return {'model':models[selected], 'model_key':selected, 'width':generated.width,
                    'height':generated.height, 'steps':steps if selected!='klein' else 'provider_fixed',
                    'seed':seed, 'reference_count':len(references)}
    except (ValueError, KeyError, TypeError, AttributeError, binascii.Error, UnidentifiedImageError, OSError):
        raise ProviderError('Cloudflare geçerli bir görsel döndürmedi.') from None


def elevenlabs_audio(text, check_cancel, *, transport=None, voice_id=None, voice_settings=None):
    cfg = settings()
    selected_voice = voice_id or cfg.elevenlabs_voice_id
    if not cfg.elevenlabs_api_key or not re.fullmatch(r'[A-Za-z0-9_-]+', selected_voice):
        raise ProviderError('ElevenLabs için ELEVENLABS_API_KEY ve ELEVENLABS_VOICE_ID ayarlanmalı.')
    payload = {'text': text, 'model_id': cfg.elevenlabs_model}
    if voice_settings is not None:
        payload['voice_settings'] = voice_settings
    endpoint = f'https://api.elevenlabs.io/v1/text-to-speech/{selected_voice}'
    if cfg.elevenlabs_model == 'eleven_v4':
        endpoint = 'https://api.elevenlabs.io/v1/text-to-dialogue'
        payload = {'inputs': [{'text': text, 'voice_id': selected_voice}], 'model_id': 'eleven_v4', 'language_code': 'tr'}
        if voice_settings:
            payload['settings'] = {'stability': voice_settings.get('stability', .5), 'similarity': voice_settings.get('similarity_boost', .75)}
    audio = request_media(
        endpoint,
        {'xi-api-key': cfg.elevenlabs_api_key, 'Accept': 'audio/mpeg'},
        payload, check_cancel,
        transport=transport, params={'output_format': 'mp3_44100_128'},
    )
    if not audio:
        raise ProviderError('ElevenLabs boş ses yanıtı döndürdü.')
    return audio
