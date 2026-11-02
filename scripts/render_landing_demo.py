"""Render owned concept artwork into silent, pre-rendered landing demo clips.

Run inside the existing media worker with an input/output directory argument.
No model, credentials, external API, or new dependencies are needed.
"""
import json
import subprocess
import sys
from pathlib import Path


def run(*args):
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', *args], check=True)


def render(root: Path):
    examples = json.loads((root / 'examples.json').read_text(encoding='utf-8'))
    font = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    outputs = root / 'output'
    outputs.mkdir(exist_ok=True)
    for example in examples:
        scenes = []
        for index, scene in enumerate(example['scenes']):
            caption = root / f"{example['id']}-{index}.txt"
            caption.write_text(scene['caption'], encoding='utf-8')
            segment = root / f"{example['id']}-{index}.mp4"
            filters = (
                "scale=864:1536:force_original_aspect_ratio=increase,crop=864:1536,"
                "zoompan=z='min(zoom+0.0009,1.1)':x='iw/2-iw/zoom/2':"
                "y='ih/2-ih/zoom/2':d=96:s=540x960:fps=24,"
                "drawbox=x=0:y=650:w=iw:h=310:color=0x21182e@0.50:t=fill,"
                f"drawtext=fontfile={font}:text='SAHNE / ORNEK KONSEPT':"
                "fontsize=15:fontcolor=white@0.85:x=36:y=690,"
                f"drawtext=fontfile={font}:textfile={caption}:"
                "fontsize=30:line_spacing=10:fontcolor=white:x=36:y=738,"
                f"drawtext=fontfile={font}:text='0{index + 1} / 03':"
                "fontsize=15:fontcolor=white@0.8:x=36:y=908,"
                'format=yuv420p'
            )
            run('-i', str(root / (scene['image'] + '.png')), '-vf', filters,
                '-an', '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '24',
                '-threads', '2', '-movflags', '+faststart', str(segment))
            scenes.append(segment)

        for version, duration in [('original', 4), ('short', 3)]:
            inputs = []
            for segment in scenes:
                inputs.extend(['-t', str(duration), '-i', str(segment)])
            run(*inputs, '-filter_complex', '[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]',
                '-map', '[v]', '-an', '-c:v', 'libx264', '-preset', 'fast',
                '-crf', '24', '-threads', '2', '-movflags', '+faststart',
                str(outputs / f"{example['id']}-{version}.mp4"))
        print(f"Rendered {example['id']}: original 12s / short 9s", flush=True)


if __name__ == '__main__':
    render(Path(sys.argv[1]).resolve())
