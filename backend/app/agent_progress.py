"""Small, durable activity receipts for the production diagram."""
from .db import DB, Run, Event, now
from .agents import AGENTS

TASKS = {
    'AdditionalViews':'4 saniye sınırı için eksik görsel çekimler planlanıyor',
    'StockSearchPlan':'Açık lisanslı görseller için arama planı hazırlanıyor',
    'SearchBrief':'Sahneye uygun görsel arama sorguları hazırlanıyor',
    'LibraryChoice':'Arama sonuçlarından uygun kaynak seçiliyor',
    'StockDirection':'Bulunan görsele uygun hareket planı hazırlanıyor',
    'ExactStockBatch':'Çekimlerin görselleri toplu seçiliyor ve hareket yönergeleri hazırlanıyor',
    'MusicBrief':'Senaryonun müzik tonu ve temposu belirleniyor',
    'ClipPerception':'Doğrulanmış çekimlerin kareleri inceleniyor',
    'EditLook':'Sahnelerin ortak kurgu yönü hazırlanıyor',
    'GroundedScene':'Kaynakları hazır sahnenin kurgusu hazırlanıyor',
    'Storyboard':'Çekim açıları ve hareketler planlanıyor',
    'ReferenceStoryboard':'Çekim açıları ve görsel süreklilik planlanıyor',
    'CastingShortlist':'Senaryoya uygun Türkçe ses adayları seçiliyor',
    'VoiceShortlist':'Türkçe ses adayları seçiliyor',
    'VoiceCastingDecision':'Ses kayıtları dinlenip karşılaştırılıyor',
    'QualityReview':'Görüntü, ses ve kurgu bütünlüğü kontrol ediliyor',
    'PublicationCopy':'Paylaşım metinleri hazırlanıyor',
    'Copy':'Paylaşım metinleri hazırlanıyor',
}
START = {
    'supervisor':'Konu ve üretim hedefleri değerlendiriliyor',
    'strategy':'İçerik yaklaşımı ve kaynaklar hazırlanıyor',
    'script':'Açılış kancası, anlatım ve sahneler yazılıyor',
    'voice':'Anlatıcı seçimi ve seslendirme hazırlanıyor',
    'visual':'Sahnelere uygun görseller hazırlanıyor',
    'motion':'Görseller hareketli çekimlere dönüştürülüyor',
    'music':'Senaryoya uygun arka plan müziği seçiliyor',
    'editor':'Çekimler, anlatım ve müzik birleştiriliyor',
    'publisher':'Paylaşım paketi hazırlanıyor',
}
PENDING = {
    'supervisor':'Üretim kuyruğuna alınmayı bekliyor',
    'strategy':'Üretim planını bekliyor', 'script':'İçerik stratejisini bekliyor',
    'voice':'Senaryonun hazırlanmasını bekliyor',
    'visual':'Senaryoyu ve ses sürelerini bekliyor',
    'motion':'Görsellerin hazırlanmasını bekliyor',
    'music':'Onaylı senaryoyla arka plan müziği seçilecek',
    'editor':'Kurgulanabilir sahne için doğrulanmış çekimler ve seslendirme bekleniyor',
    'publisher':'Videonun ve kalite kontrolünün tamamlanmasını bekliyor',
}


def mark(run_id, agent, phase, label, *, detail='', completed=None, total=None, parallel=None):
    from sqlalchemy import select
    from .parallel_work import run_write_lock
    with run_write_lock, DB() as db:
        run = db.scalar(select(Run).where(Run.id==run_id).with_for_update())
        if not run: return
        agent = agent or run.stage
        if agent=='quality': agent='editor'
        progress = dict(run.outputs.get('_agent_progress',{}))
        prior = progress.get(agent,{})
        value = {'phase':phase,'label':label[:240],'detail':detail[:400],
                 'completed':completed if completed is not None else prior.get('completed'),
                 'total':total if total is not None else prior.get('total'),'updated_at':now()}
        if parallel is not None or prior.get('parallel'):
            value['parallel'] = prior.get('parallel') if parallel is None else parallel
        progress[agent] = value
        run.outputs = {**run.outputs,'_agent_progress':progress}
        run.updated = now()
        if prior.get('phase')!=phase or prior.get('label')!=value['label']:
            db.add(Event(run_id=run.id,stage=agent,message=value['label']))
        db.commit()


