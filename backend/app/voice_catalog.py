"""Discover account voices; measure previews without claiming LLM audio perception."""
import array
import base64
import json
import math
import re
import sys
import wave
from urllib.parse import urlsplit

from .config import settings
from .media_providers import request_media
from .providers import ProviderError


def discover_voices(check_cancel=lambda: None, *, transport=None):
    cfg = settings()
    if not cfg.elevenlabs_api_key:
        raise ProviderError('ELEVENLABS_API_KEY ayarlanmalı.')
    voices, seen, cursor = [], set(), None
    for _ in range(5):
        params = {'page_size': 100, 'include_total_count': 'false', 'include_custom_rates': 'false'}
        if cfg.elevenlabs_free_voices_only:
            params['category'] = 'premade'
        if cursor:
            params['next_page_token'] = cursor
        try:
            raw = request_media('https://api.elevenlabs.io/v2/voices', {'xi-api-key': cfg.elevenlabs_api_key},
                                None, check_cancel, method='GET', params=params, transport=transport)
        except ProviderError as exc:
            if 'HTTP 401' in str(exc) or 'HTTP 403' in str(exc):
                raise ProviderError('ElevenLabs ses listesine erişilemiyor. .env içindeki anahtarda Sesler → Okumak iznini açıp kaydet; anahtarın geçerliliğini kontrol et.') from None
            raise
        try:
            page = json.loads(raw)
            if not isinstance(page.get('voices'), list):
                raise ValueError()
            for voice in page['voices']:
                identifier = voice.get('voice_id', '')
                if not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', identifier) or identifier in seen:
                    continue
                seen.add(identifier)
                sharing = voice.get('sharing') or {}
                # Library free_users_allowed describes website access; the API
                # can still require payment. Free API tests use built-in voices.
                if cfg.elevenlabs_free_voices_only and (voice.get('category') != 'premade' or sharing.get('public_owner_id')):
                    continue
                # Do not select explicitly disabled or verification-gated voices.
                if (voice.get('voice_verification') or {}).get('requires_verification') and not (voice.get('voice_verification') or {}).get('is_verified'):
                    continue
                if sharing.get('status') == 'disabled':
                    continue
                labels = voice.get('labels') or {}
                language = str(labels.get('language') or voice.get('language') or '').strip().casefold()
                native_turkish = language in ('tr', 'turkish', 'türkçe')
                verified = [v for v in voice.get('verified_languages', []) if isinstance(v, dict)]
                turkish = next((v for v in verified if v.get('language') == 'tr'), {})
                voices.append({
                    'voice_id': identifier, 'name': str(voice.get('name') or identifier)[:100],
                    'description': str(voice.get('description') or '')[:600],
                    'labels': {str(k)[:60]: str(v)[:100] for k, v in labels.items()},
                    'turkish_verified': bool(turkish),
                    'language': 'tr' if native_turkish else language,
                    'native_turkish': native_turkish,
                    'preview_url': turkish.get('preview_url') or voice.get('preview_url'),
                    'category': str(voice.get('category', ''))[:40],
                })
            if not page.get('has_more'):
                break
            next_cursor = page.get('next_page_token')
            if not isinstance(next_cursor, str) or not next_cursor or next_cursor == cursor:
                raise ValueError()
            cursor = next_cursor
        except (ValueError, TypeError, AttributeError):
            raise ProviderError('ElevenLabs geçerli bir ses listesi döndürmedi.') from None
    if not voices:
        raise ProviderError('ElevenLabs hesabında seçilebilir ses bulunamadı.')
    if cfg.elevenlabs_turkish_only:
        native = [voice for voice in voices if voice['native_turkish']]
        if len(native) >= 3 or (not cfg.elevenlabs_casting_enabled and native):
            voices = native
    # Prefer verified Turkish voices; multilingual defaults can still speak Turkish.
    voices.sort(key=lambda v: not v['turkish_verified'])
    return [{**v, 'key': f'voice_{i}'} for i, v in enumerate(voices[:50])]


def public_preview_url(url):
    if not isinstance(url, str):
        return False
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == 'https' and parsed.hostname == 'storage.googleapis.com'
                and parsed.path.startswith('/eleven-public-prod/') and not parsed.username
                and parsed.port in (None, 443))
    except ValueError:
        return False


