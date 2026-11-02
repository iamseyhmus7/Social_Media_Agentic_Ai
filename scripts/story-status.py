"""Read-only status of the latest production; never emits configuration or credentials."""
import json
from sqlalchemy import select
from backend.app.db import DB, Run, Project, RemoteJob, Event
from backend.app.storage import media_path

with DB() as db:
    run = db.scalar(select(Run).order_by(Run.created.desc()))
    project = db.get(Project, run.project_id)
    folder = media_path(f'{project.id}/{run.id}')
    data = {'id': run.id, 'project': project.id, 'title': project.title, 'revision': run.revision,
            'status': run.status, 'stage': run.stage, 'error': run.error, 'style': run.outputs.get('_edit_style'),
            'started': run.started, 'finished': run.finished,
            'scenes': [{'title': s['title'], 'narration': s['narration'], 'action': s.get('action')} for s in run.outputs.get('script', {}).get('scenes', [])],
            'voice': {'durations': run.outputs.get('voice', {}).get('durations'), 'selection': run.outputs.get('voice', {}).get('selection', {}).get('name')},
            'reference_count': len(run.outputs.get('visual', {}).get('shot_images', {})),
            'shots': len(run.outputs.get('_motion_plan', {}).get('shots', [])),
            'jobs': [{'id': j.id, 'status': j.status, 'attempt': j.attempt, 'clips': len(j.result.get('clips', {})), 'error_count': len(j.result.get('errors', {}))} for j in db.scalars(select(RemoteJob).where(RemoteJob.run_id == run.id))],
            'quality': run.outputs.get('quality'), 'package_ready': bool(run.outputs.get('publisher', {}).get('package')),
            'events': [{'stage': e.stage, 'message': e.message, 'time': e.created} for e in db.scalars(select(Event).where(Event.run_id == run.id).order_by(Event.id.desc()).limit(5))]}
    for name in ('render-metrics.json', 'edit-plan.json'):
        path = folder / name
        if path.is_file(): data[name] = json.loads(path.read_text(encoding='utf-8'))
print(json.dumps(data, ensure_ascii=False))
