"""One finite CPU job creates an offline input bundle; never contains credentials."""
import json
import subprocess
import sys
from pathlib import Path

PACKAGES = ['diffusers==0.35.2', 'transformers==4.56.2', 'accelerate==1.10.1', 'safetensors==0.6.2', 'sentencepiece==0.2.1', 'ftfy==6.3.1', 'imageio==2.37.0', 'imageio-ffmpeg==0.6.0', 'huggingface-hub==0.34.4', 'tokenizers==0.22.0']


def main():
    root = Path('/kaggle/working')
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--quiet', *PACKAGES], check=True)
    wheels = root / 'wheels'
    wheels.mkdir(exist_ok=True)
    subprocess.run([sys.executable, '-m', 'pip', 'download', '--no-deps', '--dest', str(wheels), *PACKAGES], check=True)
    import torch
    from huggingface_hub import hf_hub_download
    from diffusers import LTXImageToVideoPipeline, LTXVideoTransformer3DModel, AutoencoderKLLTXVideo
    from safetensors import safe_open
    checkpoint = hf_hub_download('Lightricks/LTX-Video', 'ltxv-2b-0.9.6-distilled-04-25.safetensors')
    with safe_open(checkpoint, framework='pt', device='cpu') as f:
        configuration = json.loads(f.metadata()['config'])
    transformer = LTXVideoTransformer3DModel.from_single_file(checkpoint, torch_dtype=torch.float16)
    vae = AutoencoderKLLTXVideo.from_single_file(checkpoint, torch_dtype=torch.float16)
    pipe = LTXImageToVideoPipeline.from_pretrained('Lightricks/LTX-Video-0.9.5', transformer=transformer, vae=vae, torch_dtype=torch.float16)
    pipe.save_pretrained(root / 'model', safe_serialization=True)
    (root / 'runtime.json').write_text(json.dumps({'version': 'ltx-096-v1', 'python': list(sys.version_info[:2]), 'packages': PACKAGES, 'scheduler': configuration['scheduler']}))


if __name__ == '__main__':
    main()
