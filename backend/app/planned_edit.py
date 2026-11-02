"""Versioned perception cache followed by compact, text-only creative decisions."""
import base64
import hashlib
import json
from .schemas import ClipPerception, ClipObservation, EditDecisionV2, SceneEditRepair, SceneCueRepair, AutoEditPlan, SCENE_CAPABILITIES
from .edit_compiler import compile_segments, SceneBudgetError
from .config import settings
from .storage import file_hash, workdir
from . import media
from .providers import PERCEPTION_ROLE, perception_model, configure_editor_timeout

PERCEPTION_VERSION = 'sampled-3-v1'
COMPILER_VERSION = 'weighted-v2'


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def perception_cache_path(cache, clip_hash, model, reuse_models=()):
    # Explicit run migration may reuse completed observations under their original
    # model identity. Never relabel old results as outputs from the new model.
    paths = [cache/(digest({'clip':clip_hash,'schema':PERCEPTION_VERSION,'model':name})+'.json')
             for name in dict.fromkeys([model, *reuse_models])]
    return next((path for path in paths if path.is_file()), paths[0])


def prepare_decision(run, folder, shots, durations, available, llm, check, sources, brief, preferences, on_scene=None):
    from .automatic_edit import scene_frames, validate_decision
    # Cache is confined to this owned project, never shared across users.
    cache = workdir(run.project_id,run.id).parent/'perception-cache'
    cache.mkdir(exist_ok=True)
    hashes = {}
    for shot in shots:
        check()
        ident = shot['shot_id']
        hashes[ident] = file_hash(folder/run.outputs['motion']['clips'][ident]['file'])
    scene_mode = run.outputs.get('_config',{}).get('video_edit_policy') == 'scenes_v3'
    compiler_version = 'scene-v3' if scene_mode else COMPILER_VERSION
    if scene_mode and hasattr(llm,'timeout'):
        configure_editor_timeout(llm)
    signature = digest({'version':compiler_version,'sources':hashes,'shots':shots,'durations':durations,
        'script':run.outputs['script'],'brief':brief,'creative':run.outputs.get('supervisor'),
        'preferences':preferences,'feedback':run.outputs.get('_feedback'),
        'findings':run.outputs.get('_last_quality'),'capabilities':SCENE_CAPABILITIES,'references':sources})
    plan_path, marker = folder/'edit-plan.json',folder/'edit-plan-input.json'
    if marker.is_file() and plan_path.is_file() and json.loads(marker.read_text(encoding='utf-8')).get('key')==signature:
        decision = AutoEditPlan.model_validate_json(plan_path.read_text(encoding='utf-8')).model_dump()
        validate_decision(decision,shots,available,durations,enforce_reviews=False,sources=sources,preferences=preferences,require_handles=True)
        return decision
    cfg = settings()
    def perceive(shot):
        check()
        ident = shot['shot_id']
        path = perception_cache_path(cache, hashes[ident], perception_model(cfg),
                                     run.outputs.get('_perception_cache_reuse_models', []))
        if path.is_file():
            perception = ClipPerception.model_validate_json(path.read_text(encoding='utf-8')).model_dump()
        else:
            inputs=[]
            scratch=folder/'perception-work'/ident
            scratch.mkdir(parents=True,exist_ok=True)
            item=run.outputs['motion']['clips'][ident]
            seconds=item['report']['duration']
            for index,fraction in enumerate((.05,.5,.92)):
                target=scratch/f'frame-{index}.jpg'
                media.command([cfg.ffmpeg_bin,'-y','-ss',str(min(seconds-.08,seconds*fraction)),
                    '-i',folder/item['file'],'-frames:v','1','-vf','scale=270:468',target],scratch,check,timeout=60)
                inputs.append({'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+
                    base64.b64encode(target.read_bytes()).decode(),'detail':'high'}})
            perception=ClipPerception.model_validate(llm.generate(ClipPerception,PERCEPTION_ROLE,{
                'shot_id':ident,'sample_fractions':[.05,.5,.92],
                'instruction':'Yalnızca üç örnek karede gerçekten görünen özne, nesne, eylem ve kusurları betimle. '
                'Gözlemleri açık ve özlü yaz; açıklama alanlarının şemadaki karakter sınırlarına uy. '
                'Senaryo uygunluğu veya kurgu kararı verme. Hareketin tamamı ve ses bu örneklerden doğrulanamaz.'},media_inputs=inputs,**({'max_attempts':2,'max_output_tokens':1536,'repair_fields':True} if scene_mode else {}))).model_dump()
            check()
            temporary=path.with_name(path.name+'.'+ident+'.partial')
            temporary.write_text(json.dumps(perception,ensure_ascii=False),encoding='utf-8')
            temporary.replace(path)
        return perception
    if scene_mode:
        from .parallel_work import bounded_map,settled_map,editor_progress
        unique={}
        for shot in shots:unique.setdefault(hashes[shot['shot_id']],shot)
        streaming=run.outputs.get('_config',{}).get('editor_streaming_enabled',False)
        facts=(settled_map(list(unique.values()),perceive,cfg.editor_parallelism,check,
            on_success=lambda shot,value:editor_progress(getattr(run,'id',None),'perception',shot['shot_id'],'ready'),
            on_error=lambda shot,exc,attempt:editor_progress(getattr(run,'id',None),'perception',shot['shot_id'],'retry',str(exc)))
            if streaming else bounded_map(list(unique.values()),perceive,cfg.editor_parallelism,check))
        by_hash=dict(zip(unique,facts))
        observations=[{'shot_id':shot['shot_id'],**by_hash[hashes[shot['shot_id']]]} for shot in shots]
        from .scene_edit import decide, atomic_json
        decision=decide(run,folder,shots,durations,available,observations,llm,check,sources,brief,preferences,hashes,on_scene=on_scene)
        atomic_json(plan_path,decision)
        atomic_json(marker,{'key':signature,'compiler':compiler_version})
        return decision
    observations=[{'shot_id':shot['shot_id'],**perceive(shot)} for shot in shots]
    context={'script':run.outputs['script'],'brief':brief,'creative_brief':run.outputs.get('supervisor'),
        'edit_preferences':preferences,'feedback':run.outputs.get('_feedback'),'previous_quality':run.outputs.get('_last_quality'),
        'observed_sources':observations,'shots':shots,'available_frames':available,'scene_budgets':scene_frames(durations),
        'supported_scene_design':SCENE_CAPABILITIES,'sources':sources,
        'instruction':'Görsel gözlemler önceden gerçek karelerden kaydedildi; yeni görüntü eki yok. '
        'Bu gözlemlerin YENİ senaryoya uygunluğunu observations içinde pass/uncertain/reject ile değerlendir. '
        'MiMo olarak çekim sırasını, tempoyu duration_weight ile, kaynak başlangıcını source_in_frame ile ve efektleri seç. '
        'Kesin segment kare sayılarını sunucu derleyecek. Yeterli toplam kaynak süresi seç, hareketi dondurma/döngüleme. '
        'Anlatım sırasını koru, her çekim yalnız kendi sahnesinde; ilk geçiş cut. '
        'Geçişte önceki çekimde transition_frames kadar ek kaynak gerekir. İkinci kadraj aynı sahneden olmalı. '
        'Grafikler ve ses işaretleri sahne içi start_frame/frames ile bütçeye sığmalı. '
        'Kaynak kartı yalnız istenmiş ve sources verilmişse. Zorunlu estetik/efekt kotası yok. '
        'Kullanıcı tercihlerini uygula; başlıkları tekrarlama, kod veya desteklenmeyen efekt üretme.'}
    decision=EditDecisionV2.model_validate(llm.generate(EditDecisionV2,'Video Editörü / Kurgu yönetmeni',context)).model_dump()
    lookup={s['shot_id']:s['scene_index'] for s in shots}
    # Missing or duplicate suitability judgments are repaired individually, with
    # cached facts; a narration revision never sends the images again.
    judgments=[]
    for observed in observations:
        matching=[o for o in decision['observations'] if o['shot_id']==observed['shot_id']]
        if len(matching)==1:
            judgments.append(matching[0])
            continue
        judgment=ClipObservation.model_validate(llm.generate(ClipObservation,'Video Editörü / Kaynak uygunluğu',{
            'source':observed,'script':run.outputs['script']['scenes'][lookup[observed['shot_id']]],
            'instruction':'Yalnızca bu kaynağın mevcut senaryoya uygunluğunu kaydedilmiş gözlemlerden değerlendir.'})).model_dump()
        if judgment['shot_id']!=observed['shot_id']:
            raise RuntimeError('Kaynak uygunluğu yanlış çekime bağlandı.')
        judgments.append(judgment)
    decision['observations']=judgments
    for attempt in range(3):
        check()
        try:
            segments=compile_segments(decision['segments'],shots,available,scene_frames(durations))
            break
        except SceneBudgetError as exc:
            if attempt==2:
                raise RuntimeError('Sahne kare bütçesi iki yerel düzeltmede doğrulanamadı: '+str(exc)) from None
            scene=exc.scene_index
            local=[s for s in decision['segments'] if lookup.get(s['shot_id'])==scene]
            repaired=SceneEditRepair.model_validate(llm.generate(SceneEditRepair,'Video Editörü / Sahne düzeltme',{
                'scene_index':scene,'error':str(exc),'segments':local,'scene_budget':scene_frames(durations)[scene],
                'sources':[s for s in shots if s['scene_index']==scene],'available_frames':available,
                'observations':[o for o in observations if lookup[o['shot_id']]==scene],
                'instruction':'Yalnız bu sahnenin çekim seçimi/aralık/ağırlık/geçiş sorununu düzelt. Diğer sahnelere dokunma.'})).model_dump()['segments']
            if any(lookup.get(s['shot_id'])!=scene for s in repaired):
                raise RuntimeError('Sahne düzeltmesi başka sahnenin kaynağını seçti.')
            others=[s for s in decision['segments'] if lookup.get(s['shot_id'])!=scene]
            decision['segments']=sorted(others+repaired,key=lambda s:lookup.get(s['shot_id'],-1))
    (folder/'edit-decision-v2.json').write_text(json.dumps(decision,ensure_ascii=False),encoding='utf-8')
    compiled=AutoEditPlan.model_validate({k:v for k,v in decision.items() if k not in ('version','segments')}|{'segments':segments}).model_dump()
    repair_cues(compiled, durations, sources, preferences, llm, check)
    validate_decision(compiled,shots,available,durations,enforce_reviews=False,sources=sources,preferences=preferences,require_handles=True)
    plan_path.write_text(json.dumps(compiled,ensure_ascii=False),encoding='utf-8')
    marker.write_text(json.dumps({'key':signature,'compiler':COMPILER_VERSION}),encoding='utf-8')
    return compiled


