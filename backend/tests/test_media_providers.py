import base64
import io

import httpx
import pytest
from PIL import Image

from backend.app.config import settings
from backend.app.media_providers import cloudflare_image, elevenlabs_audio
from backend.app.providers import ProviderError, QuotaExceeded


@pytest.fixture
def remote_config(monkeypatch):
    cfg = settings()
    for key, value in {
        'cloudflare_account_id': 'a' * 32, 'cloudflare_api_token': 'private-token',
        'cloudflare_image_steps': 4, 'elevenlabs_api_key': 'private-key',
        'elevenlabs_voice_id': 'test-voice', 'elevenlabs_model': 'eleven_multilingual_v2',
    }.items():
        monkeypatch.setattr(cfg, key, value)
    return cfg


def test_cloudflare_decodes_image(remote_config, tmp_path):
    buffer = io.BytesIO()
    Image.new('RGB', (32, 32), 'purple').save(buffer, format='JPEG')
    def respond(request):
        import json
        assert request.headers['Authorization'] == 'Bearer private-token'
        assert json.loads(request.content)['steps'] == 4
        return httpx.Response(200, json={'success': True, 'result': {'image': base64.b64encode(buffer.getvalue()).decode()}})
    target = tmp_path / 'scene.png'
    cloudflare_image('A landscape', target, lambda: None, transport=httpx.MockTransport(respond))
    with Image.open(target) as image:
        assert image.format == 'PNG'
        assert image.size == (32, 32)


def test_elevenlabs_request(remote_config):
    def respond(request):
        import json
        assert request.headers['xi-api-key'] == 'private-key'
        assert request.url.params['output_format'] == 'mp3_44100_128'
        assert json.loads(request.content) == {'text': 'Merhaba', 'model_id': 'eleven_multilingual_v2'}
        return httpx.Response(200, content=b'fake-mp3')
    assert elevenlabs_audio('Merhaba', lambda: None, transport=httpx.MockTransport(respond)) == b'fake-mp3'


@pytest.mark.parametrize('status', [402, 429])
def test_remote_quota_waits(remote_config, status):
    with pytest.raises(QuotaExceeded):
        elevenlabs_audio('Merhaba', lambda: None, transport=httpx.MockTransport(lambda r: httpx.Response(status)))


def test_error_body_is_private(remote_config):
    with pytest.raises(ProviderError) as error:
        elevenlabs_audio('Merhaba', lambda: None, transport=httpx.MockTransport(lambda r: httpx.Response(401, text='private-key')))
    assert 'private-key' not in str(error.value)
    assert '401' in str(error.value)


def test_unusual_activity_is_access_error_not_quota_retry(remote_config):
    with pytest.raises(ProviderError, match='güvenlik denetimi') as error:
        elevenlabs_audio('Merhaba', lambda: None, transport=httpx.MockTransport(lambda r: httpx.Response(401, json={'detail': {'status': 'detected_unusual_activity', 'message': 'private-key'}})))
    assert not isinstance(error.value, QuotaExceeded)
    assert 'private-key' not in str(error.value)


def test_bad_cloudflare_image(remote_config, tmp_path):
    with pytest.raises(ProviderError, match='geçerli bir görsel'):
        cloudflare_image('test', tmp_path / 'scene.png', lambda: None, transport=httpx.MockTransport(lambda r: httpx.Response(200, json={'result': {'image': 'invalid'}})))


def test_missing_credentials_do_not_call_api(remote_config, monkeypatch):
    monkeypatch.setattr(remote_config, 'elevenlabs_api_key', '')
    with pytest.raises(ProviderError, match='ELEVENLABS_API_KEY'):
        elevenlabs_audio('test', lambda: None)


def test_remote_voice_converts_to_valid_wav(remote_config, monkeypatch, tmp_path):
    import math
    import struct
    import wave
    from backend.app import media, media_providers
    monkeypatch.setattr(remote_config, 'tts_provider', 'elevenlabs')
    monkeypatch.setattr(media_providers, 'elevenlabs_audio', lambda *args: b'fake-mp3')
    target = tmp_path / 'voice.wav'
    def convert(args, cwd, check_cancel):
        assert args[args.index('-i') + 1] == 'voice.mp3'
        with wave.open(str(target), 'wb') as wav:
            wav.setparams((1, 2, 22050, 0, 'NONE', 'not compressed'))
            wav.writeframes(b''.join(struct.pack('<h', int(1000 * math.sin(i / 10))) for i in range(22050)))
    monkeypatch.setattr(media, 'command', convert)
    assert media.voice('Merhaba', target, lambda: None) == 1
    assert not target.with_suffix('.mp3').exists()


def test_retired_brand_voice_is_not_exposed_or_saved(clients):
    from backend.app.db import DB, User
    with DB() as db:
        db.get(User, 'alice').brand = {'name':'Test', 'color':'#7645ed', 'voice':'retired-local-voice'}
        db.commit()
    alice, _ = clients
    assert 'voice' not in alice.get('/api/v1/brand').json()
    response = alice.put('/api/v1/brand', json={'name':'Test', 'color':'#7645ed'})
    assert response.status_code == 200
    with DB() as db:
        assert 'voice' not in db.get(User, 'alice').brand


def test_remote_image_dispatch_avoids_local_model(remote_config, monkeypatch, tmp_path):
    from backend.app import media, media_providers
    monkeypatch.setattr(remote_config, 'image_provider', 'cloudflare')
    monkeypatch.setattr(media, 'check_disk', lambda: None)
    seen = []
    monkeypatch.setattr(media_providers, 'cloudflare_image', lambda *args: seen.append(args[0]))
    media.image('landscape', tmp_path / 'scene.png', lambda: None)
    assert seen == ['landscape']
