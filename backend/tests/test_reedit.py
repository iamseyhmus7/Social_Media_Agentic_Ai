from uuid import uuid4
from copy import deepcopy
import pytest
from sqlalchemy import select, func
from fastapi import HTTPException
from backend.app.db import DB, Project, Run, Asset, User, RemoteJob
from backend.app.storage import workdir, register, media_path
from backend.app.schemas import Reedit, DynamicEditPlan, RenderManifest
from backend.app.reedit import create_reedit


def source_run(project):
    with DB() as db:
        db.get(Project,project['id']).duration=30
        run=Run(id=str(uuid4()),project_id=project['id'],user_id='alice',revision=1,pipeline_version=2,status='failed',stage='publisher')
        db.add(run);db.commit()
        folder=workdir(project['id'],run.id)
        ids=[]
        for name,kind in [('voice.wav','audio'),('image.png','image'),('shot-000.mp4','clip')]:
            path=folder/name;path.write_bytes(name.encode());ids.append(register(db,run,path,kind))
        run.outputs={'supervisor':{'ok':True},'strategy':{'ok':True},'script':{'scenes':[]},'voice':{'audios':[ids[0]],'durations':[30],'duration':30},'visual':{'images':[ids[1]],'cover':ids[1]},'motion':{'mode':'video','plan':{'shots':[{'shot_id':'shot-000'}]},'clips':{'shot-000':{'asset_id':ids[2],'file':'shot-000.mp4'}}},'editor':{'video':'old'},'publisher':{'old':True},'_config':{'video_provider':'kaggle'}}
        db.commit();return run.id,deepcopy(run.outputs),ids


def test_reedit_preserves_source_and_creates_owned_assets(project):
    ident,outputs,ids=source_run(project)
    with DB() as db:
        new=create_reedit(db,db.get(Project,project['id']),db.get(User,'alice'),Reedit(run_id=ident,instructions='Haritayla etkileyici açılış, sade tipografi.',map_intro=True,show_sources=False))
        assert new.revision==2 and new.stage=='editor'
        assert new.outputs['_edit_style']=='auto' and new.outputs['_edit_only']
        assert new.outputs['_edit_preferences']['map_intro'] is True
        assert new.outputs['_edit_preferences']['show_sources'] is False
        assert 'editor' not in new.outputs and 'publisher' not in new.outputs
        assert db.get(Run,ident).outputs==outputs
        assets=db.scalars(select(Asset).where(Asset.run_id==new.id)).all()
        assert new.outputs['voice']['audios'][0] not in ids
        assert new.outputs['visual']['images'][0] not in ids
        assert new.outputs['motion']['clips']['shot-000']['asset_id'] not in ids
        assert len(assets)==3 and not set(ids).intersection(a.id for a in assets)
        assert {a.sha256 for a in assets}=={db.get(Asset,i).sha256 for i in ids}
        assert db.scalar(select(func.count()).select_from(RemoteJob).where(RemoteJob.run_id==new.id))==0
        for a in assets:assert media_path(a.path).exists()


def test_reedit_hash_failure_rolls_back_revision_and_files(project):
    ident,outputs,ids=source_run(project)
    with DB() as db:
        media_path(db.get(Asset,ids[2]).path).write_bytes(b'changed')
        with pytest.raises(HTTPException) as exc:
            create_reedit(db,db.get(Project,project['id']),db.get(User,'alice'),Reedit(run_id=ident))
        assert exc.value.status_code==409
        assert db.get(Project,project['id']).revision==1
        assert db.scalar(select(func.count()).select_from(Run))==1
        assert len(list(media_path(project['id']).iterdir()))==1


