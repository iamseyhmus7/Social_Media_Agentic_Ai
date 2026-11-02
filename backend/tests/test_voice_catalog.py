import io
import json
import wave

import httpx
import pytest

from backend.app.config import settings
from backend.app.media import Cancelled
from backend.app.providers import Evren, ProviderError
from backend.app.schemas import Plan
from backend.app.voice_catalog import discover_voices, preview_metrics, public_preview_url


@pytest.fixture(autouse=True)
def legacy_catalog_policy(monkeypatch):
    monkeypatch.setattr(settings(), 'elevenlabs_turkish_only', False)


def test_catalog_paginates_and_prefers_verified_turkish(monkeypatch):
    monkeypatch.setattr(settings(), 'elevenlabs_api_key', 'secret-test-key')
    calls = []
    def respond(request):
        assert request.method == 'GET'
        assert request.headers['xi-api-key'] == 'secret-test-key'
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json={'voices': [{'voice_id': 'default', 'name': 'Default', 'category': 'premade'}], 'has_more': True, 'next_page_token': 'second'})
        assert request.url.params['next_page_token'] == 'second'
        return httpx.Response(200, json={'voices': [{'voice_id': 'native', 'name': 'Türkçe', 'category': 'premade', 'verified_languages': [{'language': 'tr', 'preview_url': 'https://storage.googleapis.com/eleven-public-prod/test.mp3'}]}], 'has_more': False})
    voices = discover_voices(transport=httpx.MockTransport(respond))
    assert [v['voice_id'] for v in voices] == ['native', 'default']
    assert len(calls) == 2


def test_read_permission_error_is_actionable_and_private(monkeypatch):
    monkeypatch.setattr(settings(), 'elevenlabs_api_key', 'secret-test-key')
    with pytest.raises(ProviderError, match='Okumak') as error:
        discover_voices(transport=httpx.MockTransport(lambda r: httpx.Response(401, text='secret-test-key')))
    assert 'secret-test-key' not in str(error.value)


def test_free_api_catalog_excludes_library_voices_even_if_free_label(monkeypatch):
    monkeypatch.setattr(settings(), 'elevenlabs_api_key', 'test')
    monkeypatch.setattr(settings(), 'elevenlabs_free_voices_only', True)
    def respond(request):
        assert request.url.params['category'] == 'premade'
        return httpx.Response(200, json={'voices': [
            {'voice_id': 'paid', 'name': 'Library', 'category': 'professional', 'sharing': {'free_users_allowed': True}},
            {'voice_id': 'unknown', 'name': 'Unknown category'},
            {'voice_id': 'builtin', 'name': 'Built-in', 'category': 'premade'},
        ], 'has_more': False})
    assert [v['voice_id'] for v in discover_voices(transport=httpx.MockTransport(respond))] == ['builtin']


@pytest.mark.parametrize('url', ['http://127.0.0.1/a', 'https://storage.googleapis.com.evil.test/eleven-public-prod/a', 'https://storage.googleapis.com/private-bucket/a', 'https://storage.googleapis.com:bad/eleven-public-prod/a', 'https://user@storage.googleapis.com/eleven-public-prod/a'])
def test_untrusted_preview_not_fetched(url):
    assert not public_preview_url(url)


def test_preview_metrics_include_audio_only_when_requested(tmp_path, monkeypatch):
    from backend.app import media
    def convert(args, cwd, check_cancel, timeout):
        with wave.open(str(cwd / 'voice-preview.wav'), 'wb') as wav:
            wav.setparams((1, 2, 16000, 0, 'NONE', 'none'))
            wav.writeframes(b'\x00\x00' * 16000)
    monkeypatch.setattr(media, 'command', convert)
    result = preview_metrics({'preview_url': 'https://storage.googleapis.com/eleven-public-prod/test.mp3'}, tmp_path, include_audio=True,
                             transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b'fake-mp3')))
    assert result['silent_fraction'] == 1
    assert result['duration_seconds'] == 1
    assert result['emotion_or_pronunciation_evaluated'] is False
    assert result['_audio_input']['input_audio']['format'] == 'wav'
    assert not list(tmp_path.glob('voice-preview.*'))


def test_cancel_is_not_swallowed(tmp_path):
    def cancel():
        raise Cancelled('stop')
    with pytest.raises(Cancelled):
        preview_metrics({'preview_url': 'https://storage.googleapis.com/eleven-public-prod/test.mp3'}, tmp_path, cancel)


