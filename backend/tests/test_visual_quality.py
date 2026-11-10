import base64
import io
import json
from types import SimpleNamespace
from uuid import uuid4
import httpx
import pytest
from PIL import Image
from sqlalchemy import select
from backend.app.config import settings,use_run_settings,snapshot_settings
from backend.app.db import DB,Run,Project,Asset,CloudflareBudget
from backend.app.providers import QuotaExceeded
from backend.app.storage import workdir,file_hash,register


def png(size=(576,1024)):
    stream=io.BytesIO();Image.new('RGB',size,'purple').save(stream,format='PNG')
    return stream.getvalue()


@pytest.fixture
def image_config(setup,monkeypatch):
    cfg=settings()
    for k,v in {'cloudflare_account_id':'a'*32,'cloudflare_api_token':'secret',
        'visual_policy':'references_v1','cloudflare_image_model':'klein','image_provider':'cloudflare'}.items():
        monkeypatch.setattr(cfg,k,v)
    monkeypatch.setattr(cfg,'wan_sampling_profile','standard20')
    return cfg


def test_klein_multipart_and_lucid_json_share_budget(image_config,tmp_path):
    from backend.app.media_providers import cloudflare_image
    from backend.app.image_budget import report
    ref=tmp_path/'ref.png';ref.write_bytes(png())
    seen=[]
    def respond(request):
        content=request.read();seen.append(request)
        if 'klein' in str(request.url):
            assert 'multipart/form-data' in request.headers['content-type']
            assert b'name="input_image_0"' in content
            assert b'name="width"' in content and b'576' in content
        else:
            payload=json.loads(content)
            assert payload['width']==576 and payload['height']==1024 and payload['num_steps']==25
        return httpx.Response(200,json={'success':True,'result':{'image':base64.b64encode(png()).decode()}})
    transport=httpx.MockTransport(respond)
    cloudflare_image('portrait',tmp_path/'klein.png',lambda:None,references=[ref],transport=transport)
    cloudflare_image('landscape',tmp_path/'lucid.png',lambda:None,model='lucid',transport=transport)
    assert len(seen)==2
    assert report()['estimated_reserved_neurons']==1546+2844
    assert report()['external_usage_included'] is False


def test_quota_is_shared_and_failed_requests_remain_reserved(image_config,tmp_path,monkeypatch):
    from backend.app.media_providers import cloudflare_image
    from backend.app.image_budget import report,reserve
    def respond(request): return httpx.Response(429,json={'errors':[{'code':4006,'message':'Daily quota exceeded'}]})
    with pytest.raises(QuotaExceeded,match='ortak'):
        cloudflare_image('portrait',tmp_path/'a.png',lambda:None,transport=httpx.MockTransport(respond))
    assert report()['provider_blocked']
    assert report()['estimated_reserved_neurons']==1364
    with pytest.raises(QuotaExceeded): reserve(1)


def test_budget_atomic_limit_across_two_connections(image_config):
    from concurrent.futures import ThreadPoolExecutor
    from backend.app.image_budget import reserve,report
    def attempt(_):
        try: reserve(6000);return True
        except QuotaExceeded:return False
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sum(executor.map(attempt,range(2)))==1
    assert report()['remaining_estimate']==4000


def test_old_snapshots_keep_old_models(image_config):
    assert snapshot_settings()['cloudflare_image_model']=='klein'
    with use_run_settings({}):
        assert settings().visual_policy=='legacy'
        assert settings().cloudflare_image_model=='schnell'
        assert settings().video_model_profile=='ltx096'


def test_reference_upload_is_owned_and_run_snapshot_is_immutable(clients,project):
    alice,bob=clients
    endpoint='/api/v1/projects/'+project['id']+'/references'
    assert bob.post(endpoint,files={'file':('x.png',png(),'image/png')}).status_code==404
    response=alice.post(endpoint,files={'file':('x.png',png(),'image/png')},data={'kind':'character','name':'Ada'})
    assert response.status_code==201
    ref=response.json()
    assert bob.get(ref['url']).status_code==404
    run=alice.post('/api/v1/projects/'+project['id']+'/runs').json()
    assert alice.patch(endpoint+'/'+ref['id'],json={'active':False}).status_code==200
    with DB() as db:
        assert db.get(Run,run['id']).outputs['_visual_references'][0]['asset_id']==ref['asset_id']
    assert alice.post(endpoint,files={'file':('x.png',b'not an image','image/png')}).status_code==422


