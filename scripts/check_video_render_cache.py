"""Six local stills verify cold/warm code bundling and private media isolation."""
import json
import os
import shutil
import sys
from pathlib import Path
from backend.app import media
from backend.app.config import settings


def streaming_check():
    """Two synthetic seconds, no model/API/GPU job; compare chunks to one full render."""
    from threading import Event
    from types import SimpleNamespace
    from backend.app.streaming_render import SceneRenderQueue
    from backend.app.schemas import SceneEditDecision,EditLook
    from backend.app.scene_local import compile_local
    from backend.app.remotion_renderer import render_visual
    from backend.app.storage import file_hash
    from PIL import Image
    cfg=settings();check=lambda:None
    folder=cfg.media_root.resolve().parent/'qa-video-speedup/streaming-render'
    public=folder/'render-inputs';public.mkdir(parents=True,exist_ok=True)
    shots=[{'shot_id':f'shot-{i:03}','scene_index':i} for i in range(2)]
    for i in range(2):
        media.command([cfg.ffmpeg_bin,'-y','-f','lavfi','-i',f'testsrc2=size=480x832:rate=24:duration=2',
            '-vf',f'hue=h={i*90}','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p',public/f'shot-{i:03}.mp4'],folder,check)
    run=SimpleNamespace(id=None,outputs={})
    base={'version':2,'style':'auto','duration_frames':60,'sources':[],
        'words':[{'text':'Birinci','startMs':0,'endMs':900},{'text':'İkinci','startMs':1000,'endMs':1900}]}
    look=EditLook(rationale='İki sahne ve tek bir geçişle kare sürekliliği kontrol edilir.').model_dump()
    started=Event();actual=[]
    queue=SceneRenderQueue(run,folder,public,shots,[1,1],base,check)
    original=queue.render_chunk
    def observed(*args):
        actual.append(args[1:5]);started.set()
        return original(*args)
    queue.render_chunk=observed
    decisions=[]
    try:
        for scene in range(2):
            if scene:assert started.wait(5),'Render did not start before the second scene decision'
            decision=SceneEditDecision.model_validate({'reviews':[{'shot_id':f'shot-{scene:03}','verdict':'pass','reason':'Sentetik test kaynağı açıkça tanımlı.'}],
                'segments':[{'shot_id':f'shot-{scene:03}','source_in_frame':0,'duration_weight':1,'transition':'cut' if scene==0 else 'dissolve','transition_frames':12,
                    'reason':'Kare zamanını ve geçişi karşılaştır.'}],
                'graphics':[{'kind':'kinetic_text','scene_index':scene,'start_frame':3,'frames':22,'title':'Birinci' if scene==0 else 'İkinci',
                    'reason':'Metin katmanını aynı global karede karşılaştır.'}]}).model_dump()
            compiled=compile_local(scene,decision,shots,{'shot-000':60,'shot-001':60},[30,30])
            decisions.append((decision,compiled))
            queue.on_scene(scene,look,decision,compiled)
        manifest=queue.partial_manifest()
        queue.finish(manifest)
    finally:queue.close()
    before=file_hash(folder/'visual-edit.mp4')
    resumed=SceneRenderQueue(run,folder,public,shots,[1,1],base,check)
    try:resumed.finish(manifest)
    finally:resumed.close()
    assert before==file_hash(folder/'visual-edit.mp4')
    (folder/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
    render_visual([cfg.node_bin,cfg.remotion_root.resolve()/'production/render.mjs',folder/'manifest.json',public,
        folder/'baseline.mp4',cfg.remotion_browser_executable],folder,check)
    media.command([cfg.ffmpeg_bin,'-i',folder/'visual-edit.mp4','-i',folder/'baseline.mp4','-lavfi','ssim','-f','null','-'],folder,check)
    import re
    match=re.search(r'All:([\d.]+)',(folder/'tool.log').read_text(encoding='utf-8'))
    assert match and float(match.group(1))>.98,'Chunk/full-render visual mismatch'
    media.command([cfg.ffmpeg_bin,'-v','error','-xerror','-i',folder/'visual-edit.mp4','-f','null','-'],folder,check)
    sheet=Image.new('RGB',(1080,480),'#111419')
    for i,frame in enumerate((0,28,34,59)):
        path=folder/f'frame-{frame}.jpg'
        media.command([cfg.ffmpeg_bin,'-y','-i',folder/'visual-edit.mp4','-vf',f'select=eq(n\\,{frame}),scale=270:480','-frames:v','1',path],folder,check)
        with Image.open(path) as picture:sheet.paste(picture,(i*270,0))
    sheet.save(folder/'comparison.jpg')
    result={'render_started_before_scene_2':started.is_set(),'range_jobs':actual,'frames':60,'fps':30,'width':1080,'height':1920,
        'resume_reused_encoded_video':True,'ssim_against_full_render':float(match.group(1)),'full_decode':True}
    (folder/'acceptance.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))


def main():
    root=settings().media_root.resolve().parent
    fixture=root/'qa-agentic-v3/render/premium'
    output=root/'qa-video-speedup/render'
    output.mkdir(parents=True,exist_ok=True)
    public=output/'render-inputs'
    shutil.copytree(fixture/'render-inputs',public,dirs_exist_ok=True)
    manifest=output/'render-manifest.json'
    shutil.copyfile(fixture/'render-manifest.json',manifest)
    frames=[15,129,135]
    (output/'preview-request.json').write_text(json.dumps(frames))
    results=[]
    for index in range(2):
        target=output/f'frames-{index}.json'
        media.command([settings().node_bin,settings().remotion_root.resolve()/'production/render.mjs',
            manifest,public,target,settings().remotion_browser_executable,'preview_frames'],output,lambda:None,timeout=600)
        results.append(json.loads((output/'render-metrics.json').read_text()))
        assert [i['frame'] for i in json.loads(target.read_text())]==frames
    assert results[1]['cache_hit'] is True
    cache=Path(os.environ.get('REMOTION_BUNDLE_CACHE','/tmp/sahne-remotion-bundles'))/results[1]['bundle_key']
    assert cache.is_dir()
    assert not list(cache.rglob('*.mp4')), 'Shared bundle must not contain private footage'
    assert not list(cache.rglob('*.png')), 'Shared bundle must not contain private pictures'
    from PIL import Image
    for frame in frames:
        with Image.open(output/f'preview-{frame:05}.jpg') as image:
            assert image.size==(1080,1920)
    windows=[{'start_frame':120,'end_frame':140}]
    (output/'preview-windows-request.json').write_text(json.dumps(windows))
    motion=output/'transition-check.mp4'
    media.command([settings().node_bin,settings().remotion_root.resolve()/'production/render.mjs',
        manifest,public,motion,settings().remotion_browser_executable,'preview_windows'],output,lambda:None,timeout=600)
    media.command([settings().ffprobe_bin,'-v','quiet','-show_streams','-print_format','json',motion],output,lambda:None)
    stream=json.loads((output/'tool.log').read_text())['streams'][0]
    assert int(stream['nb_frames'])==21 and stream['avg_frame_rate']=='30/1'
    assert (stream['width'],stream['height'])==(1080,1920)
    media.command([settings().ffmpeg_bin,'-v','error','-xerror','-i',motion,'-f','null','-'],output,lambda:None)
    (output/'acceptance.json').write_text(json.dumps(results,indent=2))
    print(json.dumps({'cold':results[0],'warm':results[1],'private_media_isolated':True}))


if __name__=='__main__':
    streaming_check() if '--streaming' in sys.argv else main()
