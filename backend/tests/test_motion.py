import json
from uuid import uuid4
import pytest
from pydantic import ValidationError
from backend.app.db import DB, Run, RemoteJob
from backend.app.config import settings, use_run_settings, snapshot_settings
from backend.app.kaggle_provider import stage_job, advance_job, RemotePending
from backend.app.schemas import MotionPlan, RenderManifest
from backend.app.storage import workdir
from backend.app.motion import create_motion_plan


def new_run(project):
    with DB() as db:
        run = Run(id=str(uuid4()), project_id=project['id'], user_id='alice', revision=1, pipeline_version=2)
        db.add(run); db.commit()
        return run


def test_motion_timing_is_authoritative():
    class LLM:
        def generate(self, schema, role, context):
            result = context['allocation']
            return {'shots': [{**shot, 'duration_seconds': 1, 'scene_index': 7, 'motion_prompt': 'Leaves gently move in the wind.', 'camera': 'locked'} for shot in result]}
    # Model can choose motion; it cannot change measured audio timing.
    plan = create_motion_plan(LLM(), {}, [9.2, 4.1])
    assert sum(s['duration_seconds'] for s in plan['shots']) == pytest.approx(13.3)
    assert max(s['duration_seconds'] for s in plan['shots']) <= 4
    assert plan['shots'][0]['scene_index'] == 0
    assert plan['shots'][-1]['scene_index'] == 1


def test_contract_rejects_duplicate_shots_and_timeline_gap():
    shot = {'shot_id': 'shot-000', 'scene_index': 0, 'duration_seconds': 4, 'motion_prompt': 'Natural subject movement.'}
    with pytest.raises(ValidationError):
        MotionPlan(shots=[shot, shot])
    with pytest.raises(ValidationError):
        RenderManifest(duration_frames=120, clips=[{'file': 'shot-000.mp4', 'start_frame': 1, 'frames': 120}])


def test_snapshot_excludes_credentials_and_freezes_provider(setup, monkeypatch):
    monkeypatch.setattr(settings(), 'video_provider', 'kaggle')
    snapshot = snapshot_settings()
    assert not any('token' in k or 'key' in k for k in snapshot)
    monkeypatch.setattr(settings(), 'video_provider', 'none')
    with use_run_settings(snapshot):
        assert settings().video_provider == 'kaggle'
    assert settings().video_provider == 'none'


def test_lost_submit_is_not_resubmitted_and_account_is_exclusive(clients, project, monkeypatch):
    monkeypatch.setattr(settings(), 'kaggle_username', 'test-account')
    run = new_run(project)
    folder = workdir(project['id'], run.id)
    job = stage_job(run, folder, {'runtime': 'test'}, bootstrap=True)
    assert stage_job(run, folder, {'runtime': 'test'}, bootstrap=True).id == job.id
    with pytest.raises(RemotePending):
        stage_job(run, folder, {'runtime': 'other'}, bootstrap=True)
    class Gateway:
        calls = 0
        def status(self, ref): return 'missing'
        def submit(self, folder, gpu):
            self.calls += 1
            raise RuntimeError('lost response')
    gateway = Gateway()
    with pytest.raises(RuntimeError): advance_job(job, folder, gateway, bootstrap=True)
    with DB() as db: job = db.get(RemoteJob, job.id)
    with pytest.raises(RemotePending): advance_job(job, folder, gateway, bootstrap=True)
    assert gateway.calls == 1


def test_waiting_remote_cancellation_and_hidden_settings(clients, project):
    alice, bob = clients
    run = alice.post('/api/v1/projects/'+project['id']+'/runs').json()
    assert run['pipeline_version'] == 3 and len(run['agents']) == 8
    assert '_config' not in run['outputs']
    with DB() as db:
        current = db.get(Run, run['id']); current.status = 'waiting_remote'; db.commit()
    assert bob.post('/api/v1/runs/'+run['id']+'/cancel').status_code == 404
    assert alice.post('/api/v1/projects/'+project['id']+'/runs').json()['id'] == run['id']
    assert alice.post('/api/v1/runs/'+run['id']+'/cancel').json()['status'] == 'cancelled'


