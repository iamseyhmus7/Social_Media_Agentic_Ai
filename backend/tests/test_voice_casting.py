import json
import math
import struct
import wave
from types import SimpleNamespace
from uuid import uuid4
import httpx
import pytest
from backend.app.config import settings
from backend.app.db import DB, Run, Project
from backend.app.providers import ProviderError, QuotaExceeded
from backend.app.schemas import VoiceShortlist
from backend.app.voice_selection import select_voice
from backend.app.voice_catalog import discover_turkish_voices
from backend.app.media_providers import elevenlabs_audio, VoiceAccessDenied
from backend.app import voice_casting as casting


def catalog():
    return [{'key': f'voice_{i}', 'voice_id': f'turkish-{i}', 'name': f'Türkçe anlatıcı {i}',
             'description': 'Türkçe hikâye anlatımı', 'language': 'tr', 'category': 'professional', 'labels': {}}
            for i in range(5)]


@pytest.fixture
def casting_run(setup, monkeypatch):
    for key, value in {'elevenlabs_voice_source': 'api', 'elevenlabs_casting_enabled': True,
                       'elevenlabs_api_key': 'test-key', 'elevenlabs_free_voices_only': False, 'elevenlabs_turkish_only':False, 'evren_audio_input_verified': True,
                       'evren_media_model': 'mimo-v2.6-pro', 'elevenlabs_preview_checks': 3}.items():
        monkeypatch.setattr(settings(), key, value)
    monkeypatch.setattr(casting, 'discover_turkish_voices', lambda check: catalog())
    with DB() as db:
        project = Project(id=str(uuid4()), user_id='alice', title='Tarih', topic='Tarih belgeseli')
        db.add(project)
        db.commit()
        run = Run(id=str(uuid4()), project_id=project.id, user_id='alice', revision=1,
                  outputs={'script': {'scenes': [{'narration': 'Bu bir Türkçe tarih hikâyesinin ortak deneme metnidir.'}]}})
        db.add(run)
        db.commit()
        return run.id


def fake_voice(text, path, check, *, voice_plan):
    with wave.open(str(path), 'wb') as audio:
        audio.setparams((1, 2, 22050, 0, 'NONE', 'none'))
        audio.writeframes(b''.join(struct.pack('<h', round(1500*math.sin(i/10))) for i in range(22050)))
    return 1


def fake_llm(calls, *, selected='voice_1', reject=False, fail=False):
    def generate(schema, role, context, **kwargs):
        calls.append((role, context, kwargs))
        if issubclass(schema, VoiceShortlist):
            return {'profile_keys': [v['key'] for v in catalog()[:3]]}
        if fail:
            raise ProviderError('Model geçici olarak erişilemiyor.')
        keys = [v['key'] for v in context['available_voices']]
        return {'reviews': [{'profile_key': key, 'heard': True, 'language': 'other' if reject else 'tr',
                             'transcript_excerpt': 'Bu bir Türkçe tarih hikâyesinin', 'suitability': .8,
                             'reason': 'Senaryo tonuyla uyumlu, anlaşılır bir örnek.', 'issues': []} for key in keys],
                'decision': {'profile_key': selected, 'reason': 'Türkçe telaffuzu ve senaryonun tonuna uygun ritmiyle seçildi.', 'stability': .6, 'style': .2}}
    return SimpleNamespace(generate=generate)


def test_three_actual_readings_and_full_script_reach_model(casting_run, monkeypatch):
    generated, calls = [], []
    def voice(text, path, check, *, voice_plan):
        generated.append((text, voice_plan['voice_id']))
        return fake_voice(text, path, check, voice_plan=voice_plan)
    monkeypatch.setattr(casting.media, 'voice', voice)
    plan = select_voice(casting_run, {'brand': {'voice': 'retired-voice'}}, fake_llm(calls))
    assert len(generated) == len({v for _, v in generated}) == 3
    assert len({text for text, _ in generated}) == 1
    listening = [call for call in calls if call[2].get('media_inputs')]
    assert len(listening) == 2 and all(len(call[2]['media_inputs']) == 2 for call in listening)
    assert {v['key'] for call in listening for v in call[1]['available_voices']} == {'voice_0','voice_1','voice_2'}
    assert calls[-1][1]['script']['scenes'][0]['narration'] == generated[0][0]
    assert 'voice' not in calls[-1][1]['brand']
    assert plan['voice_id'] == 'turkish-1' and plan['decision_model'] == 'mimo-v2.6-pro'
    with DB() as db:
        output = db.get(Run, casting_run).outputs
        ready = [v for v in output['voice_casting']['candidates'] if v.get('status') == 'ready']
        assert len(ready) == 3 and all(v['asset_id'] for v in ready)
        assert 'input_audio' not in json.dumps(output)
    monkeypatch.setattr(casting.media, 'voice', lambda *a, **k: pytest.fail('Retry must reuse selected narrator'))
    assert select_voice(casting_run, {}) == plan


