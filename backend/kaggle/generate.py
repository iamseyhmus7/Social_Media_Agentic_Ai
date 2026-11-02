"""Offline image-to-video worker. Outputs are clips + bounded machine-readable report."""
import gc
import hashlib
import json
import math
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path


def stage_model(source, target):
    """Read attached weights sequentially before memory mapping them locally.

    Network-backed input mounts can make safetensors' small page reads very
    slow. Use bounded buffers and scratch storage outside notebook outputs.
    """
    files = sorted(path for path in source.rglob('*') if path.is_file())
    if not files or any(path.is_symlink() for path in files):
        raise RuntimeError('The prepared model must contain regular files.')
    total = sum(path.stat().st_size for path in files)
    target.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(target.parent).free < total + 4 * 1024**3:
        raise RuntimeError('Not enough local scratch space for the model cache.')
    started = time.monotonic()
    print('Sahne: staging model locally', round(total / 2**30, 2), 'GiB', flush=True)
    for source_file in files:
        destination = target / source_file.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + '.partial')
        try:
            with source_file.open('rb') as reader, temporary.open('wb') as writer:
                shutil.copyfileobj(reader, writer, length=8 * 1024**2)
            if temporary.stat().st_size != source_file.stat().st_size:
                raise RuntimeError('The local model copy is incomplete.')
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        if source_file.suffix == '.safetensors':
            print('Sahne: weight staged', str(source_file.relative_to(source)),
                  round(time.monotonic() - started, 1), 'seconds', flush=True)
    print('Sahne: local model ready', round(time.monotonic() - started, 1), 'seconds', flush=True)
    return target


def distilled_scheduler(base, config):
    """Supply the checkpoint schedule through the scheduler, not pipeline kwargs.

    Diffusers 0.35.2's I2V pipeline always supplies its own sigmas to
    retrieve_timesteps, so passing pipeline timesteps raises before sampling.
    """
    steps = 8
    schedule = [1 - i / steps for i in range(steps)]
    if config.get('sampler') == 'LinearQuadratic':
        schedule = [1., .99375, .9875, .98125, .975, .909375, .725, .421875]
    elif config.get('sampler') == 'Constant':
        shift = math.exp(config['shift'])
        schedule = [shift / (shift + (1 / value - 1)) for value in schedule]

    class CheckpointScheduler(base):
        def set_timesteps(self, num_inference_steps=None, device=None, sigmas=None, mu=None, timesteps=None):
            count = num_inference_steps if num_inference_steps is not None else (len(sigmas) if sigmas is not None else 0)
            if count != steps or timesteps is not None:
                raise ValueError('The distilled checkpoint requires its eight-step schedule.')
            return super().set_timesteps(num_inference_steps=steps, device=device,
                                         timesteps=[value * 1000 for value in schedule])

    return CheckpointScheduler(num_train_timesteps=1000, shift=1.0, use_dynamic_shifting=False)


