"""Run one isolated live audio recovery against a read-only production snapshot.

No production database writes, Docker changes, video generation or publishing.
Usage: python -m scripts.accept_voice_recovery --snapshot data/...json --live
"""
import argparse
import json
from pathlib import Path
from uuid import uuid4


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',type=Path,required=True)
    parser.add_argument('--live',action='store_true',help='Allow real narration and TTS API calls.')
    args=parser.parse_args()
    if not args.live:
        parser.error('--live is required for provider calls; use pytest for offline acceptance.')
    from sqlalchemy import create_engine
    from backend.app.config import settings, snapshot_settings
    from backend.app.db import DB,Base,User,Project,Run
    from backend.app.recovery import ensure,repair_voice,provider_wait
    from backend.app.pipeline import run_stage,save_model_metric,cancellation
    from backend.app.orchestration import voice_valid,voice_timing
    from backend.app.providers import trace_calls,TransientProviderError
    from backend.app.recovery import task_budget
    snapshot=json.loads(args.snapshot.read_text(encoding='utf-8-sig'))
    folder=Path('.cache')/('voice-acceptance-'+uuid4().hex)
    folder.mkdir(parents=True)
    cfg=settings()
    cfg.media_root=(folder/'media').resolve()
    cfg.evren_response_timeout_seconds=180
    engine=create_engine('sqlite:///'+str((folder/'acceptance.db').resolve()))
    Base.metadata.create_all(engine)
    DB.configure(bind=engine)
    ident=str(uuid4());project_id=str(uuid4())
    outputs=snapshot['outputs']
    outputs['_config']={**snapshot_settings(),'video_provider':'none'}
    with DB() as db:
        db.add(User(id='acceptance',email='acceptance@example.test',name='Acceptance',password_hash='unused'))
        db.add(Project(id=project_id,user_id='acceptance',title='Sakarya recovery acceptance',topic='Sakarya Meydan Muharebesi',duration=snapshot['duration']))
        db.flush()
        db.add(Run(id=ident,project_id=project_id,user_id='acceptance',revision=1,pipeline_version=3,outputs=outputs))
        db.commit()
    ensure(ident)
    result={'source_run_id':snapshot['source_run_id'],'isolated_run_id':ident,'production_modified':False}
    try:
        with trace_calls(lambda m:save_model_metric(ident,m),check_cancel=lambda:cancellation(ident),
                         budget=lambda key,op:task_budget(ident,key,op)):
            repair_voice(ident)
            run_stage(ident,'voice')
        with DB() as db:
            run=db.get(Run,ident)
            result.update(passed=voice_valid(run.outputs),timing=voice_timing(run.outputs),
                          recovery=run.outputs['_recovery']['voice'])
    except TransientProviderError as exc:
        result.update(passed=False,status='waiting_provider',wait=provider_wait({},'voice',exc),error=str(exc))
    except Exception as exc:
        # Provider exceptions already redact request bodies and credentials.
        from backend.app.providers import ProviderError
        result.update(passed=False,status='needs_attention',error=str(exc) if isinstance(exc,ProviderError) else type(exc).__name__)
    (folder/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'passed':result['passed'],'status':result.get('status','measured'),
                      'seconds':result.get('timing',{}).get('measured_seconds'),'report':str((folder/'result.json').resolve())},ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
