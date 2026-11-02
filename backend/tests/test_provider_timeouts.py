import json
import httpx
import pytest
from backend.app.config import settings
from backend.app.providers import Evren, ProviderError
from backend.app.schemas import Plan


def configured(monkeypatch):
    for key, value in {'evren_api_key': 'test', 'evren_base_url': 'https://example.test/v1',
                       'evren_model': 'test-model', 'evren_contract_verified': True,
                       'evren_protocol': 'openai_chat'}.items():
        monkeypatch.setattr(settings(), key, value)


def test_clip_perception_repairs_only_overlong_observation(monkeypatch):
    import json
    from backend.app.schemas import ClipPerception
    configured(monkeypatch)
    original={'observation':'x'*4097,'visible_defects':'Belirgin kusur görünmüyor.',
              'motion_uncertainty':'Hareketin tamamı bu karelerden doğrulanamaz.'}
    calls=[]
    def respond(request):
        body=json.loads(request.content)
        calls.append(body)
        if len(calls)==2:
            repair=json.loads(body['messages'][1]['content'])
            assert set(repair['invalid_fields'])=={'observation'}
        value=original if len(calls)==1 else {'observation':'Karelerde bal kavanozu görünüyor.'}
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(value)}}]})
    result=Evren(httpx.MockTransport(respond)).generate(ClipPerception,'Video Editörü / Görsel inceleme',
        {'shot_id':'shot-010'},max_attempts=2,max_output_tokens=1536,repair_fields=True)
    assert len(calls)==2
    assert result=={**original,'observation':'Karelerde bal kavanozu görünüyor.'}


def test_editor_descriptions_keep_detail_without_relaxing_render_constraints():
    from pydantic import ValidationError
    from backend.app.schemas import ClipPerception,EditLook
    detail='Klipteki nesnenin konumu ve ışığı kareler boyunca korunuyor. '*25
    perception=ClipPerception.model_validate({'observation':detail,
        'visible_defects':'Belirgin kusur yok.','motion_uncertainty':'Örnek kareler tüm hareketi göstermiyor.'})
    assert perception.observation==detail
    look=EditLook.model_validate({'rationale':detail,'creative_direction':detail})
    assert look.creative_direction==detail and look.rationale==detail
    with pytest.raises(ValidationError):
        EditLook.model_validate({'rationale':detail,'opening_title':'x'*59})
    with pytest.raises(ValidationError):
        EditLook.model_validate({'rationale':detail,'caption_size':100})


def test_long_generation_keeps_connection_timeout_short(monkeypatch):
    configured(monkeypatch)
    def respond(request):
        assert request.extensions['timeout'] == {'connect': 15, 'read': 300, 'write': 30, 'pool': 15}
        return httpx.Response(200, json={'choices': [{'message': {'content': '{"goal":"Test planı","checks":["Test"]}'}}]})
    assert Evren(httpx.MockTransport(respond), timeout=300).generate(Plan, 'Senaryo Yazarı', {})['goal'] == 'Test planı'


@pytest.mark.parametrize('role', ['Senaryo Yazarı', 'Seslendirme', 'Görsel Tasarımcı', 'Video Editörü', 'Supervisor / Senaryo revizyonu'])
def test_agents_use_configured_long_response_timeout(monkeypatch, role):
    configured(monkeypatch)
    monkeypatch.setattr(settings(), 'evren_response_timeout_seconds', 1800)
    def respond(request):
        assert request.extensions['timeout'] == {'connect': 15, 'read': 1800, 'write': 30, 'pool': 15}
        return httpx.Response(200, json={'choices': [{'message': {'content': '{"goal":"Test planı","checks":["Test"]}'}}]})
    assert Evren(httpx.MockTransport(respond)).generate(Plan, role, {})['goal'] == 'Test planı'


@pytest.mark.parametrize('status', [500,502,503,504])
def test_server_errors_do_not_blame_api_key_or_leak_body(monkeypatch, status):
    configured(monkeypatch)
    with pytest.raises(ProviderError, match=f'HTTP {status}') as failure:
        Evren(httpx.MockTransport(lambda request:httpx.Response(status,text='secret provider response'))).generate(Plan,'Video Editörü',{})
    assert 'Anahtar' not in str(failure.value)
    assert 'secret' not in str(failure.value)
    assert 'korundu' in str(failure.value)


