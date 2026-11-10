"""Finite CPU-only preparation, sharded to respect notebook output disk limits."""
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(8*1024*1024),b''): h.update(chunk)
    return h.hexdigest()


def main():
    from wan_diagnostics import Diagnostics
    root=Path('/kaggle/working')
    diagnostic=Diagnostics(root)
    here=Path(globals().get('SAHNE_SOURCE_DIR',str(Path(__file__).resolve().parent)))
    lock=json.loads((here/'wan_runtime_lock.json').read_text())
    part=json.loads((here/'wan-bootstrap.json').read_text())['component']
    diagnostic.set_phase('bootstrap_start',component=part)
    if part not in ('core','high','low','lightning4','fastwan5b'):
        raise RuntimeError('Invalid runtime component')
    if shutil.disk_usage(root).free<13*2**30:
        raise RuntimeError('Not enough disk for this CPU runtime component')
    subprocess.run([sys.executable,'-m','pip','install','huggingface-hub==0.34.4'],check=True)
    def download(repo,filename,revision,target):
        # Stream directly to output, avoiding an extra 10+GB hub cache copy.
        import urllib.request
        from huggingface_hub import hf_hub_url
        target.parent.mkdir(parents=True,exist_ok=True)
        metadata=__import__('huggingface_hub').get_hf_file_metadata(hf_hub_url(repo,filename,revision=revision))
        diagnostic.set_phase('model_download',component=part,filename=filename,bytes=metadata.size)
        if not metadata.size or shutil.disk_usage(root).free<metadata.size+512*1024**2:
            raise RuntimeError('Model file exceeds available CPU output disk')
        with urllib.request.urlopen(metadata.location,timeout=120) as src,target.open('wb') as dst:
            shutil.copyfileobj(src,dst,length=8*1024*1024)
        if target.stat().st_size!=metadata.size:
            raise RuntimeError('Incomplete model download')
        if len(metadata.etag.strip('"'))==64 and sha(target)!=metadata.etag.strip('"'):
            raise RuntimeError('Model checksum mismatch')
        diagnostic.emit('download_done',filename=filename,bytes=target.stat().st_size)
    if part=='fastwan5b':
        from fastwan_workflow import native_key
        import torch
        from safetensors import safe_open
        from safetensors.torch import save_file
        fast=json.loads((here/'fastwan_runtime_lock.json').read_text())
        source=Path('/kaggle/temp/fastwan-source.safetensors')
        download(fast['repository'],fast['transformer'],fast['revision'],source)
        diagnostic.set_phase('model_conversion',component=part)
        tensors={}
        with safe_open(source,framework='pt',device='cpu') as weights:
            for key in weights.keys():
                value=weights.get_tensor(key).to(torch.float16)
                if not torch.isfinite(value).all():
                    raise RuntimeError('Checkpoint weights cannot be represented safely in FP16')
                mapped=native_key(key)
                if mapped in tensors:raise RuntimeError('Checkpoint key collision')
                tensors[mapped]=value
        if tensors['patch_embedding.weight'].shape[1]!=48 or len({k.split('.')[1] for k in tensors if k.startswith('blocks.')})!=30:
            raise RuntimeError('Unexpected FastWan architecture')
        save_file(tensors,str(root/fast['model']))
        del tensors
        source.unlink()
        download(fast['vae_repository'],'split_files/vae/'+fast['vae'],fast['vae_revision'],root/fast['vae'])
        shutil.copyfile(here/'fastwan_runtime_lock.json',root/'fastwan_runtime_lock.json')
    elif part=='lightning4':
        speed=json.loads((here/'wan_acceleration_lock.json').read_text())
        for expert in ('high','low'):
            download(speed['repository'],speed['source_directory']+'/'+expert+'_noise_model.safetensors',
                speed['revision'],root/speed[expert])
            if sha(root/speed[expert])!=speed[expert+'_sha256']:
                raise RuntimeError('Acceleration model checksum mismatch')
        shutil.copyfile(here/'wan_acceleration_lock.json',root/'wan_acceleration_lock.json')
    elif part in ('high','low'):
        download('QuantStack/Wan2.2-I2V-A14B-GGUF',
            ('HighNoise/' if part=='high' else 'LowNoise/')+lock[part],lock['gguf_revision'],root/lock[part])
    else:
        comfy=root/'ComfyUI'
        def checkout(url,revision,target):
            subprocess.run(['git','init',str(target)],check=True)
            subprocess.run(['git','-C',str(target),'fetch','--depth','1',url,revision],check=True)
            subprocess.run(['git','-C',str(target),'checkout','--detach','FETCH_HEAD'],check=True)
            measured=subprocess.check_output(['git','-C',str(target),'rev-parse','HEAD'],text=True).strip()
            if measured!=revision: raise RuntimeError('Source revision mismatch')
        checkout('https://github.com/Comfy-Org/ComfyUI.git',lock['comfy_commit'],comfy)
        plugin=comfy/'custom_nodes'/'ComfyUI-GGUF'
        checkout('https://github.com/city96/ComfyUI-GGUF.git',lock['gguf_commit'],plugin)
        constraints=root/'constraints.txt'
        constraints.write_text('torch==2.8.0\ntorchvision==0.23.0\ntorchaudio==2.8.0\nnumpy==2.2.6\n')
        wheels=root/'wheels';wheels.mkdir()
        subprocess.run([sys.executable,'-m','pip','download','--only-binary=:all:',
            '--dest',str(wheels),'-c',str(constraints),'-r',str(comfy/'requirements.txt'),
            '-r',str(plugin/'requirements.txt'),'huggingface-hub==0.34.4',
            'torch==2.8.0','torchvision==0.23.0','torchaudio==2.8.0'],check=True)
        download('Comfy-Org/Wan_2.1_ComfyUI_repackaged','split_files/text_encoders/'+lock['text_encoder'],
            lock['wan21_revision'],root/lock['text_encoder'])
        download('Comfy-Org/Wan_2.2_ComfyUI_Repackaged','split_files/vae/'+lock['vae'],
            lock['wan22_revision'],root/lock['vae'])
        # Git metadata is unnecessary at inference and consumes output disk.
        for path in (comfy/'.git',plugin/'.git'):
            if path.resolve().is_relative_to(root.resolve()): shutil.rmtree(path)
    shutil.copyfile(here/'wan_runtime_lock.json',root/'wan_runtime_lock.json')
    diagnostic.set_phase('bootstrap_manifest',component=part)
    files={p.relative_to(root).as_posix():{'sha256':sha(p),'size':p.stat().st_size}
        for p in root.rglob('*') if p.is_file() and p.name not in ('wan-runtime.json','wan-component.json')}
    manifest={'version':lock['version'],'component':part,'python':list(sys.version_info[:2]),
        'lock_sha256':sha(root/'wan_runtime_lock.json'),'files':files}
    if part=='fastwan5b':manifest['fastwan_lock_sha256']=sha(root/'fastwan_runtime_lock.json')
    if part=='lightning4':manifest['acceleration_sha256']=sha(root/'wan_acceleration_lock.json')
    name='wan-runtime.json' if part=='core' else 'wan-component.json'
    (root/name).write_text(json.dumps(manifest))
    diagnostic.emit('package_ready',component=part,file_count=len(files),bytes=sum(f['size'] for f in files.values()))


if __name__=='__main__': main()