def memory_snapshot():
    import resource
    values={'cpu_peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    for name,path,key in [('cpu_rss_kib','/proc/self/status','VmRSS:'),('host_available_kib','/proc/meminfo','MemAvailable:')]:
        try:
            values[name]=next(int(line.split()[1]) for line in Path(path).read_text().splitlines() if line.startswith(key))
        except (OSError,StopIteration,ValueError):
            pass
    return values


def balanced_shards(shots,count):
    groups=[[] for _ in range(count)]
    costs=[0]*count
    for shot in sorted(shots,key=lambda s:(-s.get('duration_seconds',0),s['shot_id'])):
        index=min(range(count),key=lambda i:(costs[i],i))
        groups[index].append(shot)
        costs[index]+=shot.get('duration_seconds',0)
    return groups


def encode_worker(request,model,gpu_memory):
    import torch
    from transformers import T5EncoderModel,T5Tokenizer
    torch.set_num_threads(2)
    model=Path(model)
    started=time.monotonic()
    tokenizer = T5Tokenizer.from_pretrained(model / 'tokenizer', local_files_only=True)
    offload = Path('/kaggle/temp/sahne-text-offload')
    encoder = T5EncoderModel.from_pretrained(model / 'text_encoder', dtype=torch.float32,
        local_files_only=True, device_map='auto', max_memory={**gpu_memory, 'cpu': '8GiB'},
        offload_folder=str(offload), offload_state_dict=True, low_cpu_mem_usage=True)
    encoder.eval()
    embeddings = {}
    for shot in request['shots']:
        prompt = 'Camera: ' + shot['camera'].replace('_', ' ') + '. ' + shot['motion_prompt'] + '. Continuous natural motion, consistent subject, no cuts, no text.'
        tokens = tokenizer(prompt, padding='max_length', max_length=128, truncation=True, return_tensors='pt')
        tokens = tokens.to(encoder.get_input_embeddings().weight.device)
        with torch.inference_mode():
            embeddings[shot['shot_id']] = (encoder(**tokens).last_hidden_state.cpu(), tokens.attention_mask.cpu())
        print('Sahne: text ready', shot['shot_id'], round(time.monotonic() - started, 1), flush=True)
    del encoder, tokenizer
    gc.collect()
    torch.cuda.empty_cache()
    # Offloaded weights are scratch files, never part of notebook outputs.
    shutil.rmtree(offload, ignore_errors=True)
    embedding_file = Path('/kaggle/temp/sahne-embeddings.pt')
    torch.save(embeddings, embedding_file)
    del embeddings
    gc.collect()


def video_worker(gpu, shots, request, runtime, model, manifest_file, embedding_file, profile, journal, output_dir):
    import torch
    from PIL import Image, ImageOps
    from diffusers import LTXImageToVideoPipeline, FlowMatchEulerDiscreteScheduler
    from diffusers.utils import export_to_video
    import numpy as np
    torch.set_num_threads(2)
    torch.cuda.set_device(gpu)
    result={'clips':{},'errors':{},'memory':memory_snapshot()}
    load_started=time.monotonic()
    path=Path(journal)
    def save():
        temporary=path.with_suffix('.partial')
        temporary.write_text(json.dumps(result))
        temporary.replace(path)
    try:
        pipe=LTXImageToVideoPipeline.from_pretrained(model,text_encoder=None,tokenizer=None,
            torch_dtype=torch.float32,local_files_only=True,low_cpu_mem_usage=True)
        if profile=='dual_fp32_group_v2':
            device=torch.device('cuda',gpu)
            pipe.transformer.enable_group_offload(onload_device=device,offload_device=torch.device('cpu'),
                offload_type='block_level',num_blocks_per_group=2,use_stream=False)
            pipe.vae.to(device)
        elif profile=='dual_fp32_model_v1':
            pipe.enable_model_cpu_offload(gpu_id=gpu)
        else:
            pipe.enable_sequential_cpu_offload(gpu_id=gpu)
        pipe.vae.enable_tiling()
        pipe.vae.use_framewise_decoding=True
        pipe.scheduler=distilled_scheduler(FlowMatchEulerDiscreteScheduler,runtime['scheduler'])
        embeddings=torch.load(embedding_file,map_location='cpu',weights_only=True)
        result['model_load_seconds']=round(time.monotonic()-load_started,3)
        result['memory']=memory_snapshot()
        save()
        for shot in shots:
            ident=shot['shot_id']
            if not __import__('re').fullmatch(r'shot-[0-9]{3}',ident):
                raise ValueError('Invalid shot identifier')
            try:
                started=time.monotonic()
                frames=max(9,min(121,8*math.ceil((math.ceil(shot['duration_seconds']*24)-1)/8)+1))
                image_path=Path(manifest_file).parent/request['images'][shot.get('image_index',shot['scene_index'])]
                if image_path.parent!=Path(manifest_file).parent:
                    raise ValueError('Invalid reference path')
                image=ImageOps.fit(Image.open(image_path).convert('RGB'),(480,832))
                embed,mask=embeddings[ident]
                device=pipe._execution_device
                seed=shot.get('fixed_seed',int(hashlib.sha256((request['run_id']+ident+str(request.get('attempt',0))).encode()).hexdigest()[:8],16))
                torch.manual_seed(seed)
                torch.cuda.reset_peak_memory_stats(gpu)
                print('Sahne: generating',ident,'gpu',gpu,'profile',profile,flush=True)
                phases={}
                def step_done(pipeline,index,timestep,values):
                    if index==7:phases['sample_end']=time.monotonic()
                    return values
                sampling_started=time.monotonic()
                video=pipe(image=image,prompt_embeds=embed.to(device),prompt_attention_mask=mask.to(device),
                    guidance_scale=1.0,num_inference_steps=8,frame_rate=24,width=480,height=832,num_frames=frames,
                    generator=torch.Generator(device=device).manual_seed(seed),decode_timestep=.05,
                    decode_noise_scale=.025,output_type='np',callback_on_step_end=step_done).frames[0]
                inference_end=time.monotonic()
                if not all(np.isfinite(frame).all() for frame in video):
                    raise RuntimeError('Non-finite output')
                target=Path(output_dir)/(ident+'.mp4')
                temporary=target.with_suffix('.partial.mp4')
                export_started=time.monotonic()
                export_to_video(video,str(temporary),fps=24)
                export_seconds=time.monotonic()-export_started
                metadata={'sha256':hashlib.sha256(temporary.read_bytes()).hexdigest(),'seed':seed,
                    'frames':frames,'fps':24,'width':480,'height':832,'gpu':gpu,'profile':profile,
                    'seconds':round(time.monotonic()-started,3),'peak_gpu_bytes':torch.cuda.max_memory_allocated(gpu),
                    'sample_seconds':round(phases.get('sample_end',inference_end)-sampling_started,3),
                    'decode_postprocess_seconds':round(inference_end-phases.get('sample_end',inference_end),3),
                    'export_seconds':round(export_seconds,3),'memory':memory_snapshot(),
                    'peak_reserved_gpu_bytes':torch.cuda.max_memory_reserved(gpu),'finite':True,'pixel_std':float(np.asarray(video)[::8,::8,::8].std())}
                # Commit metadata before the atomic final filename. The parent
                # can recover a completed clip if this process dies immediately
                # after export, without generating that shot for a second time.
                commit=target.with_suffix('.clip.json')
                pending=commit.with_suffix('.partial')
                pending.write_text(json.dumps(metadata));pending.replace(commit)
                temporary.replace(target)
                result['clips'][ident]=metadata
                print('Sahne: clip ready',ident,metadata['seconds'],'seconds',flush=True)
                del video, image, embed, mask
            except Exception as exc:
                result['errors'][ident]=type(exc).__name__
                traceback.print_exc()
                if isinstance(exc,torch.cuda.OutOfMemoryError) or 'out of memory' in str(exc).lower():
                    result['oom']=True
                    break
                if isinstance(exc,ValueError) or 'device type for generator' in str(exc):
                    result['fatal']='inference_configuration'
                    break
            finally:
                torch.cuda.empty_cache()
                save()
    except Exception as exc:
        result['worker_error']=type(exc).__name__
        result['oom']='out of memory' in str(exc).lower()
        traceback.print_exc()
    finally:
        save()


def profile_pass(shots, request, runtime, model, manifest_file, embedding_file, profile, directory, gpu_count):
    import multiprocessing as mp
    directory.mkdir(parents=True,exist_ok=True)
    workers=[]
    count=min(gpu_count,len(shots)) if profile.startswith('dual_') else 1
    assignments=balanced_shards(shots,count)
    print('Sahne: profile',profile,'visible_gpus',gpu_count,'parallel_workers',count,
          'assignments',{gpu:[s['shot_id'] for s in group] for gpu,group in enumerate(assignments)},flush=True)
    started=time.monotonic()
    for gpu in range(count):
        journal=directory/('gpu-'+str(gpu)+'.json')
        process=mp.get_context('spawn').Process(target=video_worker,args=(gpu,assignments[gpu],request,
            runtime,model,manifest_file,embedding_file,profile,str(journal),str(directory)))
        process.start()
        workers.append((process,journal))
    # The parent alone merges results. Each completed clip remains journalled even after OOM.
    clips,errors={},{}
    flags={}
    while workers:
        for process,journal in list(workers):
            process.join(timeout=.5)
            if journal.is_file():
                data=json.loads(journal.read_text())
                clips.update(data['clips']);errors.update(data['errors'])
                flags.update({k:data[k] for k in ('oom','fatal','worker_error') if data.get(k)})
                flags.setdefault('worker_diagnostics',{})[str(process.pid)]={k:data[k] for k in ('memory','model_load_seconds') if k in data}
            if not process.is_alive():
                workers.remove((process,journal))
                if process.exitcode:
                    flags['worker_error']='exit_'+str(process.exitcode)
        clips.update(committed_clips(directory, shots, clips))
        snapshot={'run_id':request['run_id'],'revision':request['revision'],'clips':clips,'errors':errors,
                  'runtime':{'dtype':'float32','steps':8,'profile':profile,'worker_count':count,
                             'gpu_assignments':{str(gpu):[s['shot_id'] for s in group] for gpu,group in enumerate(assignments)}},**flags}
        target=directory/'result.json'
        temporary=target.with_suffix('.partial');temporary.write_text(json.dumps(snapshot));temporary.replace(target)
    return {**snapshot,'wall_seconds':round(time.monotonic()-started,3)}


def committed_clips(directory, shots, known=()):
    clips={}
    for shot in shots:
        ident=shot['shot_id']
        if ident in known:
            continue
        target=directory/(ident+'.mp4')
        commit=directory/(ident+'.clip.json')
        if not target.is_file() or not commit.is_file():
            continue
        metadata=json.loads(commit.read_text())
        if hashlib.sha256(target.read_bytes()).hexdigest()==metadata.get('sha256'):
            clips[ident]=metadata
    return clips


def run_profiles(request,runtime,model,manifest_file,embedding_file):
    import torch
    out=Path('/kaggle/working')
    shots=request['shots']
    gpu_count=torch.cuda.device_count()
    if request.get('benchmark'):
        # One bounded job, exactly two fixed seeds per profile and no retry generation.
        if len(shots)!=2 or any(s['duration_seconds']>5 or 'fixed_seed' not in s for s in shots):
            raise ValueError('Benchmark permits two short fixed-seed shots only')
        profiles={}
        for name in ('legacy_fp32',request.get('candidate_profile','dual_fp32_group_v2')):
            if name.startswith('dual') and gpu_count<2:
                profiles[name]={'unavailable':'two_gpus_required'}
                continue
            directory=out/name
            result=profile_pass(shots,request,runtime,model,manifest_file,embedding_file,name,directory,gpu_count)
            profiles[name]=result
            for index,shot in enumerate(shots):
                source=directory/(shot['shot_id']+'.mp4')
                if source.is_file():
                    shutil.copyfile(source,out/('shot-'+str(index+(0 if name=='legacy_fp32' else 2)).zfill(3)+'.mp4'))
        result={'run_id':request['run_id'],'revision':request['revision'],'benchmark':True,'profiles':profiles,
                'runtime':{'gpu_count':gpu_count,'dtype':'float32','steps':8,'text_seconds':request['text_seconds']}}
    else:
        profile=request.get('profile','legacy_fp32')
        if profile not in ('legacy_fp32','dual_fp32_model_v1','dual_fp32_group_v2','dual_fp32_sequential_v1'):
            raise ValueError('Unknown GPU profile')
        if profile.startswith('dual_') and gpu_count<2:
            if profile=='dual_fp32_sequential_v1':
                raise RuntimeError('Two GPUs required by parallel policy; refusing silent single-GPU execution.')
            profile='legacy_fp32'
        result=profile_pass(shots,request,runtime,model,manifest_file,embedding_file,profile,out,gpu_count)
        if profile not in ('legacy_fp32','dual_fp32_sequential_v1') and (result.get('oom') or result.get('worker_error')):
            missing=[s for s in shots if s['shot_id'] not in result['clips']]
            if missing:
                fallback=profile_pass(missing,request,runtime,model,manifest_file,embedding_file,'legacy_fp32',out/'fallback',1)
                for ident in fallback['clips']:
                    shutil.copyfile(out/'fallback'/(ident+'.mp4'),out/(ident+'.mp4'))
                result['clips'].update(fallback['clips'])
                result['errors']={k:v for k,v in {**result['errors'],**fallback['errors']}.items() if k not in result['clips']}
                result['fallback']=fallback
        result['runtime'].update(gpu_count=gpu_count,text_seconds=request['text_seconds'])
    (out/'result.json').write_text(json.dumps(result))


def main():
    started = time.monotonic()
    inputs = Path('/kaggle/input')
    runtime_file = next(inputs.rglob('runtime.json'))
    runtime = json.loads(runtime_file.read_text())
    if runtime['version'] != 'ltx-096-v1' or runtime['python'] != list(sys.version_info[:2]):
        raise RuntimeError('Runtime ABI mismatch; prepare a new runtime version.')
    wheels = runtime_file.parent / 'wheels'
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--quiet', '--no-index', '--no-deps', '--find-links', str(wheels), *runtime['packages']], check=True)
    import torch
    from PIL import Image, ImageOps
    from transformers import T5EncoderModel, T5Tokenizer
    from diffusers import LTXImageToVideoPipeline, FlowMatchEulerDiscreteScheduler
    from diffusers.utils import export_to_video
    scheduler = distilled_scheduler(FlowMatchEulerDiscreteScheduler, runtime['scheduler'])
    # Check this before loading any weights or spending GPU time on encoding.
    from diffusers.pipelines.ltx.pipeline_ltx_image2video import retrieve_timesteps
    retrieve_timesteps(scheduler, 8, 'cpu', sigmas=[1 - i / 8 for i in range(8)])
    manifest_file = next(inputs.rglob('manifest.json'))
    request = json.loads(manifest_file.read_text())
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA GPU was not allocated.')
    # The timestep-conditioned VAE also draws noise directly on CUDA. A CPU
    # generator works for initial randn_tensor, but fails during final decode.
    torch.randn((1,), device='cuda:0', generator=torch.Generator(device='cuda:0').manual_seed(0))
    # A full FP32 T5-XXL exceeds the host RAM of a T4 notebook. Bound host
    # memory, distribute its layers across available GPUs, and spill to disk.
    # Text encoding still finishes and frees all GPUs before video inference.
    gpu_memory = {i: f'{max(1, int(torch.cuda.get_device_properties(i).total_memory / 2**30) - 3)}GiB'
                  for i in range(torch.cuda.device_count())}
    model = stage_model(runtime_file.parent / 'model', Path('/kaggle/temp/sahne-model'))
    import multiprocessing as mp
    text_started=time.monotonic()
    process=mp.get_context('spawn').Process(target=encode_worker,args=(request,str(model),gpu_memory))
    process.start();process.join()
    if process.exitcode:
        raise RuntimeError('Text encoder process failed: '+str(process.exitcode))
    embedding_file=Path('/kaggle/temp/sahne-embeddings.pt')
    request['text_seconds']=round(time.monotonic()-started,2)
    request['text_encoder_seconds']=round(time.monotonic()-text_started,2)
    run_profiles(request, runtime, str(model), str(manifest_file), str(embedding_file))


if __name__ == '__main__':
    main()
