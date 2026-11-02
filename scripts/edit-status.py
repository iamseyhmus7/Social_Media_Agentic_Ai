"""Read-only acceptance summary, with no credentials or provider payloads."""
import json
from pathlib import Path
from sqlalchemy import select,func
from backend.app.db import DB,Run,RemoteJob,Event
from backend.app.storage import media_path
PROJECT='00eb0369-a9af-414c-a301-e6a57c4d991f'
with DB() as db:
    run=db.scalar(select(Run).where(Run.project_id==PROJECT).order_by(Run.revision.desc()))
    folder=media_path(f'{PROJECT}/{run.id}')
    data={'id':run.id,'revision':run.revision,'status':run.status,'stage':run.stage,'error':run.error,'style':run.outputs.get('_edit_style','classic'),'started':run.started,'finished':run.finished,'remote_jobs':db.scalar(select(func.count()).select_from(RemoteJob).where(RemoteJob.run_id==run.id)),'quality':run.outputs.get('quality'),'package_ready':bool(run.outputs.get('publisher',{}).get('package')),'events':[{'stage':e.stage,'message':e.message,'time':e.created} for e in db.scalars(select(Event).where(Event.run_id==run.id).order_by(Event.id.desc()).limit(4))]}
    for name in ('render-metrics.json','edit-plan.json'):
        if (folder/name).is_file():data[name]=json.loads((folder/name).read_text())
print(json.dumps(data,ensure_ascii=False))
