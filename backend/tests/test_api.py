from uuid import uuid4
from pathlib import Path
import pytest
from sqlalchemy import select
from backend.app.db import DB, Run, Project, Asset, Approval, Publication, YouTubeConnection
from backend.app.storage import media_path, file_hash
from backend.app.youtube import manifest


def ready(project):
    with DB() as db:
        run=Run(id=str(uuid4()),project_id=project['id'],user_id='alice',revision=1,status='awaiting_approval',outputs={'quality':{'passed':True},'editor':{},'publisher':{'title':'Test video','description':'Açıklama','hashtags':['#test']}})
        db.add(run)
        db.commit()
        return run.id


def test_health_checks_database(clients, monkeypatch):
    from backend.app import db as dbmod
    alice, _ = clients
    assert alice.get('/api/v1/health').json()['database_backend'] in ('sqlite', 'postgresql')
    def unavailable():
        raise RuntimeError('internal database connection details must not be exposed')
    monkeypatch.setattr(dbmod.engine, 'connect', unavailable)
    response = alice.get('/api/v1/health')
    assert response.status_code == 503
    assert 'internal database' not in response.text


def test_ownership_and_csrf(clients,project):
    alice,bob=clients
    assert bob.get('/api/v1/projects/'+project['id']).status_code==404
    assert bob.get('/api/v1/projects').json()==[]
    old=alice.headers.pop('X-CSRF-Token')
    assert alice.post('/api/v1/projects',json={'topic':'Geçersiz istek'}).status_code==403
    alice.headers['X-CSRF-Token']=old
    assert alice.post('/api/v1/projects',json={'topic':'Geçersiz istek'},headers={'Origin':'https://evil.example'}).status_code==403


def test_only_admin_invites(clients):
    alice,bob=clients
    data={'email':'new@example.test','name':'Yeni','password':'a-long-password-123'}
    assert bob.post('/api/v1/users',json=data).status_code==403
    assert alice.post('/api/v1/users',json=data).status_code==201
    assert alice.post('/api/v1/users',json=data).status_code==409


def test_active_owner_limit_and_idempotent_start(clients,project):
    alice,bob=clients
    first=alice.post('/api/v1/projects/'+project['id']+'/runs').json()
    assert alice.post('/api/v1/projects/'+project['id']+'/runs').json()['id']==first['id']
    second=alice.post('/api/v1/projects',json={'topic':'İstanbul hakkında video'}).json()
    assert alice.post('/api/v1/projects/'+second['id']+'/runs').status_code==409
    assert bob.get('/api/v1/runs/'+first['id']).status_code==404
    assert bob.get('/api/v1/runs/'+first['id']+'/events').status_code==404
    assert alice.post('/api/v1/runs/'+first['id']+'/cancel').json()['status']=='cancelled'
    assert alice.post('/api/v1/projects/'+second['id']+'/runs').status_code==202


def test_on_approval_required_and_idempotent(clients,project):
    alice,_=clients
    run_id=ready(project)
    url='/api/v1/projects/'+project['id']
    assert alice.post(url+'/publication',json={'run_id':run_id}).status_code==409
    for _ in range(2):
        assert alice.post(url+'/approve',json={'run_id':run_id}).json()['approved'] is True
    with DB() as db:
        assert len(db.scalars(select(Approval)).all())==1
        db.add(YouTubeConnection(user_id='alice',encrypted_token='test-only-not-an-oauth-token'))
        db.commit()
    for _ in range(2):
        result=alice.post(url+'/publication',json={'run_id':run_id})
        assert result.status_code==202
    with DB() as db:
        assert len(db.scalars(select(Publication)).all())==1


def test_revision_invalidates_approval_and_cancel_queued_publication(clients,project):
    alice,_=clients
    run_id=ready(project)
    url='/api/v1/projects/'+project['id']
    alice.post(url+'/approve',json={'run_id':run_id})
    script={'hook':'Başlangıç','cta':'Takip et','scenes':[{'title':f'Sahne {i}','narration':'Türkçe örnek anlatım metni.','visual_prompt':'Cinematic example visual prompt'} for i in range(3)]}
    result=alice.post(url+'/revisions',json={'script':script})
    assert result.status_code==202
    assert result.json()['revision']==2
    assert alice.post(url+'/publication',json={'run_id':run_id}).status_code==409
    assert alice.get('/api/v1/runs/'+run_id).json()['approved'] is False


def test_private_asset_access_and_path_safety(clients,project):
    alice,bob=clients
    target=media_path(project['id']+'/test.srt');target.parent.mkdir(parents=True);target.write_text('Türkçe altyazı',encoding='utf-8')
    with DB() as db:
        db.add(Asset(id='asset-one',project_id=project['id'],revision=1,kind='subtitle',path=project['id']+'/test.srt',mime='application/x-subrip',sha256=file_hash(target)))
        db.commit()
    assert alice.get('/api/v1/assets/asset-one').status_code==200
    assert bob.get('/api/v1/assets/asset-one').status_code==404
    with pytest.raises(ValueError):
        media_path('../private.txt')


def test_publish_time_requires_timezone(clients,project):
    alice,_=clients
    run_id=ready(project);url='/api/v1/projects/'+project['id']
    alice.post(url+'/approve',json={'run_id':run_id})
    with DB() as db:
        db.add(YouTubeConnection(user_id='alice',encrypted_token='test-only'))
        db.commit()
    assert alice.post(url+'/publication',json={'run_id':run_id,'publish_at':'2099-01-01T12:00:00'}).status_code==422
    assert alice.post(url+'/publication',json={'run_id':run_id,'publish_at':'2099-01-01T12:00:00+03:00'}).json()['publish_at']=='2099-01-01T09:00:00+00:00'
