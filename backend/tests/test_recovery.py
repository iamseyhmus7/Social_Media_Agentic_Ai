import copy
import json
import httpx
import pytest
from backend.app.config import settings
from backend.app.db import DB, Run, Project
from backend.app import recovery
from backend.app.providers import Evren, InvalidModelOutput, TransientProviderError, trace_calls
from backend.app.orchestration import NeedsInput
from backend.tests.test_agentic import create_run, brief


def voice_run(setup, seconds=68.8, legacy=False):
    script={'scenes':[{'narration':' '.join(['kelime']*110),'visual_prompt':'KEEP','action':'KEEP'}]}
    outputs={'supervisor':{**brief(),'duration':60},'script':script,'strategy':{'keep':True},
             'voice':{'duration':seconds,'durations':[seconds],'audios':['old']},
             '_config':{'elevenlabs_model':'eleven_v4'}}
    if legacy:
        outputs.update(_repair_counts={'script':1},_duration_repairs=[{'measured_seconds':68.8}])
    ident=create_run(outputs)
    with DB() as db:
        db.get(Project,db.get(Run,ident).project_id).duration=60
        db.commit()
    recovery.ensure(ident)
    return ident


def test_two_measured_repairs_preserve_scene_and_voice_identity(setup,monkeypatch):
    ident=voice_run(setup)
    targets=[]
    def generate(self,schema,role,context,**kwargs):
        targets.append(context['required_words'])
        return schema.model_validate({'narrations':[' '.join(['kısa']*context['required_words'])]}).model_dump()
    monkeypatch.setattr(Evren,'generate',generate)
    recovery.repair_voice(ident)
    with DB() as db:
        run=db.get(Run,ident)
        assert run.outputs['script']['scenes'][0]['action']=='KEEP'
        assert run.outputs['_reuse_voice']['audios']==['old']
        assert run.outputs['strategy']=={'keep':True}
        assert run.outputs['_recovery']['voice']['text_used']==1
        run.outputs={**run.outputs,'voice':{'duration':61.68,'durations':[61.68],'audios':['new']}}
        db.commit()
    recovery.repair_voice(ident)
    with DB() as db:
        run=db.get(Run,ident)
        assert run.outputs['_recovery']['voice']['text_used']==2
        assert targets[1]<targets[0]
        run.outputs={**run.outputs,'voice':{'duration':59,'durations':[59],'audios':['final']}}
        db.commit()
    recovery.repair_voice(ident)  # Already within acceptance band: no inference.
    assert len(targets)==2


def test_legacy_history_leaves_one_text_repair_and_bounds_exhaustion(setup,monkeypatch):
    ident=voice_run(setup,61.68,True)
    monkeypatch.setattr(Evren,'generate',lambda self,schema,role,c,**kw:
        schema.model_validate({'narrations':[' '.join(['kısa']*c['required_words'])]}).model_dump())
    recovery.repair_voice(ident)
    with DB() as db:
        run=db.get(Run,ident)
        assert run.outputs['_repair_counts']=={'script':1}
        run.outputs={**run.outputs,'voice':{'duration':61,'durations':[61],'audios':['still-long']}}
        db.commit()
    with pytest.raises(NeedsInput,match='son süre 61.00'):
        recovery.repair_voice(ident)


def test_supported_speed_is_bounded_and_invalidates_audio_key(setup,monkeypatch):
    from backend.app.audio_reuse import input_key
    ident=voice_run(setup,61)
    monkeypatch.setattr(settings(),'elevenlabs_model','eleven_multilingual_v2')
    plan={'voice_id':'same','model':'eleven_multilingual_v2','decision':{'stability':.5,'style':.1}}
    with DB() as db:
        run=db.get(Run,ident);run.outputs={**run.outputs,'_voice_plan':plan};db.commit()
    recovery.repair_voice(ident)
    with DB() as db:
        run=db.get(Run,ident);new=run.outputs['_voice_plan']
        assert new['voice_id']=='same' and 1<new['speed']<=1.05
        assert run.outputs['_recovery']['voice']['speed_used']==1
        assert input_key('same',settings(),plan)!=input_key('same',settings(),new)


