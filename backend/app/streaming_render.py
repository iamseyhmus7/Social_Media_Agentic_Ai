"""Render stable scene interiors while the editor plans the remaining scenes.

Only the first 18 frames of a non-opening scene depend on its predecessor.
Unresolved scenes are private placeholders and are never allowed in a rendered range.
"""
import json
import shutil
from copy import deepcopy
from contextvars import copy_context
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from PIL import Image
from .config import settings
from .storage import file_hash
from .schemas import RenderManifest
from .automatic_edit import scene_frames
from .editorial_graphics import compile_cues
from .planned_edit import digest
from .preview import renderer_hash
from .parallel_work import editor_progress
from .scene_edit import atomic_json
from . import media


def ranges(budgets):
    cursor=0;result=[]
    for scene,frames in enumerate(budgets):
        prefix=min(18,frames) if scene else 0
        if prefix:result.append((scene,'boundary',cursor,cursor+prefix-1))
        if frames>prefix:result.append((scene,'core',cursor+prefix,cursor+frames-1))
        cursor+=frames
    return result


def visible_signature(manifest,start,end,source_hashes,code_hash):
    visible=[];files=set()
    for clip in manifest['clips']:
        finish=clip['start_frame']+clip['frames']
        if clip['start_frame']<=end and finish+clip.get('handle_frames',0)>start:
            item=deepcopy(clip)
            # An outgoing transition cannot affect any earlier frame in this chunk.
            item['handle_frames']=min(clip.get('handle_frames',0),max(0,end+1-finish))
            visible.append(item)
            files.add(clip['file'])
            if clip.get('secondary_file'):files.add(clip['secondary_file'])
    props={k:v for k,v in manifest.items() if k not in ('clips','graphics','sound_cues')}
    if manifest.get('logo'):files.add(manifest['logo'])
    graphics=[c for c in manifest.get('graphics',[]) if c['start_frame']<=end and c['start_frame']+c['frames']>start]
    return digest({'version':1,'range':[start,end],'props':props,'clips':visible,'graphics':graphics,
        'sources':{name:source_hashes[name] for name in sorted(files)},'renderer':code_hash})


