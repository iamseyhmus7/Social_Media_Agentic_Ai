from copy import deepcopy
from uuid import uuid4
import pytest
from backend.app.db import DB,Run,User,Project,Feedback
from backend.app.config import settings
from backend.app.storage import workdir,register
from backend.app import pipeline
from backend.app.audio_reuse import input_key,voice_config
from backend.app.visual_progress import visual_progress
from backend.tests.test_agentic import create_run,owned_source


@pytest.mark.parametrize('change,expected',[
    ('visual_only',0),('one_narration',1),('explicit_voice',2),
    ('one_voice',1),('model',2),('damaged_audio',1),('legacy_metadata',0)])
def test_voice_revision_uses_synthesis_inputs_not_visual_scene_flags(setup,monkeypatch,change,expected):
    from backend.app import voice_selection
    monkeypatch.setattr(settings(),'elevenlabs_voice_id','fixed-voice')
    script={'scenes':[{'narration':'İlk anlatım.'},{'narration':'İkinci anlatım.'}]}
    cfg=voice_config(settings())
    ident=create_run({'script':deepcopy(script),'_previous_script':deepcopy(script),
        '_changed_scenes':[0,1],'_repair_stages':['script','visual']})
    with DB() as db:
        r=db.get(Run,ident);folder=workdir(r.project_id,ident)
        ids=[]
        for index in range(2):
            path=folder/f'reuse-{index}.wav';path.write_bytes(f'original-{index}'.encode())
            ids.append(register(db,r,path,'audio'))
        old={'audios':ids,'durations':[2,2],'duration':4,
             'input_keys':[input_key(s['narration'],cfg) for s in script['scenes']]}
        outputs={**r.outputs,'_reuse_voice':old,'_reuse_voice_settings':{'config':cfg,'plan':None}}
        if change=='legacy_metadata':old.pop('input_keys')
        if change=='one_narration':outputs['script']['scenes'][1]['narration']='Yeni anlatım.'
        if change in ('explicit_voice','one_voice'):
            outputs['_repair_stages']=['voice'];outputs['_changed_scenes']=[] if change=='explicit_voice' else [1]
        if change=='damaged_audio':(folder/'reuse-1.wav').write_bytes(b'corrupted')
        r.outputs=outputs;db.commit()
    if change=='model':monkeypatch.setattr(settings(),'elevenlabs_model','changed-model')
    monkeypatch.setattr(voice_selection,'select_voice',lambda *a:None)
    generated=[]
    def voice(text,target,*args,**kwargs):
        generated.append(text);target.write_bytes(b'new-audio');return 2
    monkeypatch.setattr(pipeline.media,'voice',voice)
    pipeline.run_stage(ident,'voice')
    with DB() as db:
        value=db.get(Run,ident).outputs['voice']
        assert len(value['input_keys'])==2
        assert len(generated)==expected
        assert value['generated_count']==expected and value['reused_count']==2-expected
        if expected==0:assert value['audios']==ids
        if change in ('one_narration','one_voice','damaged_audio'):assert value['audios'][0]==ids[0]


def test_voice_identity_ignores_selection_reason_but_tracks_speaker_settings(monkeypatch):
    cfg={'tts_provider':'elevenlabs','elevenlabs_model':'model','elevenlabs_voice_id':'fallback'}
    plan={'voice_id':'speaker','decision':{'stability':.5,'style':.2,'reason':'Önceki gerekçe'}}
    first=input_key('İlk   cümle.',cfg,plan)
    plan['decision']['reason']='Yeni editoryal gerekçe'
    assert input_key('İlk cümle.',cfg,plan)==first
    plan['decision']['stability']=.8
    assert input_key('İlk cümle.',cfg,plan)!=first


def test_v4_voice_identity_uses_only_settings_sent_to_the_provider():
    cfg={'tts_provider':'elevenlabs','elevenlabs_model':'eleven_v4','elevenlabs_voice_id':'fallback'}
    plan={'voice_id':'speaker','decision':{'stability':.5,'style':.2}}
    original=input_key('Aynı anlatım.',cfg,plan)
    plan['decision']['style']=.9
    assert input_key('Aynı anlatım.',cfg,plan)==original
    plan['decision']['stability']=.8
    assert input_key('Aynı anlatım.',cfg,plan)!=original