def test_model_failure_reuses_generated_auditions_on_retry(casting_run, monkeypatch):
    monkeypatch.setattr(casting.media, 'voice', fake_voice)
    with pytest.raises(ProviderError, match='Model'):
        select_voice(casting_run, {}, fake_llm([], fail=True))
    monkeypatch.setattr(casting.media, 'voice', lambda *a, **k: pytest.fail('Do not bill completed audition again'))
    assert select_voice(casting_run, {}, fake_llm([]))['candidate_count'] == 3


def test_free_mode_compares_three_account_voices_in_turkish(casting_run, monkeypatch):
    monkeypatch.setattr(settings(), 'elevenlabs_free_voices_only', True)
    monkeypatch.setattr(casting, 'discover_turkish_voices', lambda check: pytest.fail('Free API must not use Voice Library'))
    monkeypatch.setattr(casting, 'discover_voices', lambda check: [{**v, 'category': 'premade', 'turkish_verified': False} for v in catalog()])
    monkeypatch.setattr(casting.media, 'voice', fake_voice)
    calls = []
    assert select_voice(casting_run, {}, fake_llm(calls))['candidate_count'] == 3
    assert len(calls[-1][2]['media_inputs']) == 2
    with DB() as db:
        assert all(v['library_users'] is None for v in db.get(Run, casting_run).outputs['voice_casting']['candidates'])


def test_retry_reuses_completed_comparison_round(casting_run, monkeypatch):
    monkeypatch.setattr(casting.media, 'voice', fake_voice)
    base = fake_llm([])
    def generate(schema, role, context, **kwargs):
        if context.get('comparison_round') == 2:
            raise ProviderError('İkinci tur bağlantısı kesildi.')
        return base.generate(schema, role, context, **kwargs)
    with pytest.raises(ProviderError, match='İkinci tur'):
        select_voice(casting_run, {}, SimpleNamespace(generate=generate))
    monkeypatch.setattr(casting.media, 'voice', lambda *a, **k: pytest.fail('Reuse recorded audio'))
    calls = []
    select_voice(casting_run, {}, fake_llm(calls))
    assert [call[1]['comparison_round'] for call in calls] == [2]


def test_account_auth_error_stops_instead_of_rotating_voices(casting_run, monkeypatch):
    calls = []
    def denied(*args, **kwargs):
        calls.append(True)
        raise ProviderError('ElevenLabs anahtarında Metinden Sese izni eksik.')
    monkeypatch.setattr(casting.media, 'voice', denied)
    with pytest.raises(ProviderError, match='izni eksik'):
        select_voice(casting_run, {}, fake_llm([]))
    assert len(calls) == 1
    with DB() as db:
        assert db.get(Run, casting_run).outputs['voice_casting']['phase'] == 'blocked'


def test_inaccessible_voice_is_not_silently_replaced(casting_run, monkeypatch):
    def voice(text, path, check, *, voice_plan):
        if voice_plan['voice_id'] == 'turkish-0':
            raise VoiceAccessDenied('Bu sese API erişimi yok.')
        return fake_voice(text, path, check, voice_plan=voice_plan)
    monkeypatch.setattr(casting.media, 'voice', voice)
    with pytest.raises(ProviderError, match='tümünde API erişimi'):
        select_voice(casting_run, {}, fake_llm([]))


