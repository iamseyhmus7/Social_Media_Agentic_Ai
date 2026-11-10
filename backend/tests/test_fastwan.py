import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.kaggle.fastwan_workflow import BRIDGE, dmd_sigmas, graph, native_key


LOCK = json.loads((Path(__file__).parents[1] / 'kaggle/fastwan_runtime_lock.json').read_text())


def test_fastwan_uses_48_channel_image_conditioning_and_one_model():
    shot = {'shot_id':'shot-003', 'duration_seconds':3.7, 'camera':'push_in',
            'motion_prompt':'A hand presses the red button.'}
    nodes = graph(LOCK, shot, 'reference.png', 12, 'locked-model')
    kinds = [n['class_type'] for n in nodes.values()]
    assert kinds.count('UNETLoader') == 1
    assert 'Wan22ImageToVideoLatent' in kinds
    assert 'WanImageToVideo' not in kinds
    assert nodes['6']['inputs']['start_image'] == ['5',0]
    assert nodes['6']['inputs']['length'] >= math.ceil(3.7*24)
    assert nodes['8']['class_type'] == 'BasicGuider'  # no second CFG evaluation
    assert nodes['10']['class_type'] == 'SahneDMDSampler'
    assert nodes['7']['inputs']['images'] == ['12',0]


def test_fastwan_weight_conversion_does_not_swap_norms_twice():
    assert native_key('blocks.2.norm2.weight') == 'blocks.2.norm3.weight'
    assert native_key('blocks.2.norm3.weight') == 'blocks.2.norm2.weight'
    assert native_key('blocks.2.scale_shift_table') == 'blocks.2.modulation'
    assert native_key('scale_shift_table') == 'head.modulation'
    assert native_key('blocks.2.attn1.to_out.0.weight') == 'blocks.2.self_attn.o.weight'
    assert native_key('condition_embedder.time_proj.weight') == 'time_projection.1.weight'
    with pytest.raises(ValueError): native_key('unexpected.weight')


def test_dmd_uses_shifted_training_table_not_an_euler_step_schedule():
    sigmas = dmd_sigmas(LOCK['timesteps'],LOCK['training_shift'])
    assert sigmas[0] == 1 and sigmas[-1] == 0
    assert len(sigmas) == 4 and all(a>b for a,b in zip(sigmas,sigmas[1:]))
    assert abs(sigmas[1] * 1000 - 757) < 1
    assert abs(sigmas[2] * 1000 - 522) < 1


def test_dmd_reinjects_noise_and_reports_all_three_steps(monkeypatch):
    torch = pytest.importorskip('torch')
    import sys
    import types
    package = types.ModuleType('test_fastwan_bridge')
    package.__path__ = []
    monkeypatch.setitem(sys.modules, 'test_fastwan_bridge', package)
    from backend.kaggle import fastwan_workflow
    monkeypatch.setitem(sys.modules, 'test_fastwan_bridge.fastwan_workflow', fastwan_workflow)
    comfy = types.ModuleType('comfy')
    comfy.samplers = SimpleNamespace()
    comfy.model_sampling = SimpleNamespace()
    monkeypatch.setitem(sys.modules, 'comfy', comfy)
    monkeypatch.setitem(sys.modules, 'comfy.samplers', comfy.samplers)
    monkeypatch.setitem(sys.modules, 'comfy.model_sampling', comfy.model_sampling)
    scope = {'__package__':'test_fastwan_bridge'}
    exec(BRIDGE, scope)
    calls, callbacks = [], []
    def model(x,t,**kwargs):
        calls.append((x.clone(),t.clone()))
        return x * .25
    x = torch.ones(1,2,2)
    sigmas = torch.tensor(dmd_sigmas(LOCK['timesteps']))
    actual = scope['sample_dmd'](model,x.clone(),sigmas,{'seed':9},callbacks.append)
    generator = torch.Generator().manual_seed(9)
    expected = x.clone()
    for index in range(3):
        clean = expected * .25
        expected = ((1-sigmas[index+1])*clean + sigmas[index+1]*torch.randn(x.shape,generator=generator)
                    if index<2 else clean)
    torch.testing.assert_close(actual,expected)
    assert len(calls) == len(callbacks) == 3


