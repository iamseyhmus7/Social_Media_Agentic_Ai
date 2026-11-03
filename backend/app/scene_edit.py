"""MiMo edits small scenes; validated checkpoints survive unrelated scene failures."""
import json
from pydantic import model_validator
from .schemas import EditLook, SceneEditDecision, SceneEditRepair, AutoEditPlan, SCENE_CAPABILITIES
from .parallel_work import bounded_map
from .edit_compiler import compile_segments, SceneBudgetError
from .config import settings


def atomic_json(path, value):
    temporary=path.with_suffix('.partial')
    temporary.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
    temporary.replace(path)


def decide(run, folder, shots, durations, available, observations, llm, check, sources, brief, preferences, signature, on_scene=None):
    from .automatic_edit import scene_frames, validate_decision
    from .editorial_graphics import compile_cues
    from .planned_edit import digest
    cfg=settings()
    streaming=run.outputs.get("_config",{}).get("editor_streaming_enabled",False)
    from .providers import configure_editor_timeout
    configure_editor_timeout(llm)
    budgets=scene_frames(durations)
    lookup={s['shot_id']:s['scene_index'] for s in shots}
    cache=folder/'scene-decisions'
    cache.mkdir(exist_ok=True)
    baseline = None
    baseline_path = folder / 'edit-source-decisions.json'
    if (run.outputs.get('_edit_only') and run.outputs.get('_changed_scenes') and baseline_path.is_file()
            and set(run.outputs.get('_repair_stages', [])) <= {'editor', 'publisher'}):
        candidate = json.loads(baseline_path.read_text(encoding='utf-8'))
        if (candidate.get('durations') == durations and candidate.get('source_hashes') == signature
                and len(candidate.get('scenes', [])) == len(durations)):
            baseline = candidate
    compact_brief={k:v for k,v in (run.outputs.get('supervisor') or {}).items() if k not in ('checks','execution_plan')}
    quality=run.outputs.get('_last_quality')
    global_quality=([f for f in (quality or {}).get('findings',[]) if f.get('scene_index') is None] or None) if streaming else quality
    look_key=digest({'compiler':'scene-v3-audience-drive','brief':compact_brief,'script':run.outputs['script'],
                     'preferences':preferences,'feedback':run.outputs.get('_feedback'),'quality':global_quality})
    look_path=cache/('look-'+look_key+'.json')
    if baseline:
        look = EditLook.model_validate(baseline['look']).model_dump()
    elif look_path.is_file():
        look=EditLook.model_validate_json(look_path.read_text(encoding='utf-8')).model_dump()
    else:
        def request_look():
            return llm.generate(EditLook,'Video Editörü / Görsel yön',{
            'brief':compact_brief,'topic':brief,
            'narration':[s['narration'] for s in run.outputs['script']['scenes']],
            'preferences':preferences,'feedback':run.outputs.get('_feedback'),
            'instruction':'Ortak yaratıcı yönü konuya göre belirle; zorunlu açılış/kapanış başlığı veya estetik dayatma. '
            'Sahne/çekim/gözlem listesi üretme. Kullanıcı altyazı tercihini uygula. '
            'Brief editorial_direction açılış/kapanış/somut örnek/tempo niyetlerini ortak creative_direction içine aktar. '
            'İlk saniyede anlatımla aynı merakı kur; düşük tempolu giriş veya uzun logo kullanma. '
            'Okunabilir kısa yazı, görünür eylem ve amaçlı ses vurgusunu birlikte yönet; her aracı aynı anda yığma. '
            'Son görüntü ve ses bitişi açılıştaki vaadi tamamlasın; kapanışı tekrar eden başlıkla uzatma.'},
            max_attempts=2,**({'repair_fields':True,'compact_schema':True} if streaming else {}))
        if streaming:
            from .parallel_work import retry_inference
            value=retry_inference(request_look,check)
        else:value=request_look()
        look=EditLook.model_validate(value).model_dump()
        look=EditLook.model_validate_json(json.dumps(look)).model_dump()
        atomic_json(look_path,look)

    checkpoint_paths={}
    def scene_call(scene, *, boundary=None, error=None):
        check()
        local_shots=[s for s in shots if s['scene_index']==scene]
        ids={s['shot_id'] for s in local_shots}
        seen=[o for o in observations if o['shot_id'] in ids]
        context={'scene_index':scene,'narrative':run.outputs['script']['scenes'][scene],
            'editorial_direction':compact_brief.get('editorial_direction',{}),
            'is_opening':scene==0,'is_closing':scene==len(durations)-1,
            'creative_direction':look,'frame_budget':budgets[scene],
            'sources':[{'shot_id':s['shot_id'],'purpose':s.get('purpose',''),
                'expected_action':s.get('expected_action',''),'available_frames':available[s['shot_id']]} for s in local_shots],
            'observed_facts':seen,'preferences':preferences,'references':sources,
            'quality_findings':([f for f in (quality or {}).get('findings',[]) if f.get('scene_index') in (None,scene)] or None) if streaming else quality,
            'feedback':run.outputs.get('_feedback'), 'next_scene_transition':boundary,
            'correction':error,
            'instruction':'Bu sahneyi gerçek kaynak gözlemlerinden kurgula. Her kaynağı reviews içinde kısa gerekçeyle '
            'pass/uncertain/reject değerlendir; gözlemleri tekrar yazma. segments için mevcut shot_id, source_in_frame, '
            'duration_weight ve içerik gerekçeli tasarım seç. Kesin kare sayısını sunucu hesaplar. '
            'Kaynak eylemi promptta istenmiş diye gerçekleşmiş sayma. Aynı sahnede kal; kaynak süresini aşma. '
            'Bütün kare değerleri 30 FPS zaman tabanındadır. İlk sahnenin ilk geçişi cut olmalı. Geçişte önceki kaynağa ek kare gerekir. '
            'Grafik ve ses işaretleri bu sahneye bağlı, scene_index aynı, start_frame/frames sahne bütçesi içinde olsun. '
            'İkincil kadraj aynı sahneden ve aynı kaynak başlangıcında yeterli sürede olmalı. '
            'Kaynak toplamı frame_budget değerini karşılamalı; tek kaynak yetmiyorsa diğer uygun kaynakları da seç. '
            'Kısa yanıt ver; kullanılmayan grafik/başlık/efekti boş bırak. Kaynak kartı yalnız istenmişse. '
            'Harita açılışı istenmişse sahne 0, kare 0 ile başlat. Kod veya yeni efekt türü üretme. '
            'Seçmediğin isteğe bağlı alanları döndürme; sunucu varsayılanları tamamlar. '
            'Yeni kamera/geçiş/yazı seçenekleri capabilities listesinde. font_family serif/sans, text_style ve '
            'template ile konuya uygun yön seç; şablon veya efekt kotası yok. object_3d yalnız cube/sphere/torus/icosahedron '
            'geometrilerini sembolik açıklama için ekler; gerçek kişi, yapı veya ürün modeli üretmez. '
            '3D render maliyetini artırır, yalnız içerik gerektiriyorsa kullan; varsayılan null. '
            'critical_questions ve attention_allocation kritik açıklamanın neyi görünür kılması gerektiğini belirtir; '
            'bu bölümde mekanizma/bağlantıyı anlaşılır göster, dekoratif görüntüyle geçiştirme. '
            'Sahnelerin kaynak bütçeleri ölçülmüş ses süresidir; birbirine eşitleme. '
            'Açılışta ilk kareden anlaşılır eylem ve narration ile aynı vaadi taşıyan kısa yazı kur. '
            'sound_cues ile seslendirmeyi örtme; gerekli vurguyu kısa tut veya sessizliği seç. '
            'Kaynak görüntüde eksik ayrıntıyı efektle olgusal kanıta dönüştürme; miktar ve ölçek ilişkisini koru. '
            'Konu dışı hareket yerine anlatımın yeni bilgisine uygun çekim/grafik değişimi seç. '
            'Kapanışta yeni sonuç/eylemi destekle; yeni boş başlık, uzun fade veya tekrar ekleme. '
            'Şablon title alanına uygulanır; grafik işareti aktifken klip başlığı gizlenir. '
            'effects color_grade/glow/vignette görüntüye uygulanır; effect_strength 0–1. '
            'motion_blur yalnız anlamlı hızlı hareketlerde; maliyetlidir, altyazıyı bulanıklaştırmaz. '
            'Aynı segmentte effects ve motion_blur birlikte kullanılamaz; içerik için uygun olanı seç veya farklı segmentlere uygula. '
            'lottie_asset pulse_ring dikkati yönlendirir, flow_arrow süreç/değişim gösterir; tarihsel kanıt değildir. '
            'annotation underline/circle/highlight yalnız kısa title vurgusudur; annotation_text ile title içinden kısa bir kelime seç. '
            'wipe/flip/clock_wipe resmî geçişlerdir. Araçları içerik gerekçesiyle seç; her sahneye efekt eklemek zorunlu değil.'}
        context['capabilities']=SCENE_CAPABILITIES
        if baseline:
            context['current_scene_edit'] = baseline['scenes'][scene]
            context['instruction'] += (' Mevcut sahne kurgusunu temel al. Yalnız kullanıcı talebindeki katmanı değiştir; '
                'kaynak seçimini, kesmeleri, sesleri ve diğer tasarım alanlarını talep gerektirmedikçe koru. '
                'Senaryodaki eski dekor talimatını kullanıcı geri bildiriminin önüne koyma.')
        if scene==0 and run.outputs.get('_config',{}).get('engagement_policy',0):
            context['opening_hook']=run.outputs['script'].get('hook','')
            context['instruction'] += (' İlk 1–3 saniyede opening_hook ile uyumlu güçlü bir görsel giriş kur. '
                'Uzun logo/selamlama açılışı yapma; mevcut doğrulanmış çekimleri ve okunabilir kısa vurguyu kullan. '
                'İzlenme garantisi veya yeni olgusal iddia ekleme.')
        cache_context=dict(context)
        if streaming:
            context['instruction'] += (' duration_weight yalnız 0.01–100 arası göreli ağırlıktır, kare sayısı değildir. '
                'split/inset seçersen design.secondary_shot_id mutlaka aynı sahnenin mevcut shot_id değeridir. '
                'reviews.reason en fazla 200 karakterdir. region yalnız spotlight grafiğinde kullanılır; diğer grafiklerde region verme. '
                'spotlight region.width en fazla 0.7, height en fazla 0.6; x/y güvenli görüntü alanında olmalı.')
        key=digest({'version':4 if streaming else 3,'input':cache_context,'source_hashes':{ident:signature[ident] for ident in ids},'capabilities':SCENE_CAPABILITIES})
        path=cache/(str(scene)+'-'+key+'.json')
        invalid_path=path.with_suffix('.invalid.json')
        checkpoint_paths[scene]=path
        class GroundedScene(SceneEditDecision):
            @model_validator(mode='after')
            def grounded(self):
                value=self.model_dump()
                if len(self.segments)>max(1,64//len(durations)) or max(len(self.graphics),len(self.sound_cues))>max(1,24//len(durations)):
                    raise ValueError('Sahne işaret/segment sayısı toplam üretim sınırını korumalı; kullanılmayan ayrıntıları çıkar.')
                if len(self.reviews)!=len(ids) or {r.shot_id for r in self.reviews}!=ids:
                    raise ValueError('Her yerel kaynak tam bir uygunluk kararı gerektirir.')
                if any(s.shot_id not in ids or (s.design.secondary_shot_id and s.design.secondary_shot_id not in ids) for s in self.segments):
                    raise ValueError('Sahne yalnız kendi mevcut kaynaklarını kullanabilir.')
                if any(c.scene_index!=scene for c in [*self.graphics,*self.sound_cues]):
                    raise ValueError('Grafik/ses işareti başka sahneye yayılamaz.')
                if scene==0 and self.segments[0].transition!='cut':
                    raise ValueError('İlk sahnenin ilk geçişi cut olmalı.')
                if not preferences.get('show_sources') and any(c.kind=='source_card' for c in self.graphics):
                    raise ValueError('Kaynak kartı istenmiyor.')
                if scene==0 and preferences.get('map_intro') and not any(c.kind=='map_flyover' and c.start_frame==0 for c in self.graphics):
                    raise ValueError('Harita açılışı sahne 0 kare 0 ile başlamalı.')
                return self
        if baseline and scene not in run.outputs['_changed_scenes']:
            result = GroundedScene.model_validate(baseline['scenes'][scene]).model_dump()
        elif path.is_file():
            result=GroundedScene.model_validate_json(path.read_text(encoding='utf-8')).model_dump()
        else:
            from .parallel_work import editor_progress
            editor_progress(getattr(run,'id',None),'scenes',scene,'planning')
            result=GroundedScene.model_validate(llm.generate(GroundedScene,'Video Editörü / Sahne kurgusu',context,
                max_attempts=3 if streaming else 2,
                **({'repair_fields':True,'compact_schema':True,
                    'initial_candidate':json.loads(invalid_path.read_text(encoding='utf-8')) if invalid_path.is_file() else None,
                    'on_invalid':lambda value:atomic_json(invalid_path,value)} if streaming else {}))).model_dump()
            check()
            atomic_json(path,result)
        if streaming:
            from .scene_local import finalize_scene
            result,compiled=finalize_scene(scene,result,shots,available,budgets,durations,sources,preferences,llm,check)
            check()
            atomic_json(path,result)
            return {'decision':result,'compiled':compiled}
        return result

    if streaming:
        from .parallel_work import settled_map,editor_progress
        from .providers import TransientProviderError,InvalidModelOutput
        def completed(scene,value):
            editor_progress(getattr(run,'id',None),'scenes',scene,'ready')
            if on_scene:on_scene(scene,look,value['decision'],value['compiled'])
        values=settled_map(list(range(len(durations))),scene_call,cfg.editor_parallelism,check,
            on_success=completed,on_error=lambda scene,exc,attempt:editor_progress(getattr(run,'id',None),'scenes',scene,'retry',str(exc)),
            retry_errors=(TransientProviderError,InvalidModelOutput))
        decisions=[v['decision'] for v in values]
        compiled=[segment for v in values for segment in v['compiled']]
        raw={**look,'segments':compiled,
            'observations':[{'shot_id':r['shot_id'],'verdict':r['verdict'],'observation':r['reason']} for d in decisions for r in d['reviews']],
            'graphics':[c for d in decisions for c in d['graphics']],
            'sound_cues':[c for d in decisions for c in d['sound_cues']]}
        decision=AutoEditPlan.model_validate(raw).model_dump()
        validate_decision(decision,shots,available,durations,enforce_reviews=False,sources=sources,preferences=preferences,require_handles=True)
        atomic_json(folder/'edit-decisions-v4.json',{'version':4,'look':look,'scenes':decisions})
        return decision
    decisions=bounded_map(list(range(len(durations))),scene_call,cfg.editor_parallelism,check)
    repairs={}
    for _ in range(1+2*len(durations)):
        segments=[s for d in decisions for s in d['segments']]
        try:
            compiled=compile_segments(segments,shots,available,budgets)
            break
        except SceneBudgetError as exc:
            scene=exc.scene_index
            if repairs.get(scene,0)>=2:
                raise RuntimeError('Sahne kaynak bütçesi iki yerel düzeltmede doğrulanamadı: '+str(exc)) from None
            local_ids={s['shot_id'] for s in shots if s['scene_index']==scene}
            following=decisions[scene+1]['segments'][0] if scene+1<len(decisions) else None
            repair=SceneEditRepair.model_validate(llm.generate(SceneEditRepair,'Video Editörü / Kaynak aralığı',{
                'scene_index':scene,'error':str(exc),'frame_budget':budgets[scene],
                'sources':{ident:available[ident] for ident in local_ids},'current_segments':decisions[scene]['segments'],
                'suitability':decisions[scene]['reviews'],'next_transition':following,
                'instruction':'Yalnız segment listesini düzelt. 30 FPS kaynak karelerinin toplamı bütçeyi karşılamalı. '
                'Tek kaynak yetmiyorsa diğer uygun yerel kaynakları kullan. Kesin kare sayısını sunucu hesaplar. '
                'Geçiş ek karelerini koru; kaynak aralığını aşma, aynı kareleri tekrar kullanma. '
                'Başka sahneye veya grafiklere dokunma.'},max_attempts=2,)).model_dump()
            if any(s['shot_id'] not in local_ids or (s['design'].get('secondary_shot_id') and s['design']['secondary_shot_id'] not in local_ids) for s in repair['segments']):
                raise RuntimeError('Kaynak aralığı düzeltmesi başka sahneye yayılamaz.')
            decisions[scene]['segments']=repair['segments']
            atomic_json(checkpoint_paths[scene],decisions[scene])
            repairs[scene]=repairs.get(scene,0)+1
    # Spotlight geometry is clipped to its intersection with the safe area;
    # this keeps the highlighted subject region rather than shifting the mask.
    for result in decisions:
        for cue in result['graphics']:
            region=cue.get('region')
            if region:
                left=max(.070001,region['x']-region['width']/2)
                right=min(.859999,region['x']+region['width']/2)
                top=max(.120001,region['y']-region['height']/2)
                bottom=min(.709999,region['y']+region['height']/2)
                if right>left and bottom>top:
                    cue['region']={'x':(left+right)/2,'y':(top+bottom)/2,'width':min(.7,right-left),'height':min(.6,bottom-top)}
                else:
                    # A fully offscreen cue needs a creative local correction.
                    from .schemas import SceneCueRepair
                    fixed=SceneCueRepair.model_validate(llm.generate(SceneCueRepair,'Video Editörü / İşaret düzeltme',{
                        'scene_index':cue['scene_index'],'cue':cue,'frame_budget':budgets[cue['scene_index']],
                        'instruction':'Yalnız bu grafik için görünür güvenli bölge seç; merkez x±width/2 .07–.86 ve y±height/2 .12–.71 içinde olmalı.'},
                        max_attempts=2,)).model_dump()
                    if len(fixed['graphics'])!=1 or fixed['graphics'][0]['scene_index']!=cue['scene_index'] or fixed['sound_cues']:
                        raise RuntimeError('İşaret düzeltmesi yalnız mevcut grafiğe uygulanabilir.')
                    cue.update(fixed['graphics'][0])
    raw={**look,'segments':compiled,
        'observations':[{'shot_id':r['shot_id'],'verdict':r['verdict'],'observation':r['reason']} for d in decisions for r in d['reviews']],
        'graphics':[c for d in decisions for c in d['graphics']],
        'sound_cues':[c for d in decisions for c in d['sound_cues']]}
    from .planned_edit import repair_cues
    repair_cues(raw,durations,sources,preferences,llm,check,bounded=True)
    decision=AutoEditPlan.model_validate(raw).model_dump()
    validate_decision(decision,shots,available,durations,enforce_reviews=False,sources=sources,preferences=preferences,require_handles=True)
    atomic_json(folder/'edit-decisions-v3.json',{'version':3,'look':look,'scenes':decisions})
    return decision
