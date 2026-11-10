"""Trusted API graphs; two requests ensure only one expert is resident.

Only pinned optional acceleration LoRAs; no generated code or GPU memory pooling.
"""
import math
import hashlib
import json


def frames_for(seconds):
    if not 0<float(seconds)<=5:
        raise ValueError('Wan shots must be at most five seconds')
    return 4*math.ceil((math.ceil(seconds*24)-1)/4)+1


def graphs(lock, shot, image, seed, acceleration=None):
    sampling=acceleration or lock
    def node(kind, **inputs):
        return {'class_type':kind,'inputs':inputs}
    def model(filename):
        return node('UnetLoaderGGUFAdvanced',unet_name=filename,
                    dequant_dtype='float16',patch_dtype='float16',patch_on_device=bool(acceleration))
    def sample(model_id,positive,negative,latent,high):
        return node('KSamplerAdvanced',model=[model_id,0],positive=positive,negative=negative,
            latent_image=latent,noise_seed=seed,steps=sampling['steps'],cfg=sampling['cfg'],
            sampler_name='euler',scheduler='simple',add_noise='enable' if high else 'disable',
            start_at_step=0 if high else sampling['switch_step'],
            end_at_step=sampling['switch_step'] if high else sampling['steps'],
            return_with_leftover_noise='enable' if high else 'disable')
    prompt = ('Camera: '+shot['camera'].replace('_',' ')+'. '+shot['motion_prompt']+
        '. Preserve the reference subject and setting. Continuous shot, no cuts, no text.')
    namespace = hashlib.sha256(json.dumps(lock, sort_keys=True).encode()).hexdigest()
    high = {
        '1':model(lock['high']),
        '2':node('ModelSamplingSD3',model=['1',0],shift=sampling['shift']),
        '4':node('SahneCachedText',clip_name=lock['text_encoder'],namespace=namespace,text=prompt),
        '5':node('SahneCachedText',clip_name=lock['text_encoder'],namespace=namespace,text='text, watermark, deformed anatomy, duplicated subjects, static frozen image, flickering'),
        '6':node('VAELoader',vae_name=lock['vae']),
        '7':node('LoadImage',image=image),
        '8':node('WanImageToVideo',positive=['4',0],negative=['5',0],vae=['6',0],
            width=480,height=832,length=frames_for(shot['duration_seconds']),batch_size=1,start_image=['7',0]),
        '9':sample('2',['8',0],['8',1],['8',2],True),
        '10':node('SahneStoreState',positive=['8',0],negative=['8',1],latent=['9',0]),
    }
    low = {
        '1':model(lock['low']),
        '2':node('ModelSamplingSD3',model=['1',0],shift=sampling['shift']),
        '3':node('SahneLoadState'),
        '4':sample('2',['3',0],['3',1],['3',2],False),
        '5':node('VAELoader',vae_name=lock['vae']),
        '6':node('VAEDecodeTiled',samples=['4',0],vae=['5',0],tile_size=256,overlap=64,
            temporal_size=32,temporal_overlap=8),
        '7':node('SaveImage',images=['6',0],filename_prefix=shot['shot_id']),
    }
    if acceleration:
        high['11']=node('LoraLoaderModelOnly',model=['1',0],lora_name=acceleration['high'],strength_model=acceleration['strength'])
        high['2']['inputs']['model']=['11',0]
        low['8']=node('LoraLoaderModelOnly',model=['1',0],lora_name=acceleration['low'],strength_model=acceleration['strength'])
        low['2']['inputs']['model']=['8',0]
    return high,low


# ComfyUI executes only this local trusted bridge. Only conditioning/latents
# survive /free between expert stages; model objects never enter this store.
BRIDGE = '''
import torch
from .prompt_cache import CachedText
state = None
def cpu(value):
    if isinstance(value,torch.Tensor): return value.detach().cpu()
    if isinstance(value,dict): return {k:cpu(v) for k,v in value.items()}
    if isinstance(value,list): return [cpu(v) for v in value]
    if isinstance(value,tuple): return tuple(cpu(v) for v in value)
    return value
class Store:
    @classmethod
    def INPUT_TYPES(cls): return {"required":{"positive":("CONDITIONING",),"negative":("CONDITIONING",),"latent":("LATENT",)}}
    RETURN_TYPES=()
    FUNCTION="save"
    OUTPUT_NODE=True
    CATEGORY="Sahne"
    def save(self,positive,negative,latent):
        global state
        state=cpu((positive,negative,latent))
        return ()
class Load:
    @classmethod
    def INPUT_TYPES(cls): return {"required":{}}
    RETURN_TYPES=("CONDITIONING","CONDITIONING","LATENT")
    FUNCTION="load"
    CATEGORY="Sahne"
    @classmethod
    def IS_CHANGED(cls): return float("nan")
    def load(self):
        if state is None: raise RuntimeError("Missing high-noise state")
        return state
NODE_CLASS_MAPPINGS={"SahneStoreState":Store,"SahneLoadState":Load,"SahneCachedText":CachedText}
'''
