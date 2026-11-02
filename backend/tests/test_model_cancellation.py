import threading
import time
import httpx
import pytest
from backend.app.providers import Evren, trace_calls
from backend.app.config import settings
from backend.app.schemas import AgentAction
from backend.app.media import Cancelled


def test_inflight_model_wait_obeys_cancellation_without_waiting_for_response(monkeypatch):
    for key,value in {'evren_api_key':'test','evren_base_url':'https://example.test',
        'evren_model':'test','evren_protocol':'openai_chat','evren_contract_verified':True}.items():
        monkeypatch.setattr(settings(),key,value)
    released=threading.Event();started=threading.Event()
    def response(request):
        started.set();released.wait(5)
        return httpx.Response(200,json={'choices':[{'message':{'content':'{}'}}]})
    def check():
        if started.is_set():raise Cancelled('User stopped')
    before=time.monotonic()
    try:
        with trace_calls(lambda metric:None,check_cancel=check),pytest.raises(Cancelled):
            Evren(httpx.MockTransport(response)).generate(AgentAction,'Supervisor',{})
        assert time.monotonic()-before<2
    finally:released.set()


def test_cancelled_model_execution_releases_owner_and_keeps_checkpoints(setup,monkeypatch):
    from types import SimpleNamespace
    from backend.tests.test_agentic import create_run
    from backend.app.db import DB,Run
    from backend.app import pipeline
    for key,value in {'evren_api_key':'test','evren_base_url':'https://example.test',
        'evren_model':'test','evren_protocol':'openai_chat','evren_contract_verified':True}.items():
        monkeypatch.setattr(settings(),key,value)
    ident=create_run({'script':{'kept':True},'_config':{'video_provider':'none'}})
    with DB() as db:
        run=db.get(Run,ident);run.active_owner='alice';db.commit()
    released=threading.Event()
    def response(request):
        with DB() as db:
            run=db.get(Run,ident);run.cancel_requested=True;db.commit()
        released.wait(5)
        return httpx.Response(200,json={'choices':[{'message':{'content':'{}'}}]})
    def invoke(*args,**kwargs):
        return Evren(httpx.MockTransport(response)).generate(AgentAction,'Supervisor',{})
    monkeypatch.setattr(pipeline,'build_graph',lambda *a:SimpleNamespace(invoke=invoke))
    try:
        pipeline.execute(ident)
        with DB() as db:
            run=db.get(Run,ident)
            assert run.status=='cancelled' and run.active_owner is None
            assert run.outputs['script']=={'kept':True}
    finally:released.set()
