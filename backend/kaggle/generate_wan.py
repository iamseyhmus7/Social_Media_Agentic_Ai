"""Finite offline Wan job. Each expert runs alone; committed clips survive errors."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(8*1024*1024),b''): h.update(chunk)
    return h.hexdigest()


def emit_preview(path, shot_id):
    """Send a compact playback copy over the private notebook log stream."""
    import base64
    preview = path.with_suffix('.preview.mp4')
    try:
        subprocess.run(['ffmpeg','-y','-v','error','-i',str(path),'-an',
            '-vf','scale=144:-2,fps=12','-c:v','libx264','-preset','veryfast',
            '-b:v','48k','-maxrate','56k','-bufsize','28k','-pix_fmt','yuv420p',
            '-movflags','+faststart',str(preview)],check=True,timeout=30)
        if not 0 < preview.stat().st_size <= 48 * 1024:
            return
        data = preview.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        parts = [data[i:i+2048] for i in range(0,len(data),2048)]
        for index,part in enumerate(parts):
            print('[SahnePreview] '+json.dumps({'shot_id':shot_id,'sha256':digest,
                'index':index,'total':len(parts),'data':base64.b64encode(part).decode('ascii')}),
                flush=True)
    except (OSError,subprocess.SubprocessError):
        pass  # Preview transport cannot fail a committed production clip.
    finally:
        preview.unlink(missing_ok=True)


def verify_manifest(path, expected_lock, diagnostic=None):
    manifest=json.loads(path.read_text())
    if manifest['version']!='wan22-q5-v1' or manifest['lock_sha256']!=expected_lock:
        raise RuntimeError('Runtime lock mismatch')
    if manifest['python']!=list(sys.version_info[:2]):
        raise RuntimeError('Runtime Python ABI mismatch')
    root=path.parent.resolve()
    started=time.monotonic()
    if diagnostic:diagnostic.emit('verify_start',component=manifest.get('component'),file_count=len(manifest['files']),bytes=sum(f['size'] for f in manifest['files'].values()))
    for name,info in manifest['files'].items():
        target=(root/name).resolve()
        if not target.is_relative_to(root) or not target.is_file() or target.stat().st_size!=info['size'] or sha(target)!=info['sha256']:
            raise RuntimeError('Runtime file checksum mismatch')
    if diagnostic:diagnostic.emit('verify_done',component=manifest.get('component'),seconds=round(time.monotonic()-started,2))
    return manifest


def local_model(source, target, diagnostic, expected_hash=None):
    """Sequential reads avoid repeated mmap page faults on attached storage."""
    size = source.stat().st_size
    if shutil.disk_usage(target.parent).free < size + 2 * 1024**3:
        raise RuntimeError('Insufficient local disk for Wan model staging')
    started = time.monotonic()
    temporary = target.with_suffix(target.suffix + '.partial')
    digest = hashlib.sha256()
    with source.open('rb') as src, temporary.open('wb') as dst:
        for chunk in iter(lambda:src.read(8*1024*1024),b''):
            dst.write(chunk)
            digest.update(chunk)
    if temporary.stat().st_size != size or digest.hexdigest() != (expected_hash or sha(source)):
        temporary.unlink(missing_ok=True)
        raise RuntimeError('Local model copy checksum mismatch')
    temporary.replace(target)
    diagnostic.emit('model_staged', filename=target.name, bytes=size,
        seconds=round(time.monotonic()-started, 3))
    return target


def main():
    from wan_workflow import graphs, BRIDGE, frames_for
    from wan_diagnostics import Diagnostics, safe_text
    import urllib.request
    input_root=Path('/kaggle/input')
    output=Path('/kaggle/working')
    here=Path(globals().get('SAHNE_SOURCE_DIR',str(Path(__file__).resolve().parent)))
    lock=json.loads((here/'wan_runtime_lock.json').read_text())
    lock_sha=sha(here/'wan_runtime_lock.json')
    acceleration=json.loads((here/'wan_acceleration_lock.json').read_text())
    acceleration_sha=sha(here/'wan_acceleration_lock.json')
    manifest_file=next(input_root.rglob('wan-request.json'))
    request=json.loads(manifest_file.read_text())
    fast=request.get('runtime')=='fastwan5b-v1'
    core_lock_sha=lock_sha
    if fast:
        lock=json.loads((here/'fastwan_runtime_lock.json').read_text())
        lock_sha=sha(here/'fastwan_runtime_lock.json')
    result={'run_id':request['run_id'],'revision':request['revision'],'clips':{},'errors':{},'runtime':lock['version']}
    result['sampling_profile']=request.get('sampling_profile','standard20')
    def save():
        temp=output/'result.partial'
        temp.write_text(json.dumps(result));temp.replace(output/'result.json')
    server=None;mirror=None
    diagnostic=Diagnostics(output);diagnostic.start()
    try:
        diagnostic.set_phase('input_validation')
        if request.get('runtime')!=lock['version'] or request.get('lock_sha256')!=lock_sha:
            raise RuntimeError('Request runtime mismatch')
        profile=request.get('sampling_profile','standard20')
        if profile not in (('dmd3_v1',) if fast else ('standard20','lightning4_v1')):
            raise RuntimeError('Unsupported sampling profile')
        if profile=='lightning4_v1' and request.get('acceleration_sha256')!=acceleration_sha:
            raise RuntimeError('Acceleration lock mismatch')
        if not 1<=len(request['shots'])<=32:
            raise RuntimeError('Invalid shot count')
        import re
        if any(not re.fullmatch('shot-[0-9]{3}',s['shot_id']) for s in request['shots']):
            raise RuntimeError('Invalid shot ID')
        for shot in request['shots']: frames_for(shot['duration_seconds'])
        for name,expected in zip(request['images'],request['image_hashes'],strict=True):
            path=(manifest_file.parent/name).resolve()
            if path.parent!=manifest_file.parent.resolve() or sha(path)!=expected:
                raise RuntimeError('Input reference checksum mismatch')
        core=next(input_root.rglob('wan-runtime.json'))
        diagnostic.set_phase('runtime_verification')
        core_manifest=verify_manifest(core,core_lock_sha,diagnostic)
        components={}
        component_manifests={}
        for candidate in input_root.rglob('wan-component.json'):
            item=verify_manifest(candidate,core_lock_sha,diagnostic)
            components[item['component']]=candidate.parent
            component_manifests[item['component']]=item
        if fast:
            if 'fastwan5b' not in components or component_manifests['fastwan5b'].get('fastwan_lock_sha256')!=lock_sha:
                raise RuntimeError('Missing or outdated FastWan weights')
        elif not {'high','low'}.issubset(components): raise RuntimeError('Missing expert weights')
        if profile=='lightning4_v1':
            if 'lightning4' not in components or component_manifests['lightning4'].get('acceleration_sha256')!=acceleration_sha:
                raise RuntimeError('Missing or outdated acceleration weights')
        # These checks happen before any model is loaded or sampling is queued.
        ram=os.sysconf('SC_PAGE_SIZE')*os.sysconf('SC_PHYS_PAGES')
        if ram<24*2**30 or shutil.disk_usage('/kaggle/temp').free<14*2**30:
            raise RuntimeError('Insufficient host RAM or scratch disk')
        scratch=Path('/kaggle/temp/sahne-wan');scratch.mkdir()
        comfy=scratch/'ComfyUI'
        diagnostic.set_phase('copy_comfy')
        shutil.copytree(core.parent/'ComfyUI',comfy)
        diagnostic.set_phase('package_install')
        subprocess.run([sys.executable,'-m','pip','install','--quiet','--no-index','--no-compile',
            '--find-links',str(core.parent/'wheels'),'-c',str(core.parent/'constraints.txt'),
            '-r',str(comfy/'requirements.txt'),'-r',str(comfy/'custom_nodes'/'ComfyUI-GGUF'/'requirements.txt'),
            'torch==2.8.0','torchvision==0.23.0','torchaudio==2.8.0'],check=True)
        diagnostic.set_phase('gpu_check')
        import torch
        if not torch.cuda.is_available() or torch.cuda.get_device_properties(0).total_memory<14*2**30:
            raise RuntimeError('GPU memory unavailable')
        for part in (() if fast else ('high','low')):
            dest=comfy/'models'/'unet'/lock[part];dest.parent.mkdir(parents=True,exist_ok=True)
            # Only one expert needs local disk at a time; staged before its graph.
        for kind,name in (('text_encoders',lock['text_encoder']),('vae',lock['vae'])):
            dest=comfy/'models'/kind/name;dest.parent.mkdir(parents=True,exist_ok=True)
            diagnostic.set_phase('stage_'+kind)
            model_root=components['fastwan5b'] if fast and kind=='vae' else core.parent
            model_manifest=component_manifests['fastwan5b'] if fast and kind=='vae' else core_manifest
            local_model(model_root/name,dest,diagnostic,model_manifest['files'][name]['sha256'])
        if fast:
            diagnostic.set_phase('stage_fastwan')
            dest=comfy/'models'/'unet'/lock['model'];dest.parent.mkdir(parents=True,exist_ok=True)
            local_model(components['fastwan5b']/lock['model'],dest,diagnostic,
                component_manifests['fastwan5b']['files'][lock['model']]['sha256'])
        if profile=='lightning4_v1':
            diagnostic.set_phase('stage_acceleration')
            for expert in ('high','low'):
                name=acceleration[expert]
                dest=comfy/'models'/'loras'/name;dest.parent.mkdir(parents=True,exist_ok=True)
                local_model(components['lightning4']/name,dest,diagnostic,acceleration[expert+'_sha256'])
        bridge=comfy/'custom_nodes'/'sahne_bridge';bridge.mkdir()
        if fast:
            from fastwan_workflow import BRIDGE as FAST_BRIDGE
            shutil.copyfile(here/'fastwan_workflow.py',bridge/'fastwan_workflow.py')
            (bridge/'__init__.py').write_text(BRIDGE+'\n'+FAST_BRIDGE+
                '\nNODE_CLASS_MAPPINGS["SahneCachedText"] = CachedText\n')
        else:
            (bridge/'__init__.py').write_text(BRIDGE)
        shutil.copyfile(here/'wan_prompt_cache.py',bridge/'prompt_cache.py')
        cache=output/'conditioning';cache.mkdir(exist_ok=True)
        for item in request.get('conditioning_cache',[]):
            name=item['file']
            if not re.fullmatch(r'cond-[a-f0-9]{64}\.pt',name):
                raise RuntimeError('Invalid conditioning cache name')
            source=manifest_file.parent/name
            if not source.is_file() or not 0<source.stat().st_size<=64*1024**2 or sha(source)!=item['sha256']:
                raise RuntimeError('Conditioning cache checksum mismatch')
            shutil.copyfile(source,cache/name)
        env={**os.environ,'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','PYTHONUNBUFFERED':'1',
            'SAHNE_PROMPT_CACHE':str(cache)}
        diagnostic.set_phase('comfy_start')
        server=subprocess.Popen([sys.executable,str(comfy/'main.py'),'--listen','127.0.0.1','--port','8188',
            '--disable-auto-launch',*(() if fast else ('--cache-none',)),
            '--force-fp16','--fp32-vae' if fast else '--fp16-vae','--use-pytorch-cross-attention'],
            cwd=comfy,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',bufsize=1)
        mirror=diagnostic.mirror(server)
        def api(path,body=None):
            data=None if body is None else json.dumps(body).encode()
            req=urllib.request.Request('http://127.0.0.1:8188'+path,data=data,headers={'Content-Type':'application/json'})
            try:
                with urllib.request.urlopen(req,timeout=30) as response:
                    payload=response.read()
                    return json.loads(payload) if payload else {}
            except urllib.error.HTTPError as exc:
                diagnostic.emit('comfy_api_error',path=path,http_status=exc.code,
                    details=safe_text(exc.read(8192).decode('utf-8',errors='replace')))
                raise
        deadline=time.monotonic()+180
        while True:
            if server.poll() is not None: raise RuntimeError('Comfy startup failed')
            try: api('/system_stats');break
            except OSError:
                if time.monotonic()>deadline: raise RuntimeError('Comfy startup timeout')
                time.sleep(1)
        def execute(graph, phase):
            diagnostic.set_phase(phase)
            diagnostic.graph_nodes={str(key):node['class_type'] for key,node in graph.items()}
            response=api('/prompt',{'prompt':graph,'client_id':'sahne'})
            if response.get('node_errors'): raise RuntimeError('Workflow input validation failed')
            ident=response['prompt_id']
            deadline=time.monotonic()+6500
            while time.monotonic()<deadline:
                if server.poll() is not None: raise RuntimeError('Comfy process exited')
                history=api('/history/'+ident).get(ident)
                if history:
                    if history.get('status',{}).get('status_str')!='success':
                        messages=history.get('status',{}).get('messages',[])
                        for message in messages:
                            if not isinstance(message,(list,tuple)) or len(message)!=2:continue
                            kind,details=message
                            if kind=='execution_error' and isinstance(details,dict):
                                diagnostic.emit('node_error',node_type=details.get('node_type'),exception_type=details.get('exception_type'),
                                    message=safe_text(details.get('exception_message',''),2048))
                        raise RuntimeError('Wan inference failed')
                    return history
                time.sleep(2)
            raise RuntimeError('Wan inference timed out')
        result['runtime_metrics']={'gpu':torch.cuda.get_device_name(0),'host_ram_bytes':ram,'worker_count':1,'dtype':'float16',
            'text_encoder_device':'cuda:1' if torch.cuda.device_count()>1 else 'cuda:0',
            'model_storage':'local_scratch','engine':request['engine'],
            'sampling_profile':profile,'steps':4 if profile=='lightning4_v1' else lock['steps']}
        diagnostic.emit('comfy_ready',**result['runtime_metrics'])
        diagnostic.observe_nodes()
        save()
        for shot in request['shots']:
            started=time.monotonic();ident=shot['shot_id']
            try:
                index=shot['image_index']
                filename=ident+'.png'
                from PIL import Image,ImageOps
                (comfy/'input').mkdir(exist_ok=True)
                ImageOps.fit(Image.open(manifest_file.parent/request['images'][index]).convert('RGB'),(480,832)).save(comfy/'input'/filename)
                seed=int(hashlib.sha256((request['run_id']+ident+request.get('session','')).encode()).hexdigest()[:8],16)
                if fast:
                    from fastwan_workflow import graph
                    history=execute(graph(lock,shot,filename,seed,lock_sha),'fastwan_sampling')
                else:
                    high,low=graphs(lock,shot,filename,seed,acceleration if profile=='lightning4_v1' else None)
                    diagnostic.set_phase('stage_high_expert')
                    high_path=comfy/'models'/'unet'/lock['high']
                    local_model(components['high']/lock['high'],high_path,diagnostic,
                        component_manifests['high']['files'][lock['high']]['sha256'])
                    execute(high,'high_noise_graph')
                    diagnostic.set_phase('expert_unload')
                    api('/free',{'unload_models':True,'free_memory':True})
                    high_path.unlink()
                    diagnostic.set_phase('stage_low_expert')
                    low_path=comfy/'models'/'unet'/lock['low']
                    local_model(components['low']/lock['low'],low_path,diagnostic,
                        component_manifests['low']['files'][lock['low']]['sha256'])
                    history=execute(low,'low_noise_graph_and_decode')
                frames=history['outputs']['7']['images']
                frame_paths=[(comfy/'output'/f.get('subfolder','')/f['filename']).resolve() for f in frames]
                if len(frame_paths)!=frames_for(shot['duration_seconds']) or any(not p.is_relative_to((comfy/'output').resolve()) for p in frame_paths):
                    raise RuntimeError('Unexpected decoded frame output')
                if fast:
                    from PIL import ImageStat
                    contrasts=[]
                    for frame_index in (0,len(frame_paths)//2,len(frame_paths)-1):
                        with Image.open(frame_paths[frame_index]) as frame:
                            contrasts.append(max(ImageStat.Stat(frame.convert('RGB').resize((64,64))).stddev))
                    if max(contrasts)<2.0:
                        raise RuntimeError('FastWan decoded blank frames; remaining shots stopped')
                staging=scratch/'frames';staging.mkdir(exist_ok=True)
                diagnostic.set_phase('video_encoding')
                for i,path in enumerate(frame_paths): shutil.move(str(path),str(staging/f'{i:04}.png'))
                temporary=output/(ident+'.partial.mp4')
                subprocess.run(['ffmpeg','-y','-v','error','-framerate','24','-i',str(staging/'%04d.png'),
                    '-c:v','libx264','-pix_fmt','yuv420p','-crf','18',str(temporary)],check=True)
                subprocess.run(['ffmpeg','-v','error','-i',str(temporary),'-f','null','-'],check=True)
                target=output/(ident+'.mp4');temporary.replace(target)
                result['clips'][ident]={'sha256':sha(target),'seed':seed,'frames':len(frame_paths),
                    'fps':24,'width':480,'height':832,'seconds':round(time.monotonic()-started,3),
                    'profile':'fastwan5b_v1' if fast else 'wan22_q5_v1'}
                result['clips'][ident]['sampling_profile']=profile
                if fast:result['clips'][ident].update(finite=True,pixel_std=round(max(contrasts)/255,5))
                diagnostic.emit('clip_ready',shot_id=ident,
                    completed=request.get('completed_before',0)+len(result['clips']),
                    total=request.get('total_shots',len(request['shots'])),**result['clips'][ident])
                save()
                if request.get('live_previews'):
                    emit_preview(target,ident)
                shutil.rmtree(staging)
                if not fast:
                    api('/free',{'unload_models':True,'free_memory':True})
                    low_path.unlink()
            except Exception as exc:
                result['errors'][ident]='inference_failed'
                result.setdefault('diagnostics',[]).append(diagnostic.failure(exc))
                save()
                break  # Never burn the remaining allocation after a failed clip.
    except Exception as exc:
        result['fatal']='runtime_or_inference_configuration'
        result.setdefault('diagnostics',[]).append(diagnostic.failure(exc))
    finally:
        result['phase_timings']=diagnostic.phase_durations()
        result['conditioning_cache']=[{'file':p.name,'sha256':sha(p)}
            for p in sorted((output/'conditioning').glob('cond-*.pt'))]
        save()
        if server:
            server.terminate()
            try: server.wait(timeout=20)
            except subprocess.TimeoutExpired: server.kill()
        if mirror:mirror.join(timeout=5)
        diagnostic.close()


if __name__=='__main__': main()
