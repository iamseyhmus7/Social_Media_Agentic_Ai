"""Durable finite Wan jobs; first production shot gates the remaining work."""
import json
import shutil
from pathlib import Path
from sqlalchemy import select
from .config import settings
from .db import DB, RemoteJob
from .providers import ProviderError, InvalidModelOutput, Evren, PERCEPTION_ROLE
from .schemas import SourceClipReview
from .storage import file_hash, register
from .visual_quality import digest, atomic_json, image_input, accepted, reserve_repair

LOCK = Path(__file__).resolve().parents[1]/'kaggle'/'wan_runtime_lock.json'
ENGINE_REVISION = 'wan-gpu-conditioning-v2-lightning4'
ACCELERATION_LOCK = LOCK.with_name('wan_acceleration_lock.json')
FASTWAN_LOCK = LOCK.with_name('fastwan_runtime_lock.json')
REVIEW_POLICY = 'wan-input-crop-and-action-v2'


def conditioning_cache(folder):
    """Only reuse verified outputs belonging to this run's private directory."""
    import re
    cache=folder/'wan-conditioning';cache.mkdir(exist_ok=True)
    for result_file in (folder/'kaggle').glob('*/output/result.json'):
        if result_file.stat().st_size>256_000:continue
        try: metadata=json.loads(result_file.read_text())
        except (OSError,ValueError):continue
        for item in metadata.get('conditioning_cache',[])[:64]:
            name=item.get('file','')
            if not re.fullmatch(r'cond-[a-f0-9]{64}\.pt',name):continue
            source=result_file.parent/'conditioning'/name
            if not source.is_file():source=result_file.parent/name
            if not source.is_file() or not 0<source.stat().st_size<=64*1024**2 or file_hash(source)!=item.get('sha256'):continue
            target=cache/name
            if not target.is_file() or file_hash(target)!=item['sha256']:shutil.copyfile(source,target)
    return [{'file':p.name,'sha256':file_hash(p)} for p in sorted(cache.glob('cond-*.pt'))
        if re.fullmatch(r'cond-[a-f0-9]{64}\.pt',p.name) and 0<p.stat().st_size<=64*1024**2][:64]


def review_clip(path, reference, shot, llm, check):
    from . import media
    from PIL import Image,ImageOps
    scratch=path.parent/(path.stem+'-review');scratch.mkdir(exist_ok=True)
    # Match generate_wan's actual I2V input, including a square source's crop.
    prepared_reference=scratch/'reference-input.png'
    with Image.open(reference) as source:
        ImageOps.fit(source.convert('RGB'),(480,832)).save(prepared_reference)
    seconds=shot['duration_seconds']
    frames=[]
    # Adjacent frames around the middle supplement sparse beginning/end samples.
    times=[seconds*.05,*[seconds*.5+i/24 for i in (-2,-1,0,1,2)],seconds*.92]
    for index,time in enumerate(times):
        check()
        target=scratch/f'{index}.jpg'
        media.command([settings().ffmpeg_bin,'-y','-ss',str(max(0,min(seconds-.05,time))),
            '-i',path,'-frames:v','1','-vf','scale=384:666',target],scratch,check,timeout=60)
        frames.append(image_input(target,(384,666)))
    return SourceClipReview.model_validate(llm.generate(SourceClipReview,PERCEPTION_ROLE,{
        'shot_id':shot['shot_id'],'scene_index':shot['scene_index'],'shot':shot,'sample_times':times,
        'expected_changes':{'camera':shot.get('camera'),'action':shot.get('motion_prompt')},
        'reference_transform':{'method':'center_crop_fit','width':480,'height':832},
        'instruction':'İlk görsel modele verilen gerçek 480x832 başlangıç kadrajı, diğerleri zaman sıralı klip örnekleridir. '
        'Beklenen eylem gerçekten görülüyor mu, özne/kimlik/mekân korunuyor mu, anatomi ve titreme kusuru var mı incele. '
        'motion_prompt içinde açıkça istenen olayın sonradan belirmesini veya gelişmesini kaynak tutarsızlığı sayma. '
        'İstenen değişimleri, istenmeyen kimlik/mekân değişiminden ayrı değerlendir. '
        'Kamera hareketiyle kadraj dışına çıkan öğeyi tek başına kimlik kaybı sayma. '
        'Kamera hareketini özne eylemi olarak sayma. Örnekler tüm hareketi kanıtlamaz. Kanıt yetersizse uncertain. '
        'Kaynak başlangıç karesi kusurluysa repair_stage=visual; hareket/klip kusurunda motion. '
        'Küçük estetik farkları reddetme; correction yalnız ilgili kusuru düzeltsin. '
        'En önemli en fazla 8 bulguyu kısa metinler olarak yaz. JSON şemasının kendisini değil, değerlendirme verisini döndür. '
        'Yanıt biçimine örnek: {"verdict":"uncertain","findings":["Örnek kareler eylemi doğrulamaya yetmiyor."],'
        '"repair_stage":"motion","correction":""}. Değerleri bu klipte gördüklerine göre belirle.'},
        media_inputs=[image_input(prepared_reference,(384,666)),*frames],max_attempts=2,
        repair_fields=True,compact_schema=True)).model_dump()