def model_task(run_id, schema, role):
    name = schema.__name__
    agent = 'music' if role.startswith('Müzik Seçici') else 'editor' if role.startswith('Video Editörü') else None
    label = TASKS.get(name)
    if not label and 'Storyboard' in name: label='Çekim açıları ve hareketler planlanıyor'
    if not label:
        with DB() as db:
            run=db.get(Run,run_id)
            label=START.get(agent or run.stage,'Görev değerlendiriliyor')
    mark(run_id,agent,'model:'+name,label)


def kaggle_activity(message):
    """Translate known events only; never publish raw remote logs."""
    import json
    phases={'input_validation':'Görsel ve çekim girdileri doğrulanıyor',
        'runtime_verification':'Video çalışma ortamı doğrulanıyor',
        'copy_comfy':'Video çalışma ortamı hazırlanıyor','package_install':'Video bağımlılıkları hazırlanıyor',
        'gpu_check':'GPU bağlantısı kontrol ediliyor','stage_text':'Metin kodlayıcı GPU için hazırlanıyor',
        'stage_vae':'Görüntü çözücü hazırlanıyor','stage_acceleration':'4 adımlı hız profili hazırlanıyor',
        'comfy_start':'Video üretim motoru başlatılıyor','stage_high_expert':'İlk video modeli GPU için hazırlanıyor',
        'high_noise_graph':'İlk hareket örneklemesi yapılıyor','expert_unload':'Sonraki örnekleme aşamasına geçiliyor',
        'stage_low_expert':'Ayrıntı modeli GPU için hazırlanıyor',
        'low_noise_graph_and_decode':'Hareket ayrıntıları ve video kareleri oluşturuluyor',
        'stage_fastwan':'FastWan 5B modeli GPU için hazırlanıyor',
        'fastwan_sampling':'FastWan 5B ile hareket üretiliyor',
        'model_download':'Video modeli kalıcı çalışma paketine hazırlanıyor',
        'model_conversion':'FastWan modeli T4 için FP16 biçimine hazırlanıyor',
        'video_encoding':'Hazır kareler video dosyasına dönüştürülüyor'}
    latest=None
    for line in str(message).splitlines():
        if not line.startswith('[Sahne] '): continue
        try: event=json.loads(line[8:])
        except (ValueError,TypeError): continue
        if not isinstance(event,dict): continue
        phase=event.get('phase')
        if event.get('event')=='phase' and phase in phases:
            latest={'phase':phase,'label':phases[phase]}
        elif event.get('event')=='clip_ready':
            completed,total=event.get('completed'),event.get('total')
            if type(completed)==int and type(total)==int and 0<=completed<=total<=64:
                latest={'phase':'clip_ready','label':f'{completed}/{total} hareketli çekim hazır',
                        'completed':completed,'total':total}
        elif event.get('event')=='sampling_progress':
            value,total=event.get('value'),event.get('total')
            if type(value)==int and type(total)==int and 0<=value<=total<=100:
                latest={'phase':'sampling','label':phases.get(phase,'Video hareketi örnekleniyor'),
                        'detail':f'Bu örnekleme aşaması: {value}/{total} adım'}
    return latest