def test_reedit_reuses_sampled_review_only_for_identical_owned_clips(project, monkeypatch):
    import json
    from backend.app import automatic_edit as editor
    ident, _, _ = source_run(project)
    base={'observations':[{'shot_id':'shot-000','verdict':'uncertain','observation':'Sfenks yüzünün üç örnek karesi, hareketin tamamı doğrulanmadı.'}],
          'segments':[{'shot_id':'shot-000','source_in_frame':0,'frames':900,'reason':'Anlatımı aynı sahnenin mevcut kaynak aralığıyla korur.'}],
          'rationale':'Önceki örnek kare incelemesiyle hazırlanmış geçerli bir montaj.'}
    with DB() as db:
        source=db.get(Run,ident)
        outputs=deepcopy(source.outputs)
        outputs['quality']={'passed':True}
        outputs['motion']['plan']['shots'][0].update(scene_index=0,duration_seconds=30)
        outputs['motion']['clips']['shot-000']['report']={'duration':30}
        source.outputs=outputs
        db.commit()
        (workdir(source.project_id,source.id)/'edit-plan.json').write_text(json.dumps(base),encoding='utf-8')
        run=create_reedit(db,db.get(Project,project['id']),db.get(User,'alice'),Reedit(run_id=ident))
    folder=workdir(run.project_id,run.id)
    calls=[]
    class LLM:
        def generate(self,schema,role,context,**kwargs):
            calls.append((context,kwargs))
            return {'segments':base['segments'],'rationale':'Yeni tipografi ve grafik tercihleri aynı kaynak kesmeleriyle uygulanır.'}
    monkeypatch.setattr(editor.media,'command',lambda *a,**k:pytest.fail('Unchanged clips must not be decoded again'))
    result,_=editor.prepare_automatic(run,folder,run.outputs['motion']['plan']['shots'],[30],LLM(),lambda:None)
    assert len(calls)==1 and not calls[0][1]['media_inputs']
    assert result['observations']==base['observations']
    assert run.outputs['_edit_review_source']==ident
    (folder/'shot-000.mp4').write_bytes(b'changed clip')
    with pytest.raises(RuntimeError,match='özeti değişmiş'):
        editor.verified_edit_base(run,folder,lambda:None)


def test_reedit_rejects_other_user_and_active_source(project):
    ident,_,_=source_run(project)
    with DB() as db:
        with pytest.raises(HTTPException) as exc:create_reedit(db,db.get(Project,project['id']),db.get(User,'bob'),Reedit(run_id=ident))
        assert exc.value.status_code==404
        db.get(Run,ident).status='running';db.commit()
        with pytest.raises(HTTPException) as exc:create_reedit(db,db.get(Project,project['id']),db.get(User,'alice'),Reedit(run_id=ident))
        assert exc.value.status_code==409


def test_dynamic_contract_requires_real_words_and_short_transitions():
    with pytest.raises(ValueError):DynamicEditPlan(opening_title='Güne böyle başla',ending_title='Bir nefes ver',shots=[{'shot_id':'shot-000','transition':'push'}])
    with pytest.raises(ValueError):DynamicEditPlan(opening_title='Güne böyle başla',ending_title='Bir nefes ver',shots=[{'shot_id':'shot-000'},{'shot_id':'shot-001','transition':'push','transition_frames':18}])
    with pytest.raises(ValueError):RenderManifest(style='dynamic',duration_frames=30,clips=[{'file':'shot-000.mp4','start_frame':0,'frames':30}])

def test_reedit_endpoint_rejects_stale_and_foreign_runs(project,clients,monkeypatch):
    from backend.app import main
    monkeypatch.setattr(main,'dispatch',lambda:None)
    ident,_,_=source_run(project)
    alice,bob=clients
    path='/api/v1/projects/'+project['id']+'/edits'
    assert bob.post(path,json={'run_id':ident}).status_code==404
    result=alice.post(path,json={'run_id':ident,'style':'dynamic'})
    assert result.status_code==202
    assert result.json()['edit_style']=='dynamic' and not result.json()['approved']
    assert result.json()['remote_jobs']==[]
    assert alice.post(path,json={'run_id':ident}).status_code==409


def test_edit_only_quality_failure_never_repairs_media(project,monkeypatch):
    from backend.app import pipeline
    ident,_,_=source_run(project)
    with DB() as db:
        run=create_reedit(db,db.get(Project,project['id']),db.get(User,'alice'),Reedit(run_id=ident))
        new_id=run.id
    seen=[]
    original=pipeline.run_stage
    def stage(identifier,key):
        if key in ('editor','quality'):
            seen.append(key)
            pipeline.checkpoint(identifier,key,{'passed':False,'issues':['Test technical failure']})
        elif key=='publisher':raise AssertionError('Failed edit cannot reach publisher')
        else:original(identifier,key) # Durable source checkpoints skip providers.
    monkeypatch.setattr(pipeline,'run_stage',stage)
    monkeypatch.setattr(pipeline.Evren,'generate',lambda *a,**k:pytest.fail('Re-edit cannot repair source media'))
    pipeline.execute(new_id)
    with DB() as db:
        run=db.get(Run,new_id)
        assert run.status=='failed' and 'otomatik GPU' in run.error
        assert '_repair_attempts' not in run.outputs
    assert seen==['editor','quality']


