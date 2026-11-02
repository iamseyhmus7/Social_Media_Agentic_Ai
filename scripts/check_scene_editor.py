"""Replay editing on owned existing clips without running a production graph/GPU job."""
import argparse
import json
import shutil
import time
from copy import deepcopy
from pathlib import Path
from threading import Lock
from backend.app.db import DB,Run
from backend.app.config import settings,use_run_settings
from backend.app.providers import Evren,trace_calls
from backend.app.storage import workdir,file_hash
from backend.app.planned_edit import prepare_decision


def main(run_id):
    with DB() as db:
        source=db.get(Run,run_id)
        if not source or not source.outputs.get('motion',{}).get('clips'):
            raise RuntimeError('A completed owned clip set is required.')
        db.expunge(source)
    original=workdir(source.project_id,source.id)
    folder=settings().media_root.resolve().parent/'qa-video-speedup'/'scene-editor-replay'
    folder.mkdir(parents=True,exist_ok=True)
    source.outputs=deepcopy(source.outputs)
    source.outputs['_config']={**source.outputs.get('_config',{}),'video_edit_policy':'scenes_v3',
        'editor_parallelism':3,'editor_call_timeout_seconds':180}
    hashes={}
    for ident,item in source.outputs['motion']['clips'].items():
        target=folder/(ident+'.mp4')
        expected=file_hash(original/item['file'])
        if not target.is_file() or file_hash(target)!=expected:
            shutil.copyfile(original/item['file'],target)
        item['file']=target.name
        hashes[ident]=expected
    metrics=[];lock=Lock()
    def sink(metric):
        with lock:
            metrics.append(metric)
            (folder/'model-metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2),encoding='utf-8')
    started=time.monotonic()
    try:
        with use_run_settings(source.outputs['_config']),trace_calls(sink):
            shots=source.outputs['motion']['plan']['shots']
            durations=source.outputs['voice']['durations']
            available={s['shot_id']:int(source.outputs['motion']['clips'][s['shot_id']]['report']['duration']*30+.001) for s in shots}
            decision=prepare_decision(source,folder,shots,durations,available,Evren(),lambda:None,[],
                'Mevcut videonun aynı senaryosu',source.outputs.get('_edit_preferences',{}))
        assert all(file_hash(folder/(ident+'.mp4'))==value for ident,value in hashes.items())
        report={'passed':True,'seconds':round(time.monotonic()-started,3),'calls':len(metrics),
            'perception_calls':sum(m['schema']=='ClipPerception' for m in metrics),
            'frames':sum(s['frames'] for s in decision['segments']),
            'scene_checkpoints':len(list((folder/'scene-decisions').glob('*.json')))}
    except Exception as exc:
        report={'passed':False,'seconds':round(time.monotonic()-started,3),'error':str(exc),
                'calls':len(metrics)}
        (folder/'acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        raise
    (folder/'acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('run_id')
    main(parser.parse_args().run_id)