def discover_turkish_voices(check_cancel=lambda: None, *, transport=None):
    """Native Turkish library performers; account defaults are a separate legacy mode."""
    cfg = settings()
    if not cfg.elevenlabs_api_key:
        raise ProviderError('ELEVENLABS_API_KEY ayarlanmalı.')
    voices, seen = [], set()
    for page in range(3):
        raw = request_media('https://api.elevenlabs.io/v1/shared-voices', {'xi-api-key': cfg.elevenlabs_api_key},
                            None, check_cancel, method='GET', transport=transport,
                            params={'language': 'tr', 'page_size': 50, 'page': page, 'sort': 'cloned_by_count', 'include_custom_rates': 'false'})
        try:
            result = json.loads(raw)
            if not isinstance(result.get('voices'), list):
                raise ValueError()
            for voice in result['voices']:
                identifier = voice.get('voice_id', '')
                if (not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', identifier)
                        or identifier in seen or voice.get('language') != 'tr'):
                    continue
                if voice.get('free_users_allowed') is not True:
                    continue
                try:
                    if float(voice.get('rate', 1)) > 1:
                        continue
                except (TypeError, ValueError):
                    continue
                seen.add(identifier)
                voices.append({'key': f'voice_{len(voices)}', 'voice_id': identifier,
                               'name': str(voice.get('name') or identifier)[:100],
                               'description': str(voice.get('description') or '')[:600],
                               'language': 'tr', 'category': str(voice.get('category', ''))[:40],
                               'library_users': max(0, int(voice.get('cloned_by_count') or 0)),
                               'usage_characters_1y': max(0, int(voice.get('usage_character_count_1y') or 0)),
                               'labels': {k: str(voice.get(k) or '')[:100] for k in ('accent', 'gender', 'age', 'use_case')},
                               'turkish_verified': True})
                if len(voices) == 50:
                    return voices
            if not result.get('has_more'):
                break
        except (ValueError, TypeError, AttributeError):
            raise ProviderError('ElevenLabs geçerli bir Türkçe ses kütüphanesi döndürmedi.') from None
    if len(voices) < 3:
        raise ProviderError('Karşılaştırma için en az üç ücretsiz kullanıma uygun Türkçe anlatıcı gerekli. ElevenLabs Türkçe kütüphane erişimini kontrol et.')
    return voices


def preview_metrics(voice, folder, check_cancel=lambda: None, *, transport=None, include_audio=False):
    """Only signal metrics, not emotion, accent or pronunciation recognition."""
    from .media import command
    if not public_preview_url(voice.get('preview_url')):
        return {'status': 'unavailable', 'method': 'no_audio_analysis'}
    mp3, wav = folder / 'voice-preview.mp3', folder / 'voice-preview.wav'
    try:
        mp3.write_bytes(request_media(voice['preview_url'], {}, None, check_cancel, method='GET', transport=transport))
        command([settings().ffmpeg_bin, '-y', '-i', mp3.name, '-t', '8', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', wav.name], folder, check_cancel, timeout=30)
        with wave.open(str(wav), 'rb') as audio:
            samples = array.array('h', audio.readframes(8 * 16000))
            if sys.byteorder != 'little':
                samples.byteswap()
        if not samples:
            return {'status': 'empty', 'method': 'signal_metrics_only'}
        rms = math.sqrt(sum(x * x for x in samples) / len(samples))
        blocks = [samples[i:i + 800] for i in range(0, len(samples), 800)]
        silence = sum(math.sqrt(sum(x * x for x in b) / len(b)) < 200 for b in blocks) / len(blocks)
        result = {'status': 'measured', 'method': 'signal_metrics_only', 'duration_seconds': round(len(samples) / 16000, 2),
                'rms_dbfs': round(20 * math.log10(max(rms, 1) / 32768), 2),
                'silent_fraction': round(silence, 3),
                'clipped_sample_fraction': round(sum(abs(x) >= 32760 for x in samples) / len(samples), 5),
                'emotion_or_pronunciation_evaluated': False}
        if include_audio:
            result['_audio_input'] = {'type': 'input_audio', 'input_audio': {'data': base64.b64encode(wav.read_bytes()).decode(), 'format': 'wav'}}
        return result
    except (ProviderError, RuntimeError, wave.Error, OSError, ValueError) as exc:
        from .media import Cancelled
        if isinstance(exc, Cancelled):
            raise
        return {'status': 'analysis_failed', 'method': 'no_audio_analysis'}
    finally:
        mp3.unlink(missing_ok=True)
        wav.unlink(missing_ok=True)