def test_reference_write_requires_csrf(clients,project):
    alice,_=clients
    token=alice.headers.pop('X-CSRF-Token')
    try:
        assert alice.post('/api/v1/projects/'+project['id']+'/references',files={'file':('x.png',png(),'image/png')}).status_code==403
    finally:alice.headers['X-CSRF-Token']=token


def prepare_run(project):
    shots=[{'shot_id':f'shot-{i:03}','scene_index':i,'duration_seconds':3,
        'reference_prompt':'A woman beside a sunlit window, portrait framing.',
        'motion_prompt':'She slowly turns her head toward the window.','camera':'locked',
        'purpose':'Karakterin tepkisi','expected_action':'Başını pencereye çevirir.',
        'continuity_group':'ada','image_model':'lucid'} for i in range(2)]
    with DB() as db:
        run=Run(id=str(uuid4()),project_id=project['id'],user_id='alice',revision=1,pipeline_version=3,
            outputs={'_config':snapshot_settings(),'_storyboard':{'shots':shots,'visual_identity':'Ada wears a blue coat.'},
                'script':{'scenes':[{'narration':'one'},{'narration':'two'}]},'voice':{'durations':[3,3]}})
        db.add(run);db.commit()
    return run,shots


def test_visual_resume_preserves_candidates_and_uses_accepted_anchor(image_config,project,monkeypatch):
    from backend.app import visual_quality as quality,media
    run,shots=prepare_run(project)
    folder=workdir(run.project_id,run.id)
    calls=[]
    scans=[]
    def generate(prompt,target,check,**kwargs):
        calls.append(kwargs);target.write_bytes(png())
        return {'model':'klein','reference_count':len(kwargs['references'])}
    monkeypatch.setattr('backend.app.media_providers.cloudflare_image',generate)
    monkeypatch.setattr(quality,'check_disk',lambda:scans.append(1) or 0)
    monkeypatch.setattr(media,'cover',lambda source,title,target,brand:target.write_bytes(png()))
    with DB() as db: project_obj=db.get(Project,run.project_id)
    first=quality.generate_visual(run,project_obj,{},folder,None,{},lambda:None)
    second=quality.generate_visual(run,project_obj,{},folder,None,{},lambda:None)
    assert first==second and len(calls)==2
    assert scans==[1]
    assert calls[0]['model']=='klein' and len(calls[0]['references'])==0
    assert len(calls[1]['references'])==1


def test_images_do_not_compare_repair_or_request_approval(image_config,project,monkeypatch):
    from backend.app import visual_quality as quality,media
    run,_=prepare_run(project);folder=workdir(run.project_id,run.id)
    calls=[]
    def generate(prompt,target,check,**kwargs):calls.append(1);target.write_bytes(png());return {'model':'klein'}
    monkeypatch.setattr('backend.app.media_providers.cloudflare_image',generate)
    monkeypatch.setattr(media,'cover',lambda source,title,target,brand:target.write_bytes(png()))
    with DB() as db: p=db.get(Project,run.project_id)
    for _ in range(2):
        result=quality.generate_visual(run,p,{},folder,None,{},lambda:None)
        assert len(result['shot_images'])==2
    assert len(calls)==2
    with DB() as db:
        assert not db.get(Run,run.id).outputs.get('_media_review')


def test_quota_uses_licensed_stock_and_resume_preserves_it(image_config,project,monkeypatch):
    from backend.app import visual_quality as quality,media,media_library as library
    run,_=prepare_run(project);folder=workdir(run.project_id,run.id)
    generated=[];downloads=[]
    def quota(*args,**kwargs):
        generated.append(1);raise QuotaExceeded('Estimated allowance insufficient')
    def stock(llm,shot,target,check,**kwargs):
        downloads.append(shot['shot_id']);target.write_bytes(png())
        return {'model':'licensed_stock','source':{'license':'cc0'},'direction':{
            'motion_prompt':'Slow push into the visible bicycle.','expected_action':'Bisiklete yaklaşılır.',
            'state_before':'A bicycle.','state_after':'Closer bicycle.'}}
    monkeypatch.setattr('backend.app.media_providers.cloudflare_image',quota)
    monkeypatch.setattr(library,'stock_image',stock)
    monkeypatch.setattr(library,'prepare_stock_batch',lambda llm,shots,*args,**kwargs:{s['shot_id']:{} for s in shots})
    monkeypatch.setattr(library,'plan_stock_search',lambda llm,shots,**kwargs:{s['shot_id']:['bicycle'] for s in shots})
    monkeypatch.setattr(media,'cover',lambda source,title,target,brand:target.write_bytes(png()))
    with DB() as db:p=db.get(Project,run.project_id)
    first=quality.generate_visual(run,p,{},folder,None,{},lambda:None)
    second=quality.generate_visual(run,p,{},folder,None,{},lambda:None)
    assert first==second and len(generated)==2 and len(downloads)==2
    assert all('bicycle' in x['motion_prompt'] for x in first['storyboard']['shots'])


