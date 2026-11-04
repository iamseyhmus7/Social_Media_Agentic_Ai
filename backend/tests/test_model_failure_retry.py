"""Technical model failures remain actionable without inventing user questions."""
import copy
import pytest
from backend.app import main, pipeline, recovery
from backend.app.db import DB, Run
from backend.app.providers import InvalidModelOutput
from backend.tests.test_agentic import create_run


@pytest.mark.parametrize('status,task_key,attempts', [('waiting_input', None, 3), ('failed', 'bad-task', 2)])
def test_editor_retry_preserves_media_and_reopens_failed_task(clients, monkeypatch, status, task_key, attempts):
    outputs = {'voice': {'audios': ['keep-audio']}, 'motion': {'clips': ['keep-clip']},
        '_editor_progress': {'render': {'0-core': {'status': 'rendered'}}},
        '_inference_attempts': {'good-task': 1, 'bad-task': attempts},
        '_recovery': {'active': 'model_output', 'model_output': {'task_key': task_key}}}
    ident = create_run(copy.deepcopy(outputs))
    with DB() as db:
        run = db.get(Run, ident)
        run.status, run.stage = status, 'editor'
        db.commit()
    monkeypatch.setattr(main, 'dispatch', lambda: None)
    public = clients[0].get('/api/v1/runs/' + ident).json()
    assert public['status'] == 'failed'
    assert public['can_retry'] == (status == 'waiting_input')
    assert clients[1].post('/api/v1/runs/' + ident + '/retry').status_code == 404
    assert clients[0].post('/api/v1/runs/' + ident + '/answers', json={'answer': 'devam'}).status_code == 409
    assert clients[0].post('/api/v1/runs/' + ident + '/retry').status_code == 202
    with DB() as db:
        run = db.get(Run, ident)
        assert run.status == 'queued' and run.stage == 'editor'
        for key in ('voice', 'motion', '_editor_progress'):
            assert run.outputs[key] == outputs[key]
        assert run.outputs['_inference_attempts'] == {'good-task': 1}
        assert run.outputs['_recovery']['active'] is None
    # A new bounded window works, then stops again rather than retrying forever.
    for _ in range(3):
        recovery.task_budget(ident, 'bad-task', 'check')
        recovery.task_budget(ident, 'bad-task', 'consume')
    with pytest.raises(InvalidModelOutput) as error:
        recovery.task_budget(ident, 'bad-task', 'check')
    assert error.value.task_key == 'bad-task'


def test_real_question_still_requires_answer(clients, monkeypatch):
    ident = create_run({'clarification': {'question': 'Hangi hedef kitle?'}})
    with DB() as db:
        db.get(Run, ident).status = 'waiting_input'
        db.commit()
    monkeypatch.setattr(main, 'dispatch', lambda: None)
    assert not clients[0].get('/api/v1/runs/' + ident).json()['can_retry']
    assert clients[0].post('/api/v1/runs/' + ident + '/retry').status_code == 409
    assert clients[0].post('/api/v1/runs/' + ident + '/answers', json={'answer': 'Yetişkinler'}).status_code == 202


def test_model_failure_is_failed_and_retains_exact_task(setup, monkeypatch):
    ident = create_run({'voice': {'audios': ['keep']}})
    with DB() as db:
        db.get(Run, ident).stage = 'editor'
        db.commit()
    class Graph:
        def invoke(self, *args, **kwargs):
            raise InvalidModelOutput('Geçersiz kurgu çıktısı', task_key='cue-repair')
    monkeypatch.setattr(pipeline, 'build_graph', lambda version: Graph())
    monkeypatch.setattr(pipeline, 'check_disk', lambda: None)
    pipeline.execute(ident)
    with DB() as db:
        run = db.get(Run, ident)
        assert run.status == 'failed'
        assert run.outputs['voice'] == {'audios': ['keep']}
        assert run.outputs['_recovery']['model_output']['task_key'] == 'cue-repair'
        assert 'clarification' not in run.outputs