def test_stale_revision_is_never_assembled(clients, project):
    from backend.app.db import Project
    from backend.app.pipeline import cancellation
    from backend.app.media import Cancelled
    run = new_run(project)
    with DB() as db:
        db.get(Project, project['id']).revision += 1
        db.commit()
    with pytest.raises(Cancelled, match='Eski sürüme'):
        cancellation(run.id)


def test_voice_checkpoint_avoids_rebilling_completed_scene(clients, project, monkeypatch):
    import wave
    from backend.app import pipeline
    from backend.app.providers import QuotaExceeded
    monkeypatch.setattr('backend.app.voice_selection.select_voice', lambda *a, **k: None)
    run = new_run(project)
    with DB() as db:
        db.get(Run, run.id).outputs = {'script': {'scenes': [{'narration': 'first'}, {'narration': 'second'}]}}
        db.commit()
    calls = []
    def voice(text, target, check, **kwargs):
        calls.append(text)
        if len(calls) == 2:
            raise QuotaExceeded('test interruption')
        with wave.open(str(target), 'wb') as wav:
            wav.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
            wav.writeframes(b'\x01\x01' * 8000)
        return 1.0
    monkeypatch.setattr(pipeline.media, 'voice', voice)
    with pytest.raises(QuotaExceeded): pipeline.run_stage(run.id, 'voice')
    pipeline.run_stage(run.id, 'voice')
    assert calls == ['first', 'second', 'second']


def test_known_unsent_job_can_reclaim_slot(clients, project, monkeypatch):
    monkeypatch.setattr(settings(), 'kaggle_username', 'test-account')
    run = new_run(project)
    folder = workdir(project['id'], run.id)
    job = stage_job(run, folder, {'runtime': 'test'}, bootstrap=True)
    with DB() as db:
        current = db.get(RemoteJob, job.id)
        current.status, current.account_slot = 'not_submitted', None
        db.commit()
    recovered = stage_job(run, folder, {'runtime': 'test'}, bootstrap=True)
    assert recovered.id == job.id
    assert recovered.status == 'prepared' and recovered.account_slot == 'test-account'


def test_partial_retry_only_regenerates_failed_shots(clients, project, monkeypatch):
    from types import SimpleNamespace
    from backend.app import kaggle_provider as provider
    from backend.app.storage import file_hash
    run = new_run(project)
    folder = workdir(project['id'], run.id)
    image = folder / 'reference.png'; image.write_bytes(b'owned reference')
    plan = {'shots': [{'shot_id': f'shot-{i:03}', 'scene_index': 0, 'duration_seconds': 4, 'motion_prompt': 'Natural motion in the forest.', 'camera': 'locked'} for i in range(2)]}
    requests = []
    class Gateway:
        def status(self, ref): return 'complete'
    monkeypatch.setattr(provider, 'KaggleGateway', Gateway)
    def staged(run, folder, request, **kwargs):
        ident = f"attempt-{request['attempt']}"
        output = folder / 'kaggle' / ident / 'output'; output.mkdir(parents=True)
        clips = {}
        for shot in request['shots']:
            path = output / (shot['shot_id'] + '.mp4'); path.write_bytes(b'clip')
            clips[shot['shot_id']] = {'sha256': file_hash(path)}
        requests.append([s['shot_id'] for s in request['shots']])
        return SimpleNamespace(id=ident, status='complete', result={'run_id': run.id, 'revision': run.revision, 'clips': clips})
    monkeypatch.setattr(provider, 'stage_job', staged)
    def inspect(path, duration, check):
        if path.name == 'shot-001.mp4' and 'attempt-0' in str(path): raise RuntimeError('bad clip')
        return {'decoded': True}
    monkeypatch.setattr('backend.app.media.inspect_clip', inspect)
    clips = provider.generate_clips(run, folder, plan, [image], lambda: None)
    assert len(clips) == 2
    assert requests == [['shot-000', 'shot-001'], ['shot-001']]