def prepare_runtime(run,folder,gateway,cfg,lock_hash):
    from .kaggle_provider import stage_job, advance_job
    runtime='wan22-q5-v1'
    base=cfg.wan_runtime_source or cfg.kaggle_username+'/sahne-'+runtime
    sources=[]
    fast=cfg.video_model_profile=='fastwan5b_v1'
    components=['core','fastwan5b'] if fast else ['core','high','low']
    if not fast and cfg.wan_sampling_profile=='lightning4_v1':components.append('lightning4')
    for component in components:
        source=(cfg.kaggle_username+'/sahne-fastwan5b-v1-fastwan5b') if component=='fastwan5b' else base+'-'+component
        # A completed remote bootstrap must release its durable account slot
        # before the next shard can be staged, including after a worker restart.
        with DB() as db:
            outstanding=db.scalar(select(RemoteJob).where(RemoteJob.run_id==run.id,
                RemoteJob.kernel==source,RemoteJob.account_slot.is_not(None)))
        if outstanding:
            advance_job(outstanding,folder,gateway,bootstrap=True)
        if gateway.status(source) not in ('complete','completed'):
            if cfg.wan_runtime_source:
                raise ProviderError('Özel Wan çalışma paketinin core/high/low kaynakları hazır değil; GPU işi başlatılmadı.')
            manifest={'runtime':runtime,'component':component,'lock_sha256':lock_hash}
            if component=='fastwan5b':
                manifest.update(runtime='fastwan5b-v1',component='fastwan5b',fastwan_lock_sha256=file_hash(FASTWAN_LOCK))
            if component=='lightning4':manifest['acceleration_sha256']=file_hash(ACCELERATION_LOCK)
            job=stage_job(run,folder,manifest,bootstrap=True)
            advance_job(job,folder,gateway,bootstrap=True)
        sources.append(source)
    return sources


