"""Owned references, durable image candidates and bounded source-media review."""
import base64
import io
import json
import hashlib
import shutil
from PIL import Image
from sqlalchemy import select
from .config import settings
from .db import DB, Run, Asset, VisualReference
from .storage import workdir, media_path, file_hash, register, check_disk
from .providers import ProviderError


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def atomic_json(path, value):
    temporary = path.with_suffix('.partial')
    temporary.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
    temporary.replace(path)


def reference_snapshot(db, project_id):
    return [{'id':r.id,'asset_id':r.asset_id,'kind':r.kind,'name':r.name,'shot_id':r.shot_id,
             'sha256':db.get(Asset,r.asset_id).sha256}
            for r in db.scalars(select(VisualReference).where(VisualReference.project_id==project_id,
                VisualReference.active.is_(True)).order_by(VisualReference.created))]


def owned_asset(run, ident, expected_hash=None):
    with DB() as db:
        asset = db.get(Asset,ident)
        if not asset or asset.project_id!=run.project_id:
            raise ProviderError('Görsel referansı bu projeye ait değil.')
        path = media_path(asset.path)
        if not path.is_file() or file_hash(path)!=asset.sha256 or (expected_hash and asset.sha256!=expected_hash):
            raise ProviderError('Görsel referansının dosyası veya özeti değişti.')
        return path


def image_input(path, size=(576,1024)):
    with Image.open(path) as source:
        image = source.convert('RGB')
        image.thumbnail(size)
        buffer = io.BytesIO()
        image.save(buffer,format='JPEG',quality=88)
    return {'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+
            base64.b64encode(buffer.getvalue()).decode(),'detail':'high'}}


def reserve_repair(run_id, shot_id, stage):
    from .parallel_work import run_write_lock
    with run_write_lock, DB() as db:
        run = db.get(Run,run_id)
        repairs = dict(run.outputs.get('_source_repairs',{}))
        ident = stage+':'+shot_id
        if ident in repairs or len({k.split(':',1)[1] for k in repairs}|{shot_id})>3:
            return False
        repairs[ident] = True
        run.outputs = {**run.outputs,'_source_repairs':repairs}
        db.commit()
    return True


def accepted(run, shot_id, sha, signature):
    with DB() as db:
        current = db.get(Run,run.id)
        return current.outputs.get('_media_acceptances',{}).get(shot_id)==digest([sha,signature])


