"""Behavioral acceptance for autonomous routing, revisions and safe scene composition."""
from copy import deepcopy
from uuid import uuid4
import json
import httpx
import pytest
from pydantic import ValidationError
from backend.app.db import DB, Project, Run, User, Asset, Feedback
from backend.app.config import settings
from backend.app.schemas import NewProject, SceneDesign, FeedbackRequest, AutoEditPlan
from backend.app import orchestration as agent
from backend.app.automatic_edit import validate_decision
from backend.app.feedback import create_feedback, process_feedback
from backend.app.storage import workdir, register, file_hash, media_path


def create_run(outputs=None, version=3):
    with DB() as db:
        p=Project(id=str(uuid4()),user_id='alice',title='Genel konu',topic='Herhangi bir konuda video üret',duration=45)
        db.add(p);db.flush()
        r=Run(id=str(uuid4()),project_id=p.id,user_id='alice',revision=1,status='queued',pipeline_version=version,outputs=outputs or {})
        db.add(r);db.commit()
        return r.id


def test_only_topic_is_required_and_extended_formats():
    assert NewProject(topic='Bir ürün için video').duration is None
    with pytest.raises(ValidationError):SceneDesign(layout='split')
    with pytest.raises(ValidationError):SceneDesign(camera={'kind':'execute_code'})
    with pytest.raises(ValidationError):SceneDesign(particles=100000)


def test_dependency_invalidation_is_targeted():
    assert agent.descendants(['editor'])=={'editor','quality','publisher'}
    assert agent.descendants(['publisher'])=={'publisher'}
    assert 'strategy' not in agent.descendants(['voice'])


def brief():
    return {'goal':'İçeriğe uygun bir video','audience':'Meraklı izleyiciler','tone':'Enerjik',
            'duration':45,'visual_direction':'Konuya göre özgün görsel anlatım','checks':['Okunabilir yazı'],'clarification':''}


def test_real_v3_graph_runs_model_selected_tools_and_finishes(setup,monkeypatch):
    from backend.app import pipeline
    ident=create_run();calls=[]
    def generate(self,schema,role,context,**kwargs):
        if schema.__name__=='CreativeBrief':return brief()
        ready=context['eligible_stages']
        return {'action':'dispatch','stage':ready[-1],'reason':'Önkoşulları tamamlanmış uzmanı çalıştır.'} if ready else {'action':'finish','reason':'Kalite ve paket tamamlandı.'}
    def choose(self,role,context,tools):
        if context['task']=='editor':
            tool='plan_preview' if not context['preview'] else 'inspect_preview' if not context['preview_review'] else 'produce_editor'
            return {'tool':tool,'arguments':{},'reason':'Gerçek önizleme sırasını denetle.'}
        return {'tool':tools[1]['name'],'arguments':{},'reason':'Üretim aracını kullanarak görevi tamamla.'}
    def stage(run_id,key,**kwargs):
        if kwargs.get('preview_only'):
            with DB() as db:
                run=db.get(Run,run_id)
                folder=workdir(run.project_id,run_id)
            manifest=folder/'render-manifest.json';manifest.write_text('{}')
            preview=folder/'visual-preview.mp4';preview.write_bytes(b'preview')
            agent.mutate(run_id,{'_editor_preview':{'manifest_hash':file_hash(manifest),'preview_hash':file_hash(preview)}})
            return
        calls.append(key)
        value={'duration':45} if key=='voice' else {'test':True}
        pipeline.checkpoint(run_id,key,value)
    monkeypatch.setattr(pipeline.Evren,'generate',generate)
    monkeypatch.setattr(pipeline.Evren,'choose_action',choose)
    monkeypatch.setattr(pipeline,'run_stage',stage)
    monkeypatch.setattr(agent,'review_quality',lambda *a,**k:{'passed':True,'findings':[]})
    monkeypatch.setattr(settings(),'video_provider','none')
    pipeline.execute(ident)
    with DB() as db:
        run=db.get(Run,ident)
        assert run.status=='awaiting_approval',run.error
        assert set(agent.DEPENDENCIES).issubset(run.outputs)
        assert len(run.outputs['_agent_actions'])>=8
    assert calls==['strategy','script','voice','visual','motion','editor','publisher']


def test_invalid_supervisor_dispatch_cannot_skip_dependencies(setup,monkeypatch):
    ident=create_run({'supervisor':brief()})
    monkeypatch.setattr(agent.Evren,'generate',lambda *a,**k:{'action':'dispatch','stage':'publisher','reason':'Hatalı erken yayın görevi'})
    with pytest.raises(RuntimeError,match='önkoşulları'):agent.supervise(ident)


def test_agent_turn_budget_survives_resume(setup,monkeypatch):
    ident=create_run({'_agent_turns':80})
    with pytest.raises(RuntimeError,match='bütçesi'):agent.tick(ident)


