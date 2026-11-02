from copy import deepcopy
from types import SimpleNamespace
import json
import httpx
import pytest
from pydantic import ValidationError
from backend.app.schemas import ExecutionPlan, ClipPerception, EditDecisionV2
from backend.app.edit_compiler import allocate, compile_segments, SceneBudgetError
from backend.app.config import settings, use_run_settings
from backend.app.providers import Evren, trace_calls
from backend.app.storage import file_hash


def execution_plan():
    from backend.app.orchestration import DEPENDENCIES
    return {'tasks':[{'stage':s,'depends_on':list(deps),'goal':'Görevi yaratıcı yönde tamamla.'} for s,deps in DEPENDENCIES.items()]}


def test_plan_cannot_skip_dependencies_or_cycle():
    ExecutionPlan.model_validate(execution_plan())
    bad=execution_plan();bad['tasks'][5]['depends_on']=[]
    with pytest.raises(ValidationError):ExecutionPlan.model_validate(bad)
    bad=execution_plan();bad['tasks'][0]['depends_on']=['publisher']
    with pytest.raises(ValidationError):ExecutionPlan.model_validate(bad)


def test_old_snapshot_keeps_original_execution_and_gpu_profile():
    with use_run_settings({}):
        assert settings().video_execution_policy=='legacy'
        assert settings().kaggle_motion_profile=='legacy_fp32'


def test_exact_frame_budget_and_capacity_waterfill():
    assert allocate(101,[1,1],[8,8],[30,100])==[30,71]
    for total in range(20,180):
        values=allocate(total,[1,2,4],[4,4,4],[40,80,90])
        assert sum(values)==total
        assert all(a<=b<=c for a,b,c in zip([4]*3,values,[40,80,90]))


def test_compiler_reserves_outgoing_and_secondary_handles():
    shots=[{'shot_id':f'shot-{i:03}','scene_index':0} for i in range(2)]
    segments=[{'shot_id':s['shot_id'],'transition':'cut' if i==0 else 'push','transition_frames':7,
               'source_in_frame':0,'duration_weight':1,'design':{}} for i,s in enumerate(shots)]
    result=compile_segments(segments,shots,{'shot-000':40,'shot-001':60},[90])
    assert [s['frames'] for s in result]==[33,57]
    segments[0]['design']={'secondary_shot_id':'shot-001'}
    with pytest.raises(SceneBudgetError) as error:
        compile_segments(segments,shots,{'shot-000':40,'shot-001':40},[90])
    assert error.value.scene_index==0


def test_preview_invalidates_changed_media_code_and_frames(tmp_path,monkeypatch):
    from backend.app import preview
    root=tmp_path/'renderer'/'production';root.mkdir(parents=True)
    (root/'src.jsx').write_text('original')
    monkeypatch.setattr(settings(),'remotion_root',root.parent)
    media=tmp_path/'render-inputs';media.mkdir();source=media/'shot-000.mp4';source.write_bytes(b'source')
    manifest={'duration_frames':30,'clips':[{'start_frame':0,'frames':30,'transition_frames':7}]}
    (tmp_path/'render-manifest.json').write_text(json.dumps(manifest))
    image=tmp_path/'frame.jpg';image.write_bytes(b'evidence')
    items=[{'frame':f,'file':image.name,'sha256':file_hash(image)} for f in preview.critical_frames(manifest)]
    (tmp_path/'preview-frames.json').write_text(json.dumps(items))
    receipt={**preview.fingerprint(tmp_path),'preview_hash':file_hash(tmp_path/'preview-frames.json')}
    preview.verify_preview(tmp_path,receipt)
    source.write_bytes(b'changed')
    with pytest.raises(RuntimeError):preview.verify_preview(tmp_path,receipt)
    source.write_bytes(b'source');(root/'src.jsx').write_text('new renderer')
    with pytest.raises(RuntimeError):preview.verify_preview(tmp_path,receipt)
    (root/'src.jsx').write_text('original');image.write_bytes(b'altered evidence')
    with pytest.raises(RuntimeError):preview.verify_preview(tmp_path,receipt)