def test_word_timing_uses_measured_source_offsets(tmp_path):
    import json
    from backend.app.remotion_renderer import word_items
    srt=tmp_path/'captions.srt'
    srt.with_suffix('.words.json').write_text(json.dumps({'scenes':[{'duration_seconds':1,'words':[{'text':'Bir','startMs':0,'endMs':500}]},{'duration_seconds':2,'words':[{'text':' İki','startMs':250,'endMs':1500}]}]}))
    words=word_items(srt,[1,2])
    assert words[1]['startMs']==1250 and words[1]['endMs']==2500
    with pytest.raises(RuntimeError):word_items(srt,[1,2.1])


def test_caption_script_correction_preserves_asr_timing():
    from backend.app.remotion_renderer import align_script_words
    words=[{'text':'Sfanks','startMs':0,'endMs':200},{'text':" 'in",'startMs':200,'endMs':300},{'text':' burnunu','startMs':300,'endMs':600}]
    result=align_script_words(words,'Sfenks’in burnunu')
    assert [w['text'] for w in result]==['Sfenks’in',' burnunu']
    assert result[0]['startMs']==0 and result[0]['endMs']==300 and result[1]['endMs']==600
    assert len(words)==3 and words[0]['text']=='Sfanks'



def test_editor_resume_reuses_validated_plan_without_model(tmp_path,monkeypatch):
    import json
    from types import SimpleNamespace
    from backend.app import remotion_renderer as renderer
    from backend.app.config import settings
    root=tmp_path/'remotion'
    (root/'production/node_modules/@remotion/renderer').mkdir(parents=True)
    monkeypatch.setattr(settings(),'remotion_root',root)
    monkeypatch.setattr(renderer.shutil,'which',lambda _: '/node')
    folder=tmp_path/'run';folder.mkdir()
    (folder/'shot-000.mp4').write_bytes(b'owned clip')
    audio=folder/'voice.wav';audio.write_bytes(b'owned audio')
    srt=folder/'captions.srt';srt.write_text('1\n00:00:00,000 --> 00:00:00,500\nBir\n')
    srt.with_suffix('.words.json').write_text(json.dumps({'scenes':[{'duration_seconds':30,'words':[{'text':'Bir','startMs':0,'endMs':500}]}]}))
    plan={'opening_title':'Bir nefes molası','ending_title':'Bir an durun','shots':[{'shot_id':'shot-000'}]}
    (folder/'edit-plan.json').write_text(json.dumps(plan))
    run=SimpleNamespace(outputs={'_edit_style':'dynamic','script':{'scenes':[]},'motion':{'mode':'video','plan':{'shots':[{'shot_id':'shot-000','scene_index':0,'duration_seconds':30}]},'clips':{'shot-000':{'file':'shot-000.mp4'}}}})
    llm=SimpleNamespace(generate=lambda *a,**k:pytest.fail('A resumed edit must preserve its decision'))
    commands=[]
    monkeypatch.setattr(renderer.media,'command',lambda args,*a,**k:commands.append(args))
    monkeypatch.setattr(renderer.media,'validate_final',lambda *a,**k:{'passed':True})
    assert renderer.render_production(run,SimpleNamespace(duration=30),folder,[],[audio],[30],srt,lambda:None,llm,{},None,{})['passed']
    assert json.loads((folder/'render-manifest.json').read_text(encoding='utf-8'))['opening_title']==plan['opening_title']
    assert commands[0][1].name=='render.mjs'


