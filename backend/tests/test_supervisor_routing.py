import json
import httpx
import pytest
from backend.app.config import settings
from backend.app.providers import Evren, trace_calls
from backend.app.schemas import CreativeBrief
from backend.app import orchestration as agent
from backend.tests.test_agentic import create_run, brief


def test_only_invalid_field_is_regenerated(monkeypatch):
    for key, value in {'evren_api_key':'test','evren_base_url':'https://example.test',
                       'evren_model':'deepseek','evren_media_model':'mimo',
                       'evren_protocol':'openai_chat','evren_contract_verified':True}.items():
        monkeypatch.setattr(settings(),key,value)
    requests=[]
    original={**brief(),'tone':'x'*81}
    def reply(request):
        body=json.loads(request.content)
        requests.append(body)
        assert body['model']=='deepseek'
        assert body['max_tokens']==1200
        value=original if len(requests)==1 else {'tone':'Merak uyandıran'}
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(value)}}]})
    metrics=[]
    with trace_calls(metrics.append):
        result=Evren(httpx.MockTransport(reply),timeout=60).generate(
            CreativeBrief,'Supervisor',{},max_attempts=2,max_output_tokens=1200,repair_fields=True)
    assert result=={**original,'tone':'Merak uyandıran'}
    assert 'yalnız' in requests[1]['messages'][0]['content'].lower()
    assert metrics[0]['validation_errors'][0]['path']==['tone']
    assert [m['status'] for m in metrics]==['validation_failed','passed']


def test_model_selects_each_dispatch_and_finish(setup,monkeypatch):
    ident=create_run({'supervisor':brief(),'_config':{
        'video_execution_policy':'planned_v1','supervisor_policy':'model_v2'}})
    calls=[]
    def decision(self,schema,role,context,**kwargs):
        calls.append(context)
        assert role=='Supervisor' and self.timeout==settings().supervisor_timeout_seconds
        assert kwargs['max_output_tokens']==600 and not kwargs['repair_fields']
        return {'action':'dispatch','stage':context['eligible_stages'][0],'reason':'Hazır uzmana yönlendir.'} if context['eligible_stages'] else {'action':'finish','reason':'Kalite ve paket hazır.'}
    monkeypatch.setattr(agent.Evren,'generate',decision)
    assert agent.supervise(ident)=='strategy'
    agent.mutate(ident,{'strategy':{'ok':True}})
    assert agent.supervise(ident)=='script'
    agent.mutate(ident,{**{s:{'ok':True} for s in agent.DEPENDENCIES},'voice':{'duration':45},'quality':{'passed':True}})
    assert agent.supervise(ident)=='done'
    assert len(calls)==3


def test_model_cannot_skip_prerequisites(setup,monkeypatch):
    import pytest
    ident=create_run({'supervisor':brief(),'_config':{'supervisor_policy':'model_v2'}})
    monkeypatch.setattr(agent.Evren,'generate',lambda *a,**k:{'action':'dispatch','stage':'editor','reason':'Geçersiz erken görev.'})
    with pytest.raises(RuntimeError,match='önkoşulları'):
        agent.supervise(ident)


@pytest.mark.parametrize('invalid', [
    {'action':'dispatch','stage':'script','reason':'Senaryoyu tekrar değiştir.'},
    {'action':'dispatch','stage':'visual','reason':'Seslendirmeyi atlayarak görsele geç.'},
    {'action':'repair','stage':'script','reason':'Kalite bulgusu olmadan senaryoyu onar.'},
    {'action':'finish','reason':'Üretimi erken tamamla.'},
])
def test_feedback_routing_repairs_only_the_decision_and_resumes(setup,monkeypatch,invalid):
    from copy import deepcopy
    from backend.app.db import DB,Run
    for key,value in {'evren_api_key':'test','evren_base_url':'https://example.test',
                      'evren_model':'mimo','evren_protocol':'openai_chat',
                      'evren_contract_verified':True}.items():
        monkeypatch.setattr(settings(),key,value)
    outputs={'supervisor':brief(),'strategy':{'title':'Korunan strateji'},
        'script':{'scenes':[{'visual_prompt':'Realistic objects, no people.'}]},
        '_feedback':{'stages':['visual','script'],'instructions':'İnsanlar yerine gerçekçi nesneler kullan.'},
        '_config':{'supervisor_policy':'model_v4'}}
    ident=create_run(deepcopy(outputs))
    calls=[]
    def reply(request):
        body=json.loads(request.content)
        calls.append(body)
        if len(calls)==1:
            context=json.loads(body['messages'][1]['content'])
            assert context['eligible_stages']==['voice']
            assert context['feedback_progress']=={
                'completed_requested_stages':['script'],'pending_requested_stages':['visual']}
            assert '"const": "voice"' in body['messages'][0]['content']
        else:
            assert 'şemaya uymadı' in body['messages'][-1]['content']
        value=invalid if len(calls)==1 else {
            'action':'dispatch','stage':'voice','reason':'Güncellenmiş senaryoyu seslendir.'}
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(value)}}]})
    transport=httpx.MockTransport(reply)
    monkeypatch.setattr(agent,'Evren',lambda **kwargs:Evren(transport,**kwargs))
    # Never execute or invalidate a production stage while correcting routing.
    monkeypatch.setattr(agent,'specialist',lambda *a:pytest.fail('Production tool repeated'))
    monkeypatch.setattr(agent,'invalidate',lambda *a,**k:pytest.fail('Completed output invalidated'))
    assert agent.supervise(ident)=='voice'
    assert agent.supervise(ident)=='voice'  # Resume uses the validated dispatch receipt.
    assert len(calls)==2
    with DB() as db:
        result=db.get(Run,ident).outputs
        assert all(result[k]==v for k,v in outputs.items())
        assert result['orchestration']['stage']=='voice'
        assert result['orchestration']['reason']=='Güncellenmiş senaryoyu seslendir.'
        assert result['_agent_turns']==1