def test_source_rejection_during_preview_returns_to_supervisor(setup, monkeypatch):
    from backend.app import pipeline
    ident = create_run({'supervisor':brief(), 'voice':{'duration':45}, 'visual':{}, 'motion':{}})
    monkeypatch.setattr(agent.Evren, 'choose_action', lambda *a,**k:
        {'tool':'plan_preview','arguments':{},'reason':'Önce gerçek kaynağı incele.'})
    def reject(*a,**k):
        raise agent.SourceRejected([{'kind':'source','severity':'error','scene_index':0,
            'start_frame':None,'end_frame':None,'evidence':'Kaynakta istenen nesne yok.','repair_stage':'motion'}])
    monkeypatch.setattr(pipeline, 'run_stage', reject)
    agent.specialist(ident, 'editor')
    with DB() as db:
        run=db.get(Run, ident)
        assert not run.outputs['quality']['passed']
        assert run.outputs['quality']['findings'][0]['repair_stage']=='motion'
        assert 'editor' not in run.outputs


def test_editor_repair_preserves_media_and_is_bounded(setup):
    original={'supervisor':brief(),'script':{'scenes':[{'narration':'Metin'}]},'voice':{'duration':45},
        'visual':{'images':['image']},'motion':{'clips':{}},'editor':{'video':'old'},
        'quality':{'passed':False},'publisher':{'package':'old'}}
    ident=create_run(deepcopy(original))
    agent.invalidate(ident,['editor'],repair=True)
    with DB() as db:
        result=db.get(Run,ident).outputs
        assert result['voice']==original['voice'] and result['motion']==original['motion']
        assert 'editor' not in result and 'quality' not in result
    agent.invalidate(ident,['editor'],repair=True)
    with pytest.raises(RuntimeError,match='sınırına'):agent.invalidate(ident,['editor'],repair=True)


def test_transition_handles_and_secondary_sources_are_validated():
    shots=[{'shot_id':'shot-000','scene_index':0},{'shot_id':'shot-001','scene_index':0}]
    decision=AutoEditPlan.model_validate({'observations':[{'shot_id':s['shot_id'],'verdict':'pass','observation':'Gerçek nesne görülebiliyor.'} for s in shots],
        'segments':[{'shot_id':'shot-000','source_in_frame':0,'frames':45,'reason':'Açılıştaki nesneyi gösterir.'},
                    {'shot_id':'shot-001','source_in_frame':0,'frames':45,'transition':'push','reason':'Aynı yöndeki hareketi devam ettirir.'}],
        'rationale':'Kaynak hareketine uygun iki çekimli özgün kurgu.'}).model_dump()
    with pytest.raises(ValueError,match='ek kaynak'):validate_decision(decision,shots,{'shot-000':45,'shot-001':45},[3],require_handles=True)
    assert validate_decision(decision,shots,{'shot-000':52,'shot-001':45},[3],require_handles=True)


def owned_source():
    ident=create_run(version=2)
    with DB() as db:
        r=db.get(Run,ident);r.status='awaiting_approval'
        folder=workdir(r.project_id,r.id)
        files={}
        for name,kind in [('voice.wav','audio'),('scene.png','image'),('shot-000.mp4','clip'),('video.mp4','video'),('captions.srt','subtitle')]:
            path=folder/name;path.write_bytes(name.encode());files[kind]=register(db,r,path,kind)
        r.outputs={'supervisor':brief(),'strategy':{'title':'Kaynak video'},
            'script':{'scenes':[{'narration':'Önceki metin'}]},
            'voice':{'audios':[files['audio']],'durations':[45],'duration':45},
            'visual':{'images':[files['image']],'cover':files['image']},
            'motion':{'mode':'video','plan':{'shots':[{'shot_id':'shot-000','scene_index':0}]},
                      'clips':{'shot-000':{'asset_id':files['clip'],'file':'shot-000.mp4'}}},
            'editor':{'video':files['video'],'subtitle':files['subtitle'],'report':{'passed':True}},
            'quality':{'passed':True},'_config':{'video_provider':'kaggle'}}
        db.commit()
        return r.id,r.project_id


