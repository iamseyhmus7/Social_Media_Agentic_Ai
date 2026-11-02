from contextvars import ContextVar
from threading import Lock
from types import SimpleNamespace
from copy import deepcopy
import time
import json
import httpx
import pytest
from backend.app.config import settings
from backend.app.parallel_work import bounded_map
from backend.app.schemas import EditLook, SceneEditDecision, AgentAction


def test_bounded_parallelism_keeps_context_and_order():
    scope=ContextVar('test_scope',default=None)
    token=scope.set('current-run')
    lock=Lock();active=0;peak=0
    def work(index):
        nonlocal active,peak
        assert scope.get()=='current-run'
        with lock:active+=1;peak=max(peak,active)
        time.sleep(.015*(4-index))
        with lock:active-=1
        return index*2
    try:
        assert bounded_map([0,1,2,3],work,2,lambda:None)==[0,2,4,6]
        assert peak==2
    finally:scope.reset(token)


def fixtures():
    shots=[{'shot_id':f'shot-{i:03}','scene_index':i,'reference_prompt':'DO NOT RESEND FULL PROMPTS',
            'purpose':'Anlatılan eylemi göster.','expected_action':'Nesne doğal hareket eder.'} for i in range(2)]
    seen=[{'shot_id':s['shot_id'],'observation':'Gerçek karede bir nesne görünüyor.',
           'visible_defects':'','motion_uncertainty':'Hareketin tamamı doğrulanmadı.'} for s in shots]
    run=SimpleNamespace(outputs={'script':{'scenes':[{'narration':'İlk eylem.'},{'narration':'Sonraki eylem.'}]},
                                 'supervisor':{'visual_direction':'İçeriğe uygun sade kurgu.'}})
    return run,shots,seen


class Model:
    timeout=1800
    def __init__(self,fail_scene=None):self.calls=[];self.fail_scene=fail_scene
    def generate(self,schema,role,context,**kwargs):
        self.calls.append((schema.__name__,deepcopy(context),kwargs))
        assert 1<=kwargs['max_attempts']<=3
        if schema is EditLook:
            return {'rationale':'İki eylemi birbirini takip eden kaynaklarla gösterir.'}
        scene=context['scene_index']
        assert 'reference_prompt' not in json.dumps(context)
        if self.fail_scene==scene:raise RuntimeError('Only this scene failed')
        ident=f'shot-{scene:03}'
        return schema.model_validate({'reviews':[{'shot_id':ident,'verdict':'uncertain','reason':'Nesne gerçekten görünür, hareket örnekleri sınırlı.'}],
            'segments':[{'shot_id':ident,'source_in_frame':0,'duration_weight':1,
                         'reason':'İlgili anlatımı mevcut kaynakla destekler.'}]}).model_dump()


def test_successful_scenes_survive_another_scene_failure(tmp_path,monkeypatch):
    from backend.app.scene_edit import decide
    monkeypatch.setattr(settings(),'editor_parallelism',1)
    run,shots,seen=fixtures()
    available={s['shot_id']:60 for s in shots};hashes={s['shot_id']:'hash'+s['shot_id'] for s in shots}
    first=Model(fail_scene=1)
    with pytest.raises(RuntimeError,match='Only this scene'):
        decide(run,tmp_path,shots,[1,1],available,seen,first,lambda:None,[],'Konu',{},hashes)
    second=Model()
    result=decide(run,tmp_path,shots,[1,1],available,seen,second,lambda:None,[],'Konu',{},hashes)
    assert [c[1].get('scene_index') for c in second.calls]==[1]
    assert sum(s['frames'] for s in result['segments'])==60
    assert len(result['observations'])==2
    # A changed clip invalidates its own scene, leaving the other checkpoint.
    hashes['shot-001']='updated'
    third=Model()
    decide(run,tmp_path,shots,[1,1],available,seen,third,lambda:None,[],'Konu',{},hashes)
    assert [c[1].get('scene_index') for c in third.calls]==[1]


def test_scene_contract_rejects_foreign_sources_and_out_of_bounds_cues(tmp_path,monkeypatch):
    from backend.app.scene_edit import decide
    monkeypatch.setattr(settings(),'editor_parallelism',1)
    run,shots,seen=fixtures()
    class BadModel(Model):
        def generate(self,schema,role,context,**kwargs):
            value=super().generate(schema,role,context,**kwargs)
            if schema is not EditLook:
                value['segments'][0]['shot_id']='shot-999'
                return schema.model_validate(value).model_dump()
            return value
    with pytest.raises(ValueError,match='kendi mevcut'):
        decide(run,tmp_path,shots,[1,1],{'shot-000':60,'shot-001':60},seen,BadModel(),lambda:None,[],'Konu',{}, {'shot-000':'a','shot-001':'b'})