def generate_clips(run,folder,plan,image_paths,check,*,allow_repair=True,on_ready=None):
    from .agent_progress import mark
    from .kaggle_provider import KaggleGateway, stage_job, advance_job
    from . import media
    check()
    cfg=settings()
    gateway=None
    sources=None
    fast=cfg.video_model_profile=='fastwan5b_v1'
    lock_hash=file_hash(FASTWAN_LOCK if fast else LOCK)
    runtime='fastwan5b-v1' if fast else 'wan22-q5-v1'
    profile='dmd3_v1' if fast else cfg.wan_sampling_profile
    with DB() as db:
        live_job=db.scalar(select(RemoteJob.id).where(RemoteJob.run_id==run.id,RemoteJob.account_slot.is_not(None)))
    if not live_job:
        mark(run.id,'motion','runtime','Video çalışma ortamı ve mevcut model dosyaları kontrol ediliyor',
            completed=0,total=len(plan['shots']))
    journal=folder/('fastwan-clips.json' if fast else 'wan-clips.json')
    state=json.loads(journal.read_text(encoding='utf-8')) if journal.is_file() else {}
    opening_batch = set()
    config = run.outputs.get('_config', {})
    if (fast and on_ready and run.outputs.get('_edit_style') == 'auto'
            and config.get('video_execution_policy') == 'planned_v1'
            and config.get('video_edit_policy') == 'scenes_v3' and config.get('editor_streaming_enabled')
            and not run.outputs.get('_reuse_motion')):
        batch_path = folder / 'opening-motion-batch.json'
        if batch_path.is_file():
            opening_batch = set(json.loads(batch_path.read_text(encoding='utf-8')))
        elif not state and not live_job:
            scene = plan['shots'][0]['scene_index']
            opening = [s['shot_id'] for s in plan['shots'] if s['scene_index'] == scene]
            if len(opening) < len(plan['shots']):
                atomic_json(batch_path, opening)
                opening_batch = set(opening)
    images=[]
    for i,path in enumerate(image_paths):
        name=f'wan-reference-{i}-{file_hash(path)[:12]}.png'
        if not (folder/name).is_file(): shutil.copyfile(path,folder/name)
        images.append(name)
    image_hashes=[file_hash(p) for p in image_paths]
    profile_key=[profile] if profile!='standard20' else []
    certificate=cfg.media_root.resolve().parent/('wan-accepted-'+digest([cfg.kaggle_username,lock_hash,*profile_key])[:24]+'.json')
    # A certificate controls admission only, never reuse of another user's media.
    admitted=False
    if certificate.is_file():
        try: admitted=json.loads(certificate.read_text()).get('lock_sha256')==lock_hash
        except (OSError,ValueError): pass
    signatures={s['shot_id']:digest({'lock':lock_hash,'shot':s,'reference':image_hashes[s['image_index']],
        'nonce':run.outputs.get('_shot_nonces',{}).get(s['shot_id']),
        **({'sampling_profile':profile,'acceleration_lock':file_hash(FASTWAN_LOCK if fast else ACCELERATION_LOCK)} if profile_key else {}),
        'session':run.outputs.get('_motion_session')}) for s in plan['shots']}
    valid={}
    while len(valid)<len(plan['shots']):
        check()
        pending=[]
        for shot in plan['shots']:
            ident=shot['shot_id'];signature=signatures[ident]
            entry=state.get(ident,{})
            if entry.get('signature')!=signature:
                entry={'signature':signature,'attempt':0}
                state[ident]=entry
            if entry.get('failure'):
                raise ProviderError('Wan çekimi önceki çalışmada başarısız oldu. Aynı GPU işi otomatik tekrarlanmadı; ilgili çekime yeni düzeltme isteği verebilirsin.')
            item=entry.get('clip')
            if not item:
                pending.append(shot);continue
            path=folder/item['file']
            if not path.is_file() or file_hash(path)!=item['sha256']:
                raise ProviderError('Kayıtlı Wan klibinin dosyası veya özeti değişti; yeniden GPU üretimi başlatılmadı.')
            if not entry.get('review') or entry.get('review_policy')!=REVIEW_POLICY:
                if entry.get('review'):
                    entry['review_history']=[*entry.get('review_history',[]),entry['review']][-2:]
                mark(run.id,'motion','clip_review',f'{ident}: görüntü ve hareket kalitesi inceleniyor',
                    completed=len(valid),total=len(plan['shots']))
                try:
                    entry['review']=review_clip(path,image_paths[shot['image_index']],shot,Evren(),check)
                except InvalidModelOutput:
                    # This advisory inspection must not invalidate an already
                    # verified clip or request a GPU repair without evidence.
                    entry['review']=SourceClipReview(
                        verdict='uncertain',
                        findings=['Görsel inceleme modeli geçerli bir değerlendirme döndürmedi.'],
                    ).model_dump()
                    mark(run.id,'motion','clip_review_advisory',f'{ident}: klip korundu, içerik değerlendirmesi doğrulanamadı',
                        completed=len(valid),total=len(plan['shots']))
                entry['review']['_policy']=REVIEW_POLICY
                entry['review_policy']=REVIEW_POLICY
                atomic_json(journal,state)
            review=entry['review']
            if review['verdict']=='pass' or accepted(run,ident,item['sha256'],signature):
                valid[ident]={**item,'review':review,'reference_hash':image_hashes[shot['image_index']],
                    'model_profile':item.get('generation',{}).get('profile',cfg.video_model_profile)}
                if not admitted:
                    atomic_json(certificate,{'lock_sha256':lock_hash,'reviewed_clip_sha256':item['sha256']})
                    admitted=True
                continue
            stage=review.get('repair_stage','motion')
            if allow_repair and stage=='motion' and review['verdict']=='reject' and entry['attempt']==0 and reserve_repair(run.id,ident,stage):
                entry.update(attempt=1,correction=review.get('correction',''))
                entry.pop('clip',None);entry.pop('review',None)
                atomic_json(journal,state)
                pending.append(shot)
                continue
            # Source-review uncertainty is advisory; only the finished video asks
            # for human approval. Do not reopen image generation from clip review.
            valid[ident]={**item,'review':review,'review_advisory':True,
                'reference_hash':image_hashes[shot['image_index']],'model_profile':item.get('generation',{}).get('profile',cfg.video_model_profile)}
            if not admitted:
                atomic_json(certificate,{'lock_sha256':lock_hash,'reviewed_clip_sha256':item['sha256'],
                    'review_advisory':True})
                admitted=True
        if not pending: break
        if on_ready:
            on_ready(valid)
        if gateway is None:
            gateway=KaggleGateway()
            sources=prepare_runtime(run,folder,gateway,cfg,file_hash(LOCK))
        selected=pending if admitted or fast else pending[:1]
        opening_pending = [shot for shot in pending if shot['shot_id'] in opening_batch]
        if opening_pending:
            selected = opening_pending
        shots=[{**shot,'motion_prompt':shot['motion_prompt']+' '+state[shot['shot_id']].get('correction','')}
               for shot in selected]
        request={'version':2,'run_id':run.id,'revision':run.revision,'runtime':runtime,'lock_sha256':lock_hash,
            'engine':'fastwan5b-dmd3-v1' if fast else ENGINE_REVISION,'conditioning_cache':conditioning_cache(folder),
            'sampling_profile':profile,
            **({'acceleration_sha256':file_hash(ACCELERATION_LOCK)} if profile_key and not fast else {}),
            'images':images,'image_hashes':image_hashes,'shots':shots,
            **({'completed_before':len(valid),'total_shots':len(plan['shots'])} if fast else {}),
            **({'live_previews':True} if fast and cfg.live_clip_previews else {}),
            'session':digest([run.outputs.get('_motion_session'),[(s['shot_id'],signatures[s['shot_id']],state[s['shot_id']]['attempt']) for s in selected]])}
        job=stage_job(run,folder,request,runtime_source=sources)
        if job.status=='prepared':
            mark(run.id,'motion','gpu_job',f'{len(valid)}/{len(plan["shots"])} çekim hazır; kalan çekimler GPU’da hazırlanıyor',
                completed=len(valid),total=len(plan['shots']))
        result=job.result if job.status=='complete' else advance_job(job,folder,gateway)
        if result.get('run_id')!=run.id or result.get('revision')!=run.revision or result.get('runtime')!=runtime:
            raise ProviderError('Wan sonucu güncel üretimle eşleşmiyor.')
        if result.get('sampling_profile','standard20')!=profile:
            raise ProviderError('Wan sonucu istenen örnekleme profiliyle eşleşmiyor.')
        output=folder/'kaggle'/job.id/'output'
        failed=False
        first_missing=next((s['shot_id'] for s in selected if s['shot_id'] not in result.get('clips',{})),None)
        for shot in selected:
            ident=shot['shot_id'];entry=state[ident]
            metadata=result.get('clips',{}).get(ident,{})
            source=output/(ident+'.mp4')
            try:
                if not source.is_file() or file_hash(source)!=metadata.get('sha256'):
                    raise RuntimeError('Missing committed clip')
                report=media.inspect_clip(source,shot['duration_seconds'],check)
                if (metadata.get('width'),metadata.get('height'),metadata.get('fps'))!=(480,832,24):
                    raise RuntimeError('Unexpected Wan dimensions')
                target=folder/(ident+'-wan-'+entry['signature'][:12]+f"-{entry['attempt']}.mp4")
                shutil.copyfile(source,target)
                with DB() as db:
                    asset_id=register(db,run,target,'clip',commit=False)
                    completed_job=db.get(RemoteJob,job.id)
                    if completed_job:
                        live=dict(completed_job.result.get('live_clips',{}))
                        live[ident]={'asset_id':asset_id,'duration_seconds':shot['duration_seconds'],'original':True}
                        completed_job.result={**completed_job.result,'live_clips':live}
                    db.commit()
                entry['clip']={'file':target.name,'asset_id':asset_id,'sha256':file_hash(target),
                    'scene_index':shot['scene_index'],'duration_seconds':shot['duration_seconds'],
                    'report':report,'generation':metadata}
            except media.Cancelled:
                raise
            except RuntimeError:
                # The remote worker stops at the first error. Later shots were
                # never attempted and must remain eligible after that shot is fixed.
                if ident in result.get('errors',{}) or metadata or ident==first_missing:
                    entry['failure']='runtime_or_inference_configuration' if result.get('fatal') else 'clip_failed'
                failed=True
        atomic_json(journal,state)
        if failed:
            raise ProviderError('Wan çalışma ortamı veya çekim doğrulanamadı. Kalan GPU üretimi durduruldu; başarılı klipler ve hazır ses/görseller korundu. Aynı başarısız iş otomatik tekrarlanmadı.')
    return valid