def test_provider_records_validation_retry_latency_and_usage(monkeypatch):
    from backend.app.schemas import AgentAction
    for name,value in {'evren_api_key':'test','evren_base_url':'https://example.test','evren_model':'test',
                       'evren_protocol':'openai_chat','evren_contract_verified':True}.items():
        monkeypatch.setattr(settings(),name,value)
    count=0
    def request(req):
        nonlocal count
        count+=1
        text='{}' if count==1 else json.dumps({'tool':'finish','reason':'Görev tamamlandı.'})
        return httpx.Response(200,json={'choices':[{'message':{'content':text}}],
            'usage':{'prompt_tokens':10,'completion_tokens':4,'total_tokens':14}})
    metrics=[]
    with trace_calls(metrics.append):
        Evren(transport=httpx.MockTransport(request)).generate(AgentAction,'Supervisor',{'task':'test'})
    assert [m['status'] for m in metrics]==['validation_failed','passed']
    assert all(m['seconds']>=0 and m['usage']['total_tokens']==14 for m in metrics)
    assert metrics[1]['attempt']==2


def test_planned_dispatch_and_completion_do_not_call_control_model(setup,monkeypatch):
    from backend.tests.test_agentic import create_run, brief
    from backend.app import orchestration as agent, pipeline
    from backend.app.db import DB,Run
    ident=create_run({'supervisor':brief(),'_execution_plan':execution_plan(),
                      '_config':{'video_execution_policy':'planned_v1'}})
    def forbidden(*a,**k):raise AssertionError('Redundant control model call')
    monkeypatch.setattr(agent.Evren,'generate',forbidden)
    monkeypatch.setattr(agent.Evren,'choose_action',forbidden)
    assert agent.supervise(ident)=='strategy'
    monkeypatch.setattr(pipeline,'run_stage',lambda run_id,stage: pipeline.checkpoint(run_id,stage,{'ok':True}))
    agent.specialist(ident,'strategy')
    assert agent.supervise(ident)=='script'
    with DB() as db:
        run=db.get(Run,ident)
        run.outputs={**run.outputs,'quality':{'passed':True},'publisher':{'ok':True}}
        db.commit()
    assert agent.supervise(ident)=='done'


def test_perception_reused_when_script_changes_but_not_source(tmp_path,monkeypatch):
    from backend.app import planned_edit, media
    monkeypatch.setattr(settings(),'media_root',tmp_path)
    folder=tmp_path/'project'/'run';folder.mkdir(parents=True)
    source=folder/'shot-000.mp4';source.write_bytes(b'clip1')
    run=SimpleNamespace(id='run',project_id='project',outputs={
        'script':{'scenes':[{'narration':'İlk metin'}]},'motion':{'clips':{'shot-000':{'file':source.name,'report':{'duration':2}}}}})
    calls=[]
    class Model:
        def generate(self,schema,role,context,**kw):
            calls.append(schema.__name__)
            if schema is ClipPerception:
                return {'observation':'Nehir üzerinde taş bir köprü görünüyor.','visible_defects':'','motion_uncertainty':'Kesintisiz hareket doğrulanamaz.'}
            return {'observations':[{'shot_id':'shot-000','verdict':'uncertain','observation':'Köprü anlatımla uyumlu görünüyor.'}],
                'segments':[{'shot_id':'shot-000','source_in_frame':0,'duration_weight':1,'reason':'Köprüyü doğrudan gösterir.'}],
                'rationale':'Anlatımı mevcut köprü görüntüsüyle destekler.'}
    def command(args,*a,**kw):
        from pathlib import Path
        Path(args[-1]).write_bytes(b'image')
    monkeypatch.setattr(media,'command',command)
    shots=[{'shot_id':'shot-000','scene_index':0}]
    def prepare():return planned_edit.prepare_decision(run,folder,shots,[1],{'shot-000':60},Model(),lambda:None,[],'Köprü',{})
    prepare();prepare()
    assert calls==['ClipPerception','EditDecisionV2']
    run.outputs['script']['scenes'][0]['narration']='Yeni anlatım'
    prepare()
    assert calls==['ClipPerception','EditDecisionV2','EditDecisionV2']
    source.write_bytes(b'clip2');prepare()
    assert calls.count('ClipPerception')==2


def test_candidate_cannot_activate_without_matching_measurement(tmp_path,monkeypatch):
    from backend.app import gpu_profile
    monkeypatch.setattr(settings(),'media_root',tmp_path/'media')
    monkeypatch.setattr(settings(),'kaggle_motion_profile','certified_auto')
    assert gpu_profile.selected_profile()=='legacy_fp32'

    c={'engine_hash':gpu_profile.engine_hash(),'profile':gpu_profile.PROFILE,'outputs_valid':True,'clip_count':4,'speedup':.19}
    gpu_profile.certificate_path().write_text(json.dumps(c))
    assert gpu_profile.selected_profile()=='legacy_fp32'
    c['speedup']=.2;gpu_profile.certificate_path().write_text(json.dumps(c))
    assert gpu_profile.selected_profile()==gpu_profile.PROFILE
    c['engine_hash']='obsolete';gpu_profile.certificate_path().write_text(json.dumps(c))
    assert gpu_profile.selected_profile()=='legacy_fp32'