@pytest.fixture
def models(monkeypatch):
    monkeypatch.setattr(settings(), 'evren_supervisor_model', 'mimo-v2.6-pro')
    cfg = settings()
    for name, value in {'evren_api_key': 'test', 'evren_base_url': 'https://example.test/v1',
                        'evren_model': 'deepseek-v4.1-flash', 'evren_media_model': 'mimo-v2.6-pro',
                        'evren_protocol': 'openai_chat', 'evren_contract_verified': True,
                        'evren_audio_input_verified': False, 'evren_video_input_verified': False}.items():
        monkeypatch.setattr(cfg, name, value)
    return cfg


@pytest.mark.parametrize('role,expected', [('Supervisor', 'mimo-v2.6-pro'), ('Senaryo Yazarı', 'deepseek-v4.1-flash'), ('İçerik Stratejisti', 'deepseek-v4.1-flash'), ('Seslendirme Yönetmeni', 'mimo-v2.6-pro'), ('Görsel Tasarımcı', 'mimo-v2.6-pro'), ('Video Editörü', 'mimo-v2.6-pro'), ('Yayıncı', 'deepseek-v4.1-flash')])
def test_role_model_routing(models, role, expected):
    def respond(request):
        assert json.loads(request.content)['model'] == expected
        return httpx.Response(200, json={'choices': [{'message': {'content': '{"goal":"Test planı","checks":["test"]}'}}]})
    Evren(transport=httpx.MockTransport(respond)).generate(Plan, role, {})


@pytest.mark.parametrize('kind', ['input_audio', 'video_url'])
def test_unverified_gateway_contract_blocks_media_input(models, kind):
    with pytest.raises(ProviderError, match='sözleşmesi'):
        Evren().generate(Plan, 'Seslendirme', {}, media_inputs=[{'type': kind}])


def test_audio_payload_uses_media_model(models, monkeypatch):
    monkeypatch.setattr(models, 'evren_audio_input_verified', True)
    part = {'type': 'input_audio', 'input_audio': {'data': 'dGVzdA==', 'format': 'wav'}}
    def respond(request):
        payload = json.loads(request.content)
        assert payload['model'] == 'mimo-v2.6-pro'
        assert payload['messages'][1]['content'][1] == part
        return httpx.Response(200, json={'choices': [{'message': {'content': '{"goal":"Ses testi","checks":["test"]}'}}]})
    Evren(transport=httpx.MockTransport(respond)).generate(Plan, 'Seslendirme', {}, media_inputs=[part])


def test_strict_turkish_requires_language_label_not_name_or_multilingual_support(monkeypatch):
    monkeypatch.setattr(settings(),'elevenlabs_api_key','test')
    monkeypatch.setattr(settings(),'elevenlabs_free_voices_only',True)
    monkeypatch.setattr(settings(),'elevenlabs_turkish_only',True)
    monkeypatch.setattr(settings(),'elevenlabs_casting_enabled',False)
    def respond(request):
        return httpx.Response(200,json={'voices':[
            {'voice_id':'liam','name':'Liam','category':'premade','labels':{'language':'en'},'verified_languages':[{'language':'tr'}]},
            {'voice_id':'misleading','name':'Türkçe anlatıcı','category':'premade','labels':{'language':'en'}},
            {'voice_id':'native','name':'Any Name','category':'premade','labels':{'language':'tr'}},
            {'voice_id':'paid','name':'Türkçe','category':'professional','labels':{'language':'tr'},'sharing':{'free_users_allowed':True}}
        ],'has_more':False})
    voices=discover_voices(transport=httpx.MockTransport(respond))
    assert [v['voice_id'] for v in voices]==['native']
    assert voices[0]['native_turkish'] and voices[0]['language']=='tr'


def test_free_mode_falls_back_to_turkish_capable_premade(monkeypatch):
    monkeypatch.setattr(settings(),'elevenlabs_api_key','test')
    monkeypatch.setattr(settings(),'elevenlabs_turkish_only',True)
    transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'voices':[
        {'voice_id':'liam','name':'Liam','category':'premade','labels':{'language':'en'},'verified_languages':[{'language':'tr'}]}],'has_more':False}))
    voices = discover_voices(transport=transport)
    assert [voice['voice_id'] for voice in voices] == ['liam']
    assert voices[0]['turkish_verified'] is True


def test_turkish_policy_snapshots_preserve_existing_runs(monkeypatch):
    from backend.app.config import snapshot_settings,use_run_settings
    monkeypatch.setattr(settings(),'elevenlabs_turkish_only',True)
    assert snapshot_settings()['elevenlabs_turkish_only'] is True
    with use_run_settings({}):assert settings().elevenlabs_turkish_only is False
