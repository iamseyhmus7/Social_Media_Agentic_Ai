"""Render existing owned media without generation API calls or publication."""
import json
from pathlib import Path
from types import SimpleNamespace
from sqlalchemy import select
from backend.app.db import DB, Run, Asset
from backend.app.config import use_run_settings, settings
from backend.app.storage import media_path
from backend.app.remotion_renderer import render_production

class Decisions:
    def generate(self, schema, role, context):
        return {'shots': [{'shot_id': s['shot_id'], 'transition': 'cut', 'title': ''} for s in context['shots']]}

with DB() as db:
    run = db.scalar(select(Run).where(Run.pipeline_version == 1, Run.status == 'awaiting_approval'))
    if not run:
        raise RuntimeError('Existing media required for the smoke check.')
    def paths(ids): return [media_path(db.get(Asset, i).path) for i in ids]
    images, audios = paths(run.outputs['visual']['images']), paths(run.outputs['voice']['audios'])
    srt = paths([run.outputs['editor']['subtitle']])[0]
folder = settings().media_root / 'render-smoke'
folder.mkdir(exist_ok=True)
durations = run.outputs['voice']['durations']
with use_run_settings({'video_provider': 'none', 'editor_provider': 'remotion'}):
    report = render_production(run, SimpleNamespace(duration=round(sum(durations))), folder.resolve(), images, audios, durations, srt, lambda: None, Decisions(), {}, None, {'name': 'Sahne', 'color': '#A98BFF'})
(folder / 'report.json').write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False))
