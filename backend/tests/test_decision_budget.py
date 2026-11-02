from copy import deepcopy
import pytest
from backend.app import orchestration as agent
from backend.app.config import settings
from backend.app.db import DB,Run
from backend.app.providers import TransientProviderError,ProviderTimeout,InvalidModelOutput,QuotaExceeded,trace_calls
from backend.tests.test_agentic import create_run,brief


def output(ident):
    with DB() as db:return deepcopy(db.get(Run,ident).outputs)


@pytest.mark.parametrize('failure',[TransientProviderError('503',http_status=503),ProviderTimeout('timeout')])
def test_transient_decision_does_not_consume_turn_but_success_does(setup,failure):
    ident=create_run({'_agent_turns':4})
    def fail():raise failure
    with pytest.raises(type(failure)):agent.decision_call(ident,fail)
    assert output(ident)['_agent_turns']==4
    assert agent.decision_call(ident,lambda:'ok')=='ok'
    assert output(ident)['_agent_turns']==5
    assert output(ident)['_decision_budget']['transient_refunds']==1


@pytest.mark.parametrize('failure',[InvalidModelOutput('bad JSON'),QuotaExceeded('quota')])
def test_nontransport_failures_are_not_refunded(setup,failure):
    ident=create_run()
    def fail():raise failure
    with pytest.raises(type(failure)):agent.decision_call(ident,fail)
    assert output(ident)['_agent_turns']==1


def test_legacy_credit_is_evidence_based_once_only_and_preserves_outputs(setup):
    metrics=[{'role':'Supervisor','schema':'ReadySupervisorDecision','status':'service_unavailable','http_status':503},
             {'role':'Supervisor','schema':'SupervisorDecision','status':'timeout'},
             {'role':'Video Editörü / Sahne kurgusu','schema':'GroundedScene','status':'timeout'},
             {'role':'Supervisor','schema':'ReadySupervisorDecision','status':'passed'},
             {'role':'Supervisor','schema':'ReadySupervisorDecision','status':'service_unavailable','http_status':501}]
    original={'_agent_turns':80,'_model_metrics':metrics,'voice':{'duration':58.32},
              '_provider_wait':{'cycles':6,'deadline':123},'_recovery':{'voice':{'text_used':2}},
              '_editor_progress':{'render':{'1-core':{'status':'rendered'}}}}
    ident=create_run(deepcopy(original));record=agent.ensure_agent_budget(ident)
    assert record['legacy_refunded']==2 and output(ident)['_agent_turns']==78
    agent.ensure_agent_budget(ident)
    assert output(ident)['_agent_turns']==78
    for key in original:
        if key!='_agent_turns':assert output(ident)[key]==original[key]


def test_real_limit_still_blocks_new_decisions(setup,monkeypatch):
    monkeypatch.setattr(settings(),'agent_max_turns',12)
    ident=create_run({'_agent_turns':12})
    with pytest.raises(RuntimeError,match='karar bütçesi'):agent.decision_call(ident,lambda:pytest.fail('must not call provider'))


def test_supervisor_503_refunds_with_production_retry_budget(setup,monkeypatch):
    ident=create_run({'supervisor':brief(),'_agent_turns':3,'_config':{'supervisor_policy':'model_v4'}})
    def fail(*args,**kwargs):raise TransientProviderError('HTTP 503',http_status=503)
    monkeypatch.setattr(agent.Evren,'generate',fail)
    with trace_calls(lambda metric:None,budget=lambda *args:None):
        with pytest.raises(TransientProviderError):agent.supervise(ident)
    assert output(ident)['_agent_turns']==3