def repair_cues(decision, durations, sources, preferences, llm, check, *, bounded=False, scene_indices=None):
    from .editorial_graphics import compile_cues
    from .automatic_edit import scene_frames
    invalid=[c for name in ('graphics','sound_cues') for c in decision[name] if c['scene_index']>=len(durations)]
    if invalid:
        raise RuntimeError('Kurgu işareti mevcut olmayan bir sahneye bağlı.')
    for scene,budget in enumerate(scene_frames(durations)):
        if scene_indices is not None and scene not in scene_indices:continue
        for attempt in range(3):
            check()
            local={name:[c for c in decision[name] if c['scene_index']==scene] for name in ('graphics','sound_cues')}
            try:
                compile_cues(local,durations,sources)
                if not preferences.get('show_sources') and any(c['kind']=='source_card' for c in local['graphics']):
                    raise ValueError('Videoda kaynak kartı istenmiyor.')
                if scene==0 and preferences.get('map_intro') and not any(c['kind']=='map_flyover' and c['start_frame']==0 for c in local['graphics']):
                    raise ValueError('İstenen harita açılışı 0. karede başlamalı.')
                break
            except ValueError as exc:
                if attempt==2:
                    raise RuntimeError('Sahne grafik/ses düzeltme sınırı: '+str(exc)) from None
                repaired=SceneCueRepair.model_validate(llm.generate(SceneCueRepair,'Video Editörü / İşaret düzeltme',{
                    'scene_index':scene,'scene_budget':budget,'error':str(exc),'cues':local,'sources':sources,
                    'preferences':preferences,'instruction':'Yalnız bu sahnenin grafik/ses işaretlerini düzelt. '
                    'Kesme planını, diğer sahneleri ve yaratıcı kararları koru.'}, **({'max_attempts':2} if bounded else {}))).model_dump()
                if any(c['scene_index']!=scene for cues in repaired.values() for c in cues):
                    raise RuntimeError('İşaret düzeltmesi başka sahneye yayılamaz.')
                for name in ('graphics','sound_cues'):
                    decision[name]=[c for c in decision[name] if c['scene_index']!=scene]+repaired[name]