def test_storyboard_revision_sends_only_model_fields_and_keeps_runtime_indices():
    from backend.app.storyboard import revise_storyboard
    previous={'shots':[{'shot_id':f'shot-{i:03}','scene_index':i,'duration_seconds':2,
        'reference_prompt':'A realistic object on a dark table.','motion_prompt':'The object turns slowly.',
        'purpose':'Nesneyi göster.','expected_action':'Nesne yavaşça döner.','camera':'locked','image_index':i} for i in range(2)]}
    class Model:
        def generate(self,schema,role,context):
            assert all('image_index' not in s for s in context['previous']['shots'])
            value=schema.model_validate(context['previous']).model_dump()
            for shot in value['shots']:shot['reference_prompt']='A newly revised realistic object on a table.'
            return value
    result=revise_storyboard(Model(),previous,{},[2,2],[0],{},None)
    assert result['shots'][0]['image_index']==0 and result['shots'][1]['image_index']==1
    assert result['shots'][0]['reference_prompt']!=previous['shots'][0]['reference_prompt']
    assert result['shots'][1]['reference_prompt']==previous['shots'][1]['reference_prompt']


def test_visual_progress_requires_current_checkpoints_and_counts_shots():
    outputs={'script':{'scenes':[{},{}]},'_reuse_visual':{'images':['old-a','old-b']}}
    assert visual_progress(outputs)['completed']==0
    outputs['_visual_progress']={'completed':2,'total':4,'unit':'shots','scene_images':{'0':'new-a'}}
    assert visual_progress(outputs)['completed']==2
    outputs['visual']={'images':['new-a','new-b'],'shot_images':{'a':'new-a','b':'new-c','c':'new-b','d':'new-d'}}
    assert visual_progress(outputs)=={'completed':4,'total':4,'unit':'shots','scene_images':{'0':'new-a','1':'new-b'}}


def test_visual_stage_records_incremental_progress_separately_from_old_assets(setup,monkeypatch):
    ident=create_run({'script':{'scenes':[{'visual_prompt':'First object.'},{'visual_prompt':'Second object.'}]},
        '_reuse_visual':{'images':['old-a','old-b']}})
    progress=[]
    def image(prompt,target,*args):
        with DB() as db:
            progress.append(visual_progress(db.get(Run,ident).outputs)['completed'])
        target.write_bytes(b'new-image')
    monkeypatch.setattr(pipeline.media,'image',image)
    monkeypatch.setattr(pipeline.media,'cover',lambda source,title,target,brand:target.write_bytes(b'cover'))
    pipeline.run_stage(ident,'visual')
    assert progress==[0,1]
    with DB() as db:
        r=db.get(Run,ident)
        assert visual_progress(r.outputs)['completed']==2
        assert r.outputs['_visual_progress']['scene_images']=={
            '0':r.outputs['visual']['images'][0],'1':r.outputs['visual']['images'][1]}


def test_copy_only_feedback_updates_package_without_rendering_media(setup,monkeypatch):
    from backend.app.feedback import create_feedback,process_feedback
    from backend.app.schemas import FeedbackRequest,FeedbackDecision,PublicationCopy
    source_id,project_id=owned_source()
    monkeypatch.setattr(settings(),'video_review_policy','technical_only')
    with DB() as db:
        source=db.get(Run,source_id)
        source.outputs={**source.outputs,'publisher':{'title':'Eski başlık','description':'Eski paylaşım açıklaması.','hashtags':['#eski']}}
        db.commit()
        item=create_feedback(db,db.get(Project,project_id),db.get(User,'alice'),FeedbackRequest(
            run_id=source_id,prompt='Paylaşım başlığını ve açıklamasını kısalt, etiketleri kaldır.',request_id=str(uuid4())))
        feedback_id=item.id
    calls=[]
    def generate(self,schema,role,context,**kwargs):
        calls.append(schema)
        if schema is FeedbackDecision:
            return {'summary':'Yalnız paylaşım metnini değiştir.','stages':['publisher'],
                'instructions':'Başlık ve açıklamayı kısalt, etiketleri kaldır.'}
        assert schema is PublicationCopy and role=='Yayıncı'
        assert context['previous_copy']['description']=='Eski paylaşım açıklaması.'
        return {'title':'Yeni başlık','description':'Kısa paylaşım açıklaması.','hashtags':[],
                'instagram':'Kısa Instagram metni.','tiktok':'Kısa TikTok metni.'}
    monkeypatch.setattr(pipeline.Evren,'generate',generate)
    process_feedback(feedback_id)
    with DB() as db:
        item=db.get(Feedback,feedback_id);assert item.status=='applied',item.error
        ident=item.run_id
    original=pipeline.run_stage
    def only_package(run_id,stage,**kwargs):
        assert stage=='publisher'  # No render, TTS, images or GPU generation.
        return original(run_id,stage,**kwargs)
    monkeypatch.setattr(pipeline,'run_stage',only_package)
    pipeline.execute(ident)
    with DB() as db:
        r=db.get(Run,ident)
        assert r.status=='awaiting_approval',r.error
        assert r.outputs['publisher']['description']=='Kısa paylaşım açıklaması.'
        assert r.outputs['publisher']['hashtags']==[]
        assert r.outputs['publisher']['method']=='user_requested_copy_revision'
    assert calls==[FeedbackDecision,PublicationCopy]