def test_provider_window_survives_restart_and_respects_retry_after():
    exc=TransientProviderError('503',retry_after=90,http_status=503,request_id='safe-id')
    first=recovery.provider_wait({},'script',exc,100,jitter=0)
    assert first['retry_at']==190 and first['deadline']==1900
    restarted=recovery.provider_wait(first,'script',exc,1800,jitter=0)
    assert restarted['deadline']==1900 and restarted['started_at']==100
    expired=recovery.provider_wait(restarted,'script',exc,1900,jitter=0)
    assert not expired['automatic'] and expired['retry_at'] is None
    assert recovery.provider_wait({},'script',TransientProviderError('503'),100,jitter=0)['retry_at']==130


def test_attempt_budget_is_shared_across_reentry_but_503_is_free(setup,monkeypatch):
    ident=create_run()
    for k,v in {'evren_api_key':'test','evren_base_url':'https://example.test',
                'evren_model':'test','evren_contract_verified':True,'evren_protocol':'openai_chat'}.items():
        monkeypatch.setattr(settings(),k,v)
    from backend.app.schemas import Plan
    calls=[]
    def reply(request):
        calls.append(1)
        return httpx.Response(200,json={'choices':[{'message':{'content':'not json'}}]})
    with trace_calls(lambda m:None,budget=lambda key,op:recovery.task_budget(ident,key,op)):
        for _ in range(2):
            with pytest.raises(InvalidModelOutput):
                Evren(httpx.MockTransport(reply)).generate(Plan,'test',{})
        assert len(calls)==3
        with pytest.raises(TransientProviderError):
            Evren(httpx.MockTransport(lambda r:httpx.Response(503))).generate(Plan,'different',{})
    with DB() as db:
        assert list(db.get(Run,ident).outputs['_inference_attempts'].values())==[3]


def test_quality_uses_current_command_result_and_reports_intervals(tmp_path,monkeypatch):
    from backend.app import media
    data={'streams':[{'codec_type':'video','width':1080,'height':1920,'codec_name':'h264','avg_frame_rate':'30/1'},
                     {'codec_type':'audio','codec_name':'aac'}],'format':{'duration':'59'}}
    srt=tmp_path/'captions.srt';srt.write_text('1\n00:00:00,000 --> 00:00:01,000\nMerhaba',encoding='utf-8')
    def command(args,folder,*a,**kw):
        (folder/'tool.log').write_text(json.dumps(data) if 'ffprobe' in str(args[0]) else 'old black_start: 0 black_end: 5',encoding='utf-8')
        return ''
    monkeypatch.setattr(media,'command',command)
    assert media.validate_final(tmp_path,srt,lambda:None,60)['passed']
    def black(args,folder,*a,**kw):
        if 'ffprobe' in str(args[0]):return command(args,folder)
        return 'black_start: 2 black_end: 3 black_duration: 1'
    monkeypatch.setattr(media,'command',black)
    report=media.validate_final(tmp_path,srt,lambda:None,60)
    assert not report['passed'] and report['findings'][0]['start_frame']==60
    assert report['findings'][0]['repair_stage']=='editor'


def test_sakarya_snapshot_migrates_and_dispatches_remaining_repair(setup,monkeypatch):
    from pathlib import Path
    snapshot=Path('data/recovery-sakarya-snapshot-20261101.json')
    if not snapshot.is_file():
        pytest.skip('Local production snapshot is optional.')
    data=json.loads(snapshot.read_text(encoding='utf-8-sig'))
    outputs=data['outputs']
    outputs['_config']={'elevenlabs_model':'eleven_v4'}
    ident=create_run(outputs)
    with DB() as db:
        db.get(Project,db.get(Run,ident).project_id).duration=data['duration'];db.commit()
    recovery.ensure(ident)
    calls=[]
    def revise(self,schema,role,context,**kw):
        calls.append(context)
        texts=[s['narration'].split() for s in context['script']['scenes']]
        while sum(len(t) for t in texts)>context['required_words']:
            max(texts,key=len).pop()
        return schema.model_validate({'narrations':[' '.join(t) for t in texts]}).model_dump()
    monkeypatch.setattr(Evren,'generate',revise)
    recovery.repair_voice(ident)
    with DB() as db:
        result=db.get(Run,ident).outputs
        assert result['_recovery']['voice']['text_used']==2
        assert result['_voice_plan']==outputs['_voice_plan']
        for before,after in zip(outputs['script']['scenes'],result['script']['scenes']):
            assert {k:v for k,v in before.items() if k!='narration'}=={k:v for k,v in after.items() if k!='narration'}
        assert result['_reuse_voice']==outputs['voice']
    assert len(calls)==1 and calls[0]['measured_seconds']==61.68
    assert calls[0]['required_words']==96