@pytest.mark.parametrize(('error_type', 'message'), [(httpx.ReadTimeout, '300 saniye'), (httpx.ConnectTimeout, 'bağlantı kurma'), (httpx.ConnectError, 'bağlantısı')])
def test_failure_identifies_timeout_without_leaking_request(monkeypatch, error_type, message):
    configured(monkeypatch)
    calls = []
    def fail(request):
        calls.append(request)
        raise error_type('secret request details must not appear', request=request)
    with pytest.raises(ProviderError, match=message) as failure:
        Evren(httpx.MockTransport(fail), timeout=300).generate(Plan, 'Senaryo Yazarı', {})
    assert 'secret' not in str(failure.value)
    assert len(calls) == 1  # A timed-out generation is retried explicitly, not silently billed again.

def test_editor_zero_disables_read_timeout_but_keeps_transport_limits(monkeypatch):
    from backend.app.providers import configure_editor_timeout
    configured(monkeypatch)
    monkeypatch.setattr(settings(),'editor_call_timeout_seconds',0)
    def respond(request):
        assert request.extensions['timeout']=={'connect':15,'read':None,'write':30,'pool':15}
        return httpx.Response(200,json={'choices':[{'message':{'content':'{"goal":"Test planı","checks":["Test"]}'}}]})
    llm=Evren(httpx.MockTransport(respond))
    configure_editor_timeout(llm)
    assert llm.timeout is None
    configure_editor_timeout(llm)  # Repeated planned-edit/scene-edit setup is safe.
    assert llm.generate(Plan,'Video Editörü / Sahne kurgusu',{})['goal']=='Test planı'


def test_finite_editor_snapshot_keeps_its_limit(monkeypatch):
    from backend.app.providers import configure_editor_timeout
    monkeypatch.setattr(settings(),'editor_call_timeout_seconds',300)
    llm=Evren(timeout=1800)
    configure_editor_timeout(llm)
    assert llm.timeout==300


def test_unlimited_response_wait_can_still_be_cancelled(monkeypatch):
    from threading import Event
    from backend.app.providers import configure_editor_timeout,trace_calls
    from backend.app.media import Cancelled
    configured(monkeypatch)
    monkeypatch.setattr(settings(),'editor_call_timeout_seconds',0)
    entered=Event();release=Event();finished=Event()
    def respond(request):
        entered.set()
        try:
            release.wait(3)
            return httpx.Response(200,json={'choices':[{'message':{'content':'{"goal":"Test planı","checks":["Test"]}'}}]})
        finally:finished.set()
    def check():
        if entered.is_set():raise Cancelled('User cancellation')
    llm=Evren(httpx.MockTransport(respond));configure_editor_timeout(llm)
    try:
        with trace_calls(lambda metric:None,check_cancel=check):
            with pytest.raises(Cancelled):llm.generate(Plan,'Video Editörü / Sahne kurgusu',{})
    finally:
        release.set();assert finished.wait(2)

def test_editor_omits_output_caps_and_short_response_instruction(monkeypatch):
    from backend.app.schemas import Plan
    configured(monkeypatch)
    def respond(request):
        payload=json.loads(request.content)
        assert not {'max_tokens','max_completion_tokens','thinking','reasoning_effort'} & payload.keys()
        assert 'Kısa yanıt ver' not in payload['messages'][1]['content']
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{"goal":"Kurgu planı","checks":["Test"]}'}}],
            'usage':{'completion_tokens':10000,'completion_tokens_details':{'reasoning_tokens':9000}}})
    assert Evren(httpx.MockTransport(respond)).generate(Plan,'Video Editörü / Sahne kurgusu',
        {'instruction':'Kısa yanıt ver; mevcut kaynakları kullan.'},max_output_tokens=3072)['goal']=='Kurgu planı'


def test_upstream_truncation_is_reported_without_ineffective_repeat(monkeypatch):
    from backend.app.providers import InvalidModelOutput,trace_calls
    configured(monkeypatch);calls=[];metrics=[]
    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200,json={'choices':[{'finish_reason':'length','message':{'content':'{"goal":'}}]})
    with trace_calls(metrics.append),pytest.raises(InvalidModelOutput,match='sağlayıcının çıktı sınırında'):
        Evren(httpx.MockTransport(respond)).generate(Plan,'Video Editörü / Sahne kurgusu',{},max_output_tokens=3072)
    assert len(calls)==1 and 'max_tokens' not in calls[0]
    assert metrics[0]['failure_kind']=='provider_output_limit'