def test_cancelled_planned_dispatch_never_runs_a_tool(setup,monkeypatch):
    from backend.tests.test_agentic import create_run, brief
    from backend.app import orchestration as agent, pipeline, media
    from backend.app.db import DB,Run
    ident=create_run({'supervisor':brief(),'_execution_plan':execution_plan(),
                      '_config':{'video_execution_policy':'planned_v1'}})
    with DB() as db:
        run=db.get(Run,ident);run.cancel_requested=True;db.commit()
    monkeypatch.setattr(pipeline,'run_stage',lambda *a,**k:pytest.fail('Cancelled tool executed'))
    with pytest.raises(media.Cancelled):agent.specialist(ident,'strategy')


def test_gpu_oom_preserves_completed_clip_and_falls_back_only_missing(tmp_path,monkeypatch):
    import importlib.util
    import sys
    from pathlib import Path
    spec=importlib.util.spec_from_file_location('speedup_gpu_worker',Path(__file__).parents[1]/'kaggle/generate.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setitem(sys.modules,'torch',SimpleNamespace(cuda=SimpleNamespace(device_count=lambda:2)))
    original_path=Path
    monkeypatch.setattr(module,'Path',lambda value:tmp_path if value=='/kaggle/working' else original_path(value))
    calls=[]
    def profile(shots,request,runtime,model,manifest,embeddings,name,directory,count):
        directory.mkdir(parents=True,exist_ok=True)
        calls.append((name,[s['shot_id'] for s in shots]))
        chosen=shots[:1] if name!='legacy_fp32' else shots
        for shot in chosen:(directory/(shot['shot_id']+'.mp4')).write_bytes(name.encode())
        return {'clips':{s['shot_id']:{'seed':s['fixed_seed']} for s in chosen},'errors':{},
                'runtime':{'profile':name},'oom':name!='legacy_fp32'}
    monkeypatch.setattr(module,'profile_pass',profile)
    request={'run_id':'test','revision':1,'text_seconds':0,'profile':'dual_fp32_model_v1',
             'shots':[{'shot_id':f'shot-{i:03}','fixed_seed':i} for i in range(3)]}
    module.run_profiles(request,{},'model','manifest','embeddings')
    result=json.loads((tmp_path/'result.json').read_text())
    assert calls==[('dual_fp32_model_v1',['shot-000','shot-001','shot-002']),('legacy_fp32',['shot-001','shot-002'])]
    assert set(result['clips'])=={'shot-000','shot-001','shot-002'}
    assert (tmp_path/'shot-000.mp4').read_bytes()==b'dual_fp32_model_v1'


def test_scene_budget_repair_does_not_rewrite_other_scenes():
    from backend.app.planned_edit import repair_cues
    cues=[{'kind':'kinetic_text','scene_index':i,'start_frame':0,'frames':50 if i else 20,
           'title':'Başlık','reason':'Anlatılan bilgiyi görünür kılar.'} for i in range(2)]
    original=deepcopy(cues[0]);decision={'graphics':cues,'sound_cues':[]}
    calls=[]
    class Model:
        def generate(self,schema,role,context):
            calls.append(context['scene_index'])
            return {'graphics':[{**cues[1],'frames':20}],'sound_cues':[]}
    repair_cues(decision,[1,1],[],{},Model(),lambda:None)
    assert calls==[1]
    assert decision['graphics'][0]==original


def test_export_commit_survives_worker_exit_and_rejects_partial_or_modified_files(tmp_path):
    import importlib.util
    import hashlib
    from pathlib import Path
    spec=importlib.util.spec_from_file_location('speedup_commit',Path(__file__).parents[1]/'kaggle/generate.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    shot={'shot_id':'shot-000'}
    payload=b'complete clip'
    (tmp_path/'shot-000.clip.json').write_text(json.dumps({'sha256':hashlib.sha256(payload).hexdigest(),'seed':42}))
    (tmp_path/'shot-000.partial.mp4').write_bytes(payload)
    assert module.committed_clips(tmp_path,[shot])=={}
    (tmp_path/'shot-000.partial.mp4').replace(tmp_path/'shot-000.mp4')
    assert module.committed_clips(tmp_path,[shot])['shot-000']['seed']==42
    assert module.committed_clips(tmp_path,[shot],{'shot-000'})=={}
    (tmp_path/'shot-000.mp4').write_bytes(b'changed')
    assert module.committed_clips(tmp_path,[shot])=={}