def test_repeated_invalid_routing_is_bounded_without_changing_checkpoints(setup,monkeypatch):
    from backend.app.db import DB,Run
    from backend.app.providers import InvalidModelOutput
    for key,value in {'evren_api_key':'test','evren_base_url':'https://example.test',
                      'evren_model':'mimo','evren_protocol':'openai_chat',
                      'evren_contract_verified':True}.items():
        monkeypatch.setattr(settings(),key,value)
    ident=create_run({'supervisor':brief(),'strategy':{'ok':True},'script':{'ok':True},
        '_config':{'supervisor_policy':'model_v4'}})
    calls=[]
    def reply(request):
        calls.append(1)
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({
            'action':'dispatch','stage':'script','reason':'Tamamlanmış görevi tekrar seç.'})}}]})
    monkeypatch.setattr(agent,'Evren',lambda **kwargs:Evren(httpx.MockTransport(reply),**kwargs))
    with pytest.raises(InvalidModelOutput):
        agent.supervise(ident)
    assert len(calls)==2
    with DB() as db:
        outputs=db.get(Run,ident).outputs
        assert outputs['script']=={'ok':True}
        assert 'orchestration' not in outputs
        assert '_supervisor_dispatch' not in outputs


def test_full_scope_restores_original_brief_and_plan(setup,monkeypatch):
    from backend.tests.test_video_speedup import execution_plan
    ident=create_run({'_config':{'supervisor_policy':'model_v3','video_execution_policy':'planned_v1'}})
    def generate(self,schema,role,context,**kwargs):
        assert schema.__name__=='ProductionBrief'
        assert role=='Supervisor'
        assert self.timeout==settings().evren_response_timeout_seconds
        assert kwargs=={'repair_fields':True}
        assert 'Ayrıntılı senaryo veya kurgu yazma' not in context['instruction']
        assert set(context['required_task_dependencies'])==set(agent.DEPENDENCIES)
        return {**brief(),'execution_plan':execution_plan()}
    monkeypatch.setattr(agent.Evren,'generate',generate)
    agent.initial_brief(ident)
    from backend.app.db import DB,Run
    with DB() as d:
        r=d.get(Run,ident)
        assert r.outputs['supervisor']==brief()
        assert len(r.outputs['_execution_plan']['tasks'])==8


def test_supervisor_model_is_independent_and_old_snapshots_preserve_deepseek(monkeypatch):
    from backend.app.config import use_run_settings
    monkeypatch.setattr(settings(),'evren_model','deepseek')
    monkeypatch.setattr(settings(),'evren_media_model','mimo')
    monkeypatch.setattr(settings(),'evren_supervisor_model','mimo')
    assert Evren().model_for('Supervisor')=='mimo'
    assert Evren().model_for('Senaryo Yazarı')=='deepseek'
    with use_run_settings({'evren_model':'deepseek','evren_media_model':'mimo'}):
        assert Evren().model_for('Supervisor')=='deepseek'


def test_mimo_full_brief_uses_actual_audio_provider_and_pending_checks(setup,monkeypatch):
    from backend.tests.test_video_speedup import execution_plan
    monkeypatch.setattr(settings(),'tts_provider','elevenlabs')
    ident=create_run({'_config':{'supervisor_policy':'model_v4','video_execution_policy':'planned_v1'},
                      '_brand':{'color':'#ed5145'}})
    def generate(self,schema,role,context,**kwargs):
        assert schema.__name__=='ProductionBrief' and role=='Supervisor'
        assert context['audio_backend']['provider']=='elevenlabs'
        assert 'voice' not in context['brand']
        assert 'henüz yapılmamış denetimi' in context['instruction']
        assert 'kaynak doğrulaması iste' in context['instruction']
        assert kwargs=={'repair_fields':True}
        return {**brief(),'execution_plan':execution_plan()}
    monkeypatch.setattr(agent.Evren,'generate',generate)
    agent.initial_brief(ident)


