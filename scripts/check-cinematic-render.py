"""Deterministic renderer acceptance with labelled synthetic footage; no external generation."""
import argparse
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from backend.app import media
from backend.app.config import settings
from backend.app.schemas import AutoEditPlan
from backend.app.remotion_renderer import render_production
from backend.app.storage import file_hash

parser=argparse.ArgumentParser()
parser.add_argument('output',type=Path)
args=parser.parse_args()
root=args.output.resolve();root.mkdir(parents=True,exist_ok=True)
check=lambda:None
media.command([settings().ffmpeg_bin,'-y','-f','lavfi','-i','testsrc2=size=480x832:rate=24',
    '-t','5','-c:v','libx264','-pix_fmt','yuv420p',root/'source.mp4'],root,check)
media.command([settings().ffmpeg_bin,'-y','-f','lavfi','-i','sine=frequency=330:sample_rate=24000',
    '-t','30','-c:a','pcm_s16le',root/'voice.wav'],root,check)
profiles=[('premium','Kontrollü ürün sunumu',['cut','dissolve','cut','light_sweep','cut','reveal','cut']),
          ('energetic','Hızlı ritim ve hareketli tipografi',['cut','whip','cut','zoom','push','cut','whip']),
          ('explainer','Bilgi hiyerarşisi ve detay kadrajı',['cut','cut','reveal','cut','dissolve','cut','push'])]
reports=[]
for name,direction,transitions in profiles:
    folder=root/name;folder.mkdir(exist_ok=True)
    frames=[129,129,129,129,128,128,128]
    shots=[];clips={};segments=[]
    for i,count in enumerate(frames):
        ident=f'shot-{i:03}'
        shutil.copyfile(root/'source.mp4',folder/(ident+'.mp4'))
        shots.append({'shot_id':ident,'scene_index':0,'duration_seconds':5})
        clips[ident]={'file':ident+'.mp4','report':{'duration':5}}
        segments.append({'shot_id':ident,'source_in_frame':0,'frames':count,'transition':transitions[i],
            'transition_frames':12,'title':f'Teknik kontrol {i+1}','reason':'Sentetik kaynakla bileşen ve geçiş sınırlarını denetler.',
            'design':{'camera':{'kind':['locked','push_in','pan_left'][i%3],'strength':.05},
                'layout':'inset' if i==2 else 'split' if i==4 else 'full',
                'secondary_shot_id':'shot-000' if i in (2,4) else None,
                'typography':['rise','words','characters','mask'][i%4],
                'lighting':['none','glow','sweep','gradient'][i%4],'particles':8 if i==3 else 0}})
    decision=AutoEditPlan(observations=[{'shot_id':s['shot_id'],'verdict':'pass',
        'observation':'Bu kaynak test için oluşturulmuş sentetik renkli hareket desenidir.'} for s in shots],
        segments=segments,rationale=direction+'; sentetik teknik kabul görüntüsüdür.',creative_direction=direction,
        opening_title='SENTETİK RENDER TESTİ',ending_title='',caption_size=48)
    (folder/'edit-plan.json').write_text(decision.model_dump_json(),encoding='utf-8')
    srt=folder/'captions.srt';srt.write_text('1\n00:00:00,000 --> 00:00:30,000\nSentetik teknik kontrol\n',encoding='utf-8')
    srt.with_suffix('.words.json').write_text(json.dumps({'scenes':[{'duration_seconds':30,'words':[
        {'text':'Sentetik','startMs':0,'endMs':1000},{'text':'teknik','startMs':1000,'endMs':2000},
        {'text':'kontrol','startMs':2000,'endMs':3000}]}]}),encoding='utf-8')
    run=SimpleNamespace(pipeline_version=3,outputs={'_edit_style':'auto','script':{'format':'other','scenes':[{'narration':'Sentetik teknik kontrol'}]},
        'motion':{'mode':'video','plan':{'shots':shots},'clips':clips}})
    project=SimpleNamespace(duration=30,topic='Genel amaçlı sentetik bileşen kabul testi')
    preview=render_production(run,project,folder,[],[root/'voice.wav'],[30],srt,check,None,{},None,{},preview_only=True)
    result=render_production(run,project,folder,[],[root/'voice.wav'],[30],srt,check,None,{},None,{})
    assert result['passed'],result
    assert json.loads((folder/'render-manifest.json').read_text())['version']==2
    media.command([settings().ffmpeg_bin,'-y','-ss','10','-i',folder/'video.mp4','-frames:v','1',folder/'inspection.png'],folder,check)
    reports.append({'profile':name,'preview':preview,'final':result,'video_sha256':file_hash(folder/'video.mp4')})
    (root/'acceptance.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')
    print(name,'passed',flush=True)
print('All synthetic renderer profiles passed.',flush=True)