def test_license_filter_rejects_restricted_and_inconsistent_sources():
    from backend.app.media_library import licensed
    item={'license':'by','license_url':'https://creativecommons.org/licenses/by/4.0/',
        'foreign_landing_url':'https://example.org/work','url':'https://example.org/image.jpg'}
    assert licensed(item)
    assert not licensed({**item,'license':'by-nc'})
    assert not licensed({**item,'license_url':'https://example.org/licenses/by/4.0/'})
    assert not licensed({**item,'license_url':'https://creativecommons.org/licenses/by-nc/4.0/'})


def test_stock_search_uses_text_model_and_actual_frame_uses_vision(image_config,monkeypatch):
    from backend.app.providers import Evren,PERCEPTION_ROLE
    monkeypatch.setattr(image_config,'evren_model','text-model')
    monkeypatch.setattr(image_config,'evren_media_model','media-model')
    monkeypatch.setattr(image_config,'evren_media_model2','vision-model')
    llm=Evren()
    assert llm.model_for('Görsel Tasarımcı / Açık lisanslı kaynak planı')=='text-model'
    assert llm.model_for('Görsel Tasarımcı / Kaynak seçimi')=='text-model'
    assert llm.model_for(PERCEPTION_ROLE,[{}])=='vision-model'


def test_catalog_requests_do_not_inherit_long_editorial_timeout():
    from backend.app.media_library import ask
    class Director:
        timeout=1800
        def generate(self):
            assert self.timeout==90
            return 'ok'
    llm=Director()
    assert ask(llm)=='ok' and llm.timeout==1800


def test_four_stock_shots_use_one_vision_call_and_reuse_downloads(tmp_path,monkeypatch):
    from backend.app import media_library as library
    from backend.app.providers import PERCEPTION_ROLE,TransientProviderError
    shots=[{'shot_id':f'shot-{i:03}','reference_prompt':'A window in daylight.'} for i in range(4)]
    candidates=[{'id':str(i),'title':'Window','creator':'Artist','url':f'https://example.org/{i}.png',
        'foreign_landing_url':f'https://example.org/work/{i}','license':'cc0',
        'license_url':'https://creativecommons.org/publicdomain/zero/1.0/','width':576,'height':1024} for i in range(8)]
    downloads=[];calls=[]
    monkeypatch.setattr(library,'search',lambda *args:candidates)
    monkeypatch.setattr(library,'download',lambda url,*args:downloads.append(url) or png())
    class Director:
        timeout=1800
        def generate(self,schema,role,context,**kwargs):
            assert role==PERCEPTION_ROLE and self.timeout==180
            assert len(kwargs['media_inputs'])==8
            assert all(part['type']=='image_url' for part in kwargs['media_inputs'])
            assert [candidate['image_position'] for item in context['shots'] for candidate in item['candidates']]==list(range(1,9))
            calls.append(schema.__name__)
            if len(calls)==1:raise TransientProviderError('Temporary timeout')
            return {'shots':[{'shot_id':s['shot_id'],'image_position':context['shots'][{0:1,1:0}.get(i,i)]['candidates'][0]['image_position'],
                'suitable':True,'rationale':'Matches the visible scene.',
                'motion_prompt':'The camera slowly approaches the visible window.',
                'expected_action':'Pencereye yaklaşılır.','state_before':'A visible window.',
                'state_after':'A closer window.'} for i,s in enumerate(shots)]}
    llm=Director();queries={s['shot_id']:['window'] for s in shots}
    with pytest.raises(TransientProviderError):library.prepare_stock_batch(llm,shots,tmp_path,queries,lambda:None)
    assert len(downloads)==8 and llm.timeout==1800
    result=library.prepare_stock_batch(llm,shots,tmp_path,queries,lambda:None)
    cached=library.prepare_stock_batch(llm,shots,tmp_path,queries,lambda:None)
    assert result==cached and len(calls)==2 and len(downloads)==8
    assert result['shot-000']['info']['source']['id']=='2'
    assert result['shot-001']['info']['source']['id']=='0'
    assert all(value['info']['selection_method']=='batch_vision_v2' for value in result.values())


