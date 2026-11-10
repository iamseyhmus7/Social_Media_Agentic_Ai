import base64
import io

import httpx
import pytest
from PIL import Image

from backend.app.config import settings
from backend.app.media_providers import cloudflare_image, elevenlabs_audio
from backend.app.providers import ProviderError, QuotaExceeded


@pytest.mark.parametrize('provider',['pexels','pixabay','unsplash','openverse'])
def test_catalog_normalizes_license_and_caches_without_credentials(setup,monkeypatch,provider):
    from backend.app import media_library as library
    cfg=settings()
    for key in ('pexels_api_key','pixabay_api_key','unsplash_access_key'):
        monkeypatch.setattr(cfg,key,'catalog-test-credential')
    fixtures={
        'pexels':{'photos':[{'id':1,'alt':'Father and daughter','photographer':'Artist','photographer_url':'https://www.pexels.com/@artist',
            'url':'https://www.pexels.com/photo/1/','src':{'large2x':'https://images.pexels.com/photos/1/photo.jpg'},'width':1000,'height':1500}]},
        'pixabay':{'hits':[{'id':2,'tags':'father, daughter','user':'Artist','pageURL':'https://pixabay.com/photos/2/',
            'largeImageURL':'https://cdn.pixabay.com/photo/2.jpg','imageWidth':1000,'imageHeight':1500}]},
        'unsplash':{'results':[{'id':'photo-3','alt_description':'Father and daughter','user':{'name':'Artist','links':{'html':'https://unsplash.com/@artist'}},
            'links':{'html':'https://unsplash.com/photos/photo-3','download_location':'https://api.unsplash.com/photos/photo-3/download'},
            'urls':{'regular':'https://images.unsplash.com/photo-3?w=1080&ixid=public-reference'},'width':1000,'height':1500}]},
        'openverse':{'results':[{'id':'4','title':'Father and daughter','creator':'Artist','foreign_landing_url':'https://example.org/photo/4',
            'url':'https://example.org/4.jpg','width':1000,'height':1500,'license':'by','license_url':'https://creativecommons.org/licenses/by/4.0/'}]},
    }
    calls=[];real_client=httpx.Client
    def respond(request):
        calls.append(request)
        if provider=='pexels':assert request.headers['Authorization']=='catalog-test-credential'
        if provider=='pixabay':assert request.url.params['key']=='catalog-test-credential'
        if provider=='unsplash':assert request.headers['Authorization']=='Client-ID catalog-test-credential'
        return httpx.Response(200,json=fixtures[provider])
    monkeypatch.setattr(library.httpx,'Client',lambda **kw:real_client(transport=httpx.MockTransport(respond),**kw))
    first=library.catalog_search(provider,'images','father daughter',lambda:None)
    assert first and first[0]['catalog']==provider and library.licensed(first[0])
    assert library.catalog_search(provider,'images','father daughter',lambda:None)==first
    assert len(calls)==1
    saved=''.join(p.read_text() for p in (cfg.media_root/'.catalog').glob('*.json'))
    assert 'catalog-test-credential' not in saved
    if provider=='unsplash':
        receipt=library.provenance(first[0])
        assert receipt['preview_url']==fixtures[provider]['results'][0]['urls']['regular']
        assert 'utm_source=sahne' in receipt['creator_url']


def test_catalog_outage_preserves_other_results_and_redacts_query_key(setup,monkeypatch,caplog):
    from backend.app import media_library as library
    monkeypatch.setattr(settings(),'pexels_api_key','fake-pexels-key')
    monkeypatch.setattr(settings(),'pixabay_api_key','fake-pixabay-key')
    caplog.set_level('INFO',logger='httpx')
    real_client=httpx.Client
    def respond(request):
        if request.url.host=='api.pexels.com':return httpx.Response(401,text='fake-pexels-key')
        if request.url.host=='api.openverse.org':return httpx.Response(429,json={})
        return httpx.Response(200,json={'hits':[{'id':2,'tags':'phone','user':'Artist',
            'pageURL':'https://pixabay.com/photos/2/','largeImageURL':'https://cdn.pixabay.com/photo/2.jpg',
            'imageWidth':1000,'imageHeight':1500}]})
    monkeypatch.setattr(library.httpx,'Client',lambda **kw:real_client(transport=httpx.MockTransport(respond),**kw))
    result=library.search('images','phone',lambda:None)
    assert result and result[0]['catalog']=='pixabay'
    assert 'fake-pixabay-key' not in caplog.text and 'fake-pexels-key' not in caplog.text
    with pytest.raises(ProviderError) as error:
        library.catalog_search('pexels','images','phone',lambda:None)
    assert 'fake-pexels-key' not in str(error.value)