def test_remote_progress_is_safe_and_failed_engine_retry_retains_upstream(clients, project):
    from backend.app.kaggle_provider import ENGINE_REVISION
    alice, _ = clients
    run = new_run(project)
    with DB() as db:
        current = db.get(Run, run.id)
        current.status, current.stage = 'failed', 'motion'
        current.outputs = {'voice': {'duration': 31}, 'visual': {'images': ['reference']}, '_motion_plan': {'shots': []}}
        db.add(RemoteJob(id=str(uuid4()), run_id=run.id, input_hash='a'*64, kernel='test/private', status='complete',
                         result={'clips': {'shot-000': {}}, 'errors': {'shot-001': 'ValueError'}, 'private_log': 'must-stay-private'}))
        db.commit()
    response = alice.get('/api/v1/projects/' + project['id'])
    assert response.status_code == 200
    job = response.json()['run']['remote_jobs'][0]
    assert job['completed_clips'] == job['failed_clips'] == 1
    assert 'must-stay-private' not in response.text
    response = alice.post('/api/v1/runs/' + run.id + '/retry')
    assert response.status_code == 202
    with DB() as db:
        outputs = db.get(Run, run.id).outputs
        assert outputs['_motion_engine'] == ENGINE_REVISION
        assert outputs['voice']['duration'] == 31 and outputs['visual']['images'] == ['reference']