def test_music_catalog_outage_skips_legacy_generated_music(setup,monkeypatch):
    from backend.app import media_library as library
    from backend.tests.test_agentic import create_run
    ident=create_run({'script':{'scenes':[{'narration':'Bir düğme.'}]}})
    with DB() as db:
        run=db.get(Run,ident)
        folder=workdir(run.project_id,run.id)
        old_track=folder/'background-music.wav';old_track.write_bytes(b'old generated music')
        run.outputs={**run.outputs,'music':{'provider':'original_procedural','asset_id':register(db,run,old_track,'music',commit=False)}}
        db.commit()
    calls=[]
    class Director:
        def generate(self,schema,role,context,**kwargs):
            calls.append(role)
            return {'queries':['suspense instrumental','ambient'],'mood':'tense','bpm':78,'mode':'minor'}
    monkeypatch.setattr(library,'search',lambda *args:[])
    with DB() as db:p=db.get(Project,run.project_id)
    assert library.select_music(run,p,folder,Director(),lambda:None) is None
    with DB() as db:
        resumed=db.get(Run,run.id)
    assert library.select_music(resumed,p,folder,Director(),lambda:None) is None
    assert calls==['Müzik Seçici'] and old_track.read_bytes()==b'old generated music'
    assert resumed.outputs['music']['provider']=='none' and not resumed.outputs['music']['ducking']
    assert not list(folder.glob('background-music-licensed-*.wav'))


def test_music_tries_next_ranked_catalog_and_keeps_actual_credits(setup,monkeypatch):
    from backend.app import media, media_library as library
    from backend.tests.test_agentic import create_run
    ident=create_run({'script':{'scenes':[{'narration':'Piyano çalıyor.'}]}})
    with DB() as db:
        run=db.get(Run,ident)
        p=db.get(Project,run.project_id)
    folder=workdir(run.project_id,run.id)
    first={'catalog':'openverse','title':'Ambient piano','url':'https://example.org/one.mp3'}
    second={'catalog':'ccmixter','title':'Quiet piano','url':'https://ccmixter.org/content/quiet.mp3',
            'creator':'An artist','foreign_landing_url':'https://ccmixter.org/files/artist/1',
            'license':'by','license_url':'https://creativecommons.org/licenses/by/4.0/'}
    downloads=[]

    class Director:
        def generate(self,schema,role,context,**kwargs):
            if schema is library.MusicBrief:
                return {'queries':['piano instrumental'],'mood':'quiet','bpm':78,'mode':'minor'}
            assert [item['catalog'] for item in context['candidates']]==['openverse','ccmixter']
            return {'ranked':[{'index':0,'rationale':'Uygun ilk kayıt.'},{'index':1,'rationale':'Uygun ikinci kayıt.'}]}

    def download(url,check,**options):
        downloads.append(url)
        if url==first['url']:
            raise OSError('source unavailable')
        assert options=={'referer':second['foreign_landing_url']}
        return b'catalog music'

    monkeypatch.setattr(library,'search',lambda *args:[first,second])
    monkeypatch.setattr(library,'download',download)
    monkeypatch.setattr(media,'command',lambda args,*a,**kw:folder.joinpath(args[-1]).write_bytes(b'converted audio'))
    path=library.select_music(run,p,folder,Director(),lambda:None)
    assert downloads==[first['url'],second['url']] and path.read_bytes()==b'converted audio'
    with DB() as db:
        saved=db.get(Run,run.id).outputs['music']
    assert saved['provider']=='ccmixter' and saved['source']['creator']=='An artist' and saved['ducking']


def test_irrelevant_stock_is_never_saved_as_selected(tmp_path,monkeypatch):
    from backend.app import media_library as library
    from backend.app.providers import ProviderError
    item={'title':'Fingerprint wallpaper','creator':'Artist','url':'https://example.org/wallpaper.png',
        'foreign_landing_url':'https://example.org/work','license':'cc0','width':576,'height':1024,
        'license_url':'https://creativecommons.org/publicdomain/zero/1.0/'}
    monkeypatch.setattr(library,'search',lambda *args:[item])
    monkeypatch.setattr(library,'download',lambda *args:png())
    class Director:
        timeout=1800
        def generate(self,schema,role,context,**kwargs):
            assert context['story']['hook']=='A phone notification changes everything.'
            return {'shots':[{'shot_id':'shot-000','suitable':False,
                'rationale':'A wallpaper cannot depict a phone receiving a notification.'}]}
    with pytest.raises(ProviderError,match='İlgisiz adaylar reddedildi'):
        library.prepare_stock_batch(Director(),[{'shot_id':'shot-000','reference_prompt':'A man holding a phone.'}],
            tmp_path,{'shot-000':['phone']},lambda:None,story={'hook':'A phone notification changes everything.'})
    saved=json.loads(next(tmp_path.glob('stock-*.json')).read_text())
    assert not saved.get('selection') and saved['rejected_urls']==[item['url']]