def test_provider_records_error_paths_and_output_budget_without_values(monkeypatch):
    from backend.app.providers import Evren,trace_calls,ProviderError
    for key,value in {'evren_api_key':'test','evren_base_url':'https://example.test','evren_model':'test',
                      'evren_protocol':'openai_chat','evren_contract_verified':True}.items():monkeypatch.setattr(settings(),key,value)
    calls=[];metrics=[]
    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200,json={'choices':[{'finish_reason':'length','message':{'content':'{"tool":"secret value"}'}}],
            'usage':{'completion_tokens_details':{'reasoning_tokens':99}}})
    with trace_calls(metrics.append),pytest.raises(ProviderError):
        Evren(httpx.MockTransport(respond)).generate(AgentAction,'Senaryo Yazarı',{},max_attempts=2,max_output_tokens=1024)
    assert [c['max_tokens'] for c in calls]==[1024,2048]
    assert metrics[0]['finish_reason']=='length' and metrics[0]['reasoning_tokens']==99
    assert metrics[0]['validation_errors'][0]['path']==['reason']
    assert 'secret value' not in json.dumps(metrics)


def test_gpu_assignment_balances_work_not_just_clip_count():
    import importlib.util
    from pathlib import Path
    spec=importlib.util.spec_from_file_location('gpu_shards',Path(__file__).parents[1]/'kaggle/generate.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    shots=[{'shot_id':f'shot-{i:03}','duration_seconds':d} for i,d in enumerate((5,1,5,1))]
    groups=module.balanced_shards(shots,2)
    assert [sum(s['duration_seconds'] for s in group) for group in groups]==[6,6]


def test_parallel_model_accounting_does_not_lose_updates(setup):
    from backend.tests.test_agentic import create_run
    from backend.app.orchestration import tick
    from backend.app.pipeline import save_model_metric
    from backend.app.db import DB,Run
    ident=create_run()
    def account(index):
        tick(ident)
        save_model_metric(ident,{'schema':'ConcurrentTest','attempt':index})
    bounded_map(list(range(8)),account,3,lambda:None)
    with DB() as db:
        outputs=db.get(Run,ident).outputs
        assert outputs['_agent_turns']==8
        assert len(outputs['_model_metrics'])==8


def test_transient_failure_does_not_block_later_items_and_retries_only_missing():
    from backend.app.parallel_work import settled_map
    from backend.app.providers import TransientProviderError
    calls=[];completed=[];delays=[]
    def work(item):
        calls.append(item)
        if item==2 and calls.count(2)==1:raise TransientProviderError('503')
        return item*10
    result=settled_map([0,1,2,3],work,1,lambda:None,
        on_success=lambda item,value:completed.append(item),sleeper=lambda seconds,check:delays.append(seconds))
    assert calls==[0,1,2,3,2]
    assert completed==[0,1,3,2]
    assert result==[0,10,20,30] and delays==[5]


def test_render_ranges_cover_every_frame_once_and_cache_ignores_unseen_neighbor():
    from backend.app.streaming_render import ranges,visible_signature
    spans=ranges([30,1,18,40])
    assert [frame for _,_,start,end in spans for frame in range(start,end+1)]==list(range(89))
    clip={'file':'shot-001.mp4','kind':'clip','start_frame':30,'frames':40,'handle_frames':0,'transition':'dissolve','transition_frames':18}
    first={'duration_frames':70,'clips':[{'file':'shot-000.png','kind':'image','start_frame':0,'frames':30,'handle_frames':18},clip],'graphics':[]}
    second=deepcopy(first)
    second['clips'][0]={'file':'shot-000.mp4','kind':'clip','start_frame':0,'frames':30,'handle_frames':18}
    hashes={'shot-000.png':'placeholder','shot-000.mp4':'real','shot-001.mp4':'current'}
    assert visible_signature(first,48,69,hashes,'code')==visible_signature(second,48,69,hashes,'code')
    assert visible_signature(first,30,47,hashes,'code')!=visible_signature(second,30,47,hashes,'code')


def test_streaming_model_and_render_overlap_and_late_scene_keeps_order(tmp_path,monkeypatch):
    from threading import Event
    from backend.app.scene_edit import decide
    from backend.app.streaming_render import SceneRenderQueue
    from backend.app.providers import TransientProviderError
    import backend.app.streaming_render as rendering
    monkeypatch.setattr(settings(),'editor_parallelism',1)
    monkeypatch.setattr(rendering,'renderer_hash',lambda:'test-code')
    run,shots,seen=fixtures()
    run.outputs['_config']={'editor_streaming_enabled':True}
    public=tmp_path/'public';public.mkdir()
    for shot in shots:(public/(shot['shot_id']+'.mp4')).write_bytes(b'media')
    started=Event();rendered=[]
    class FakeRender(SceneRenderQueue):
        def render_chunk(self,key,scene,part,start,end,manifest):
            rendered.append((scene,part,start,end))
            started.set()
    class SlowModel(Model):
        def generate(self,schema,role,context,**kwargs):
            if schema is not EditLook and context['scene_index']==1:
                assert started.wait(2),'Render waited for all model decisions'
            return super().generate(schema,role,context,**kwargs)
    queue=FakeRender(run,tmp_path,public,shots,[1,1],{'version':2,'style':'auto','duration_frames':60,'sources':[]},lambda:None)
    try:
        result=decide(run,tmp_path,shots,[1,1],{'shot-000':90,'shot-001':90},seen,SlowModel(),lambda:None,[],'Konu',{}, {'shot-000':'a','shot-001':'b'},on_scene=queue.on_scene)
    finally:queue.close()
    assert rendered[0]==(0,'core',0,29)
    assert sorted((a,b) for _,_,a,b in rendered)==[(0,29),(30,47),(48,59)]
    assert sum(s['frames'] for s in result['segments'])==60


def test_partial_failure_keeps_unrelated_successes_even_for_fatal_input():
    from backend.app.parallel_work import settled_map
    completed=[]
    def work(item):
        if item==1:raise ValueError('bad scene')
        return item
    with pytest.raises(ValueError,match='bad scene'):
        settled_map([0,1,2],work,1,lambda:None,on_success=lambda item,value:completed.append(item))
    assert completed==[0,2]


def test_exhausted_transient_service_waits_without_losing_checkpoints(setup,monkeypatch):
    from backend.tests.test_agentic import create_run
    from backend.app import pipeline
    from backend.app.providers import TransientProviderError
    from backend.app.db import DB,Run
    ident=create_run({'script':{'kept':True},'_config':{'video_provider':'none'}})
    def fail(*args,**kwargs):raise TransientProviderError('HTTP 503')
    monkeypatch.setattr(pipeline,'build_graph',lambda *args:SimpleNamespace(invoke=fail))
    pipeline.execute(ident)
    with DB() as db:
        run=db.get(Run,ident)
        assert run.status=='waiting_provider'
        assert run.outputs['script']=={'kept':True}
        assert run.outputs['_provider_wait']['automatic'] is True
        assert run.finished is None


def test_provider_resume_clears_stale_error_but_preserves_retry_budget(setup,monkeypatch):
    from backend.tests.test_agentic import create_run
    from backend.app import pipeline
    from backend.app.providers import TransientProviderError
    from backend.app.db import DB,Run
    waiting={'stage':'supervisor','cycles':2,'automatic':True,'retry_at':0}
    ident=create_run({'script':{'kept':True},'_provider_wait':waiting,
        '_config':{'video_provider':'none'}})
    with DB() as db:
        run=db.get(Run,ident)
        run.error='HTTP 503 from previous attempt'
        db.commit()
    def resumed(*args,**kwargs):
        with DB() as db:
            run=db.get(Run,ident)
            assert run.status=='running' and run.error is None
            assert run.outputs['_provider_wait']==waiting
            assert run.outputs['script']=={'kept':True}
        raise TransientProviderError('HTTP 503 from current attempt')
    monkeypatch.setattr(pipeline,'build_graph',lambda *args:SimpleNamespace(invoke=resumed))
    pipeline.execute(ident)
    with DB() as db:
        run=db.get(Run,ident)
        assert run.status=='waiting_provider'
        assert run.error=='HTTP 503 from current attempt'
        assert run.outputs['_provider_wait']['cycles']==3


def test_compact_schema_keeps_real_title_field_and_constraints(monkeypatch):
    from pydantic import BaseModel,Field
    from backend.app.providers import Evren
    class Title(BaseModel):
        title:str=Field(default='',max_length=8)
    for key,value in {'evren_api_key':'test','evren_base_url':'https://example.test','evren_model':'test',
                      'evren_protocol':'openai_chat','evren_contract_verified':True}.items():
        monkeypatch.setattr(settings(),key,value)
    def respond(request):
        text=json.loads(request.content)['messages'][0]['content']
        definition=json.loads(text.split('nesne döndür: ',1)[1])
        assert definition['properties']['title']['maxLength']==8
        assert 'default' not in definition['properties']['title']
        return httpx.Response(200,json={'choices':[{'message':{'content':'{"title":"Başlık"}'}}]})
    assert Evren(httpx.MockTransport(respond)).generate(Title,'Video Editörü',{},compact_schema=True)['title']=='Başlık'


def test_batch_budget_preserves_success_and_defers_unstarted_items(monkeypatch):
    import backend.app.parallel_work as work
    from backend.app.providers import TransientProviderError
    clock=[0];calls=[];completed=[]
    monkeypatch.setattr(work.time,'monotonic',lambda:clock[0])
    def action(item):
        calls.append(item);clock[0]+=6
        return item
    with pytest.raises(TransientProviderError,match='tamamlanmamış'):
        work.settled_map([0,1,2],action,1,lambda:None,budget_seconds=5,on_success=lambda item,value:completed.append(item))
    assert calls==[0] and completed==[0]


def test_final_review_covers_full_actual_audio_without_unverified_video_upload(setup,monkeypatch):
    from backend.tests.test_agentic import owned_source
    from backend.app.db import DB,Run
    from backend.app.storage import workdir
    from backend.app import orchestration as agent
    from PIL import Image
    ident,project=owned_source()
    folder=workdir(project,ident)
    (folder/'render-manifest.json').write_text(json.dumps({'duration_frames':1350,'clips':[{'start_frame':0,'frames':1350,'transition_frames':3}]}))
    with DB() as db:
        run=db.get(Run,ident)
        run.outputs={**run.outputs,'_config':{'editor_streaming_enabled':True}}
        db.commit()
    monkeypatch.setattr(settings(),'evren_audio_input_verified',True)
    monkeypatch.setattr(settings(),'evren_video_input_verified',False)
    def command(args,cwd,check,**kwargs):
        if '-frames:v' in args:Image.new('RGB',(270,480)).save(args[-1])
        elif '-vn' in args:
            assert args[args.index('-t')+1]=='45.0'
            args[-1].write_bytes(b'actual-final-mix-test')
        else:raise AssertionError('Unsupported whole-video input must not be sent')
    from backend.app import media as media_module
    monkeypatch.setattr(media_module,'command',command)
    def generate(self,schema,role,context,**kwargs):
        assert context['audio_sample_seconds']==45
        assert context['full_video_proxy']['included'] is False
        assert [m['type'] for m in kwargs['media_inputs']].count('input_audio')==1
        assert not any(m['type']=='video_url' for m in kwargs['media_inputs'])
        return {'summary':'Tüm anlatım ve örnek kareler incelendi.','findings':[]}
    monkeypatch.setattr(agent.Evren,'generate',generate)
    result=agent.review_quality(ident)
    assert result['passed'] and result['method']=='rendered_sampled_frames_full_audio'


def test_invalid_candidate_resumes_only_bad_fields(monkeypatch):
    from pydantic import BaseModel,Field
    from backend.app.providers import Evren,InvalidModelOutput
    class Decision(BaseModel):
        title:str
        weight:int=Field(le=100)
    for key,value in {'evren_api_key':'test','evren_base_url':'https://example.test','evren_model':'test',
                      'evren_protocol':'openai_chat','evren_contract_verified':True}.items():
        monkeypatch.setattr(settings(),key,value)
    retained=[]
    def bad(request):
        return httpx.Response(200,json={'choices':[{'message':{'content':'{"title":"Keep creative choice","weight":101}'}}]})
    with pytest.raises(InvalidModelOutput):
        Evren(httpx.MockTransport(bad)).generate(Decision,'Video Editörü',{},max_attempts=1,repair_fields=True,on_invalid=retained.append)
    def fix(request):
        prompt=json.loads(request.content)['messages']
        assert '"required": ["weight"]' in prompt[0]['content']
        assert 'Keep creative choice' not in prompt[1]['content']
        return httpx.Response(200,json={'choices':[{'message':{'content':'{"weight":50}'}}]})
    result=Evren(httpx.MockTransport(fix)).generate(Decision,'Video Editörü',{},repair_fields=True,initial_candidate=retained[0])
    assert result=={'title':'Keep creative choice','weight':50}


def test_schema_failure_retries_after_independent_scenes():
    from backend.app.parallel_work import settled_map
    from backend.app.providers import InvalidModelOutput
    calls=[]
    def action(item):
        calls.append(item)
        if item==0 and calls.count(0)==1:raise InvalidModelOutput('repair')
        return item
    assert settled_map([0,1,2],action,1,lambda:None,retry_errors=(InvalidModelOutput,),sleeper=lambda *args:None)==[0,1,2]
    assert calls==[0,1,2,0]