def test_boundary_gap_preserves_existing_speech_and_prior_checkpoints(setup,monkeypatch):
    import wave
    from backend.app.db import DB,Run
    from backend.app.storage import workdir,register
    from backend.app.pipeline import asset_path
    ident=create_run({'supervisor':brief(),'strategy':{'title':'Kalıcı strateji'},
        'script':{'scenes':[{'narration':'Aynı anlatım'}]},'_repair_counts':{'script':1},
        '_config':{'supervisor_policy':'model_v4','video_execution_policy':'planned_v1'}})
    with DB() as d:
        run=d.get(Run,ident)
        folder=workdir(run.project_id,ident)
        source=folder/'voice-0.wav'
        pcm=b'\x01\x02'*42960
        with wave.open(str(source),'wb') as wav:
            wav.setparams((1,2,1000,0,'NONE','not compressed'));wav.writeframes(pcm)
        audio=register(d,run,source,'audio')
        run.outputs={**run.outputs,'voice':{'audios':[audio],'durations':[42.96],'duration':42.96}}
        d.commit()
    def decide(self,schema,role,context,**kwargs):
        assert context['voice_timing']['measured_seconds']==43
        assert context['voice_timing']['problem'] is None
        assert 'visual' in context['eligible_stages']
        return {'action':'dispatch','stage':'visual','reason':'Hazır ses korunarak görsele geç.'}
    monkeypatch.setattr(agent.Evren,'generate',decide)
    assert agent.supervise(ident)=='visual'
    with DB() as d:
        outputs=d.get(Run,ident).outputs
        assert outputs['_repair_counts']=={'script':1}
        assert outputs['strategy']=={'title':'Kalıcı strateji'}
        assert outputs['script']['scenes'][0]['narration']=='Aynı anlatım'
        assert outputs['voice']['boundary_padding_added_seconds']==.04
        fitted=asset_path(outputs['voice']['audios'][0])
    with wave.open(str(source),'rb') as wav:
        assert wav.readframes(wav.getnframes())==pcm
    with wave.open(str(fitted),'rb') as wav:
        assert wav.getnframes()==43000
        assert wav.readframes(43000)==pcm+b'\0'*80
    agent.fit_voice_boundary(ident)
    with DB() as d:
        assert d.get(Run,ident).outputs['voice']['audios']==outputs['voice']['audios']


def test_timing_context_does_not_hide_large_error_or_pad_unsupported_gap():
    assert agent.voice_timing({'supervisor':brief(),'voice':{'duration':39.76}})['problem']=='too_short'
    assert agent.voice_timing({'supervisor':brief(),'voice':{'duration':49}})['problem']=='too_long'
    assert agent.voice_timing({'supervisor':brief(),'voice':{'duration':45}})['problem'] is None
    from backend.app.media import pad_silent_tail
    assert pad_silent_tail(None,None,.051) is None


def test_pending_model_dispatch_is_not_regenerated_on_resume(setup,monkeypatch):
    ident=create_run({'supervisor':brief(),'_config':{'supervisor_policy':'model_v4'}})
    calls=[]
    def decide(*args,**kwargs):
        calls.append(1)
        return {'action':'dispatch','stage':'strategy','reason':'Önce strateji üret.'}
    monkeypatch.setattr(agent.Evren,'generate',decide)
    assert agent.supervise(ident)=='strategy'
    assert agent.supervise(ident)=='strategy'
    assert len(calls)==1
    agent.mutate(ident,{'strategy':{'title':'Tamamlandı'}})
    monkeypatch.setattr(agent.Evren,'generate',lambda *a,**k:{'action':'dispatch','stage':'script','reason':'Şimdi senaryo yaz.'})
    assert agent.supervise(ident)=='script'


def test_only_unanswered_supervisor_inference_is_retried(setup,monkeypatch):
    from backend.app.providers import ProviderTimeout
    ident=create_run({'supervisor':brief(),'_config':{'supervisor_policy':'model_v4'}})
    calls=[]
    def decide(*args,**kwargs):
        calls.append(1)
        if len(calls)==1: raise ProviderTimeout('test timeout')
        return {'action':'dispatch','stage':'strategy','reason':'Hazır uzmana yönlendir.'}
    monkeypatch.setattr(agent.Evren,'generate',decide)
    assert agent.supervise(ident)=='strategy'
    assert len(calls)==2
    from backend.app.db import DB,Run
    with DB() as d:
        outputs=d.get(Run,ident).outputs
        assert outputs['supervisor']==brief()
        assert '_repair_counts' not in outputs


def test_timeout_retry_is_bounded_and_quota_is_not_retried(setup,monkeypatch):
    import pytest
    from backend.app.providers import ProviderTimeout,QuotaExceeded
    for error,budget in [(ProviderTimeout,2),(QuotaExceeded,1)]:
        ident=create_run({'supervisor':brief(),'_config':{'supervisor_policy':'model_v4'}})
        calls=[]
        def fail(*args,**kwargs):
            calls.append(1)
            raise error('test failure')
        monkeypatch.setattr(agent.Evren,'generate',fail)
        with pytest.raises(error):agent.supervise(ident)
        assert len(calls)==budget
