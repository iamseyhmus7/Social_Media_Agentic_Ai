"""Authenticated reference library and explicit source-media interventions."""
import io
from uuid import uuid4
from copy import deepcopy
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .db import get_db, Run, Asset, VisualReference, RemoteJob
from .security import current_user
from .schemas import ReferencePatch, ShotChange, MediaReviewAnswer, Reedit
from .storage import media_path, file_hash, check_disk
from .visual_quality import digest, reference_snapshot

router = APIRouter(prefix='/api/v1')


def project_for(db, project_id, user):
    from .main import owned_project
    return owned_project(db,project_id,user)


def reference_data(db, item):
    return {'id':item.id,'asset_id':item.asset_id,'name':item.name,'kind':item.kind,
        'shot_id':item.shot_id,'active':item.active,'url':'/api/v1/assets/'+item.asset_id}


@router.get('/media/image-budget')
def image_budget(user=Depends(current_user)):
    from .image_budget import report
    return report()


@router.get('/projects/{project_id}/references')
def references(project_id: str, user=Depends(current_user), db: Session=Depends(get_db)):
    project_for(db,project_id,user)
    return [reference_data(db,r) for r in db.scalars(select(VisualReference).where(
        VisualReference.project_id==project_id).order_by(VisualReference.created))]


@router.post('/projects/{project_id}/references',status_code=201)
def upload_reference(project_id: str, file: UploadFile=File(...), kind: str=Form('character'),
                     name: str=Form('Referans'), user=Depends(current_user), db: Session=Depends(get_db)):
    project = project_for(db,project_id,user)
    if kind not in ('character','location') or not 1<=len(name.strip())<=120:
        raise HTTPException(422,'Karakter veya mekân ve en fazla 120 karakterlik ad seç.')
    if len(list(db.scalars(select(VisualReference.id).where(VisualReference.project_id==project_id,
        VisualReference.active.is_(True)))))>=4:
        raise HTTPException(409,'En fazla dört etkin referans kullanılabilir; önce bir referansı devre dışı bırak.')
    data = file.file.read(12*1024*1024+1)
    if len(data)>12*1024*1024:
        raise HTTPException(413,'Referans en fazla 12 MB olabilir.')
    try:
        with Image.open(io.BytesIO(data)) as source:
            if source.format not in ('PNG','JPEG','WEBP') or source.width*source.height>16_000_000:
                raise ValueError()
            source.load()
            image = source.convert('RGB')
            image.thumbnail((1536,1536))
    except (ValueError,OSError,UnidentifiedImageError,Image.DecompressionBombError):
        raise HTTPException(422,'En fazla 16 megapiksel PNG, JPEG veya WEBP görseli seç.') from None
    check_disk()
    ident = str(uuid4())
    path = media_path(f'{project_id}/references/{ident}.png')
    path.parent.mkdir(parents=True,exist_ok=True)
    image.save(path,format='PNG')
    asset = Asset(id=ident,project_id=project_id,run_id=None,revision=project.revision,kind='reference',
        path=path.relative_to(media_path('')).as_posix(),mime='image/png',sha256=file_hash(path))
    item = VisualReference(id=str(uuid4()),project_id=project_id,asset_id=ident,name=name.strip(),kind=kind,active=True)
    try:
        db.add(asset); db.flush(); db.add(item); db.commit()
    except Exception:
        db.rollback(); path.unlink(missing_ok=True)
        raise
    return reference_data(db,item)


@router.patch('/projects/{project_id}/references/{reference_id}')
def patch_reference(project_id: str, reference_id: str, data: ReferencePatch,
                    user=Depends(current_user), db: Session=Depends(get_db)):
    project_for(db,project_id,user)
    item = db.get(VisualReference,reference_id)
    if not item or item.project_id!=project_id:
        raise HTTPException(404,'Referans bulunamadı.')
    if data.active and not item.active and len(list(db.scalars(select(VisualReference.id).where(
        VisualReference.project_id==project_id,VisualReference.active.is_(True)))))>=4:
        raise HTTPException(409,'En fazla dört etkin referans kullanılabilir.')
    item.active = data.active
    db.commit()
    return reference_data(db,item)


def queue(db, run, user):
    from .worker import dispatch
    run.status,run.error,run.active_owner,run.cancel_requested = 'queued',None,user.id,False
    run.finished = None
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409,'Başka bir üretimin zaten aktif.') from None
    dispatch()
    from .main import run_data
    return run_data(db,run)


@router.post('/runs/{run_id}/media-review',status_code=202)
def media_review(run_id: str, data: MediaReviewAnswer, user=Depends(current_user), db: Session=Depends(get_db)):
    from .main import owned_run
    run = owned_run(db,run_id,user,lock=True)
    project = project_for(db,run.project_id,user)
    review = run.outputs.get('_media_review',{})
    asset = db.get(Asset,data.asset_id)
    if (run.status!='waiting_input' or run.revision!=project.revision or review.get('shot_id')!=data.shot_id
        or review.get('asset_id')!=data.asset_id or not asset or asset.project_id!=project.id
        or asset.run_id!=run.id or file_hash(media_path(asset.path))!=review.get('sha256')):
        raise HTTPException(409,'İncelenen medya veya video sürümü değişmiş.')
    if not data.accept:
        raise HTTPException(422,'Düzeltmek için çekimin Görseli değiştir veya Yalnız hareketi yeniden üret işlemini kullan.')
    outputs = deepcopy(run.outputs)
    outputs.setdefault('_media_acceptances',{})[data.shot_id] = digest([review['sha256'],review['signature']])
    outputs.pop('_media_review',None)
    run.outputs = outputs
    return queue(db,run,user)


