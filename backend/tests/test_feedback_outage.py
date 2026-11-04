from uuid import uuid4
import pytest
from backend.app import feedback, main
from backend.app.db import DB, Feedback, Project, Run, User, now
from backend.app.providers import TransientProviderError
from backend.app.schemas import FeedbackRequest
from backend.tests.test_agentic import owned_source


def command(source, project, text='İlk sahnedeki çift yazıyı ve gereksiz daireleri kaldır.'):
    with DB() as db:
        item = feedback.create_feedback(db, db.get(Project, project), db.get(User, 'alice'),
            FeedbackRequest(run_id=source, prompt=text, request_id=str(uuid4())))
        return item.id


def test_503_waits_automatically_then_applies_original_command(setup, monkeypatch):
    source, project = owned_source()
    # A completed render can need correction despite a terminal technical stop.
    with DB() as db:
        db.get(Run, source).status = 'waiting_input'
        db.commit()
    ident = command(source, project)
    calls = []
    def decide(run, prompt, answer='', previous_question=''):
        calls.append((prompt, answer))
        if len(calls) == 1:
            raise TransientProviderError('HTTP 503', http_status=503, retry_after=15)
        return {'summary':'Üstteki yinelenen yazıyı ve daireleri kaldır.', 'clarification':'',
            'stages':['editor'], 'scene_indices':[], 'target_duration':None,
            'instructions':'İlk sahnedeki yinelenen üst yazıyı ve sahnelerdeki gereksiz daireleri kaldır.'}
    monkeypatch.setattr(feedback, 'feedback_decision', decide)
    feedback.process_feedback(ident)
    with DB() as db:
        item = db.get(Feedback, ident)
        assert item.status == 'waiting_provider' and item.run_id is None
        assert '_provider_wait' not in feedback.serialize(item)['decision']
        feedback.resume_provider_waits(db)
        assert item.status == 'waiting_provider'
        waiting = {**item.decision['_provider_wait'], 'retry_at':now()-1}
        item.decision = {**item.decision, '_provider_wait':waiting}
        db.commit()
    with DB() as db:
        feedback.resume_provider_waits(db)
        db.commit()
    feedback.process_feedback(ident)
    with DB() as db:
        item = db.get(Feedback, ident)
        assert item.status == 'applied' and item.error is None
        assert db.get(Project, project).revision == 2
        revised = db.get(Run, item.run_id)
        assert revised.outputs['_feedback']['prompt'] == calls[0][0] == calls[1][0]
        assert calls[0][1] == calls[1][1] == ''
        assert revised.outputs['_repair_stages'] == ['editor']
        assert all(key in revised.outputs for key in ('voice','visual','motion'))


def test_new_command_supersedes_waiting_request_without_becoming_an_answer(setup):
    source, project = owned_source()
    old = command(source, project)
    with DB() as db:
        db.get(Feedback, old).status = 'waiting_provider'
        db.commit()
    new = command(source, project, 'Yalnız üstteki beyaz yazıyı kaldır.')
    with DB() as db:
        assert db.get(Feedback, old).status == 'superseded'
        assert db.get(Feedback, new).status == 'queued'
        assert db.get(Feedback, new).answer == ''


@pytest.mark.parametrize('status', ['failed','waiting_provider','waiting_quota'])
def test_outage_is_not_a_clarification_answer(clients, monkeypatch, status):
    source, project = owned_source()
    ident = command(source, project)
    with DB() as db:
        db.get(Feedback, ident).status = status
        db.commit()
    monkeypatch.setattr(main, 'dispatch', lambda: None)
    response = clients[0].post(f'/api/v1/projects/{project}/feedback/{ident}/answers', json={'answer':'İlk yazıyı kaldır'})
    assert response.status_code == 409


def test_outage_deadline_does_not_create_a_question_or_revision(setup):
    source, project = owned_source()
    ident = command(source, project)
    with DB() as db:
        item = db.get(Feedback, ident)
        item.status = 'waiting_provider'
        item.decision = {'_provider_wait':{'deadline':now()-1,'retry_at':now()-2}}
        db.commit()
    with DB() as db:
        feedback.resume_provider_waits(db)
        db.commit()
        item = db.get(Feedback, ident)
        assert item.status == 'failed' and not item.decision.get('clarification')
        assert db.get(Project, project).revision == 1
