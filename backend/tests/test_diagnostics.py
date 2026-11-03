import json
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, Field, ValidationError, model_validator

from backend.app.diagnostics import validation_failure, failure_message


class Payload(BaseModel):
    title: str = Field(max_length=5)


def invalid_payload():
    try:
        Payload.model_validate({'title': 'PRIVATE_API_TOKEN_DO_NOT_LOG'})
    except ValidationError as exc:
        return exc


def test_report_identifies_field_and_limit_without_logging_value():
    report = validation_failure(invalid_payload(), 'script')
    assert report['schema'] == 'Payload'
    assert report['errors'][0]['path'] == ['title']
    assert report['errors'][0]['type'] == 'string_too_long'
    assert report['errors'][0]['limits']['max_length'] == 5
    assert report['locations'][-1]['function'] == 'invalid_payload'
    assert 'PRIVATE_API_TOKEN' not in json.dumps(report)
    assert 'title' in failure_message(report)


def test_custom_validator_cannot_leak_its_error_message():
    class PrivatePayload(BaseModel):
        @model_validator(mode='after')
        def invalid(self):
            raise ValueError('secret-password-and-provider-response')
    with pytest.raises(ValidationError) as captured:
        PrivatePayload.model_validate({})
    report = validation_failure(captured.value, 'script')
    assert report['errors'][0]['type'] == 'value_error'
    assert 'secret-password' not in json.dumps(report)
    assert 'secret-password' not in failure_message(report)


def test_pipeline_persists_diagnostic_and_preserves_completed_stages(setup, monkeypatch, caplog):
    from backend.tests.test_agentic import create_run
    from backend.app import pipeline
    from backend.app.db import DB, Run, Event
    from sqlalchemy import select
    ident = create_run({'supervisor': {'keep': True}, '_config': {'video_provider': 'none'}})
    with DB() as db:
        run = db.get(Run, ident)
        run.stage = 'script'
        db.commit()
    def fail(*a, **kw):
        raise invalid_payload()
    monkeypatch.setattr(pipeline, 'build_graph', lambda *a: SimpleNamespace(invoke=fail))
    monkeypatch.setattr(pipeline, 'check_disk', lambda: None)
    pipeline.execute(ident)
    with DB() as db:
        run = db.get(Run, ident)
        report = run.outputs['_diagnostics'][-1]
        assert run.status == 'failed'
        assert run.outputs['_worker_runtime']['validation_diagnostics'] is True
        assert run.outputs['_worker_runtime']['pid'] > 0
        assert run.outputs['supervisor'] == {'keep': True}
        assert report['stage'] == 'script'
        assert report['id'] in run.error and 'title' in run.error
        assert 'Bağımlılık' not in run.error
        messages = [e.message for e in db.scalars(select(Event).where(Event.run_id == ident))]
        assert any(report['id'] in message for message in messages)
        assert report['id'] in caplog.text
        assert 'PRIVATE_API_TOKEN' not in caplog.text
        assert 'PRIVATE_API_TOKEN' not in json.dumps(run.outputs)
