"""One resumable, private four-clip component check; never invokes the production graph.

Run from the media worker: python scripts/check_video_gpu.py [--visual-checked]
The private job retains the normal account lock and is never resubmitted on polling.
"""
import argparse
import json
import shutil
from pathlib import Path
from uuid import uuid4
from sqlalchemy import select
from backend.app.db import DB, Project, Run, Asset, RemoteJob, now
from backend.app.config import settings, snapshot_settings
from backend.app.storage import media_path, workdir, file_hash
from backend.app.kaggle_provider import stage_job, advance_job, KaggleGateway, RemotePending, RUNTIME_VERSION
from backend.app.gpu_profile import evaluate, certificate_path, PROFILE, PARALLEL_PROFILE
from backend.app import media


def tick(visual_checked=False, label="", seconds=2, candidate_profile=PARALLEL_PROFILE, source_run_id=None):
    root=settings().media_root.resolve().parent/'qa-video-speedup'
    if label:
        if not __import__('re').fullmatch(r'[a-z0-9-]{1,32}',label):raise ValueError('Invalid check label')
        root=root/label
    root.mkdir(parents=True,exist_ok=True)
    marker=root/'gpu-job.json'
    if marker.is_file():
        identity=json.loads(marker.read_text(encoding='utf-8'))
    else:
        with DB() as db:
            if db.scalar(select(RemoteJob.id).where(RemoteJob.account_slot.is_not(None))):
                print('GPU account occupied; no job submitted.')
                return
            source=db.get(Run,source_run_id) if source_run_id else db.scalar(select(Run).where(Run.status=='awaiting_approval').order_by(Run.created.desc()))
            # Choose an existing motion reference, without changing the source project.
            candidates=db.scalars(select(Run).where(Run.project_id==source.project_id).order_by(Run.created.desc())).all() if source else []
            source=next((r for r in candidates if r.outputs.get('motion',{}).get('plan',{}).get('shots') and r.outputs.get('visual',{}).get('images')),None)
            if source is None:
                raise RuntimeError('No existing reference available for the bounded GPU check.')
            shot=source.outputs['motion']['plan']['shots'][0]
            image_id=source.outputs['visual'].get('shot_images',{}).get(shot['shot_id']) or source.outputs['visual']['images'][shot['scene_index']]
            image=db.get(Asset,image_id)
            if not image or image.project_id!=source.project_id or file_hash(media_path(image.path))!=image.sha256:
                raise RuntimeError('Existing reference ownership/hash mismatch.')
            project=Project(id=str(uuid4()),user_id=source.user_id,title='GPU bileşen karşılaştırması',
                topic='Özel kısa GPU profil kontrolü',duration=30)
            db.add(project);db.flush()
            run=Run(id=str(uuid4()),project_id=project.id,user_id=source.user_id,revision=1,pipeline_version=3,
                status='component_check',stage='gpu_check',outputs={'_config':snapshot_settings(),'_component_check':True})
            db.add(run);db.commit()
            folder=workdir(project.id,run.id)
            shutil.copyfile(media_path(image.path),folder/'reference-0.png')
            shots=[{**shot,'shot_id':f'shot-{i:03}','scene_index':0,'image_index':0,
                    'duration_seconds':seconds,'fixed_seed':seed} for i,seed in enumerate((41917,83471))]
            request={'version':1,'run_id':run.id,'revision':1,'images':['reference-0.png'],
                    'image_hashes':[image.sha256],'shots':shots,'benchmark':True,'candidate_profile':candidate_profile}
            identity={'run_id':run.id,'project_id':project.id,'manifest':request,
                      'runtime':settings().kaggle_runtime_source or settings().kaggle_username+'/sahne-'+RUNTIME_VERSION}
            marker.write_text(json.dumps(identity),encoding='utf-8')
    with DB() as db:
        run=db.get(Run,identity['run_id'])
    folder=workdir(run.project_id,run.id)
    try:
        job=stage_job(run,folder,identity['manifest'],runtime_source=identity['runtime'])
        result=job.result if job.status=='complete' else advance_job(job,folder,KaggleGateway())
    except RemotePending:
        print('Bounded GPU check pending; same durable job retained.')
        return
    output=folder/'kaggle'/job.id/'output'
    checks=[]
    for index in range(4):
        clip=output/f'shot-{index:03}.mp4'
        if not clip.is_file():
            checks.append(False)
            continue
        expected=identity['manifest']['shots'][index%2]['duration_seconds']
        report=media.inspect_clip(clip,expected,lambda:None)
        from PIL import Image
        import numpy as np
        samples=[]
        for frame in (6,round(expected*12),round(expected*24)-6):
            target=root/f'gpu-{index}-{frame}.jpg'
            media.command([settings().ffmpeg_bin,'-y','-ss',str(frame/24),'-i',clip,'-frames:v','1',
                '-vf','scale=240:416',target],root,lambda:None,timeout=60)
            samples.append(np.asarray(Image.open(target).convert('RGB'),dtype=float))
        moving=float(np.abs(samples[-1]-samples[0]).mean())>.25
        checks.append(report['decoded'] and moving)
    certificate=evaluate(result,all(checks) and visual_checked,file_hash(folder/'kaggle'/job.id/'run.py'),identity['manifest'].get('candidate_profile',PROFILE))
    (root/'gpu-result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    (root/'gpu-assessment.json').write_text(json.dumps(certificate,indent=2),encoding='utf-8')
    if visual_checked:
        certificate_path().write_text(json.dumps(certificate,indent=2),encoding='utf-8')
        with DB() as db:
            current=db.get(Run,run.id)
            current.status='component_complete';current.finished=now()
            db.commit()
    print(json.dumps({'job_id':job.id,'technical_checks':checks,'visual_checked':visual_checked,**certificate}))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--visual-checked',action='store_true')
    parser.add_argument('--label',default='')
    parser.add_argument('--seconds',type=float,default=2,choices=(2,5))
    parser.add_argument('--profile',default=PARALLEL_PROFILE,choices=(PARALLEL_PROFILE,PROFILE))
    parser.add_argument('--source-run')
    args=parser.parse_args()
    tick(args.visual_checked,args.label,args.seconds,args.profile,args.source_run)
