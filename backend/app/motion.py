import math
import base64
import io
from PIL import Image
from .schemas import MotionPlan
from .providers import ProviderError
from .storyboard import MAX_VISUAL_SECONDS


def generate_missing_clips(run, folder, plan, reference_ids, check, *, on_ready=None):
    from .pipeline import asset_path
    from .kaggle_provider import generate_clips
    old = run.outputs.get('_reuse_motion', {})
    old_shots = {s['shot_id']: s for s in old.get('plan', {}).get('shots', [])}
    reused, missing, paths = {}, [], []
    changed = run.outputs.get('_changed_scenes', [])
    changed_shots = run.outputs.get('_changed_shots', [])
    durations = run.outputs['voice']['durations']
    for shot, reference in zip(plan['shots'], reference_ids):
        ident = shot['shot_id']
        previous, clip = old_shots.get(ident), old.get('clips', {}).get(ident)
        from .storage import file_hash
        reference_matches = (run.outputs.get('_config',{}).get('visual_policy') != 'references_v1' or
            (clip and clip.get('reference_hash')==file_hash(asset_path(reference))))
        force = bool(set(run.outputs.get('_repair_stages', [])) & {'visual', 'motion'}) and (ident in changed_shots if changed_shots else not changed or shot['scene_index'] in changed)
        needed = durations[shot['scene_index']]/sum(s['scene_index']==shot['scene_index'] for s in plan['shots'])
        if (previous and clip and reference_matches and not force and (folder/clip['file']).is_file()
                and previous.get('reference_prompt')==shot.get('reference_prompt')
                and previous.get('motion_prompt')==shot.get('motion_prompt')
                and previous.get('camera')==shot.get('camera')
                and clip.get('report', {}).get('duration', 0)>=needed):
            from .db import DB, Asset
            from .storage import file_hash
            with DB() as db:
                asset = db.get(Asset, clip['asset_id'])
                if not asset or asset.run_id!=run.id or asset.sha256!=file_hash(folder/clip['file']):
                    raise ProviderError('Yeniden kullanılacak klip özeti veya sahipliği değişti.')
            reused[ident] = clip
        else:
            missing.append({**shot, 'image_index': len(paths), 'scene_index': shot['scene_index']})
            paths.append(asset_path(reference))
    if missing:
        if run.outputs.get('_edit_only'):
            raise ProviderError('Yeniden kurgu için kaynak süreleri yetersiz; medya değiştirilmedi.')
        options = {'on_ready': lambda clips: on_ready({**reused, **clips})} if on_ready else {}
        reused.update(generate_clips(run, folder, {'shots': missing}, paths, check, **options))
    return reused


def refine_requested_motion(run, plan, llm):
    from .schemas import ShotPlan
    from .config import settings
    requests = run.outputs.get('_shot_requests',{})
    if settings().visual_policy!='references_v1' or not requests:
        return plan
    shots=[]
    for shot in plan['shots']:
        request=requests.get(shot['shot_id'])
        if request and request['action']=='motion':
            proposed=ShotPlan.model_validate(llm.generate(ShotPlan,'Video Üretim Agentı',{
                'shot':shot,'instructions':request['instructions'],
                'instruction':'Yalnız bu çekimin İngilizce hareket yönergesini ve kamera seçimini düzelt. '
                'Başlangıç karesini, özneyi ve süreyi koru; tek gerçekleştirilebilir eylem seç.'})).model_dump()
            shot={**shot,'motion_prompt':proposed['motion_prompt'],'camera':proposed['camera']}
        shots.append(shot)
    return {**plan,'shots':shots}


def create_motion_plan(llm, context, durations, image_paths=None):
    if image_paths is None and context.get('completed', {}).get('visual', {}).get('images'):
        from .db import DB, Asset
        from .storage import media_path
        with DB() as db:
            image_paths = [media_path(db.get(Asset, ident).path) for ident in context['completed']['visual']['images']]
    allocation = []
    for index, duration in enumerate(durations):
        count = math.ceil(duration / MAX_VISUAL_SECONDS)
        for _ in range(count):
            allocation.append({'shot_id': f'shot-{len(allocation):03}', 'scene_index': index, 'duration_seconds': duration / count})
    if len(allocation) > 32:
        raise ProviderError('Çekim sayısı desteklenen sınırı aşıyor.')
    references = []
    for path in image_paths or []:
        with Image.open(path) as source:
            image = source.convert('RGB')
            image.thumbnail((384, 640))
            buffer = io.BytesIO()
            image.save(buffer, format='JPEG', quality=80)
        references.append({'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + base64.b64encode(buffer.getvalue()).decode(), 'detail': 'low'}})
    payload = {**context, 'allocation': allocation, 'reference_scene_order': list(range(len(references))), 'instructions': 'Her allocation kaydı için aynı shot_id, scene_index ve süreyi koru. Referans görseller scene_index sırasındadır. İngilizce motion_prompt içinde görseldeki öznenin eylemini, doğal hareketi ve çevreyi anlat. Kamera listedeki seçeneklerden olsun. 9:16 dikey kadrajı ve görseldeki özneyi koru; yeni karakter veya yazı ekleme. Klipte kesme/geçiş isteme.'}
    proposed = llm.generate(MotionPlan, 'Video Üretim Agentı', payload, **({'media_inputs': references} if references else {}))
    plan = MotionPlan.model_validate(proposed)
    if {s.shot_id for s in plan.shots} != {s['shot_id'] for s in allocation}:
        raise ProviderError('Video Üretim Agentı beklenen çekim listesini korumadı.')
    by_id = {s.shot_id: s for s in plan.shots}
    # Timing is measured data, never delegated to a language model.
    return {'shots': [{**by_id[s['shot_id']].model_dump(), **s} for s in allocation]}
