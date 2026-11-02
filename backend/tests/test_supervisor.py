from uuid import uuid4
from backend.app.db import DB, Run, Project
from backend.app.pipeline import execute, checkpoint


def create_run():
    with DB() as db:
        project = Project(id=str(uuid4()),user_id='alice',title='Supervisor testi',topic='Bir hikâye')
        db.add(project)
        db.commit()
        run = Run(id=str(uuid4()),project_id=project.id,user_id='alice',revision=1,status='queued')
        db.add(run)
        db.commit()
        return run.id


def test_real_graph_durable_stage_resume(setup,monkeypatch):
    from backend.app import pipeline
    run_id=create_run()
    seen=[]
    def stage(identifier,key):
        seen.append(key)
        checkpoint(identifier,key,{'passed':True} if key=='quality' else {'duration':45} if key=='voice' else {'test':True})
    monkeypatch.setattr(pipeline,'run_stage',stage)
    execute(run_id)
    with DB() as db:
        result=db.get(Run,run_id)
        assert result.status=='awaiting_approval'
        assert result.active_owner is None
        assert set(pipeline.STAGES).issubset(result.outputs)
    assert seen==pipeline.STAGES


def test_quality_revision_is_bounded(setup,monkeypatch):
    from backend.app import pipeline
    run_id=create_run()
    with DB() as db:
        db.get(Run,run_id).outputs = {'_motion_session': 'explicit-restart'}
        db.commit()
    voices=[]
    def stage(identifier,key):
        if key=='voice':voices.append(key)
        checkpoint(identifier,key,{'duration':90} if key=='voice' else {'scenes':[{'narration':'Örnek anlatım metni.'}]} if key=='script' else {'test':True})
    monkeypatch.setattr(pipeline,'run_stage',stage)
    monkeypatch.setattr(pipeline.Evren,'generate',lambda *args,**kwargs:{'hook':'Test','cta':'Test','scenes':[]})
    execute(run_id)
    with DB() as db:
        result=db.get(Run,run_id)
        assert result.status=='failed'
        assert result.outputs['_repair_attempts']==1
        assert result.outputs['_motion_session']=='explicit-restart'
        assert 'bir otomatik revizyon' in result.error
    assert len(voices)==2