class SceneRenderQueue:
    def __init__(self,run,folder,public,shots,durations,base,check):
        self.run=run;self.folder=folder;self.public=public;self.shots=shots
        self.durations=durations;self.budgets=scene_frames(durations);self.base=base;self.check=check
        self.ready={};self.look=None;self.jobs={};self.closed=False
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='editor-render')
        self.code_hash=renderer_hash()
        self.hashes={p.name:file_hash(p) for p in public.iterdir() if p.is_file()}
        self.parts=folder/'render-parts';self.parts.mkdir(exist_ok=True)
        self.cfg=settings()
        self.source_parts = None
        if run.outputs.get('_edit_only') and run.outputs.get('_edit_source_run'):
            from .db import DB, Run
            from .storage import media_path
            with DB() as db:
                source = db.get(Run, run.outputs['_edit_source_run'])
                if source and source.user_id == run.user_id and source.project_id == run.project_id:
                    self.source_parts = media_path(f'{source.project_id}/{source.id}/render-parts')

    def partial_manifest(self):
        clips=[];cursor=0;graphics=[];sounds=[]
        for scene,budget in enumerate(self.budgets):
            if scene in self.ready:
                decision,compiled=self.ready[scene]
                graphics+=decision['graphics'];sounds+=decision['sound_cues']
                for segment in compiled:
                    clip={k:deepcopy(segment[k]) for k in ('source_in_frame','frames','transition','transition_frames','title','punch_in','design')}
                    clip.update(file=segment['shot_id']+'.mp4',kind='clip',scene_index=scene,start_frame=cursor)
                    secondary=segment.get('design',{}).get('secondary_shot_id')
                    if secondary:clip.update(secondary_file=secondary+'.mp4',secondary_source_in_frame=segment['source_in_frame'])
                    clips.append(clip);cursor+=segment['frames']
            else:
                ident=next(s['shot_id'] for s in self.shots if s['scene_index']==scene)
                name=ident+'.png';path=self.public/name
                if not path.exists():Image.new('RGB',(2,2),'black').save(path)
                self.hashes[name]=file_hash(path)
                clips.append({'file':name,'kind':'image','scene_index':scene,'start_frame':cursor,'frames':budget,'transition':'cut','transition_frames':3})
                cursor+=budget
        for index,clip in enumerate(clips):
            following=clips[index+1] if index+1<len(clips) else None
            clip['handle_frames']=following['transition_frames'] if following and following['transition']!='cut' else 0
        absolute_graphics,absolute_sounds=compile_cues({'graphics':graphics,'sound_cues':sounds},self.durations,self.base['sources'])
        allowed={k:v for k,v in self.look.items() if k in RenderManifest.model_fields}
        return RenderManifest.model_validate({**self.base,**allowed,'clips':clips,'graphics':absolute_graphics,'sound_cues':absolute_sounds},
            context={'verified_media_files':[s['shot_id']+'.mp4' for s in self.shots]}).model_dump()

    def on_scene(self,scene,look,decision,compiled):
        self.check()
        self.look=deepcopy(look);self.ready[scene]=(deepcopy(decision),deepcopy(compiled))
        manifest=self.partial_manifest()
        for owner,part,start,end in ranges(self.budgets):
            if owner not in self.ready:continue
            if part=='boundary' and owner-1 not in self.ready:continue
            self.submit(owner,part,start,end,manifest)

    def submit(self,scene,part,start,end,manifest):
        self.check()
        key=visible_signature(manifest,start,end,self.hashes,self.code_hash)
        if key in self.jobs:return
        payload=deepcopy(manifest)
        context=copy_context()
        self.jobs[key]=(scene,part,start,end,self.pool.submit(context.run,self.render_chunk,key,scene,part,start,end,payload))

    def render_chunk(self,key,scene,part,start,end,manifest):
        self.check()
        folder=self.parts/key;folder.mkdir(exist_ok=True)
        output=folder/'video.mp4';receipt=folder/'complete.json'
        if not receipt.is_file() and getattr(self, 'source_parts', None):
            old = self.source_parts/key
            if (old/'complete.json').is_file() and (old/'video.mp4').is_file():
                saved = json.loads((old/'complete.json').read_text(encoding='utf-8'))
                if saved.get('range') == [start,end] and saved.get('sha256') == file_hash(old/'video.mp4'):
                    shutil.copyfile(old/'video.mp4', output)
                    atomic_json(receipt, saved)
        if receipt.is_file() and output.is_file():
            saved=json.loads(receipt.read_text(encoding='utf-8'))
            if saved.get('sha256')==file_hash(output) and saved.get('range')==[start,end]:
                editor_progress(getattr(self.run,'id',None),'render',f'{scene}-{part}','rendered','Önceki parça kullanıldı.',asset_path=output)
                return output
        editor_progress(getattr(self.run,'id',None),'render',f'{scene}-{part}','rendering')
        atomic_json(folder/'manifest.json',manifest)
        atomic_json(folder/'render-range.json',{'start_frame':start,'end_frame':end})
        from .remotion_renderer import render_visual
        try:
            render_visual([self.cfg.node_bin,self.cfg.remotion_root.resolve()/'production/render.mjs',folder/'manifest.json',
                self.public,output,self.cfg.remotion_browser_executable,'chunk'],folder,self.check)
            self.inspect(output,end-start+1,manifest.get('output_fps',30))
            atomic_json(receipt,{'key':key,'range':[start,end],'sha256':file_hash(output),'scene':scene,'part':part})
            editor_progress(getattr(self.run,'id',None),'render',f'{scene}-{part}','rendered',asset_path=output)
            return output
        except Exception as exc:
            editor_progress(getattr(self.run,'id',None),'render',f'{scene}-{part}','retry',
                f'{type(exc).__name__}: {exc} Ayrıntılar: render-parts/{key}/tool.log')
            raise

    def inspect(self,path,frames,output_fps=30):
        media.command([self.cfg.ffprobe_bin,'-v','error','-count_frames','-show_streams','-of','json',path],path.parent,self.check,timeout=120)
        data=json.loads((path.parent/'tool.log').read_text(encoding='utf-8'))
        video=next(v for v in data['streams'] if v['codec_type']=='video')
        if (video['width'],video['height'],video['avg_frame_rate'],int(video['nb_read_frames']))!=(1080,1920,f'{output_fps}/1',frames*output_fps//30):
            raise RuntimeError('Render parçasının çözünürlük/FPS/kare sayısı doğrulanamadı.')

    def finish(self,manifest):
        self.hashes.update({p.name:file_hash(p) for p in self.public.iterdir() if p.is_file()})
        selected=[]
        for scene,part,start,end in ranges(self.budgets):
            key=visible_signature(manifest,start,end,self.hashes,self.code_hash)
            self.submit(scene,part,start,end,manifest)
            selected.append((start,end,key))
        paths=[]
        for start,end,key in selected:
            future=self.jobs[key][-1]
            while not future.done():
                self.check()
                from concurrent.futures import wait
                wait([future],timeout=.25)
            paths.append(future.result())
        output=self.folder/'visual-edit.mp4';marker=self.folder/'visual-parts-complete.json'
        signature=digest({'parts':[(a,b,key,file_hash(path)) for (a,b,key),path in zip(selected,paths)]})
        if marker.is_file() and output.is_file() and json.loads(marker.read_text()).get('signature')==signature:
            if json.loads(marker.read_text()).get('sha256')==file_hash(output):return
        listing=self.folder/'parts-concat.txt'
        listing.write_text('\n'.join("file '"+p.relative_to(self.folder).as_posix()+"'" for p in paths),encoding='utf-8')
        media.command([self.cfg.ffmpeg_bin,'-y','-f','concat','-safe','1','-i',listing.name,'-map','0:v:0','-an','-c:v','copy',
            '-movflags','+faststart',output.name],self.folder,self.check)
        self.inspect(output,manifest['duration_frames'],manifest.get('output_fps',30))
        atomic_json(marker,{'signature':signature,'sha256':file_hash(output),'parts':len(paths),'frames':manifest['duration_frames']})

    def close(self):
        if self.closed:return
        self.closed=True
        self.pool.shutdown(wait=True,cancel_futures=False)