def test_openverse_oauth_reuses_token_and_unsplash_tracking_uses_fixed_api_host(setup,monkeypatch):
    from backend.app import media_library as library
    cfg=settings()
    monkeypatch.setattr(cfg,'openverse_client_id','test-client')
    monkeypatch.setattr(cfg,'openverse_client_secret','test-secret')
    monkeypatch.setattr(cfg,'unsplash_access_key','test-access')
    library._openverse_token.clear()
    calls=[];real_client=httpx.Client
    def respond(request):
        calls.append(request)
        if request.url.path=='/v1/auth_tokens/token/':
            assert b'grant_type=client_credentials' in request.content
            assert b'client_secret=test-secret' in request.content
            return httpx.Response(200,json={'access_token':'test-token','expires_in':3600})
        if request.url.host=='api.openverse.org':
            assert request.headers['Authorization']=='Bearer test-token'
            return httpx.Response(200,json={'results':[]})
        assert request.url.host=='api.unsplash.com' and request.url.path=='/photos/photo-3/download'
        assert request.headers['Authorization']=='Client-ID test-access'
        return httpx.Response(200,json={'url':'https://images.unsplash.com/photo-3'})
    monkeypatch.setattr(library.httpx,'Client',lambda **kw:real_client(transport=httpx.MockTransport(respond),**kw))
    library.catalog_search('openverse','images','phone',lambda:None)
    library.catalog_search('openverse','images','bicycle',lambda:None)
    assert sum(request.url.path=='/v1/auth_tokens/token/' for request in calls)==1
    library.track_selection({'catalog':'unsplash','id':'photo-3','download_location':'https://untrusted.example/'},lambda:None)


def test_audio_search_uses_ccmixter_when_openverse_is_unavailable(tmp_path,monkeypatch):
    from backend.app import media_library as library
    monkeypatch.setattr(settings(),'media_root',tmp_path)
    real_client=httpx.Client
    row={'upload_id':99,'upload_name':'Instrumental piano','user_real_name':'Artist',
        'upload_tags':'instrumental,piano','file_page_url':'https://ccmixter.org/files/artist/99',
        'license_url':'http://creativecommons.org/licenses/by/2.5/',
        'files':[{'download_url':'https://ccmixter.org/content/artist/99.mp3','file_format_info':{'mime_type':'audio/mpeg'}}]}

    def respond(request):
        if request.url.host=='api.openverse.org':
            return httpx.Response(429,json={})
        assert request.url.host=='ccmixter.org' and request.url.params['lic']=='by'
        assert request.url.params['search']=='suspense piano'
        rejected={**row,'upload_id':100,'license_url':'https://creativecommons.org/licenses/by-nc/4.0/'}
        return httpx.Response(200,json=[rejected,row])

    monkeypatch.setattr(library.httpx,'Client',lambda **kw:real_client(transport=httpx.MockTransport(respond),**kw))
    tracks=library.search('audio','suspense piano',lambda:None)
    assert [(track['id'],track['catalog'],track['license_url']) for track in tracks]==[
        ('99','ccmixter','https://creativecommons.org/licenses/by/2.5/')]


def test_probe_uses_bounded_threads_without_changing_explicit_choice(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from backend.app import media
    calls = []
    def launch(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(poll=lambda: 0, returncode=0)
    monkeypatch.setattr(media.subprocess, 'Popen', launch)
    probe = media.settings().ffprobe_bin
    media.command([probe, '-v', 'error', 'clip.mp4'], tmp_path)
    assert calls[-1][1:3] == ['-threads', '1']
    media.command([probe, '-threads', '2', 'clip.mp4'], tmp_path)
    assert calls[-1].count('-threads') == 1 and calls[-1][2] == '2'


@pytest.fixture
def remote_config(monkeypatch):
    cfg = settings()
    for key, value in {
        'cloudflare_account_id': 'a' * 32, 'cloudflare_api_token': 'private-token',
        'cloudflare_image_steps': 4, 'elevenlabs_api_key': 'private-key',
        'cloudflare_image_model':'schnell', 'visual_policy':'legacy',
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
    monkeypatch.setattr(media.shutil, 'which', lambda name: name)
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


@pytest.mark.parametrize('missing',['ffmpeg','ffprobe'])
def test_voice_checks_local_tools_before_paid_request(remote_config,monkeypatch,tmp_path,missing):
    from backend.app import media,media_providers
    monkeypatch.setattr(remote_config,'ffmpeg_bin','ffmpeg')
    monkeypatch.setattr(remote_config,'ffprobe_bin','ffprobe')
    monkeypatch.setattr(media.shutil,'which',lambda name:None if name==missing else name)
    monkeypatch.setattr(media_providers,'elevenlabs_audio',lambda *a,**kw:pytest.fail('No paid request before tool preflight'))
    with pytest.raises(RuntimeError,match=missing.upper()+'_BIN'):
        media.voice('Test',tmp_path/'voice.wav',lambda:None)


def test_missing_executable_reports_tool_name(monkeypatch,tmp_path):
    from backend.app import media
    def missing(*args,**kwargs):raise FileNotFoundError('missing')
    monkeypatch.setattr(media.subprocess,'Popen',missing)
    with pytest.raises(RuntimeError,match='Medya aracı bulunamadı.*absent-ffmpeg'):
        media.command(['absent-ffmpeg','-version'],tmp_path)
