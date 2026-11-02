import zipfile
import pytest
from sqlalchemy import select, func
from backend.app.db import DB, Run, Approval, Publication
from backend.app.config import snapshot_settings, use_run_settings, settings
from backend.app.storage import workdir, register
from backend.tests.test_agentic import create_run
from backend.app import pipeline, orchestration


def prohibit_models(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail('Rendered video must not trigger a model call')
    monkeypatch.setattr(pipeline.Evren, 'generate', fail)
    monkeypatch.setattr(pipeline.Evren, 'choose_action', fail)


def test_completed_render_is_packaged_for_owner_without_models_or_publication(setup, monkeypatch):
    prohibit_models(monkeypatch)
    ident = create_run({'_config': {'video_review_policy': 'technical_only', 'video_provider': 'none'},
        'script': {'scenes': [{'narration': 'Mevcut anlatım değişmeden kullanıcıya sunulur.'}]}})
    with DB() as db:
        run = db.get(Run, ident)
        folder = workdir(run.project_id, ident)
        ids = []
        for name, kind in [('video.mp4', 'video'), ('captions.srt', 'subtitle'), ('cover.png', 'cover')]:
            path = folder/name
            path.write_bytes(b'previously-validated-file')
            ids.append(register(db, run, path, kind))
        run.outputs = {**run.outputs, 'editor': {'video': ids[0], 'subtitle': ids[1],
            'report': {'passed': True, 'duration': 45, 'issues': []}}, 'visual': {'cover': ids[2]}}
        db.commit()
    pipeline.execute(ident)
    with DB() as db:
        run = db.get(Run, ident)
        assert run.status == 'awaiting_approval', run.error
        assert run.outputs['quality']['model_review_performed'] is False
        assert run.outputs['quality']['requires_human_review'] is True
        assert run.outputs['publisher']['method'] == 'existing_content_package'
        assert db.scalar(select(func.count()).select_from(Approval)) == 0
        assert db.scalar(select(func.count()).select_from(Publication)) == 0
    with zipfile.ZipFile(folder/'share-package.zip') as package:
        assert set(package.namelist()) == {'video.mp4', 'captions.srt', 'cover.png', 'publication.json'}


def test_technical_failure_requests_two_local_editor_repairs_then_waits(setup, monkeypatch):
    prohibit_models(monkeypatch)
    calls=[]
    def repair(run_id, stage, **kwargs):
        assert stage=='editor'
        calls.append(stage)
        pipeline.checkpoint(run_id,stage,{'report':{'passed':False,'issues':['Eksik ses akışı.']}})
    monkeypatch.setattr(pipeline,'run_stage',repair)
    ident = create_run({'_config': {'video_review_policy': 'technical_only', 'video_provider': 'none'},
        'editor': {'report': {'passed': False, 'issues': ['Eksik ses akışı.']}}})
    pipeline.execute(ident)
    with DB() as db:
        run = db.get(Run, ident)
        assert run.status == 'waiting_input'
        assert run.outputs['editor']['report']['issues']==['Eksik ses akışı.']
        assert calls==['editor','editor']
        assert 'publisher' not in run.outputs


def test_editor_skips_preview_and_model_review(setup, monkeypatch):
    prohibit_models(monkeypatch)
    ident = create_run({'_config': {'video_review_policy': 'technical_only'}})
    calls = []
    def stage(run_id, key, **kwargs):
        assert key == 'editor' and not kwargs.get('preview_only')
        calls.append(key)
        pipeline.checkpoint(run_id, key, {'report': {'passed': True}})
    monkeypatch.setattr(pipeline, 'run_stage', stage)
    monkeypatch.setattr(orchestration, 'review_quality', lambda *a, **k: pytest.fail('No model review'))
    orchestration.specialist(ident, 'editor')
    assert calls == ['editor']


def test_new_policy_snapshot_and_legacy_compatibility():
    assert snapshot_settings()['video_review_policy'] == 'technical_only'
    with use_run_settings({}):
        assert settings().video_review_policy == 'model'
    with use_run_settings({'video_review_policy': 'technical_only'}):
        assert settings().video_review_policy == 'technical_only'