@pytest.mark.parametrize('stages',[['editor'],['voice'],['script'],['visual'],['publisher']])
def test_feedback_routes_and_reuses_owned_sources(setup,monkeypatch,stages):
    source_id,project_id=owned_source()
    monkeypatch.setattr(agent.Evren,'generate',lambda *a,**k:{'summary':'İstenen alanı yeniden düzenle.',
        'stages':stages,'instructions':'Yalnızca istenen değişikliği uygula.','scene_indices':[],'clarification':''})
    with DB() as db:
        request=FeedbackRequest(run_id=source_id,prompt='Bu alanda değişiklik yap',request_id=str(uuid4()))
        f=create_feedback(db,db.get(Project,project_id),db.get(User,'alice'),request);fid=f.id
        assert create_feedback(db,db.get(Project,project_id),db.get(User,'alice'),request).id==fid
    process_feedback(fid)
    with DB() as db:
        f=db.get(Feedback,fid);assert f.status=='applied',f.error
        new=db.get(Run,f.run_id);assert new.pipeline_version==3
        assert new.revision==2
        assert all(stage not in new.outputs for stage in stages)
        assert ('editor' in new.outputs)==(stages==['publisher'])
        assert ('motion' in new.outputs)==(stages in (['editor'],['publisher']))
        assert new.outputs['_edit_only']==(stages in (['editor'],['publisher']))
        old=db.get(Run,source_id);assert old.outputs['editor']['video']
        for asset in db.scalars(__import__('sqlalchemy').select(Asset).where(Asset.run_id==new.id)):
            assert file_hash(media_path(asset.path))==asset.sha256


def test_ambiguous_feedback_asks_before_creating_revision(setup,monkeypatch):
    source_id,project_id=owned_source()
    monkeypatch.setattr(agent.Evren,'generate',lambda *a,**k:{'summary':'Tercihi netleştir.',
        'clarification':'Hangi bölümü değiştirmek istersin?','stages':[]})
    with DB() as db:
        f=create_feedback(db,db.get(Project,project_id),db.get(User,'alice'),
            FeedbackRequest(run_id=source_id,prompt='Daha güzel olsun',request_id=str(uuid4())));fid=f.id
    process_feedback(fid)
    with DB() as db:
        assert db.get(Feedback,fid).status=='needs_clarification'
        assert db.get(Project,project_id).revision==1


def test_duration_feedback_updates_target_and_rebuilds_narration(setup,monkeypatch):
    source_id,project_id=owned_source()
    monkeypatch.setattr(agent.Evren,'generate',lambda *a,**k:{'summary':'Videoyu 30 saniyeye kısalt.',
        'stages':['editor'],'target_duration':30,'instructions':'Anlatımı 30 saniyeye uygun yeniden kurgula.'})
    with DB() as db:
        f=create_feedback(db,db.get(Project,project_id),db.get(User,'alice'),
            FeedbackRequest(run_id=source_id,prompt='Videoyu 30 saniyeye kısalt',request_id=str(uuid4())));fid=f.id
    process_feedback(fid)
    with DB() as db:
        f=db.get(Feedback,fid)
        assert f.status=='applied',f.error
        run=db.get(Run,f.run_id)
        assert db.get(Project,project_id).duration==30
        assert run.outputs['supervisor']['duration']==30
        assert 'voice' not in run.outputs and 'script' not in run.outputs


def test_native_tools_and_explicit_media_routing(monkeypatch):
    from backend.app.providers import Evren
    for key,value in {'evren_api_key':'test','evren_base_url':'https://test.invalid/v1','evren_model':'text',
        'evren_media_model':'mimo','evren_protocol':'openai_chat','evren_contract_verified':True,'agent_protocol':'native_tools'}.items():monkeypatch.setattr(settings(),key,value)
    def respond(request):
        payload=json.loads(request.content)
        assert payload['model']=='mimo' and payload['tool_choice']=='required'
        return httpx.Response(200,json={'choices':[{'message':{'tool_calls':[{'function':{'name':'inspect_state','arguments':'{}'}}]}}]})
    llm=Evren(transport=httpx.MockTransport(respond))
    assert llm.model_for('Senaryo Yazarı')=='text'
    assert llm.model_for('Supervisor')=='text'
    assert llm.model_for('Supervisor / Yönlendirme')=='text'
    assert llm.choose_action('Video Editörü',{},[agent.tool_schema('inspect_state','İncele')])['tool']=='inspect_state'


def test_feedback_http_ownership_csrf_and_clarification(clients,monkeypatch):
    alice,bob=clients
    source,project=owned_source()
    path='/api/v1/projects/'+project+'/feedback'
    data={'run_id':source,'prompt':'Daha iyi olsun','request_id':str(uuid4())}
    assert bob.post(path,json=data).status_code==404
    csrf=alice.headers.pop('X-CSRF-Token')
    assert alice.post(path,json=data).status_code==403
    alice.headers['X-CSRF-Token']=csrf
    created=alice.post(path,json=data)
    assert created.status_code==202
    assert alice.post(path,json=data).json()['id']==created.json()['id']
    monkeypatch.setattr(agent.Evren,'generate',lambda *a,**k:{'summary':'Tercih gerekiyor.',
        'clarification':'Hangi sahne değişsin?','stages':[]})
    process_feedback(created.json()['id'])
    answer_path=path+'/'+created.json()['id']+'/answers'
    assert bob.post(answer_path,json={'answer':'İlk sahne'}).status_code==404
    assert alice.post(answer_path,json={'answer':'İlk sahne'}).json()['status']=='queued'
    assert alice.get(path).json()[0]['answer']=='İlk sahne'
