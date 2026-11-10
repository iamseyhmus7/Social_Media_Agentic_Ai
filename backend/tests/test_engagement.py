from copy import deepcopy
from types import SimpleNamespace
import importlib.util
from pathlib import Path
import pytest
from pydantic import ValidationError
from backend.app.engagement import engaging_script,validate_engagement
from backend.app.schemas import Script
from backend.app.config import settings,snapshot_settings,use_run_settings


def sample():
    return {'hook':'Bir nehir savaşın kaderini nasıl değiştirdi?',
        'cta':'Savunma başarıya ulaştı.',
        'scenes':[{'title':'Açılış','narration':'Bir nehir savaşın kaderini nasıl değiştirdi? Sakarya savunmasını anlatıyoruz.',
                   'visual_prompt':'A cinematic vertical view of the Sakarya river at dawn.'},
                  {'title':'Gelişme','narration':'Ordu savunma için hazırlık yaptı ve mücadele başladı.',
                   'visual_prompt':'A cinematic vertical view of the defensive trenches.'},
                  {'title':'Sonuç','narration':'Savunma başarıya ulaştı.',
                   'visual_prompt':'A cinematic vertical view of soldiers at dawn after the battle.'}]}


def test_hook_is_in_actual_spoken_narration_and_closing_needs_no_social_cta():
    schema=engaging_script(Script)
    assert schema.model_validate(sample()).cta==sample()['cta']
    wrong=sample();wrong['scenes'][0]['narration']='Bu başlangıç hook ile eşleşmiyor.'
    with pytest.raises(ValidationError):schema.model_validate(wrong)


def test_new_closing_is_spoken_and_old_run_policy_stays_unchanged(monkeypatch):
    from backend.app.engagement import instruction_for
    monkeypatch.setattr(settings(),'engagement_policy',2)
    assert snapshot_settings()['engagement_policy']==2
    with use_run_settings({'engagement_policy':1}):
        assert settings().engagement_policy==1
        assert engaging_script(Script,1).model_validate(sample())
    payload=sample()
    payload['cta']='Bu savunmada en kritik kararı yorumlarda paylaş.'
    schema=engaging_script(Script,2)
    with pytest.raises(ValidationError):schema.model_validate(payload)
    payload['scenes'][-1]['narration']+=' '+payload['cta']
    assert schema.model_validate(payload).scenes[-1].narration.endswith(payload['cta'])
    assert 'otomatik beğeni veya takip çağrısı ekleme' not in instruction_for(2)
    assert 'tek bir etkileşim' in instruction_for(2)


def test_new_script_agent_places_contextual_cta_in_actual_narration(setup,monkeypatch):
    from backend.tests.test_agentic import create_run
    from backend.app import pipeline
    from backend.app.db import DB,Run
    ident=create_run({'_config':{'engagement_policy':2},'_edit_style':'classic'})
    payload=sample();payload['cta']='Bu savunmada en kritik kararı yorumlarda paylaş.'
    payload['scenes'][-1]['narration']+=' '+payload['cta']
    def generate(self,schema,role,context,**kwargs):
        assert context['engagement_policy']==2
        assert 'tek bir etkileşim' in context['mandatory_engagement']
        assert 'otomatik beğeni veya takip çağrısı ekleme' not in context['instructions'].lower()
        return schema.model_validate(payload).model_dump()
    monkeypatch.setattr(pipeline.Evren,'generate',generate)
    pipeline.run_stage(ident,'script')
    with DB() as db:
        value=db.get(Run,ident).outputs['script']
        assert value['scenes'][-1]['narration'].endswith(value['cta'])


def test_spoken_cta_survives_editorial_writing_supervisor_and_scene_allocation():
    from backend.tests.test_script_editorial import WriterV2,v2_context,v2_draft
    from backend.app.script_editorial import StoryDraft,SupervisorVerdict,generate_editorial_script_v2
    from backend.app.engagement import instruction_for
    cta='Bu alarmda hangi kontrolü yapardın, yorumlarda paylaş.'
    class Writer(WriterV2):
        reviewed=False
        def generate(self,schema,role,context):
            if issubclass(schema,StoryDraft):
                value=v2_draft();value['beats'][-1]['narration']+=' '+cta
                return schema.model_validate(value).model_dump()
            if issubclass(schema,SupervisorVerdict):
                assert context['mandatory_engagement']==instruction_for(2)
                assert context['draft']['beats'][-1]['narration'].endswith(cta)
                self.reviewed=True
            return super().generate(schema,role,context)
    context={**v2_context(),'engagement_policy':2,'mandatory_engagement':instruction_for(2)}
    writer=Writer()
    script,_=generate_editorial_script_v2(writer,engaging_script(Script,2),context,'Konuya özel sesli etkileşimle bitir.')
    assert writer.reviewed and script['cta']==cta
    assert script['scenes'][-1]['narration'].endswith(cta)