@router.post('/projects/{project_id}/shots/{shot_id}/change',status_code=202)
def change_shot(project_id: str, shot_id: str, data: ShotChange,
                user=Depends(current_user), db: Session=Depends(get_db)):
    from .main import owned_run
    project = project_for(db,project_id,user)
    source = owned_run(db,data.run_id,user,lock=True)
    board = source.outputs.get('visual',{}).get('storyboard') or source.outputs.get('_storyboard',{})
    shot = next((s for s in board.get('shots',[]) if s['shot_id']==shot_id),None)
    if source.project_id!=project_id or source.revision!=project.revision or not shot:
        raise HTTPException(404,'Güncel çekim bulunamadı.')
    requested=set(data.shot_ids or [shot_id])
    selected_shots=[s for s in board.get('shots',[]) if s['shot_id'] in requested]
    if shot_id not in requested or len(selected_shots)!=len(requested) or (data.action=='pin' and len(requested)!=1):
        raise HTTPException(422,'Yalnız güncel plandaki çekimler birlikte düzeltilebilir.')
    if data.action=='pin':
        asset_id = source.outputs.get('visual',{}).get('shot_images',{}).get(shot_id)
        if not asset_id:
            raise HTTPException(409,'Sabitlenebilecek kabul edilmiş görsel yok.')
        existing = db.scalar(select(VisualReference).where(VisualReference.project_id==project_id,
            VisualReference.asset_id==asset_id,VisualReference.active.is_(True)))
        if existing:
            return reference_data(db,existing)
        if len(reference_snapshot(db,project_id))>=4:
            raise HTTPException(409,'Önce bir referansı devre dışı bırak.')
        item = VisualReference(id=str(uuid4()),project_id=project_id,asset_id=asset_id,
            name='Çekim '+shot_id,kind='character',active=True)
        db.add(item); db.commit()
        return reference_data(db,item)
    if source.outputs.get('_config',{}).get('visual_policy')!='references_v1':
        raise HTTPException(409,'Çekim kontrolleri yeni kalite profiliyle üretilen videolarda kullanılabilir. Eski video için mevcut geri bildirim alanını kullan.')
    if not data.instructions.strip():
        raise HTTPException(422,'Bu çekimde neyin değişmesini istediğini yaz.')
    if db.scalar(select(Run.id).where(Run.user_id==user.id,Run.active_owner.is_not(None))):
        raise HTTPException(409,'Aktif üretim tamamlanmalı veya durdurulmalı.')
    if db.scalar(select(RemoteJob.id).where(RemoteJob.run_id==source.id,RemoteJob.account_slot.is_not(None))):
        raise HTTPException(409,'Uzak GPU işi henüz kapanmadı.')
    stage = 'visual' if data.action=='image' else 'motion'
    if ((source.status=='waiting_input' and source.outputs.get('_media_review')) or
        (source.status in ('failed','cancelled') and not source.outputs.get('editor') and source.stage in ('visual','motion'))):
        run = source
        outputs = deepcopy(run.outputs)
        outputs.pop('_media_review',None)
        for selected in selected_shots:
            outputs.setdefault('_shot_nonces',{})[selected['shot_id']] = str(uuid4())
        outputs.pop('_motion_plan',None)
        if stage=='visual' and outputs.get('visual'):
            outputs['_reuse_visual']=outputs.pop('visual')
    else:
        from .reedit import create_reedit
        run = create_reedit(db,project,user,Reedit(run_id=source.id),commit=False)
        outputs = deepcopy(run.outputs)
        for name in (('visual','motion') if stage=='visual' else ('motion',)):
            outputs['_reuse_'+name] = outputs.pop(name)
        outputs['_storyboard'] = deepcopy(board)
        run.pipeline_version = 3
    outputs.pop('_stock_queries',None)
    if stage=='visual':
        outputs.pop('_visual_progress',None)
    outputs.update(_changed_shots=[s['shot_id'] for s in selected_shots],_changed_scenes=sorted({s['scene_index'] for s in selected_shots}),_repair_stages=[stage],
        _edit_only=False,_feedback={'instructions':data.instructions,'stages':[stage]},
        _visual_references=reference_snapshot(db,project_id))
    outputs['_config'] = deepcopy(source.outputs.get('_config',{}))
    outputs['_shot_requests'] = {s['shot_id']:{'action':data.action,'instructions':data.instructions} for s in selected_shots}
    run.outputs, run.stage = outputs,stage
    return queue(db,run,user)