def test_fastwan_bootstrap_and_request_are_durable(setup, tmp_path,monkeypatch):
    from backend.app.config import Settings, _run_settings
    from backend.app.db import DB, User, Project, Run
    from backend.app.kaggle_provider import stage_job
    token = _run_settings.set(Settings(kaggle_username='owned-user',video_model_profile='fastwan5b_v1'))
    try:
        with DB() as db:
            project=Project(id='fast-project',user_id='alice',topic='FastWan',title='FastWan');db.add(project);db.flush()
            run=Run(id='fast-run',project_id=project.id,user_id='alice',revision=1);db.add(run);db.commit()
        request={'runtime':'fastwan5b-v1','component':'fastwan5b','fastwan_lock_sha256':'locked'}
        first=stage_job(run,tmp_path,request,bootstrap=True)
        again=stage_job(run,tmp_path,request,bootstrap=True)
        assert again.id==first.id
        root=tmp_path/'kaggle'/first.id
        metadata=json.loads((root/'kernel-metadata.json').read_text())
        assert metadata['is_private'] and not metadata['enable_gpu']
        assert metadata['enable_internet']
        assert metadata['id'].endswith('/sahne-fastwan5b-v1-fastwan5b')
        source=(root/'run.py').read_text()
        assert 'fastwan_runtime_lock.json' in source and 'fastwan_workflow.py' in source
    finally:
        _run_settings.reset(token)


def test_fastwan_delivers_opening_scene_before_remaining_batch(tmp_path,monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    import pytest
    from backend.app import agent_progress, kaggle_provider, media, wan_provider as wan
    from backend.app.config import Settings
    from backend.app.storage import file_hash

    monkeypatch.setattr(wan,'settings',lambda:Settings(media_root=tmp_path/'media',video_model_profile='fastwan5b_v1'))
    monkeypatch.setattr(wan,'DB',lambda:nullcontext(SimpleNamespace(scalar=lambda *_:None,get=lambda *_:None,commit=lambda:None)))
    monkeypatch.setattr(agent_progress,'mark',lambda *a,**kw:None)
    monkeypatch.setattr(wan,'register',lambda db,run,target,*a,**kw:target.stem)
    monkeypatch.setattr(wan,'review_clip',lambda *a:{'verdict':'pass'})
    monkeypatch.setattr(media,'inspect_clip',lambda *a:{'duration':3,'decoded':True})
    monkeypatch.setattr(kaggle_provider,'KaggleGateway',object)
    monkeypatch.setattr(wan,'prepare_runtime',lambda *a:[])
    run=SimpleNamespace(id='run',revision=1,outputs={'_edit_style':'auto','_config':{
        'video_execution_policy':'planned_v1','video_edit_policy':'scenes_v3','editor_streaming_enabled':True}})
    shots=[{'shot_id':f'shot-{i:03}','scene_index':int(i==2),'image_index':0,'motion_prompt':'A person turns.',
            'duration_seconds':3} for i in range(3)]
    reference=tmp_path/'ref.png';reference.write_bytes(b'input')
    requests=[]
    snapshots=[]

    def stage(run,folder,request,**kw):
        ids=[shot['shot_id'] for shot in request['shots']]
        requests.append((ids,request['session']))
        if len(requests)!=2:
            raise kaggle_provider.RemotePending()
        output=folder/'kaggle'/'first'/'output';output.mkdir(parents=True)
        clips={}
        for ident in ids:
            path=output/(ident+'.mp4');path.write_bytes(ident.encode())
            clips[ident]={'sha256':file_hash(path),'width':480,'height':832,'fps':24}
        return SimpleNamespace(id='first',status='complete',result={'run_id':run.id,'revision':run.revision,
            'runtime':'fastwan5b-v1','sampling_profile':'dmd3_v1','clips':clips})

    monkeypatch.setattr(kaggle_provider,'stage_job',stage)
    for _ in range(2):
        with pytest.raises(kaggle_provider.RemotePending):
            wan.generate_clips(run,tmp_path,{'shots':shots},[reference],lambda:None,
                on_ready=lambda clips:snapshots.append(list(clips)))
    assert requests[0]==requests[1]
    assert [ids for ids,_ in requests]==[['shot-000','shot-001'],['shot-000','shot-001'],['shot-002']]
    assert snapshots==[[],[],['shot-000','shot-001']]
