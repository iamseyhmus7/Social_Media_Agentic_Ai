from uuid import uuid4
from pathlib import Path
import pytest
from sqlalchemy import select
from backend.app.db import DB, Project, Run, Asset, Event, Approval, Publication, RemoteJob, User
from backend.app.storage import workdir, register, media_path
from backend.app.content_deletion import delete_content


def content(user='alice', status='failed'):
    with DB() as db:
        project=Project(id=str(uuid4()),user_id=user,title='Silme kontrolü',topic='Geçici test içeriği',duration=45)
        db.add(project);db.flush()
        run=Run(id=str(uuid4()),project_id=project.id,user_id=user,revision=1,status=status)
        db.add(run);db.commit()
        path=workdir(project.id,run.id)/'video.mp4';path.write_bytes(b'test-media')
        register(db,run,path,'video')
        db.add(Event(run_id=run.id,stage='editor',message='test'))
        db.add(Approval(id=str(uuid4()),run_id=run.id,user_id=user,manifest='test'))
        db.add(RemoteJob(id=str(uuid4()),run_id=run.id,input_hash='test',kernel='private-test',status='complete'))
        db.commit()
        return project.id,run.id,path


def test_batch_delete_checks_csrf_ownership_active_runs_and_removes_owned_media(clients):
    alice,bob=clients
    first=content();second=content();foreign=content('bob')
    csrf=alice.headers.pop('X-CSRF-Token')
    assert alice.delete('/api/v1/projects/'+first[0]).status_code==403
    alice.headers['X-CSRF-Token']=csrf
    assert alice.post('/api/v1/projects/delete',json={'project_ids':[first[0],foreign[0]]}).status_code==404
    assert first[2].exists() and foreign[2].exists()
    with DB() as db:
        run=db.get(Run,second[1]);run.status='running';db.commit()
    assert alice.post('/api/v1/projects/delete',json={'project_ids':[first[0],second[0]]}).status_code==409
    assert first[2].exists() and second[2].exists()
    with DB() as db:
        run=db.get(Run,second[1]);run.status='cancelled';db.commit()
    response=alice.post('/api/v1/projects/delete',json={'project_ids':[first[0],second[0]]})
    assert response.status_code==200,response.text
    assert response.json()['deleted_count']==2
    assert not first[2].exists() and not second[2].exists() and foreign[2].exists()
    with DB() as db:
        assert db.get(Project,first[0]) is None and db.get(Run,first[1]) is None
        assert db.scalar(select(Asset.id).where(Asset.project_id==first[0])) is None
        assert db.scalar(select(Event.id).where(Event.run_id==first[1])) is None
        assert db.scalar(select(Approval.id).where(Approval.run_id==first[1])) is None
        assert db.get(Project,foreign[0]) is not None
    assert bob.delete('/api/v1/projects/'+foreign[0]).status_code==200


def test_database_failure_restores_media_for_entire_batch(setup,monkeypatch):
    first=content();second=content()
    with DB() as db:
        user=db.get(User,'alice')
        def fail():raise RuntimeError('database unavailable')
        monkeypatch.setattr(db,'commit',fail)
        with pytest.raises(RuntimeError,match='database unavailable'):
            delete_content(db,user,[first[0],second[0]])
    assert first[2].read_bytes()==second[2].read_bytes()==b'test-media'
    with DB() as db:
        assert db.get(Project,first[0]) is not None and db.get(Project,second[0]) is not None


def test_remote_slot_and_uncertain_upload_block_deletion(setup):
    item=content()
    with DB() as db:
        remote=db.scalar(select(RemoteJob).where(RemoteJob.run_id==item[1]));remote.account_slot='test';db.commit()
        with pytest.raises(Exception) as exc:delete_content(db,db.get(User,'alice'),[item[0]])
        assert exc.value.status_code==409
        remote.account_slot=None
        db.add(Publication(id=str(uuid4()),project_id=item[0],run_id=item[1],status='uncertain'))
        db.commit()
        with pytest.raises(Exception) as exc:delete_content(db,db.get(User,'alice'),[item[0]])
        assert exc.value.status_code==409 and item[2].exists()


def test_quarantine_cleanup_never_purges_a_project_still_in_database(setup):
    from backend.app.content_deletion import purge_pending_content
    from backend.app.config import settings
    item=content()
    root=settings().media_root.resolve()
    folder=root/'.deleted-content'/str(uuid4())
    folder.mkdir(parents=True)
    (root/item[0]).rename(folder/item[0])
    purge_pending_content()
    assert folder.is_dir()
    with DB() as db:
        delete_content(db,db.get(User,'alice'),[item[0]])
    purge_pending_content()
    assert not folder.exists()
