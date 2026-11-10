"""Pinned FastWan weights, native Wan22 image conditioning and DMD sampling.

Key conversion reverses Diffusers' convert_wan_to_diffusers.py. DMD follows
FastVideo's denoising stage: predict clean latent, re-noise, repeat; not Euler.
"""
import math


def native_key(key):
    prefixes = {
        'condition_embedder.time_embedder.linear_1': 'time_embedding.0',
        'condition_embedder.time_embedder.linear_2': 'time_embedding.2',
        'condition_embedder.text_embedder.linear_1': 'text_embedding.0',
        'condition_embedder.text_embedder.linear_2': 'text_embedding.2',
        'condition_embedder.time_proj': 'time_projection.1',
        'scale_shift_table': 'head.modulation', 'proj_out': 'head.head',
    }
    for old, new in prefixes.items():
        if key == old or key.startswith(old + '.'):
            return new + key[len(old):]
    replacements = {
        '.attn1.to_q.': '.self_attn.q.', '.attn1.to_k.': '.self_attn.k.',
        '.attn1.to_v.': '.self_attn.v.', '.attn1.to_out.0.': '.self_attn.o.',
        '.attn1.norm_q.': '.self_attn.norm_q.', '.attn1.norm_k.': '.self_attn.norm_k.',
        '.attn2.to_q.': '.cross_attn.q.', '.attn2.to_k.': '.cross_attn.k.',
        '.attn2.to_v.': '.cross_attn.v.', '.attn2.to_out.0.': '.cross_attn.o.',
        '.attn2.norm_q.': '.cross_attn.norm_q.', '.attn2.norm_k.': '.cross_attn.norm_k.',
        '.ffn.net.0.proj.': '.ffn.0.', '.ffn.net.2.': '.ffn.2.',
        '.norm2.': '.norm3.', '.norm3.': '.norm2.',
    }
    for old, new in replacements.items():
        if old in key:
            return key.replace(old, new)
    if key.startswith('blocks.') and key.endswith('.scale_shift_table'):
        return key.removesuffix('scale_shift_table') + 'modulation'
    if key.startswith('patch_embedding.'):
        return key
    raise ValueError('Unknown FastWan checkpoint key: ' + key)


def dmd_sigmas(timesteps, shift=8.0):
    # FastVideo uses nearest entries from the complete shifted training table.
    table = [shift * (i / 1000) / (1 + (shift - 1) * (i / 1000)) for i in range(1000, 0, -1)]
    return [min(table, key=lambda s: abs(s * 1000 - t)) for t in timesteps] + [0.0]


def graph(lock, shot, image, seed, namespace):
    def node(kind, **inputs):
        return {'class_type': kind, 'inputs': inputs}
    seconds = float(shot['duration_seconds'])
    if not 0 < seconds <= lock['max_seconds']:
        raise ValueError('FastWan shot duration is out of bounds')
    length = 4 * math.ceil((math.ceil(seconds * lock['fps']) - 1) / 4) + 1
    prompt = ('Camera: ' + shot['camera'].replace('_', ' ') + '. ' + shot['motion_prompt']
              + '. Preserve the reference subject and setting. Continuous shot, no cuts, no text.')
    return {
        '1': node('UNETLoader', unet_name=lock['model'], weight_dtype='default'),
        '2': node('SahneDMDModel', model=['1', 0]),
        '3': node('SahneCachedText', clip_name=lock['text_encoder'], namespace=namespace, text=prompt),
        '4': node('VAELoader', vae_name=lock['vae']),
        '5': node('LoadImage', image=image),
        '6': node('Wan22ImageToVideoLatent', vae=['4', 0], width=lock['width'], height=lock['height'],
                  length=length, batch_size=1, start_image=['5', 0]),
        '8': node('BasicGuider', model=['2', 0], conditioning=['3', 0]),
        '9': node('RandomNoise', noise_seed=seed),
        '10': node('SahneDMDSampler'),
        '11': node('SamplerCustomAdvanced', noise=['9', 0], guider=['8', 0], sampler=['10', 0],
                   sigmas=['10', 1], latent_image=['6', 0]),
        '12': node('VAEDecodeTiled', samples=['11', 0], vae=['4', 0], tile_size=256, overlap=64,
                   temporal_size=32, temporal_overlap=8),
        '7': node('SaveImage', images=['12', 0], filename_prefix=shot['shot_id']),
    }


BRIDGE = '''
import json
import torch
import comfy.samplers
import comfy.model_sampling
from .fastwan_workflow import dmd_sigmas

TIMESTEPS = [1000, 757, 522]
SIGMAS = dmd_sigmas(TIMESTEPS)

def sample_dmd(model, x, sigmas, extra_args=None, callback=None, disable=None):
    extra_args = extra_args or {}
    generator = torch.Generator(device=x.device).manual_seed(extra_args.get('seed', 0))
    for i in range(len(sigmas) - 1):
        sigma = sigmas[i]
        clean = model(x, sigma * x.new_ones([x.shape[0]]), **extra_args)
        if not torch.isfinite(clean).all():
            raise RuntimeError('FastWan produced non-finite latents; remaining shots stopped')
        if callback:
            callback({'x': x, 'i': i, 'sigma': sigma, 'sigma_hat': sigma, 'denoised': clean})
        print('[Sahne] ' + json.dumps({'event': 'sampling_progress', 'phase': 'fastwan_sampling',
              'value': i + 1, 'total': len(sigmas) - 1}), flush=True)
        next_sigma = sigmas[i + 1]
        if next_sigma > 0:
            noise = torch.randn(x.shape, device=x.device, dtype=clean.dtype, generator=generator)
            x = (1 - next_sigma) * clean + next_sigma * noise
        else:
            x = clean
    return x

class DMDModel:
    @classmethod
    def INPUT_TYPES(cls): return {'required': {'model': ('MODEL',)}}
    RETURN_TYPES = ('MODEL',)
    FUNCTION = 'patch'
    CATEGORY = 'Sahne'
    def patch(self, model):
        class Sampling(comfy.model_sampling.ModelSamplingDiscreteFlow, comfy.model_sampling.CONST):
            def timestep(self, sigma):
                table = sigma.new_tensor(SIGMAS[:-1])
                times = sigma.new_tensor(TIMESTEPS)
                return times[(sigma[..., None] - table).abs().argmin(dim=-1)]
        patched = model.clone()
        sampling = Sampling(model.model.model_config)
        sampling.set_parameters(shift=1.0)
        patched.add_object_patch('model_sampling', sampling)
        return (patched,)

class DMDSampler:
    @classmethod
    def INPUT_TYPES(cls): return {'required': {}}
    RETURN_TYPES = ('SAMPLER', 'SIGMAS')
    FUNCTION = 'create'
    CATEGORY = 'Sahne'
    def create(self):
        return (comfy.samplers.KSAMPLER(sample_dmd), torch.tensor(SIGMAS, dtype=torch.float32))

NODE_CLASS_MAPPINGS = {'SahneDMDModel': DMDModel, 'SahneDMDSampler': DMDSampler}
'''
