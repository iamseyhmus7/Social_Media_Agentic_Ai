"""Durable failure reports without input values, provider bodies or traceback locals."""
import logging
import re
import traceback
from pathlib import Path
from uuid import uuid4


def identifier(value):
    value = str(value)
    return value if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,79}', value) else '[redacted]'


def validation_failure(exc, stage):
    root = Path(__file__).resolve().parents[2]
    locations = []
    for frame in traceback.extract_tb(exc.__traceback__):
        path = Path(frame.filename).resolve()
        if path.is_relative_to(root):
            relative = path.relative_to(root)
            if any(part in ('.venv', 'node_modules') for part in relative.parts):
                continue
            locations.append({'file': relative.as_posix(),
                              'line': frame.lineno, 'function': identifier(frame.name)})
    errors = []
    for item in exc.errors(include_input=False, include_url=False)[:12]:
        errors.append({'path': [part if isinstance(part, int) else identifier(part)
                                for part in item['loc']], 'type': identifier(item['type']),
                       'limits': {key: value for key, value in item.get('ctx', {}).items()
                                  if key in ('max_length', 'min_length', 'actual_length', 'ge', 'gt', 'le', 'lt')
                                  and type(value) in (int, float)}})
    report = {'id': uuid4().hex[:12], 'kind': 'validation', 'exception': 'ValidationError',
              'stage': stage, 'schema': identifier(exc.title), 'errors': errors,
              'locations': locations[-12:], 'input_values_logged': False}
    return report


def failure_message(report):
    fields = '; '.join('.'.join(map(str, e['path'])) or '(nesnenin tamamı)'
                       for e in report['errors'][:4])
    rules = ', '.join(dict.fromkeys(e['type'] for e in report['errors'][:4]))
    return (f"Veri doğrulama hatası ({report['schema']}): {fields}. Kural: {rules}. "
            f"Hata kaydı: {report['id']}. Tamamlanan aşamalar korundu.")


def log_failure(run_id, report):
    import json
    logging.getLogger('sahne.pipeline').error('production_failure %s',
        json.dumps({'run_id': run_id, **report}, ensure_ascii=True))
