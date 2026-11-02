import json
from pathlib import Path
import httpx
from backend.app.config import settings, snapshot_settings, use_run_settings
from backend.app.providers import Evren, PERCEPTION_ROLE
from backend.app.schemas import ClipPerception
from backend.app.planned_edit import perception_cache_path


def test_only_perception_routes_to_second_media_model(monkeypatch):
    cfg=settings()
    for key,value in {'evren_model':'text','evren_media_model':'mimo','evren_media_model2':'qwen3-vl-30b','evren_supervisor_model':'supervisor'}.items():
        monkeypatch.setattr(cfg,key,value)
    llm=Evren()
    assert llm.model_for(PERCEPTION_ROLE)=='qwen3-vl-30b'
    assert llm.model_for('Video Editörü / Sahne kurgusu')=='mimo'
    assert llm.model_for('Görsel Tasarımcı',media_inputs=[{}])=='mimo'
    assert llm.model_for('Supervisor')=='supervisor'
    assert llm.model_for('Senaryo Yazarı')=='text'
    monkeypatch.setattr(cfg,'evren_media_model2','')
    assert Evren().model_for(PERCEPTION_ROLE)=='mimo'


def test_snapshot_isolates_legacy_runs(monkeypatch):
    monkeypatch.setattr(settings(),'evren_media_model2','qwen3-vl-30b')
    assert snapshot_settings()['evren_media_model2']=='qwen3-vl-30b'
    with use_run_settings({}):assert settings().evren_media_model2==''
    with use_run_settings({'evren_media_model2':'qwen3-vl-30b'}):
        assert Evren().model_for(PERCEPTION_ROLE)=='qwen3-vl-30b'


def test_cache_reuses_completed_old_observation_only_when_explicit(tmp_path):
    old=perception_cache_path(tmp_path,'clip-a','mimo')
    old.write_text('{}')
    fresh=perception_cache_path(tmp_path,'clip-a','qwen')
    assert fresh!=old and not fresh.exists()
    assert perception_cache_path(tmp_path,'clip-a','qwen',['mimo'])==old
    assert perception_cache_path(tmp_path,'changed-clip','qwen',['mimo'])!=old
    fresh.write_text('{}')
    assert perception_cache_path(tmp_path,'clip-a','qwen',['mimo'])==fresh
    assert old.read_text()=='{}'


def test_perception_wire_uses_qwen_with_multiple_images(monkeypatch):
    for key,value in {'evren_model':'text','evren_media_model':'mimo','evren_media_model2':'qwen3-vl-30b',
                      'evren_api_key':'test','evren_base_url':'https://example.test/v1',
                      'evren_contract_verified':True,'evren_protocol':'openai_chat'}.items():
        monkeypatch.setattr(settings(),key,value)
    observation={'observation':'Karelerde askerler ve açık arazi görülüyor.',
                 'visible_defects':'','motion_uncertainty':'Üç kare tüm hareketi doğrulamaz.'}
    def respond(request):
        payload=json.loads(request.content)
        assert payload['model']=='qwen3-vl-30b'
        assert sum(item['type']=='image_url' for item in payload['messages'][1]['content'])==3
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(observation)}}]})
    inputs=[{'type':'image_url','image_url':{'url':'data:image/jpeg;base64,eA=='}}]*3
    assert Evren(httpx.MockTransport(respond)).generate(ClipPerception,PERCEPTION_ROLE,{},media_inputs=inputs)==observation