def test_official_cancel_resolves_exact_session_and_closes_stream(setup, monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from backend.app.kaggle_provider import KaggleGateway
    from backend.app.providers import ProviderError
    monkeypatch.setattr(settings(), 'kaggle_username', 'test-account')
    calls = []
    class Response:
        history = []
        url = 'https://api.kaggle.com/v1/kernels/output/download_zip/123456'
        def close(self): calls.append('closed')
    class API:
        def download_kernel_output(self, request):
            assert request.owner_slug == 'test-account' and request.kernel_slug == 'owned'
            assert request.version_number == 3
            return Response()
        def cancel_kernel_session(self, request):
            assert calls == ['closed']
            calls.append(request.kernel_session_id)
            return SimpleNamespace(error_message='')
    gateway = KaggleGateway.__new__(KaggleGateway)
    gateway.api = SimpleNamespace(build_kaggle_client=lambda: nullcontext(SimpleNamespace(kernels=SimpleNamespace(kernels_api_client=API()))))
    gateway.cancel('test-account/owned/3')
    assert calls == ['closed', 123456]
    with pytest.raises(ProviderError): gateway.cancel('another-account/owned/3')


def test_kaggle_cancel_acknowledged_releases_account_slot(clients, project, monkeypatch):
    from backend.app.providers import ProviderError
    monkeypatch.setattr(settings(), 'kaggle_username', 'test-account')
    run = new_run(project)
    folder = workdir(project['id'], run.id)
    job = stage_job(run, folder, {'runtime': 'test'}, bootstrap=True)
    class Gateway:
        def status(self, ref): return 'cancel_acknowledged'
    with pytest.raises(ProviderError): advance_job(job, folder, Gateway(), bootstrap=True)
    with DB() as db:
        current = db.get(RemoteJob, job.id)
        assert current.status == 'failed' and current.account_slot is None


def test_lost_dataset_upload_response_backs_off_and_submits_once(clients, project, monkeypatch):
    from backend.app.db import now
    from backend.app.kaggle_provider import safe_error
    from requests.exceptions import ConnectionError
    monkeypatch.setattr(settings(), 'kaggle_username', 'test-account')
    run = new_run(project)
    folder = workdir(project['id'], run.id)
    job = stage_job(run, folder, {'runtime': 'test'}, bootstrap=True)
    class Gateway:
        uploads = 0
        submissions = 0
        def status(self, ref): return 'missing'
        def upload(self, folder):
            self.uploads += 1
            if self.uploads == 1:
                # The remote dataset exists, but its response was lost.
                raise safe_error(ConnectionError('connection interrupted'))
        def submit(self, folder, gpu):
            self.submissions += 1
            return 1
    gateway = Gateway()
    before = now()
    with pytest.raises(RemotePending): advance_job(job, folder, gateway)
    with DB() as db:
        saved = db.get(RemoteJob, job.id)
        assert saved.status == 'prepared' and saved.next_poll > before
    with pytest.raises(RemotePending): advance_job(job, folder, gateway)
    assert gateway.uploads == 2 and gateway.submissions == 1
    with DB() as db:
        assert db.get(RemoteJob, job.id).status == 'pending'


def test_cancel_restart_waits_for_remote_stop_and_changes_session(clients, project):
    alice, _ = clients
    run = new_run(project)
    ident = str(uuid4())
    with DB() as db:
        current = db.get(Run, run.id)
        current.status, current.stage = 'waiting_remote', 'motion'
        current.outputs = {'voice': {'duration': 31}, 'visual': {'images': ['reference']}}
        db.add(RemoteJob(id=ident, run_id=run.id, input_hash='b'*64, kernel='test/owned',
                         status='running', account_slot='test-account'))
        db.commit()
    assert alice.post('/api/v1/runs/' + run.id + '/cancel').status_code == 200
    assert alice.post('/api/v1/runs/' + run.id + '/retry').status_code == 409
    with DB() as db:
        job = db.get(RemoteJob, ident)
        job.status, job.account_slot = 'discarded', None
        db.commit()
    response = alice.post('/api/v1/runs/' + run.id + '/retry')
    assert response.status_code == 202
    assert '_motion_session' not in response.json()['outputs']
    with DB() as db:
        outputs = db.get(Run, run.id).outputs
        assert outputs['_motion_session']
        assert outputs['voice']['duration'] == 31
        assert outputs['visual']['images'] == ['reference']


def test_concurrent_cancel_restart_uses_one_session_on_postgres(clients, project):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from backend.app import db as dbmod
    if dbmod.engine.dialect.name != 'postgresql':
        pytest.skip('Requires PostgreSQL row locking.')
    alice, _ = clients
    run = new_run(project)
    with DB() as db:
        current = db.get(Run, run.id)
        current.status, current.stage = 'cancelled', 'motion'
        db.commit()
    barrier = Barrier(2)
    def retry():
        barrier.wait(timeout=10)
        return alice.post('/api/v1/runs/' + run.id + '/retry').status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: retry(), range(2)))
    assert sorted(results) == [202, 409]
    with DB() as db:
        current = db.get(Run, run.id)
        assert current.status == 'queued' and current.outputs['_motion_session']


def test_finished_remote_output_is_recovered_after_long_worker_outage(clients, project, monkeypatch):
    from backend.app.db import now
    monkeypatch.setattr(settings(), 'kaggle_username', 'test-account')
    run = new_run(project)
    folder = workdir(project['id'], run.id)
    job = stage_job(run, folder, {'runtime': 'test'}, bootstrap=True)
    with DB() as db:
        db.get(RemoteJob, job.id).created = now() - settings().kaggle_timeout_seconds - 3600
        db.commit()
        job = db.get(RemoteJob, job.id)
    class Gateway:
        def status(self, ref): return 'complete'
        def submit(self, *args, **kwargs): raise AssertionError('Must not submit a second job')
        def collect(self, ref, target):
            target.mkdir(parents=True)
            (target / 'result.json').write_text(json.dumps({'run_id': run.id, 'revision': 1, 'clips': {}, 'errors': {}}))
    result = advance_job(job, folder, Gateway())
    assert result['run_id'] == run.id
    with DB() as db:
        current = db.get(RemoteJob, job.id)
        assert current.status == 'complete' and current.account_slot is None
