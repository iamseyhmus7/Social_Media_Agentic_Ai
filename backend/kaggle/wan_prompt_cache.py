"""Private, versioned conditioning cache; no model objects or unsafe pickle loads."""
import hashlib
import json
import os
import pickle
from pathlib import Path
import time

MAX_CACHE_BYTES = 64 * 1024 * 1024
ENGINE_REVISION = 'wan-gpu-conditioning-v1'


def cache_key(namespace, clip_name, text):
    return hashlib.sha256(json.dumps([ENGINE_REVISION, namespace, clip_name, text],
        ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


class CachedText:
    clip = None
    clip_identity = None

    @classmethod
    def INPUT_TYPES(cls):
        import folder_paths
        return {'required': {'clip_name': (folder_paths.get_filename_list('text_encoders'),),
            'text': ('STRING', {'multiline': True}), 'namespace': ('STRING',)}}

    RETURN_TYPES = ('CONDITIONING',)
    FUNCTION = 'encode'
    CATEGORY = 'Sahne'

    def encode(self, clip_name, text, namespace):
        import torch
        import comfy.sd
        import folder_paths
        started = time.monotonic()
        key = cache_key(namespace, clip_name, text)
        root = Path(os.environ['SAHNE_PROMPT_CACHE'])
        root.mkdir(parents=True, exist_ok=True)
        target = root / ('cond-' + key + '.pt')
        if target.is_file() and 0 < target.stat().st_size <= MAX_CACHE_BYTES:
            try:
                value = torch.load(target, map_location='cpu', weights_only=True)
                if value['key'] == key and isinstance(value['conditioning'], list):
                    print('[Sahne] ' + json.dumps({'event': 'conditioning_cache_hit', 'key': key,
                        'seconds': round(time.monotonic()-started, 3)}), flush=True)
                    return (value['conditioning'],)
            except (OSError, ValueError, RuntimeError, KeyError, TypeError, EOFError, pickle.UnpicklingError):
                pass  # A damaged cache is a miss, never a reason to trust another key.
        if not torch.cuda.is_available():
            raise RuntimeError('Wan text encoding requires CUDA; CPU fallback is disabled')
        device = torch.device('cuda:1' if torch.cuda.device_count() > 1 else 'cuda:0')
        identity = (namespace, clip_name, str(device))
        if type(self).clip_identity != identity:
            type(self).clip = comfy.sd.load_clip(
                ckpt_paths=[folder_paths.get_full_path_or_raise('text_encoders', clip_name)],
                embedding_directory=folder_paths.get_folder_paths('embeddings'),
                clip_type=comfy.sd.CLIPType.WAN,
                model_options={'load_device': device, 'offload_device': torch.device('cpu'),
                    'initial_device': torch.device('cpu')})
            type(self).clip_identity = identity
        clip = type(self).clip
        if clip.patcher.load_device.type != 'cuda':
            raise RuntimeError('Text encoder rejected CUDA; CPU fallback is disabled')
        value = clip.encode_from_tokens_scheduled(clip.tokenize(text))
        def cpu(item):
            if isinstance(item, torch.Tensor): return item.detach().cpu()
            if isinstance(item, dict): return {k: cpu(v) for k, v in item.items()}
            if isinstance(item, list): return [cpu(v) for v in item]
            if isinstance(item, tuple): return tuple(cpu(v) for v in item)
            return item
        value = cpu(value)
        temporary = target.with_suffix('.partial')
        torch.save({'key': key, 'conditioning': value}, temporary)
        if temporary.stat().st_size > MAX_CACHE_BYTES:
            temporary.unlink()
            raise RuntimeError('Conditioning cache exceeds size limit')
        temporary.replace(target)
        print('[Sahne] ' + json.dumps({'event': 'conditioning_encoded', 'key': key,
            'device': str(device), 'seconds': round(time.monotonic()-started, 3)}), flush=True)
        return (value,)
