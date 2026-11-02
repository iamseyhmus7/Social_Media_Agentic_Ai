from uuid import uuid4
from types import SimpleNamespace

import httpx
import pytest

from backend.app.config import settings
from backend.app.db import DB, Project, Run, Event
from backend.app.media_providers import elevenlabs_audio
from backend.app.pipeline import checkpoint, run_stage
from backend.app.providers import ProviderError
from backend.app.schemas import VoiceProfile
from backend.app.voice_selection import select_voice


@pytest.fixture
def voice_run(setup, monkeypatch):
    cfg = settings()
    monkeypatch.setattr(cfg, 'elevenlabs_turkish_only', False)
    monkeypatch.setattr(cfg, 'tts_provider', 'elevenlabs')
    monkeypatch.setattr(cfg, 'elevenlabs_voice_source', 'profiles')
    monkeypatch.setattr(cfg, 'elevenlabs_casting_enabled', False)
    monkeypatch.setattr(cfg, 'elevenlabs_model', 'eleven_multilingual_v2')
    monkeypatch.setattr(cfg, 'evren_audio_input_verified', False)
    monkeypatch.setattr(cfg, 'elevenlabs_api_key', 'private-test-key')
    monkeypatch.setattr(cfg, 'elevenlabs_voice_profiles', [
        VoiceProfile(key='warm', name='Sıcak anlatıcı', voice_id='female-id', description='Türkçe, sıcak, sakin, kadın anlatıcı.'),
        VoiceProfile(key='energetic', name='Enerjik anlatıcı', voice_id='male-id', description='Türkçe, dinamik, net, erkek anlatıcı.'),
    ])
    with DB() as db:
        project = Project(id=str(uuid4()), user_id='alice', title='Test', topic='Spor hikâyesi')
        db.add(project)
        db.commit()
        run = Run(id=str(uuid4()), project_id=project.id, user_id='alice', revision=1, status='running')
        db.add(run)
        db.commit()
        return run.id


def decision(profile='energetic'):
    return {'profile_key': profile, 'reason': 'Hareketli anlatım temposuna uygun bir ses.', 'stability': 0.45, 'style': 0.3}


def test_selection_persisted_and_reused_on_retry(voice_run):
    calls = []
    def generate(schema, role, context):
        calls.append(context)
        assert 'voice_id' not in context['available_voices'][0]
        return decision()
    first = select_voice(voice_run, {'topic': 'Spor'}, SimpleNamespace(generate=generate))
    second = select_voice(voice_run, {}, SimpleNamespace(generate=lambda *a: pytest.fail('Must reuse choice')))
    assert first == second
    assert first['voice_id'] == 'male-id'
    assert len(calls) == 1
    with DB() as db:
        assert db.query(Event).filter(Event.run_id == voice_run).count() == 1


def test_unknown_voice_rejected_before_tts(voice_run):
    with pytest.raises(ProviderError, match='listesinin dışında'):
        select_voice(voice_run, {}, SimpleNamespace(generate=lambda *args: decision('invented')))
    with DB() as db:
        assert '_voice_plan' not in db.get(Run, voice_run).outputs


def test_removed_voice_does_not_silently_change_narrator(voice_run, monkeypatch):
    select_voice(voice_run, {}, SimpleNamespace(generate=lambda *args: decision()))
    monkeypatch.setattr(settings(), 'elevenlabs_voice_profiles', [])
    with pytest.raises(ProviderError, match='kaldırılmış'):
        select_voice(voice_run, {})


def test_single_voice_compatibility(voice_run, monkeypatch):
    monkeypatch.setattr(settings(), 'elevenlabs_voice_profiles', [])
    assert select_voice(voice_run, {}) is None