def test_short_voice_expands_narration_and_cancel_prevents_inference(setup,monkeypatch):
    ident=voice_run(setup,54)
    targets=[]
    def generate(self,schema,role,c,**kw):
        targets.append(c['required_words'])
        return schema.model_validate({'narrations':[' '.join(['uzun']*c['required_words'])]}).model_dump()
    monkeypatch.setattr(Evren,'generate',generate)
    recovery.repair_voice(ident)
    assert targets[0]>110
    with DB() as db:
        db.get(Run,ident).cancel_requested=True;db.commit()
    from backend.app.media import Cancelled
    with pytest.raises(Cancelled):recovery.repair_voice(ident)
    assert len(targets)==1


def test_expired_provider_window_never_dispatches_worker(setup,monkeypatch):
    from backend.app import worker
    ident=create_run({'_provider_wait':{'stage':'script','automatic':True,'retry_at':50,'deadline':100}})
    with DB() as db:
        db.get(Run,ident).status='waiting_provider';db.commit()
    monkeypatch.setattr(worker,'now',lambda:101)
    monkeypatch.setattr(worker,'execute',lambda ident:pytest.fail('Expired request dispatched'))
    worker.tick()
    with DB() as db:
        run=db.get(Run,ident)
        assert run.status=='waiting_provider' and run.outputs['_provider_wait']['automatic'] is False


def test_old_render_asset_keeps_original_bytes_after_invalidation(setup):
    from backend.app.orchestration import invalidate
    from backend.app.db import Asset
    from backend.app.storage import register,workdir,media_path
    ident=create_run()
    with DB() as db:
        run=db.get(Run,ident);folder=workdir(run.project_id,ident)
        video=folder/'video.mp4';video.write_bytes(b'original render')
        asset_id=register(db,run,video,'video')
        run.outputs={'editor':{'video':asset_id},'quality':{'passed':False}}
        db.commit()
    invalidate(ident,['editor'],repair=True)
    video.write_bytes(b'replacement render')
    with DB() as db:
        assert media_path(db.get(Asset,asset_id).path).read_bytes()==b'original render'
        assert db.get(Run,ident).outputs['_output_history'][0]['stages']['editor']['video']==asset_id


def test_technical_interval_spanning_scenes_is_localized():
    report={'findings':[{'scene_index':None,'start_frame':25,'end_frame':35,'repair_stage':'editor'}]}
    result=recovery.localize_findings(report,[1,1,1])
    assert [f['scene_index'] for f in result['findings']]==[0,1]
    assert report['findings'][0]['scene_index'] is None


def test_success_ends_outage_window_without_resetting_voice_budget(setup):
    from backend.app.pipeline import save_model_metric
    ident=create_run({'_provider_wait':{'stage':'supervisor','model':'same','deadline':1800},
        '_recovery':{'version':1,'voice':{'text_used':1,'speed_used':0,'history':[]}}})
    save_model_metric(ident,{'status':'passed','model':'same'})
    with DB() as db:
        run=db.get(Run,ident)
        assert run.outputs['_provider_wait']=={}
        assert run.outputs['_recovery']['voice']['text_used']==1


def test_truncation_budget_expansion_is_persisted_once(setup):
    ident=create_run()
    assert recovery.task_budget(ident,'task','expanded') is False
    assert recovery.task_budget(ident,'task','expand') is True
    assert recovery.task_budget(ident,'task','expand') is False
    assert recovery.task_budget(ident,'task','expanded') is True