def test_non_turkish_or_invented_model_choice_is_rejected(casting_run, monkeypatch):
    monkeypatch.setattr(casting.media, 'voice', fake_voice)
    with pytest.raises(ValueError, match='Türkçe'):
        select_voice(casting_run, {}, fake_llm([], reject=True))
    with pytest.raises(ValueError, match='Türkçe'):
        select_voice(casting_run, {}, fake_llm([], selected='invented'))


def test_native_library_filters_language_rates_and_paginates(monkeypatch):
    monkeypatch.setattr(settings(), 'elevenlabs_api_key', 'test')
    monkeypatch.setattr(settings(), 'elevenlabs_free_voices_only', True)
    calls = []
    def respond(request):
        calls.append(request)
        assert request.url.params['language'] == 'tr'
        page = int(request.url.params['page'])
        return httpx.Response(200, json={'voices': [
            {'voice_id': f'turkish-{page}', 'name': 'Türkçe anlatıcı', 'language': 'tr', 'free_users_allowed': True, 'rate': 1},
            {'voice_id': 'other-native', 'name': 'Türkçe ses', 'language': 'tr', 'free_users_allowed': True, 'rate': 1, 'cloned_by_count': 123},
            {'voice_id': 'english', 'language': 'en', 'free_users_allowed': True},
            {'voice_id': 'premium', 'language': 'tr', 'free_users_allowed': True, 'rate': 2},
            {'voice_id': 'paid', 'language': 'tr', 'free_users_allowed': False},
        ], 'has_more': page == 0})
    result = discover_turkish_voices(transport=httpx.MockTransport(respond))
    assert len(result) == 3 and len(calls) == 2
    assert {v['voice_id'] for v in result} == {'turkish-0','turkish-1','other-native'}
    assert next(v for v in result if v['voice_id']=='other-native')['library_users'] == 123


def test_eleven_v4_uses_supported_dialogue_settings(monkeypatch):
    monkeypatch.setattr(settings(), 'elevenlabs_api_key', 'test')
    monkeypatch.setattr(settings(), 'elevenlabs_model', 'eleven_v4')
    def respond(request):
        data = json.loads(request.content)
        assert request.url.path == '/v1/text-to-dialogue'
        assert data['model_id'] == 'eleven_v4' and data['language_code'] == 'tr'
        assert data['inputs'] == [{'text': 'Merhaba', 'voice_id': 'native'}]
        assert data['settings'] == {'stability': .6, 'similarity': .75}
        assert 'voice_settings' not in data
        return httpx.Response(200, content=b'audio')
    assert elevenlabs_audio('Merhaba', lambda:None, voice_id='native', voice_settings={'stability':.6,'style':.2}, transport=httpx.MockTransport(respond)) == b'audio'


@pytest.mark.parametrize(('status', 'message', 'error'), [('quota_exceeded', 'kotası', QuotaExceeded), ('missing_permissions', 'Metinden Sese', ProviderError), ('invalid_api_key', 'anahtarı', ProviderError)])
def test_401_errors_are_specific_and_private(monkeypatch, status, message, error):
    monkeypatch.setattr(settings(), 'elevenlabs_api_key', 'secret-key')
    with pytest.raises(error, match=message) as caught:
        elevenlabs_audio('Test', lambda: None, voice_id='test', transport=httpx.MockTransport(lambda request: httpx.Response(401, json={'detail': {'status': status, 'message': 'secret-key'}})))
    assert 'secret-key' not in str(caught.value)

def test_strict_casting_uses_only_native_account_candidates_and_confirms_api_access(casting_run,monkeypatch):
    monkeypatch.setattr(settings(),'elevenlabs_turkish_only',True)
    monkeypatch.setattr(settings(),'elevenlabs_free_voices_only',True)
    monkeypatch.setattr(casting,'discover_voices',lambda check:[{**v,'category':'premade','native_turkish':True} for v in catalog()])
    monkeypatch.setattr(casting,'discover_turkish_voices',lambda check:pytest.fail('No automatic library switch'))
    monkeypatch.setattr(casting.media,'voice',fake_voice)
    plan=select_voice(casting_run,{},fake_llm([]))
    assert plan['native_turkish'] and plan['api_access_verified']
    with DB() as db:
        candidates=db.get(Run,casting_run).outputs['voice_casting']['candidates']
        assert all(v['native_turkish'] and v['api_access_verified'] for v in candidates)
