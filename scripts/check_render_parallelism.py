"""Compare actual frame rendering at bounded concurrency on the same local fixture."""
import json
import shutil
from pathlib import Path
from backend.app import media
from backend.app.config import settings


def main():
    cfg=settings()
    fixture=cfg.media_root.resolve().parent/'qa-agentic-v3/render/premium'
    root=cfg.media_root.resolve().parent/'qa-video-speedup/render-concurrency'
    root.mkdir(parents=True,exist_ok=True)
    reports=[]
    for concurrency in (2,3,4):
        folder=root/str(concurrency);folder.mkdir(exist_ok=True)
        target=folder/'visual.mp4'
        media.command([cfg.node_bin,cfg.remotion_root.resolve()/'production/render.mjs',
            fixture/'render-manifest.json',fixture/'render-inputs',target,cfg.remotion_browser_executable,
            'final',str(concurrency)],folder,lambda:None,timeout=600)
        metric=json.loads((folder/'render-metrics.json').read_text())
        media.command([cfg.ffprobe_bin,'-v','quiet','-show_streams','-print_format','json',target],folder,lambda:None)
        stream=json.loads((folder/'tool.log').read_text())['streams'][0]
        assert (stream['width'],stream['height'],stream['avg_frame_rate'],int(stream['nb_frames']))==(1080,1920,'30/1',900)
        media.command([cfg.ffmpeg_bin,'-v','error','-xerror','-i',target,'-f','null','-'],folder,lambda:None)
        assert metric['rendered_frames']==900 and metric['encoded_frames']==900
        reports.append(metric)
        (root/'acceptance.json').write_text(json.dumps(reports,indent=2))
    best=min(reports,key=lambda r:r['render_seconds'])
    baseline=reports[0]['render_seconds']
    # Only change production if the same output/workload shows a useful gain.
    chosen=best['concurrency'] if best['render_seconds']<=baseline*.9 else 2
    print(json.dumps({'selected_concurrency':chosen,'reports':reports}))


if __name__=='__main__':main()