def test_new_defaults_require_parallel_and_old_snapshots_stay_compatible(monkeypatch):
    from backend.app import gpu_profile
    monkeypatch.setattr(settings(),'kaggle_motion_profile','dual_required')
    monkeypatch.setattr(settings(),'engagement_policy',1)
    assert snapshot_settings()['engagement_policy']==1
    assert gpu_profile.selected_profile()==gpu_profile.PARALLEL_PROFILE
    with use_run_settings({}):
        assert settings().engagement_policy==0
        assert gpu_profile.selected_profile()=='legacy_fp32'


def test_parallel_profile_never_silently_runs_with_one_gpu(tmp_path,monkeypatch):
    import sys
    spec=importlib.util.spec_from_file_location('engagement_gpu',Path('backend/kaggle/generate.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setitem(sys.modules,'torch',SimpleNamespace(cuda=SimpleNamespace(device_count=lambda:1)))
    original=Path
    monkeypatch.setattr(module,'Path',lambda p:tmp_path if p=='/kaggle/working' else original(p))
    with pytest.raises(RuntimeError,match='Two GPUs required'):
        module.run_profiles({'profile':'dual_fp32_sequential_v1','run_id':'test','revision':1,'text_seconds':0,'shots':[]},None,None,None,None)


def test_dual_shards_assign_every_shot_once():
    spec=importlib.util.spec_from_file_location('engagement_shards',Path('backend/kaggle/generate.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    shots=[{'shot_id':f'shot-{i:03}','duration_seconds':i+1} for i in range(17)]
    assignments=module.balanced_shards(shots,2)
    assert len(assignments)==2 and all(assignments)
    assert sorted(s['shot_id'] for group in assignments for s in group)==sorted(s['shot_id'] for s in shots)


def test_two_gpu_processes_start_before_any_join(tmp_path,monkeypatch):
    import json,sys
    spec=importlib.util.spec_from_file_location('engagement_parallel',Path('backend/kaggle/generate.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    started=[]
    class Process:
        exitcode=0
        def __init__(self,target,args):self.args=args;self.pid=100+args[0]
        def start(self):
            gpu,shots,*_=self.args
            started.append(gpu)
            Path(self.args[-2]).write_text(json.dumps({'clips':{s['shot_id']:{'gpu':gpu} for s in shots},'errors':{}}))
        def join(self,timeout):assert started==[0,1]
        def is_alive(self):return False
    monkeypatch.setitem(sys.modules,'multiprocessing',SimpleNamespace(get_context=lambda mode:SimpleNamespace(Process=Process)))
    result=module.profile_pass([{'shot_id':'shot-000','duration_seconds':1},{'shot_id':'shot-001','duration_seconds':1}],
        {'run_id':'test','revision':1},None,None,None,None,'dual_fp32_sequential_v1',tmp_path,2)
    assert {c['gpu'] for c in result['clips'].values()}=={0,1}


def test_timing_repair_cannot_remove_opening_hook(setup,monkeypatch):
    from backend.tests.test_agentic import create_run
    from backend.app.recovery import repair_voice
    from backend.app.providers import Evren
    script=sample()
    ident=create_run({'script':script,'supervisor':{'duration':60},
        'voice':{'duration':61.68,'durations':[20,20,21.68],'audios':['a','b','c']},
        '_config':{'engagement_policy':1}})
    def generate(self,schema,role,context,**kw):
        texts=[s['narration'] for s in script['scenes']]
        remaining=context['required_words']-sum(len(text.split()) for text in texts[1:])
        texts[0]=' '.join(['Anlatım']*remaining)
        with pytest.raises(ValidationError,match='hook'):
            schema.model_validate({'narrations':texts})
        raise RuntimeError('test stops before generation')
    monkeypatch.setattr(Evren,'generate',generate)
    with pytest.raises(RuntimeError,match='test stops'):repair_voice(ident)


def test_script_agent_receives_rules_without_user_prompt(setup,monkeypatch):
    from backend.tests.test_agentic import create_run
    from backend.app import pipeline
    from backend.app.db import DB,Run
    ident=create_run({'_config':{'engagement_policy':1},'_edit_style':'classic'})
    def generate(self,schema,role,context,**kwargs):
        assert '1–3 saniyede' in context['mandatory_engagement']
        assert 'otomatik beğeni veya takip çağrısı ekleme' in context['mandatory_engagement']
        return schema.model_validate(sample()).model_dump()
    monkeypatch.setattr(pipeline.Evren,'generate',generate)
    pipeline.run_stage(ident,'script')
    with DB() as db:validate_engagement(db.get(Run,ident).outputs['script'])


def test_gpu_component_check_does_not_replace_video_in_project_list(clients):
    from backend.tests.test_agentic import create_run
    from backend.app.db import DB,Run
    check=create_run({'_component_check':True})
    normal=create_run()
    with DB() as db:
        hidden=db.get(Run,check).project_id;visible=db.get(Run,normal).project_id
    projects=clients[0].get('/api/v1/projects').json()
    assert hidden not in [p['id'] for p in projects]
    assert visible in [p['id'] for p in projects]