def test_cloudflare_rate_limit_does_not_block_daily_budget(image_config,tmp_path):
    from backend.app.media_providers import cloudflare_image
    from backend.app.providers import TransientProviderError
    from backend.app.image_budget import report
    with pytest.raises(TransientProviderError):
        cloudflare_image('portrait',tmp_path/'x.png',lambda:None,
            transport=httpx.MockTransport(lambda req:httpx.Response(429)))
    assert report()['provider_blocked'] is False


@pytest.mark.parametrize('invalid_review',[False,True])
def test_wan_first_real_clip_gates_remaining_and_reuses_success(image_config,project,monkeypatch,invalid_review):
    from backend.app import wan_provider as wan,kaggle_provider as kaggle,media
    from backend.app.providers import InvalidModelOutput
    monkeypatch.setattr(image_config,'video_model_profile','wan22_q5_v1')
    run,shots=prepare_run(project);folder=workdir(run.project_id,run.id)
    image=folder/'reference.png';image.write_bytes(png())
    for i,shot in enumerate(shots):shot['image_index']=i
    submitted=[]
    class Gateway:
        def status(self,ref):return 'complete'
    monkeypatch.setattr(kaggle,'KaggleGateway',Gateway)
    def stage(run,folder,request,**kwargs):
        submitted.append([s['shot_id'] for s in request['shots']])
        ident='job-'+str(len(submitted));output=folder/'kaggle'/ident/'output';output.mkdir(parents=True)
        clips={}
        for shot in request['shots']:
            target=output/(shot['shot_id']+'.mp4');target.write_bytes(b'video')
            clips[shot['shot_id']]={'sha256':file_hash(target),'width':480,'height':832,'fps':24}
        return SimpleNamespace(id=ident,status='complete',result={'run_id':run.id,'revision':1,'runtime':'wan22-q5-v1','clips':clips})
    monkeypatch.setattr(kaggle,'stage_job',stage)
    monkeypatch.setattr(media,'inspect_clip',lambda *args:{'duration':3,'passed':True})
    reviewed=[]
    def review(*args):
        reviewed.append(args[2]['shot_id'])
        if invalid_review:
            raise InvalidModelOutput('Malformed SourceClipReview')
        return {'verdict':'pass','findings':[],'repair_stage':'motion','correction':''}
    monkeypatch.setattr(wan,'review_clip',review)
    result=wan.generate_clips(run,folder,{'shots':shots},[image,image],lambda:None)
    assert submitted==[['shot-000'],['shot-001']]
    assert len(result)==2
    if invalid_review:
        assert all(item['review_advisory'] and item['review']['verdict']=='uncertain' for item in result.values())
    wan.generate_clips(run,folder,{'shots':shots},[image,image],lambda:None)
    assert len(submitted)==2
    assert len(reviewed)==2


def test_source_clip_review_accepts_overlong_text_findings_on_first_response(tmp_path,monkeypatch):
    from backend.app import media, wan_provider
    from backend.app.providers import Evren, trace_calls
    for key,value in {'evren_api_key':'test','evren_base_url':'https://example.test/v1',
                      'evren_model':'test-model','evren_contract_verified':True,
                      'evren_protocol':'openai_chat'}.items():
        monkeypatch.setattr(settings(),key,value)
    frame=png()
    reference=tmp_path/'reference.png'
    reference.write_bytes(frame)
    monkeypatch.setattr(media,'command',lambda args,*a,**kw:args[-1].write_bytes(frame))
    calls=[]
    original={'verdict':'reject','findings':[str(i) for i in range(9)],
              'repair_stage':'motion','correction':'Özne sabit kalsın.'}
    def respond(request):
        calls.append(request)
        value=original if len(calls)==1 else {'type':'object','properties':{'findings':{'type':'array'}}}
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop',
            'message':{'content':json.dumps(value)}}]})
    metrics=[]
    with trace_calls(metrics.append):
        result=wan_provider.review_clip(tmp_path/'shot-008.mp4',reference,
            {'shot_id':'shot-008','scene_index':3,'duration_seconds':4},
            Evren(httpx.MockTransport(respond)),lambda:None)
    assert len(calls)==1
    assert result=={**original,'findings':original['findings'][:8]}
    assert [(m['shot_id'],m['scene_index'],m['status']) for m in metrics]==[('shot-008',3,'passed')]


