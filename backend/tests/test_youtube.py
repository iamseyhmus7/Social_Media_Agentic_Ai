from uuid import uuid4
import httpx
from backend.app.db import DB, Project, Run, Asset, Approval, Publication
from backend.app.storage import media_path, file_hash
from backend.app import youtube


def prepared():
    with DB() as db:
        project=Project(id=str(uuid4()),user_id='alice',title='Test yayını',topic='Test yayını')
        db.add(project);db.commit()
        run=Run(id=str(uuid4()),project_id=project.id,user_id='alice',revision=1,status='awaiting_approval',outputs={'quality':{'passed':True},'editor':{},'publisher':{'title':'Test yayını','description':'Bu yalnızca izole test verisidir.','hashtags':['#test']}})
        db.add(run);db.commit()
        path=media_path(f'{project.id}/{run.id}/video.mp4');path.parent.mkdir(parents=True);path.write_bytes(b'isolated-test-video-bytes')
        asset=Asset(id=str(uuid4()),project_id=project.id,run_id=run.id,revision=1,kind='video',path=path.relative_to(youtube.settings().media_root.resolve()).as_posix(),mime='video/mp4',sha256=file_hash(path))
        db.add(asset);db.commit()
        run.outputs={**run.outputs,'editor':{'video':asset.id}};db.commit()
        db.add(Approval(id=str(uuid4()),run_id=run.id,user_id='alice',manifest=youtube.manifest(db,run)))
        pub=Publication(id=str(uuid4()),project_id=project.id,run_id=run.id,status='queued')
        db.add(pub);db.commit()
        return pub.id,run.id


def test_uncertain_upload_resumes_same_session_without_second_insert(setup,monkeypatch):
    pub_id,run_id=prepared();calls=[]
    def handler(request):
        calls.append((request.method,str(request.url)))
        with DB() as db:
            publication=db.get(Publication,pub_id)
            if request.method=='POST':
                return httpx.Response(200,headers={'location':'https://www.googleapis.com/upload/youtube/v3/videos?upload_id=test-session'})
            assert publication.upload_url is not None # persisted before first chunk
        if request.headers.get('Content-Range','').startswith('bytes */'):
            return httpx.Response(200,json={'id':'already-created-video'})
        return httpx.Response(500)
    original=httpx.Client
    monkeypatch.setattr(youtube.httpx,'Client',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))
    monkeypatch.setattr(youtube,'access_token',lambda *args:'isolated-test-access-token')
    youtube.upload(pub_id)
    with DB() as db:assert db.get(Publication,pub_id).status=='uncertain'
    youtube.upload(pub_id)
    with DB() as db:
        pub=db.get(Publication,pub_id)
        assert pub.video_id=='already-created-video'
        assert pub.status=='published'
    assert sum(method=='POST' for method,_ in calls)==1
    assert len(calls)==3


def test_changed_approved_file_blocks_upload(setup,monkeypatch):
    pub_id,run_id=prepared()
    with DB() as db:
        run=db.get(Run,run_id);asset=db.get(Asset,run.outputs['editor']['video']);media_path(asset.path).write_bytes(b'changed-content')
    youtube.upload(pub_id)
    with DB() as db:
        publication=db.get(Publication,pub_id)
        assert publication.status=='failed'
        assert publication.upload_url is None
        assert 'değişmiş' in publication.error


def test_revision_blocks_external_upload(setup):
    pub_id,run_id=prepared()
    with DB() as db:
        publication=db.get(Publication,pub_id);project=db.get(Project,publication.project_id);project.revision=2;db.commit()
    youtube.upload(pub_id)
    with DB() as db:
        assert db.get(Publication,pub_id).status=='cancelled'