def snapshot(run, *, remote_jobs=(), script_progress=None, publication=None):
    outputs=run.outputs
    result={}
    current='editor' if run.stage=='quality' else run.stage
    stored=outputs.get('_agent_progress',{})
    for agent in AGENTS:
        key=agent['id']; saved=stored.get(key,{})
        value={'state':'pending','label':PENDING[key],'detail':'',
               'updated_at':saved.get('updated_at'),'completed':None,'total':None}
        if key in outputs:
            value.update(state='done',label='Görev tamamlandı')
            if key=='supervisor': value['label']='Üretim hedefi ve çalışma planı hazır'
            elif key=='strategy': value['label']='İçerik yaklaşımı ve anlatım yönü hazır'
            elif key=='script': value['label']=f"{len(outputs[key].get('scenes',[]))} sahnelik senaryo hazır"
            elif key=='voice':
                voice=outputs[key];count=len(voice.get('audios',[]))
                value.update(label=f'{count} sahnenin seslendirmesi hazır',completed=count,total=count,
                    detail=f"Toplam {round(voice.get('duration',sum(voice.get('durations',[]))),1)} saniye")
            elif key=='visual':
                visual=outputs[key];count=len(visual.get('shot_images') or visual.get('images',[]))
                value.update(label=f'{count} çekim görseli hazır',completed=count,total=count)
            elif key=='motion':
                count=len(outputs[key].get('clips',{}))
                value.update(label=f'{count} hareketli çekim hazır',completed=count,total=count)
            elif key=='music':
                music=outputs[key]
                if music.get('provider')=='none':
                    value.update(label='Kurgu arka plan müziği olmadan devam ediyor',detail=music.get('reason',''))
                else:
                    value.update(label='Arka plan müziği hazır',detail=music.get('source',{}).get('title')
                        or ('Yüklediğin müzik kullanılacak' if music.get('provider')=='user_upload' else 'Senaryoya uygun müzik ve ses ayarı hazır'))
            elif key=='editor': value['label']='Video kurgusu ve ses karışımı hazır'
            elif key=='publisher': value['label']='Paylaşım paketi hazır · Yayın için onayın bekleniyor'
        parallel = key not in outputs and saved.get('parallel') and run.stage=='motion' and run.status=='running'
        if key not in outputs and run.stage=='motion' and saved.get('phase') in ('early_wait','early_deferred'):
            value.update(state='waiting',label=saved['label'])
            if key=='editor':
                renders=outputs.get('_editor_progress',{}).get('render',{})
                if renders:
                    value.update(completed=sum(v['status']=='rendered' for v in renders.values()),total=len(renders))
        if parallel or (key==current and run.status not in ('awaiting_approval','published','scheduled','script_ready')):
            value.update({k:v for k,v in saved.items() if k not in ('state','parallel')})
            value.update(state='active',label=saved.get('label') or START.get(key,'Görev yürütülüyor'))
            if not saved and key=='visual' and run.status=='waiting_provider':
                last=next((m for m in reversed(outputs.get('_model_metrics',[]))
                    if m.get('schema')=='StockSearchPlan'),None)
                if last: value['label']=TASKS['StockSearchPlan']
            if key=='script' and script_progress and script_progress.get('phase'):
                value['label']=script_progress['label']
            if key=='voice' and not saved:
                casting=outputs.get('voice_casting',{})
                if casting:
                    value['label']='Türkçe ses adayları değerlendiriliyor'
                    count=sum(c.get('status')=='ready' for c in casting.get('candidates',[]))
                    value.update(completed=count,total=len(casting.get('candidates',[])) or None)
            if key=='visual':
                progress=outputs.get('_visual_progress',{})
                value.update(completed=progress.get('completed'),total=progress.get('total'))
            if key=='motion' and remote_jobs:
                jobs=[j for j in remote_jobs if j['status'] not in ('failed','error','cancelled','canceled')]
                completed=saved.get('completed')
                if completed is None: completed=max((j.get('completed_clips',0) for j in jobs),default=0)
                total=len(outputs.get('_motion_plan',{}).get('shots',[]))
                value.update(completed=min(completed,total) if total else completed,total=total or None)
            if key=='editor':
                progress=outputs.get('_editor_progress',{})
                scenes=progress.get('scenes',{})
                renders=progress.get('render',{})
                if renders:
                    value.update(completed=sum(v['status']=='rendered' for v in renders.values()),total=len(renders))
                    if not saved or saved.get('phase')=='start': value['label']='Video parçaları oluşturuluyor'
                elif scenes:
                    value.update(completed=sum(v['status']=='ready' for v in scenes.values()),total=len(outputs.get('script',{}).get('scenes',[])))
                    if not saved or saved.get('phase')=='start': value['label']='Sahnelerin kurgusu hazırlanıyor'
            if run.status=='waiting_provider':
                wait=outputs.get('_provider_wait',{})
                value.update(state='waiting',detail=(run.error or 'İlgili hizmetin yanıtı bekleniyor. Hazır çıktılar korundu.')[:400],
                    retry_at=wait.get('retry_at'),automatic=wait.get('automatic',False))
            elif run.status=='waiting_remote':
                value.update(state='remote',detail='Kaggle işi takip ediliyor; tamamlanan çekimler korunuyor.')
                if remote_jobs and remote_jobs[-1]['status'] in ('queued','pending','starting'):
                    value.update(state='waiting',detail='Kaggle işi sırada; GPU çalışmasının başlaması bekleniyor.')
            elif run.status in ('failed','waiting_quota','waiting_input','cancelled'):
                value.update(state='paused',detail=(run.error or 'Üretim duraklatıldı.')[:400])
            elif run.status=='queued':
                value.update(state='queued',detail='Üretim sırası bekleniyor; henüz çalışmaya başlamadı.')
        if key=='publisher' and publication:
            status=publication.get('status')
            if status=='uploading': value.update(state='active',label='Video YouTube’a yükleniyor')
            elif status=='published': value.update(state='done',label='Video yayınlandı')
            elif status=='scheduled': value.update(state='done',label='Yayın zamanı planlandı')
        result[key]=value
    return result