def test_wan_failure_never_submits_remaining_shots(image_config,project,monkeypatch):
    from backend.app import wan_provider as wan,kaggle_provider as kaggle
    from backend.app.providers import ProviderError
    monkeypatch.setattr(image_config,'video_model_profile','wan22_q5_v1')
    run,shots=prepare_run(project);folder=workdir(run.project_id,run.id)
    image=folder/'reference.png';image.write_bytes(png())
    for i,shot in enumerate(shots):shot['image_index']=i
    calls=[]
    monkeypatch.setattr(kaggle,'KaggleGateway',lambda:SimpleNamespace(status=lambda ref:'complete'))
    def stage(run,folder,request,**kwargs):
        calls.append(request)
        return SimpleNamespace(id='broken',status='complete',result={'run_id':run.id,'revision':1,
            'runtime':'wan22-q5-v1','fatal':'runtime_or_inference_configuration'})
    monkeypatch.setattr(kaggle,'stage_job',stage)
    for _ in range(2):
        with pytest.raises(ProviderError):wan.generate_clips(run,folder,{'shots':shots},[image,image],lambda:None)
    assert len(calls)==1 and len(calls[0]['shots'])==1


def test_wan_runtime_script_is_self_contained_and_shards_are_private(image_config,project):
    from backend.app.kaggle_provider import stage_job
    run,_=prepare_run(project);folder=workdir(run.project_id,run.id)
    job=stage_job(run,folder,{'runtime':'wan22-q5-v1','component':'high'},bootstrap=True)
    root=folder/'kaggle'/job.id
    metadata=json.loads((root/'kernel-metadata.json').read_text())
    assert metadata['is_private'] and not metadata['enable_gpu']
    assert metadata['id'].endswith('-high')
    script=(root/'run.py').read_text(encoding='utf-8')
    assert 'wan-bootstrap.json' in script and 'SAHNE_SOURCE_DIR' in script
    compile(script,str(root/'run.py'),'exec')
    with DB() as db:
        from backend.app.db import RemoteJob
        db.get(RemoteJob,job.id).account_slot=None
        db.commit()
    image=folder/'reference.png';image.write_bytes(png())
    request={'runtime':'wan22-q5-v1','run_id':run.id,'revision':1,'images':['reference.png'],
        'image_hashes':[file_hash(image)],'shots':[]}
    gpu_job=stage_job(run,folder,request,runtime_source=['owner/core','owner/high','owner/low'])
    gpu_root=folder/'kaggle'/gpu_job.id
    gpu_metadata=json.loads((gpu_root/'kernel-metadata.json').read_text())
    assert gpu_metadata['kernel_sources']==['owner/core','owner/high','owner/low']
    assert gpu_metadata['enable_gpu'] and not gpu_metadata['enable_internet']
    assert json.loads((gpu_root/'inputs'/'wan-request.json').read_text())==request
    compile((gpu_root/'run.py').read_text(encoding='utf-8'),'wan.py','exec')


def test_wan_workflow_runs_experts_in_separate_graphs():
    from backend.kaggle.wan_workflow import graphs,frames_for
    from backend.app.wan_provider import LOCK
    high,low=graphs(json.loads(LOCK.read_text()),{'shot_id':'shot-000','camera':'locked',
        'motion_prompt':'She turns her head.','duration_seconds':5},'input.png',42)
    assert frames_for(5)==121
    assert high['1']['inputs']['unet_name'].endswith('HighNoise-Q5_K_M.gguf')
    assert low['1']['inputs']['unet_name'].endswith('LowNoise-Q5_K_M.gguf')
    assert high['9']['inputs']['end_at_step']==low['4']['inputs']['start_at_step']==10
    assert not any('LoRA' in n['class_type'] for n in [*high.values(),*low.values()])


