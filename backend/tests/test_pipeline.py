from uuid import uuid4
import json
import httpx
import pytest
from backend.app.db import DB, Run, Project, WorkerLease, now
from backend.app.pipeline import execute, checkpoint, build_graph, STAGES
from backend.app.providers import Evren, ProviderError, QuotaExceeded
from backend.app.config import settings
from backend.app.schemas import Plan
from backend.app.worker import lease, tick
from backend.app.storage import check_disk


def test_evren_requires_verified_contract(setup,monkeypatch):
    cfg=settings()
    for key,value in [('evren_api_key','test'),('evren_base_url','https://example.test/v1'),('evren_model','test-model')]:monkeypatch.setattr(cfg,key,value)
    with pytest.raises(ProviderError,match='sözleşmesi'):
        Evren().generate(Plan,'Supervisor',{})


def test_validation_repair_limited_and_quota(setup,monkeypatch):
    cfg=settings()
    for key,value in [('evren_api_key','test'),('evren_base_url','https://example.test/v1'),('evren_model','test-model'),('evren_contract_verified',True),('evren_protocol','openai_chat')]:monkeypatch.setattr(cfg,key,value)
    calls=[]
    def invalid(request):
        calls.append(request)
        return httpx.Response(200,json={'choices':[{'message':{'content':'not json'}}]})
    with pytest.raises(ProviderError,match='üç'):
        Evren(httpx.MockTransport(invalid)).generate(Plan,'Supervisor',{})
    assert len(calls)==3
    with pytest.raises(QuotaExceeded):
        Evren(httpx.MockTransport(lambda req:httpx.Response(429))).generate(Plan,'Supervisor',{})


def test_checkpoint_resume_and_missing_evren(clients,project,monkeypatch):
    alice,_=clients
    run_id=alice.post('/api/v1/projects/'+project['id']+'/runs').json()['id']
    with DB() as db:
        db.get(Run,run_id).pipeline_version=2
        db.commit()
    checkpoint(run_id,'supervisor',{'goal':'Önceden tamamlandı','checks':['Ses']})
    execute(run_id)
    result=alice.get('/api/v1/runs/'+run_id).json()
    assert result['status']=='failed'
    assert 'supervisor' in result['outputs']
    assert result['stage']=='strategy'
    assert result['error'].startswith('Evren API')


def test_worker_exclusive_and_recovers_interruption(setup):
    run_id = str(uuid4())
    with DB() as db:
        project = Project(id=str(uuid4()), user_id='alice', title='Test', topic='Kesinti testi')
        db.add(project)
        db.commit()
        db.add(Run(id=run_id, project_id=project.id, user_id='alice', revision=1, status='queued'))
        db.commit()
    with lease() as first:
        assert first
        with lease() as second:assert not second
    with DB() as db:
        run=db.get(Run,run_id);run.status='running';db.commit()
    tick()
    with DB() as db:
        result = db.get(Run,run_id)
        assert result.status=='failed'
        assert 'Worker kesintisi' in result.error


def test_quota_releases_active_slot_and_cancel(clients,project,monkeypatch):
    alice,_=clients
    run_id=alice.post('/api/v1/projects/'+project['id']+'/runs').json()['id']
    def quota(*a,**k):raise QuotaExceeded('Kota bekleniyor')
    monkeypatch.setattr(Evren,'generate',quota)
    execute(run_id)
    assert alice.get('/api/v1/runs/'+run_id).json()['status']=='waiting_quota'
    with DB() as db:assert db.get(Run,run_id).active_owner is None
    assert alice.post('/api/v1/runs/'+run_id+'/cancel').json()['status']=='cancelled'


def test_disk_limit_is_real(setup,monkeypatch):
    monkeypatch.setattr(settings(),'max_disk_gb',0)
    with pytest.raises(RuntimeError,match='depolama'):
        check_disk()


def test_full_graph_with_mocked_media_only(clients,project,monkeypatch):
    """Graph integration; deliberately no claim to live Evren/TTS/GPU verification."""
    from backend.app import pipeline
    alice,_=clients
    run_id=alice.post('/api/v1/projects/'+project['id']+'/runs').json()['id']
    with DB() as db:
        db.get(Run,run_id).pipeline_version=2
        db.commit()
    seen=[]
    def fake_stage(identifier,stage):
        seen.append(stage)
        checkpoint(identifier,stage,{'passed':True} if stage=='quality' else {'test':True})
    monkeypatch.setattr(pipeline,'run_stage',fake_stage)
    execute(run_id)
    result=alice.get('/api/v1/runs/'+run_id).json()
    assert result['status']=='awaiting_approval'
    assert seen==pipeline.V2_STAGES
    assert result['approved'] is False


def test_silent_tail_trim_preserves_spoken_samples(tmp_path):
    import wave
    from backend.app.media import trim_silent_tail
    source, target = tmp_path/'original.wav', tmp_path/'fitted.wav'
    spoken = b'\xe8\x03' * 1000
    pcm = spoken + b'\x00\x00' * 200
    with wave.open(str(source), 'wb') as wav:
        wav.setparams((1, 2, 1000, 0, 'NONE', 'none'))
        wav.writeframes(pcm)
    assert trim_silent_tail(source, target, .09) == 1.11
    with wave.open(str(target), 'rb') as wav:
        assert wav.readframes(wav.getnframes()) == pcm[:2220]
    assert trim_silent_tail(source, target, .11) is None
    with wave.open(str(source), 'wb') as wav:
        wav.setparams((1, 2, 1000, 0, 'NONE', 'none'))
        wav.writeframes(spoken + b'\x00\x00' * 100)
    assert trim_silent_tail(source, target, .09) is None


def test_boundary_recovery_resumes_without_another_script_or_tts(setup, monkeypatch):
    import wave
    from backend.app import pipeline
    from backend.app.storage import workdir, register, file_hash
    with DB() as db:
        project = Project(id=str(uuid4()), user_id='alice', title='Test', topic='Tarih', duration=45)
        db.add(project)
        db.commit()
        run = Run(id=str(uuid4()), project_id=project.id, user_id='alice', revision=1, pipeline_version=2)
        db.add(run)
        db.commit()
        run_id = run.id
        source = workdir(project.id, run_id)/'voice-0.wav'
        with wave.open(str(source), 'wb') as wav:
            wav.setparams((1, 2, 1000, 0, 'NONE', 'none'))
            wav.writeframes(b'\xe8\x03' * 46840 + b'\x00\x00' * 200)
        original_hash = file_hash(source)
        audio = register(db, run, source, 'audio')
        run.outputs = {'supervisor': {}, 'strategy': {}, 'script': {}, '_repair_attempts': 1,
                       'voice': {'audios': [audio], 'durations': [47.04], 'duration': 47.04},
                       'quality': {'passed': False, 'issues': ['Too long']}}
        db.commit()
    seen = []
    def cached_stage(identifier, stage):
        with DB() as db:
            if stage in db.get(Run, identifier).outputs:
                return
        assert stage not in ('supervisor', 'script', 'voice')
        seen.append(stage)
        checkpoint(identifier, stage, {'passed': True} if stage=='quality' else {})
    monkeypatch.setattr(pipeline, 'run_stage', cached_stage)
    build_graph(2).invoke({'run_id': run_id})
    with DB() as db:
        outputs = db.get(Run, run_id).outputs
        assert 46.94 < outputs['voice']['duration'] <= 46.95
        assert outputs['voice']['audios'] != [audio]
        assert outputs['quality']['passed']
    assert file_hash(source) == original_hash
    assert seen == ['visual', 'motion', 'editor', 'quality', 'publisher']