def generate_visual(run, project, brand, folder, llm, context, check):
    from .agent_progress import mark
    from .storyboard import direct_story, retime_storyboard, enforce_storyboard_cadence
    from .orchestration import mutate
    from . import media
    from .media_providers import cloudflare_image
    board = run.outputs.get('_storyboard')
    if not board:
        previous = run.outputs.get('_reuse_visual',{}).get('storyboard')
        board = retime_storyboard(previous,run.outputs['voice']['durations']) if previous else None
        board = board or direct_story(llm,run.outputs['script'],run.outputs['voice']['durations'],handles=True,context=context)
        if previous and board:
            board['visual_identity'] = previous.get('visual_identity','')
        mutate(run.id,{'_storyboard':board})
    updated_board=enforce_storyboard_cadence(llm,board,run.outputs['script'],run.outputs['voice']['durations'])
    if updated_board is not board:
        board=updated_board
        mutate(run.id,{'_storyboard':board,'_motion_plan':None})
    # Stock directions are returned in the selected board; cached input signatures stay stable.
    board = json.loads(json.dumps(board))
    references = run.outputs.get('_visual_references',[])
    identity = board.get('visual_identity','')
    selected, receipts, anchors = {}, {}, {}
    changed = set(run.outputs.get('_changed_shots',[]))
    changed_scenes = set(run.outputs.get('_changed_scenes',[]))
    previous = run.outputs.get('_reuse_visual',{})
    stock_queries = run.outputs.get('_stock_queries',{})
    stock_prepared = {}
    media_bytes = None
    progress = {'completed':0,'total':len(board['shots']),'unit':'shots','scene_images':{}}
    for shot in board['shots']:
        check()
        ident, scene = shot['shot_id'],shot['scene_index']
        prior = previous.get('shot_images',{}).get(ident)
        force = ('visual' in run.outputs.get('_repair_stages',[]) and
            (ident in changed if changed else not changed_scenes or scene in changed_scenes))
        old_shot = next((s for s in previous.get('storyboard',{}).get('shots',[]) if s['shot_id']==ident),None)
        if prior and old_shot and old_shot['reference_prompt']==shot['reference_prompt'] and not force:
            path = owned_asset(run,prior)
            selected[ident] = prior
            receipts[ident] = previous.get('generation',{}).get(ident,{})
        else:
            refs = [r for r in references if r.get('shot_id') in (None,ident)]
            ref_paths = [owned_asset(run,r['asset_id'],r['sha256']) for r in refs]
            group = shot.get('continuity_group','')
            if group and group in anchors and len(ref_paths)<4:
                ref_paths.append(anchors[group])
            ref_paths = ref_paths[:4]
            # One quality model and one request per shot, without comparison rounds.
            model = 'klein'
            instruction = run.outputs.get('_feedback',{}).get('instructions','') if force else ''
            prompt = ('Requested correction: '+instruction[:450]+'\n' if instruction else '')
            prompt += shot['reference_prompt'][:1000]+'\n'+identity[:400]+'\nVertical portrait, single starting frame, no text, no panels.'
            signature = digest({'shot':shot,'prompt':prompt,'model':model,'size':[576,1024],
                'refs':[file_hash(p) for p in ref_paths],'policy':1,
                'nonce':run.outputs.get('_shot_nonces',{}).get(ident),
                'provider':settings().image_provider,'steps':25 if model=='lucid' else 'fixed'})
            journal = folder/(ident+'-image.json')
            state = json.loads(journal.read_text(encoding='utf-8')) if journal.is_file() else {}
            if state.get('signature')!=signature:
                state = {'signature':signature,'attempt':0}
            while True:
                check()
                attempt = state['attempt']
                target = folder/(ident+'-image-'+signature[:12]+f'-{attempt}.png')
                if not (state.get('sha256') and target.is_file() and file_hash(target)==state['sha256']):
                    if media_bytes is None:
                        media_bytes = check_disk()
                    if (media_bytes >= settings().max_disk_gb*1024**3
                            or shutil.disk_usage(folder).free < 512*1024**2):
                        raise ProviderError('Medya depolama sınırına ulaşıldı veya diskte yeterli boş alan yok.')
                    previous_size = target.stat().st_size if target.is_file() else 0
                    if state.get('pinned_asset'):
                        raise ProviderError('Sabitlenmiş görsel özeti geçersiz.')
                    if ref_paths and settings().image_provider!='cloudflare':
                        raise ProviderError('Yerel görsel adaptörü referansla düzenlemeyi desteklemiyor.')
                    if settings().image_provider=='cloudflare':
                        from .providers import QuotaExceeded
                        try:
                            mark(run.id,'visual','generate',f'{ident}: başlangıç görseli üretiliyor',
                                completed=progress['completed'],total=progress['total'])
                            info = cloudflare_image(state.get('correction','')[:500]+'\n'+prompt,target,check,
                                model=model,references=ref_paths,seed=int(digest([run.id,ident,signature,attempt])[:8],16))
                        except QuotaExceeded:
                            from .media_library import stock_image,plan_stock_search,prepare_stock_batch
                            unplanned=[s for s in board['shots'] if s['shot_id'] not in selected and
                                (s['shot_id'] not in stock_queries or any(len(q.split())>5 for q in stock_queries[s['shot_id']]))]
                            if unplanned:
                                mark(run.id,'visual','stock_plan','Kota yetersiz; açık lisanslı kaynak araması planlanıyor')
                                stock_queries.update(plan_stock_search(llm,unplanned,story=run.outputs['script']))
                                mutate(run.id,{'_stock_queries':stock_queries})
                            update=lambda phase,label,detail:mark(run.id,'visual',phase,label,detail=detail,
                                completed=progress['completed'],total=progress['total'])
                            if ident not in stock_prepared:
                                pending=[]
                                for candidate in board['shots'][board['shots'].index(shot):]:
                                    cached_file=folder/(candidate['shot_id']+'-image.json')
                                    cached=json.loads(cached_file.read_text()) if cached_file.is_file() else {}
                                    future_force=('visual' in run.outputs.get('_repair_stages',[]) and
                                        (candidate['shot_id'] in changed if changed else not changed_scenes or candidate['scene_index'] in changed_scenes))
                                    if candidate['shot_id']!=ident and not future_force and cached.get('sha256'):
                                        cached_path=folder/(candidate['shot_id']+'-image-'+cached['signature'][:12]+f'-{cached["attempt"]}.png')
                                        if cached_path.is_file() and file_hash(cached_path)==cached['sha256']:continue
                                    pending.append(candidate)
                                    if len(pending)==4:break
                                stock_prepared.update(prepare_stock_batch(llm,pending,folder,stock_queries,check,update,
                                    story=run.outputs['script'],excluded_sources=[r['source'] for r in receipts.values() if r.get('source')]))
                            info = stock_image(llm,shot,target,check,prepared=stock_prepared[ident])
                            from .db import Event
                            with DB() as db:
                                db.add(Event(run_id=run.id,stage='visual',message=f'{ident}: ücretsiz görsel bütçesi yetersiz; açık lisanslı kaynak kullanıldı.'))
                                db.commit()
                    else:
                        media.image(prompt+'\n'+state.get('correction',''),target,check)
                        info = {'model':settings().image_model,'reference_count':0}
                    media_bytes += target.stat().st_size-previous_size
                    state.update(sha256=file_hash(target),generation={**info,'reason':info.get('reason','Tek görsel modeli: FLUX.2 Klein 9B'),
                        'signature':signature,'reference_hashes':[file_hash(p) for p in ref_paths]})
                    atomic_json(journal,state)
                with DB() as db:
                    asset_id = register(db,run,target,'image')
                selected[ident] = asset_id
                receipts[ident] = {**state['generation'],'review':state.get('review'),
                    'attempt':attempt,'acceptance':'automatic_source_selection'}
                if state['generation'].get('direction'):
                    shot.update(state['generation']['direction'])
                path = target
                break
        if shot.get('continuity_group'):
            anchors.setdefault(shot['continuity_group'],path)
        progress['completed'] += 1
        progress['scene_images'].setdefault(str(scene),selected[ident])
        progress['shot_images']=dict(selected)
        progress['generation']=dict(receipts)
        mutate(run.id,{'_visual_progress':progress})
        mark(run.id,'visual','image_ready',f'{progress["completed"]}/{progress["total"]} çekim görseli hazır',
            completed=progress['completed'],total=progress['total'])
    # Persist references to generated anchors with their project, not a provider prompt.
    mutate(run.id,{'_visual_identity':identity,'_media_review':None})
    cover = folder/'cover.png'
    media.cover(owned_asset(run,selected[board['shots'][0]['shot_id']]),project.title,cover,brand)
    with DB() as db:
        cover_id = register(db,run,cover,'cover')
    images = [selected[next(s['shot_id'] for s in board['shots'] if s['scene_index']==i)]
              for i in range(len(run.outputs['script']['scenes']))]
    return {'images':images,'shot_images':selected,'cover':cover_id,'storyboard':board,
            'visual_identity':identity,'generation':receipts}