def test_same_agent_choice_used_for_all_scenes(voice_run, monkeypatch):
    from backend.app import pipeline
    monkeypatch.setattr(pipeline.Evren, 'generate', lambda *a: decision())
    seen = []
    def voice(text, target, check, *, voice_plan):
        seen.append(voice_plan)
        target.write_bytes(b'test-audio')
        return 15
    monkeypatch.setattr(pipeline.media, 'voice', voice)
    checkpoint(voice_run, 'script', {'scenes': [{'narration': 'Test bir'}, {'narration': 'Test iki'}]})
    run_stage(voice_run, 'voice')
    assert len(seen) == 2
    assert seen[0] == seen[1]
    with DB() as db:
        output = db.get(Run, voice_run).outputs['voice']
        assert output['selection']['voice_id'] == 'male-id'
        assert output['duration'] == 30


def test_selected_voice_and_settings_reach_elevenlabs(voice_run):
    def respond(request):
        import json
        assert request.url.path.endswith('/female-id')
        assert json.loads(request.content)['voice_settings']['stability'] == 0.5
        return httpx.Response(200, content=b'test-audio')
    elevenlabs_audio('Merhaba', lambda: None, voice_id='female-id', voice_settings={'stability': 0.5}, transport=httpx.MockTransport(respond))


def test_discovery_works_without_manual_profiles_and_preserves_choice(voice_run, monkeypatch):
    from backend.app import voice_selection as selection
    from backend.app.schemas import VoiceShortlist
    monkeypatch.setattr(settings(), 'elevenlabs_voice_source', 'api')
    monkeypatch.setattr(settings(), 'elevenlabs_voice_profiles', [])
    monkeypatch.setattr(selection, 'discover_voices', lambda *a: [{'key': 'voice_0', 'voice_id': 'api-voice', 'name': 'API voice', 'description': 'Warm voice', 'labels': {}, 'turkish_verified': True}])
    monkeypatch.setattr(selection, 'preview_metrics', lambda *a, **k: {'status': 'measured', 'method': 'signal_metrics_only'})
    def generate(schema, role, context):
        return {'profile_keys': ['voice_0']} if schema is VoiceShortlist else decision('voice_0')
    plan = select_voice(voice_run, {}, SimpleNamespace(generate=generate))
    assert plan['voice_id'] == 'api-voice'
    assert plan['audio_understanding_performed'] is False
    monkeypatch.setattr(selection, 'discover_voices', lambda *a: pytest.fail('Must reuse saved choice'))
    assert select_voice(voice_run, {}) == plan


def test_audio_review_receives_clip_and_does_not_persist_base64(voice_run, monkeypatch):
    from backend.app import voice_selection as selection
    from backend.app.schemas import VoiceShortlist, VoiceAudition
    monkeypatch.setattr(settings(), 'elevenlabs_voice_source', 'api')
    monkeypatch.setattr(settings(), 'evren_audio_input_verified', True)
    monkeypatch.setattr(selection, 'discover_voices', lambda *a: [{'key': 'voice_0', 'voice_id': 'api-voice', 'name': 'API voice', 'description': 'Warm voice', 'labels': {}, 'turkish_verified': True}])
    monkeypatch.setattr(selection, 'preview_metrics', lambda *a, **k: {'status': 'measured', '_audio_input': {'type': 'input_audio', 'input_audio': {'data': 'dGVzdA==', 'format': 'wav'}}})
    def generate(schema, role, context, **kwargs):
        if schema is VoiceShortlist:
            return {'profile_keys': ['voice_0']}
        if schema is VoiceAudition:
            assert kwargs['media_inputs'][0]['input_audio']['format'] == 'wav'
            return {'heard': True, 'transcript_excerpt': 'Merhaba', 'suitability': 0.8, 'reason': 'Anlaşılır ve uygun.', 'issues': []}
        assert context['evaluation_method'] == 'audio_model_review'
        return decision('voice_0')
    plan = select_voice(voice_run, {}, SimpleNamespace(generate=generate))
    assert plan['audio_understanding_performed'] is True
    assert '_audio_input' not in str(plan)