def test_editorial_contract_requires_directed_montage():
    from backend.app.schemas import EditorialEditPlan
    payload={'opening_title':'Gürültüyü geride bırak','ending_title':'Bu an yanında kalsın','intro_beats':['Bir an dur','Işığa dön','Nefes al'],'teaser_shots':['shot-000','shot-001','shot-002'],'chapters':[{'scene_index':0,'title':'Işık','phrase':'Sabah yeniden başlar'}],'shots':[{'shot_id':'shot-000'},{'shot_id':'shot-001','transition':'whip','transition_frames':10},{'shot_id':'shot-002','transition':'reveal','transition_frames':16}]}
    assert EditorialEditPlan.model_validate(payload).teaser_shots[2]=='shot-002'
    wrong=deepcopy(payload);wrong['shots'][1]['transition']='cut'
    with pytest.raises(ValueError):EditorialEditPlan.model_validate(wrong)
    wrong=deepcopy(payload);wrong['teaser_shots'][1]='shot-000'
    with pytest.raises(ValueError):EditorialEditPlan.model_validate(wrong)
    wrong=deepcopy(payload);wrong['intro_beats'][0]='Bu açılış vurgusu güvenli uzunluk sınırını aşıyor'
    with pytest.raises(ValueError):EditorialEditPlan.model_validate(wrong)


def test_render_retries_only_browser_startup_timeout(tmp_path, monkeypatch):
    from backend.app import remotion_renderer as renderer
    calls = []
    def command(*args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            (tmp_path/'tool.log').write_text('TimeoutError: Timed out after 25000 ms while trying to connect to the browser!')
            raise RuntimeError('Medya aracı başarısız.')
    monkeypatch.setattr(renderer.media, 'command', command)
    renderer.render_visual(['node','render.mjs'], tmp_path, lambda:None)
    assert len(calls) == 2
    assert (tmp_path/'render-browser-attempt-1.log').is_file()


def test_chunk_frame_timeout_retries_same_range_once(tmp_path,monkeypatch):
    from backend.app import remotion_renderer as renderer
    calls=[]
    def command(args,*rest,**kwargs):
        calls.append(list(args))
        if len(calls)==1:
            (tmp_path/'tool.log').write_text('TimeoutError: waiting for the page to render the React component at frame 497 failed')
            raise RuntimeError('Medya aracı başarısız.')
    monkeypatch.setattr(renderer.media,'command',command)
    renderer.render_visual(['node','render.mjs','manifest','public','output','browser','chunk'],tmp_path,lambda:None)
    assert len(calls)==2 and calls[0][:-1]==calls[1][:-1]
    assert calls[1][-1]=='1'
    assert (tmp_path/'render-frame-attempt-1.log').is_file()


def test_exhausted_frame_timeout_identifies_frame_instead_of_browser_connection(tmp_path,monkeypatch):
    from backend.app import remotion_renderer as renderer
    calls=[]
    def command(args,*rest,**kwargs):
        calls.append(list(args))
        (tmp_path/'tool.log').write_text('TimeoutError: waiting for the page to render the React component at frame 630 failed')
        raise RuntimeError('Medya aracı başarısız.')
    monkeypatch.setattr(renderer.media,'command',command)
    with pytest.raises(RuntimeError,match='630. karede') as failure:
        renderer.render_visual(['node','render.mjs','manifest','public','output','browser','chunk'],tmp_path,lambda:None)
    assert 'bağlanamadı' not in str(failure.value)
    assert len(calls)==2
    assert (tmp_path/'render-frame-attempt-2.log').is_file()


@pytest.mark.parametrize('browser_timeout', [False, True])
def test_render_retry_is_bounded_and_does_not_hide_other_errors(tmp_path, monkeypatch, browser_timeout):
    from backend.app import remotion_renderer as renderer
    calls = []
    def command(*args, **kwargs):
        calls.append(args)
        (tmp_path/'tool.log').write_text('TimeoutError: while trying to connect to the browser!' if browser_timeout else 'Invalid composition')
        raise RuntimeError('Medya aracı başarısız.')
    monkeypatch.setattr(renderer.media, 'command', command)
    with pytest.raises(RuntimeError, match='Chrome' if browser_timeout else 'Medya'):
        renderer.render_visual(['node','render.mjs'], tmp_path, lambda:None)
    assert len(calls) == (2 if browser_timeout else 1)