def test_wan_bootstrap_completion_releases_slot_before_next_shard(image_config,project,monkeypatch):
    from backend.app import wan_provider as wan,kaggle_provider as kaggle
    from backend.app.db import RemoteJob
    monkeypatch.setattr(image_config,'video_model_profile','wan22_q5_v1')
    monkeypatch.setattr(image_config,'kaggle_username','test-account')
    monkeypatch.setattr(image_config,'wan_runtime_source','')
    run,_=prepare_run(project);folder=workdir(run.project_id,run.id)
    lock_hash=file_hash(wan.LOCK)
    core=kaggle.stage_job(run,folder,{'runtime':'wan22-q5-v1','component':'core',
        'lock_sha256':lock_hash},bootstrap=True)
    with DB() as db:
        db.get(RemoteJob,core.id).status='running';db.commit()
    complete={'core'};submitted=[]
    class Gateway:
        def status(self,ref):return 'complete' if ref.split('/')[1].rsplit('-',1)[-1] in complete else 'missing'
        def submit(self,root,gpu):
            assert gpu is False
            submitted.append(json.loads((root/'kernel-metadata.json').read_text())['id'].rsplit('-',1)[-1])
            return 1
    gateway=Gateway()
    for finished,next_shard in [('core','high'),('high','low')]:
        complete.add(finished)
        with pytest.raises(kaggle.RemotePending):
            wan.prepare_runtime(run,folder,gateway,image_config,lock_hash)
        with DB() as db:
            jobs=list(db.scalars(select(RemoteJob).where(RemoteJob.run_id==run.id)))
            assert [j.kernel.rsplit('-',1)[-1] for j in jobs if j.account_slot]==[next_shard]
            assert all(j.status=='complete' for j in jobs if j.kernel.rsplit('-',1)[-1] in complete)
    complete.add('low')
    assert len(wan.prepare_runtime(run,folder,gateway,image_config,lock_hash))==3
    with DB() as db:
        assert not db.scalar(select(RemoteJob.id).where(RemoteJob.account_slot.is_not(None)))
    assert submitted==['high','low']


def test_media_acceptance_is_bound_to_owned_file_and_current_input(image_config,project,clients):
    from backend.app.visual_quality import digest
    alice,bob=clients
    run,_=prepare_run(project);folder=workdir(run.project_id,run.id)
    path=folder/'candidate.png';path.write_bytes(png())
    with DB() as db:
        asset_id=register(db,run,path,'image')
        current=db.get(Run,run.id)
        current.status='waiting_input'
        current.outputs={**current.outputs,'_media_review':{'shot_id':'shot-000','asset_id':asset_id,
            'sha256':file_hash(path),'signature':'input-a','stage':'visual',
            'review':{'verdict':'uncertain','findings':['Needs review']}}}
        db.commit()
    body={'shot_id':'shot-000','asset_id':asset_id,'accept':True}
    endpoint='/api/v1/runs/'+run.id+'/media-review'
    assert bob.post(endpoint,json=body).status_code==404
    assert alice.post(endpoint,json={**body,'asset_id':'stale'}).status_code==409
    assert alice.post(endpoint,json=body).status_code==202
    with DB() as db:
        current=db.get(Run,run.id)
        assert current.outputs['_media_acceptances']['shot-000']==digest([file_hash(path),'input-a'])
        assert '_media_review' not in current.outputs


@pytest.mark.parametrize('action,batch',[('image',False),('motion',False),('image',True)])
def test_shot_change_keeps_other_sources_and_audio(image_config,project,clients,action,batch,monkeypatch):
    from copy import deepcopy
    from backend.app.motion import generate_missing_clips
    from backend.app import motion
    # Complete, owned two-shot source with distinct image and clip assets.
    alice,_=clients
    run,shots=prepare_run(project);folder=workdir(run.project_id,run.id)
    with DB() as db:
        images={};clips={}
        for shot in shots:
            ident=shot['shot_id']
            image=folder/(ident+'.png');image.write_bytes(png())
            images[ident]=register(db,run,image,'image')
            clip=folder/(ident+'.mp4');clip.write_bytes(ident.encode())
            clips[ident]={'asset_id':register(db,run,clip,'clip'),'file':clip.name,
                'report':{'duration':3},'reference_hash':file_hash(image),'duration_seconds':3,'scene_index':shot['scene_index']}
        audio=folder/'voice.wav';audio.write_bytes(b'audio')
        voice_id=register(db,run,audio,'audio')
        current=db.get(Run,run.id)
        current.status='awaiting_approval'
        current.outputs={**current.outputs,'voice':{'audios':[voice_id,voice_id],'durations':[3,3]},
            'visual':{'images':list(images.values()),'cover':images['shot-000'],'shot_images':images,'storyboard':{'shots':shots}},
            'motion':{'mode':'video','plan':{'shots':shots},'clips':clips},'editor':{'video':'existing'}}
        db.commit()
        old=deepcopy(current.outputs)
    response=alice.post('/api/v1/projects/'+project['id']+'/shots/shot-000/change',json={
        'run_id':run.id,'action':action,'instructions':'Başını biraz daha yavaş çevirsin.',
        'shot_ids':['shot-000','shot-001'] if batch else []})
    assert response.status_code==202,response.text
    with DB() as db:
        new=db.get(Run,response.json()['id'])
        assert new.revision==2 and db.get(Run,run.id).outputs==old
        assert new.outputs['_changed_shots']==(['shot-000','shot-001'] if batch else ['shot-000'])
        assert new.outputs['voice']['durations']==[3,3]
        assert 'voice' not in new.outputs['_repair_stages']
        assert new.outputs['_reuse_motion']['clips']['shot-001']['reference_hash']==old['motion']['clips']['shot-001']['reference_hash']
        assert ('visual' in new.outputs)==(action=='motion')
    if batch:
        from backend.app import orchestration as agent
        monkeypatch.setattr(agent,'initial_brief',lambda *args:None)
        monkeypatch.setattr(agent,'fit_voice_boundary',lambda *args:None)
        monkeypatch.setattr(agent,'voice_valid',lambda *args:True)
        monkeypatch.setattr(agent,'supervisor_decision',lambda *args:pytest.fail('Explicit shot repair must not call the routing model'))
        assert agent.supervise(new.id)=='visual'
    if action=='motion':
        requested=[]
        def generate(run,folder,plan,paths,check):
            requested.extend(s['shot_id'] for s in plan['shots'])
            return {'shot-000':{'new':True}}
        monkeypatch.setattr('backend.app.kaggle_provider.generate_clips',generate)
        result=generate_missing_clips(new,workdir(new.project_id,new.id),new.outputs['_reuse_motion']['plan'],
            [new.outputs['visual']['shot_images'][s['shot_id']] for s in shots],lambda:None)
        assert requested==['shot-000']
        assert result['shot-001']==new.outputs['_reuse_motion']['clips']['shot-001']


def test_source_repair_budget_is_durable_and_bounded(image_config,project):
    from backend.app.visual_quality import reserve_repair
    run,_=prepare_run(project)
    assert reserve_repair(run.id,'shot-000','visual')
    assert not reserve_repair(run.id,'shot-000','visual')
    assert reserve_repair(run.id,'shot-001','motion')
    assert reserve_repair(run.id,'shot-002','motion')
    assert not reserve_repair(run.id,'shot-003','motion')


def test_wan_unattempted_shots_resume_after_failed_shot_is_changed(image_config,project,monkeypatch):
    from backend.app import wan_provider as wan,kaggle_provider as kaggle,media
    from backend.app.providers import ProviderError
    monkeypatch.setattr(image_config,'video_model_profile','wan22_q5_v1')
    run,shots=prepare_run(project)
    shots.append({**shots[-1],'shot_id':'shot-002'})
    folder=workdir(run.project_id,run.id);image=folder/'ref.png';image.write_bytes(png())
    for i,s in enumerate(shots):s['image_index']=i
    calls=[]
    monkeypatch.setattr(kaggle,'KaggleGateway',lambda:SimpleNamespace(status=lambda ref:'complete'))
    def stage(run,folder,request,**kwargs):
        calls.append([s['shot_id'] for s in request['shots']])
        ident='job-'+str(len(calls));output=folder/'kaggle'/ident/'output';output.mkdir(parents=True)
        result={'run_id':run.id,'revision':1,'runtime':'wan22-q5-v1','clips':{}}
        if len(calls)==2:result['errors']={'shot-001':'inference_failed'}
        else:
            for s in request['shots']:
                path=output/(s['shot_id']+'.mp4');path.write_bytes(b'video')
                result['clips'][s['shot_id']]={'sha256':file_hash(path),'width':480,'height':832,'fps':24}
        return SimpleNamespace(id=ident,status='complete',result=result)
    monkeypatch.setattr(kaggle,'stage_job',stage)
    monkeypatch.setattr(media,'inspect_clip',lambda *a:{'duration':3})
    monkeypatch.setattr(wan,'review_clip',lambda *a:{'verdict':'pass','findings':[]})
    with pytest.raises(ProviderError):wan.generate_clips(run,folder,{'shots':shots},[image]*3,lambda:None)
    state=json.loads((folder/'wan-clips.json').read_text())
    assert 'failure' in state['shot-001'] and 'failure' not in state['shot-002']
    run.outputs={**run.outputs,'_shot_nonces':{'shot-001':'explicit-user-correction'}}
    assert len(wan.generate_clips(run,folder,{'shots':shots},[image]*3,lambda:None))==3
    assert calls==[['shot-000'],['shot-001','shot-002'],['shot-001','shot-002']]
