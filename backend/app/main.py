import asyncio
import json
import secrets
import shutil
import httpx
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, Depends, HTTPException, Request, Response, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse, RedirectResponse
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession
from .config import settings, snapshot_settings
from .agents import AGENTS
from .db import DB, get_db, init_db, User, Session, Project, Run, RemoteJob, Asset, Event, Approval, Publication, YouTubeConnection, WorkerLease, now
from .security import current_user, admin, digest, hasher, verify_password
from .schemas import Login, Registration, NewUser, NewProject, RunOptions, Revision, Reedit, Approve, Publish, Brand, FeedbackRequest, FeedbackAnswer, DeleteProjects
from .storage import media_path, register, check_disk
from . import youtube
from .worker import dispatch


@asynccontextmanager
async def lifespan(_app):
    init_db()
    settings().media_root.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title='Sahne API', version='0.1.0', lifespan=lifespan)
attempts = defaultdict(deque)


@app.middleware('http')
async def security_headers(request, call_next):
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        origin = request.headers.get('origin')
        if origin and origin != settings().app_origin:
            return Response('Origin izinli değil.', status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Cache-Control'] = 'no-store'
    return response


def owned_project(db, project_id, user):
    project = db.scalar(select(Project).where(Project.id == project_id, Project.user_id == user.id).with_for_update())
    if not project or project.user_id != user.id:
        raise HTTPException(404, 'Proje bulunamadı.')
    return project


def owned_run(db, run_id, user, *, lock=False):
    run = db.scalar(select(Run).where(Run.id == run_id, Run.user_id == user.id).with_for_update()) if lock else db.get(Run, run_id)
    if not run or run.user_id != user.id:
        raise HTTPException(404, 'Üretim bulunamadı.')
    return run


def retryable_model_review(run):
    return (run.status == 'waiting_input' and run.stage == 'script'
        and (run.outputs.get('_recovery', {}).get('active') == 'model_output'
            or run.outputs.get('_script_editorial', {}).get('phase') == 'visual_revision_pending')
        and bool(run.outputs.get('_script_editorial', {}).get('draft')))


def continuable_script(run):
    return (run.status == 'script_ready' and bool(run.outputs.get('_script_only'))
        and bool(run.outputs.get('script', {}).get('scenes')))


def run_data(db, run):
    if not run:
        return None
    result = {key: getattr(run, key) for key in ['id', 'project_id', 'revision', 'status', 'stage', 'outputs', 'error', 'created', 'updated', 'started', 'finished', 'cancel_requested']}
    result['approved'] = youtube.valid_approval(db, run)
    result['pipeline_version'] = run.pipeline_version
    result['can_retry'] = retryable_model_review(run)
    result['can_continue'] = continuable_script(run) and run.revision == db.get(Project, run.project_id).revision
    editorial = run.outputs.get('_script_editorial', {})
    labels = {'writing':'Senaryo yazılıyor', 'text_repair':'Senaryo metni düzeltiliyor',
        'text_review':'Supervisor senaryo metnini inceliyor', 'visual_allocation':'Görsel plan hazırlanıyor',
        'visual_repair':'Görsel plan düzeltiliyor', 'visual_review':'Supervisor görsel planı inceliyor',
        'visual_revision_pending':'Metin hazır · Görsel plan düzeltme bekliyor', 'ready':'Senaryo ve görsel plan hazır'}
    phase = editorial.get('phase')
    if not phase and editorial.get('approved') and not editorial.get('visuals_approved'):
        phase = 'visual_revision_pending' if run.status == 'failed' else 'visual_review' if editorial.get('visuals') else 'visual_allocation'
    result['script_progress'] = {'phase':phase, 'label':labels.get(phase, 'Senaryo hazırlanıyor'),
        'text_approved':bool(editorial.get('approved')), 'visuals_approved':bool(editorial.get('visuals_approved')),
        'approved_text':editorial.get('draft') if editorial.get('approved') else None,
        'review_reason':(editorial.get('visual_reviews') or [{}])[-1].get('reason')}
    result['editor_progress'] = run.outputs.get('_editor_progress',{})
    result['provider_wait'] = run.outputs.get('_provider_wait',{})
    from .recovery import initial
    result['recovery'] = initial(run.outputs)
    from .visual_progress import visual_progress
    result['visual_progress'] = visual_progress(run.outputs)
    result['edit_style'] = run.outputs.get('_edit_style', 'classic')
    result['outputs'] = {k: v for k, v in run.outputs.items() if not k.startswith('_')}
    result['agents'] = [a['id'] for a in AGENTS if run.pipeline_version >= 2 or a['id'] != 'motion']
    result['remote_jobs'] = [{'status': j.status, 'attempt': j.attempt, 'version': j.version, 'created': j.created,
                             'completed_clips': len(j.result.get('clips', {})), 'failed_clips': len(j.result.get('errors', {}))}
                            for j in db.scalars(select(RemoteJob).where(RemoteJob.run_id == run.id).order_by(RemoteJob.created))]
    result['assets'] = [{'id': a.id, 'kind': a.kind, 'url': f'/api/v1/assets/{a.id}'} for a in db.scalars(select(Asset).where(Asset.run_id == run.id))]
    publication = db.scalar(select(Publication).where(Publication.run_id == run.id))
    result['publication'] = publication_data(publication)
    return result


def publication_data(publication):
    return {key: getattr(publication, key) for key in ['id', 'run_id', 'status', 'publish_at', 'video_id', 'error']} if publication else None


def project_data(db, project):
    run = db.scalar(select(Run).where(Run.project_id == project.id, Run.revision == project.revision).order_by(Run.created.desc()))
    return {**{key: getattr(project, key) for key in ['id', 'title', 'topic', 'audience', 'tone', 'duration', 'revision', 'created', 'music_asset']}, 'run': run_data(db, run)}


@app.get('/api/v1/health')
def health():
    cfg = settings()
    from .db import engine
    from sqlalchemy import text
    try:
        with engine.connect() as connection:
            connection.execute(text('SELECT 1'))
    except Exception:
        raise HTTPException(503, 'Veritabanına erişilemiyor.') from None
    from .kaggle_provider import configured
    return {'ok': True, 'database_backend': engine.dialect.name, 'queue_mode': cfg.queue_mode, 'evren_configured': bool(cfg.evren_api_key and cfg.evren_base_url and cfg.evren_model and cfg.evren_contract_verified and cfg.evren_protocol == 'openai_chat'), 'youtube_configured': bool(cfg.youtube_client_id and cfg.youtube_client_secret and cfg.token_encryption_key), 'ffmpeg_available': bool(shutil.which(cfg.ffmpeg_bin) and shutil.which(cfg.ffprobe_bin)), 'tts_provider': cfg.tts_provider, 'tts_configured': bool(cfg.elevenlabs_api_key), 'image_provider': cfg.image_provider, 'video_provider': cfg.video_provider, 'editor_provider': cfg.editor_provider, 'kaggle_configured': configured(), 'agents': AGENTS}


def start_session(user, response, db):
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    db.add(Session(id=digest(token), user_id=user.id, csrf=csrf, expires=now() + settings().session_hours * 3600))
    db.commit()
    response.set_cookie('sahne_session', token, httponly=True, secure=settings().cookie_secure, samesite='lax', max_age=settings().session_hours * 3600, path='/')
    return {'user': {'id': user.id, 'name': user.name, 'email': user.email, 'role': user.role}, 'csrf': csrf}


@app.post('/api/v1/auth/register', status_code=201)
def register(data: Registration, request: Request, response: Response, db: DBSession = Depends(get_db)):
    if not settings().allow_registration:
        raise HTTPException(403, 'Yeni hesap kaydı kapalı. Yöneticinle iletişime geç.')
    history = attempts['register:' + (request.client.host if request.client else 'local')]
    while history and history[0] < now() - 60:
        history.popleft()
    if len(history) >= 5:
        raise HTTPException(429, 'Çok fazla kayıt denemesi. Bir dakika sonra tekrar dene.')
    history.append(now())
    password_hash = hasher.hash(data.password)
    # Serialize first-account selection across API processes; only one admin can bootstrap.
    if db.bind.dialect.name == 'postgresql':
        from sqlalchemy import text
        db.execute(text('SELECT pg_advisory_xact_lock(73624601)'))
    elif db.bind.dialect.name == 'sqlite':
        db.connection().exec_driver_sql('BEGIN IMMEDIATE')
    first = db.scalar(select(func.count(User.id))) == 0
    created = User(id=str(uuid4()), email=data.email, name=data.name,
                   role='admin' if first else 'member', password_hash=password_hash)
    db.add(created)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Bu e-posta zaten kayıtlı. Giriş yapabilirsin.') from None
    return start_session(created, response, db)


@app.post('/api/v1/auth/login')
def login(data: Login, response: Response, request: Request, db: DBSession = Depends(get_db)):
    key = request.client.host if request.client else 'local'
    history = attempts[key]
    while history and history[0] < now() - 60:
        history.popleft()
    if len(history) >= 8:
        raise HTTPException(429, 'Çok fazla giriş denemesi. Bir dakika sonra tekrar dene.')
    history.append(now())
    user = db.scalar(select(User).where(User.email == data.email.strip().lower()))
    if not user or not user.active or not verify_password(data.password, user.password_hash):
        raise HTTPException(401, 'E-posta veya parola hatalı.')
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    db.add(Session(id=digest(token), user_id=user.id, csrf=csrf, expires=now() + settings().session_hours * 3600))
    db.commit()
    response.set_cookie('sahne_session', token, httponly=True, secure=settings().cookie_secure, samesite='lax', max_age=settings().session_hours * 3600, path='/')
    return {'user': {'id': user.id, 'name': user.name, 'email': user.email, 'role': user.role}, 'csrf': csrf}


@app.get('/api/v1/auth/session')
def session(request: Request, db: DBSession = Depends(get_db)):
    record = db.get(Session, digest(request.cookies.get('sahne_session', '')))
    user = db.get(User, record.user_id) if record and record.expires > now() else None
    if not user or not user.active:
        return {'user': None, 'csrf': None}
    return {'user': {'id': user.id, 'name': user.name, 'email': user.email, 'role': user.role}, 'csrf': record.csrf}


@app.post('/api/v1/auth/logout')
def logout(request: Request, response: Response, user=Depends(current_user), db: DBSession = Depends(get_db)):
    db.delete(db.get(Session, request.state.session.id))
    db.commit()
    response.delete_cookie('sahne_session', path='/')
    return {'ok': True}


@app.post('/api/v1/users', status_code=201)
def new_user(data: NewUser, user=Depends(admin), db: DBSession = Depends(get_db)):
    created = User(id=str(uuid4()), email=data.email.strip().lower(), name=data.name, role=data.role, password_hash=hasher.hash(data.password))
    db.add(created)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Bu e-posta zaten kayıtlı.') from None
    return {'id': created.id, 'email': created.email, 'name': created.name, 'role': created.role}


@app.get('/api/v1/users')
def users(user=Depends(admin), db: DBSession = Depends(get_db)):
    return [{'id': u.id, 'name': u.name, 'email': u.email, 'role': u.role} for u in db.scalars(select(User))]


@app.get('/api/v1/brand')
def brand(user=Depends(current_user)):
    fields = {key: value for key, value in (user.brand or {}).items() if key in Brand.model_fields}
    return {**Brand.model_validate(fields).model_dump(), 'has_logo': bool(user.brand.get('logo_path'))}


@app.put('/api/v1/brand')
def update_brand(data: Brand, user=Depends(current_user), db: DBSession = Depends(get_db)):
    db.get(User, user.id).brand = {**{k:v for k,v in user.brand.items() if k!='voice'}, **data.model_dump()}
    db.commit()
    return data


@app.post('/api/v1/brand/logo', status_code=201)
def upload_logo(file: UploadFile = File(...), user=Depends(current_user), db: DBSession = Depends(get_db)):
    from PIL import Image, UnidentifiedImageError
    import io
    data = file.file.read(5 * 1024 * 1024 + 1)
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(413, 'Logo en fazla 5 MB olabilir.')
    try:
        image = Image.open(io.BytesIO(data))
        if image.width * image.height > 16_000_000:
            raise ValueError()
        image = image.convert('RGBA')
        image.thumbnail((1024, 1024))
    except (UnidentifiedImageError, ValueError, OSError, Image.DecompressionBombError):
        raise HTTPException(422, 'Geçerli ve en fazla 16 megapiksel PNG/JPEG/WebP görseli seç.') from None
    check_disk()
    relative = f'brands/{user.id}/{uuid4()}.png'
    path = media_path(relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    db.get(User, user.id).brand = {**user.brand, 'logo_path': relative}
    db.commit()
    return {'has_logo': True, 'url': '/api/v1/brand/logo'}


@app.get('/api/v1/brand/logo')
def get_logo(user=Depends(current_user)):
    if not user.brand.get('logo_path'):
        raise HTTPException(404, 'Logo eklenmemiş.')
    return FileResponse(media_path(user.brand['logo_path']), media_type='image/png')


@app.get('/api/v1/projects')
def projects(user=Depends(current_user), db: DBSession = Depends(get_db)):
    component_check = select(Run.id).where(Run.project_id == Project.id,
        Run.outputs['_component_check'].as_boolean().is_(True)).exists()
    return [project_data(db, p) for p in db.scalars(select(Project).where(
        Project.user_id == user.id, ~component_check).order_by(Project.created.desc()))]


@app.post('/api/v1/projects', status_code=201)
def create_project(data: NewProject, user=Depends(current_user), db: DBSession = Depends(get_db)):
    project = Project(id=str(uuid4()), user_id=user.id, title=data.topic[:120],
        **{**data.model_dump(), 'duration': data.duration or 45}, duration_auto=data.duration is None)
    db.add(project)
    db.commit()
    return project_data(db, project)


@app.get('/api/v1/projects/{project_id}')
def get_project(project_id: str, user=Depends(current_user), db: DBSession = Depends(get_db)):
    return project_data(db, owned_project(db, project_id, user))


@app.post('/api/v1/projects/{project_id}/runs', status_code=202)
def start_run(project_id: str, data: RunOptions | None = None, user=Depends(current_user), db: DBSession = Depends(get_db)):
    project = owned_project(db, project_id, user)
    existing = db.scalar(select(Run).where(Run.project_id == project_id, Run.revision == project.revision).order_by(Run.created.desc()))
    if existing:
        return run_data(db, existing)
    from .db import Feedback
    if db.scalar(select(Feedback.id).where(Feedback.user_id==user.id, Feedback.status.in_(['queued', 'waiting_quota']))):
        raise HTTPException(409, 'Önce geri bildirim değerlendirmesi tamamlanmalı.')
    run = Run(id=str(uuid4()), project_id=project.id, user_id=user.id, active_owner=user.id,
        revision=project.revision, pipeline_version=3, outputs={'_script_only': bool(data and data.script_only), '_config': snapshot_settings(),
        '_brand': {k:v for k,v in user.brand.items() if k!='voice'}, '_edit_style': 'auto',
        '_requested_duration': None if project.duration_auto else project.duration,
        '_recovery': {'version':1,'voice':{'text_used':0,'speed_used':0,'history':[]}}})
    db.add(run)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Kullanıcı başına bir aktif üretim çalışabilir.') from None
    dispatch()
    return run_data(db, run)


@app.delete('/api/v1/projects/{project_id}')
def delete_project(project_id: str, user=Depends(current_user), db: DBSession = Depends(get_db)):
    from .content_deletion import delete_content
    return delete_content(db, user, [project_id])


@app.post('/api/v1/projects/delete')
def delete_projects(data: DeleteProjects, user=Depends(current_user), db: DBSession = Depends(get_db)):
    from .content_deletion import delete_content
    return delete_content(db, user, data.project_ids)


@app.get('/api/v1/runs/{run_id}')
def get_run(run_id: str, user=Depends(current_user), db: DBSession = Depends(get_db)):
    return run_data(db, owned_run(db, run_id, user))


@app.get('/api/v1/runs/{run_id}/events')
def events(run_id: str, request: Request, after: int = 0, user=Depends(current_user), db: DBSession = Depends(get_db)):
    owned_run(db, run_id, user)
    try:
        cursor = max(after, int(request.headers.get('last-event-id', '0')))
    except ValueError:
        raise HTTPException(400, 'Geçersiz olay imleci.') from None

    async def stream():
        nonlocal cursor
        for _ in range(120):  # reconnect revalidates session and access
            if await request.is_disconnected():
                break
            with DB() as connection:
                current = connection.get(Run, run_id)
                if current is None:
                    yield 'event: status\ndata: ' + json.dumps({'status':'deleted','stage':''}) + '\n\n'
                    return
                batch = connection.scalars(select(Event).where(Event.run_id == run_id, Event.id > cursor).order_by(Event.id)).all()
                for entry in batch:
                    cursor = entry.id
                    payload = json.dumps({'stage': entry.stage, 'message': entry.message, 'created': entry.created}, ensure_ascii=False)
                    yield f'id: {entry.id}\nevent: progress\ndata: {payload}\n\n'
                yield 'event: status\ndata: ' + json.dumps({'status': current.status, 'stage': current.stage}) + '\n\n'
                if current.status not in ('queued', 'running', 'waiting_remote', 'waiting_provider'):
                    break
            yield ': heartbeat\n\n'
            await asyncio.sleep(2)
    return StreamingResponse(stream(), media_type='text/event-stream', headers={'X-Accel-Buffering': 'no'})


@app.get('/api/v1/runs/{run_id}/log')
def log(run_id: str, user=Depends(current_user), db: DBSession = Depends(get_db)):
    owned_run(db, run_id, user)
    return [{'id': e.id, 'stage': e.stage, 'message': e.message, 'created': e.created} for e in db.scalars(select(Event).where(Event.run_id == run_id).order_by(Event.id))]


@app.post('/api/v1/runs/{run_id}/cancel')
def cancel_run(run_id: str, user=Depends(current_user), db: DBSession = Depends(get_db)):
    run = owned_run(db, run_id, user)
    if run.status not in ('running', 'queued', 'waiting_quota', 'waiting_remote', 'waiting_input', 'waiting_provider'):
        raise HTTPException(409, 'Bu üretim şu anda çalışmıyor.')
    run.cancel_requested = True
    if run.status != 'running':
        run.status, run.active_owner = 'cancelled', None
    db.commit()
    return run_data(db, run)


@app.post('/api/v1/runs/{run_id}/continue', status_code=202)
def continue_run(run_id: str, user=Depends(current_user), db: DBSession = Depends(get_db)):
    run = owned_run(db, run_id, user, lock=True)
    project = db.get(Project, run.project_id)
    if not continuable_script(run) or run.revision != project.revision:
        raise HTTPException(409, 'Yalnızca güncel sürümde senaryosu tamamlanmış üretim kaldığı yerden sürdürülebilir.')
    # Keep the existing run, approved script, plan and provider configuration.
    # Removing this explicit stop lets the supervisor select the next eligible stage.
    run.outputs = {**run.outputs, '_script_only':False}
    run.status, run.error, run.cancel_requested, run.active_owner = 'queued', None, False, user.id
    run.finished, run.updated = None, now()
    db.add(Event(run_id=run.id, stage='script',
        message='Senaryo testi tamamlandı; mevcut plan ve senaryo korunarak ses ve medya üretimine devam istendi.'))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Başka bir üretimin zaten aktif.') from None
    dispatch()
    return run_data(db, run)


@app.post('/api/v1/runs/{run_id}/retry', status_code=202)
def retry_run(run_id: str, user=Depends(current_user), db: DBSession = Depends(get_db)):
    run = owned_run(db, run_id, user, lock=True)
    project = db.get(Project, run.project_id)
    review_retry = retryable_model_review(run)
    if (run.status not in ('failed', 'waiting_quota', 'cancelled', 'waiting_provider') and not review_retry) or run.revision != project.revision:
        raise HTTPException(409, 'Yalnızca güncel sürümde durdurulmuş veya başarısız üretim yeniden denenebilir.')
    if run.status == 'cancelled' and run.pipeline_version >= 2:
        if db.scalar(select(RemoteJob.id).where(RemoteJob.run_id == run.id, RemoteJob.account_slot.is_not(None))):
            raise HTTPException(409, 'Kaggle durdurma işlemi henüz bitmedi. Tamamlandığında yeniden deneyebilirsin.')
        # An explicit restart gets a new remote identity. Late outputs from the
        # canceled session are never reused, while speech/images remain cached.
        if 'motion' not in run.outputs:
            run.outputs = {**run.outputs, '_motion_session': str(uuid4())}
    if run.status == 'failed' and run.stage == 'motion':
        from .kaggle_provider import ENGINE_REVISION
        if run.outputs.get('_motion_engine') != ENGINE_REVISION:
            # A code fix gets a new remote input identity, while all completed
            # upstream stages remain durable. Never swap an active GPU job.
            run.outputs = {**run.outputs, '_motion_engine': ENGINE_REVISION}
            db.add(Event(run_id=run.id, stage='motion', message='Düzeltilmiş video üretim motoruyla yeniden deneme istendi. Hazır ses ve görseller korunuyor.'))
    editorial = run.outputs.get('_script_editorial', {})
    if run.stage == 'script' and editorial.get('approved') and not editorial.get('visuals_approved'):
        previous = (editorial.get('visual_reviews') or [{}])[-1]
        if previous.get('decision') == 'revise':
            # Only an explicit user retry opens another bounded review window.
            # Provider retries retain the current window and repair checkpoint.
            editorial = {**editorial, 'visual_review_window_start':len(editorial.get('visual_reviews', [])),
                'phase':'visual_repair' if not editorial.get('visual_repair_done') else 'visual_review'}
            run.outputs = {**run.outputs, '_script_editorial':editorial}
    if review_retry and run.outputs.get('_recovery', {}).get('active') == 'model_output':
        recovery = {**run.outputs.get('_recovery', {}), 'active':None,
            'model_output':{'kind':'invalid_output','status':'repairing','action':'retry_review'}}
        run.outputs = {**run.outputs, '_recovery':recovery}
    run.status, run.error, run.cancel_requested, run.active_owner = 'queued', None, False, user.id
    if '_provider_wait' in run.outputs:
        # Only an explicit user retry starts a new outage tracking window.
        run.outputs={**run.outputs,'_provider_wait':{}}
    run.finished = None
    db.add(Event(run_id=run.id, stage=run.stage,
        message='Mevcut üretim kayıtlı kontrol noktasından sürdürülecek; tamamlanmış aşamalar korunuyor.'))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Başka bir üretimin zaten aktif.') from None
    dispatch()
    return run_data(db, run)


@app.post('/api/v1/projects/{project_id}/revisions', status_code=202)
def revise(project_id: str, data: Revision, user=Depends(current_user), db: DBSession = Depends(get_db)):
    project = owned_project(db, project_id, user)
    latest = db.scalar(select(Run).where(Run.project_id == project_id, Run.revision == project.revision).order_by(Run.created.desc()))
    if not latest or latest.status in ('queued', 'running', 'waiting_remote'):
        raise HTTPException(409, 'Revizyon öncesi aktif üretimi durdur.')
    publication = db.scalar(select(Publication).where(Publication.run_id == latest.id))
    if publication and (publication.status in ('uploading', 'uncertain') or publication.video_id):
        raise HTTPException(409, 'Yayınlanan, planlanan veya sonucu belirsiz yükleme varken revizyon yapılamaz. Önce YouTube kanalını kontrol et.')
    if publication:
        publication.status = 'cancelled'
    project.revision += 1
    retained = {k: v for k, v in latest.outputs.items() if k in ('supervisor', 'strategy')}
    retained['script'] = data.script.model_dump()
    retained.update({'_config': snapshot_settings(), '_brand': dict(user.brand), '_edit_style': latest.outputs.get('_edit_style', 'dynamic')})
    run = Run(id=str(uuid4()), project_id=project.id, user_id=user.id, active_owner=user.id, revision=project.revision, outputs=retained, pipeline_version=2)
    db.add(run)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Başka bir üretimin zaten aktif.') from None
    dispatch()
    return run_data(db, run)


@app.post('/api/v1/projects/{project_id}/edits', status_code=202)
def reedit(project_id: str, data: Reedit, user=Depends(current_user), db: DBSession = Depends(get_db)):
    from .reedit import create_reedit
    project = owned_project(db, project_id, user)
    run = create_reedit(db, project, user, data)
    dispatch()
    return run_data(db, run)


@app.post('/api/v1/projects/{project_id}/approve')
def approve(project_id: str, data: Approve, user=Depends(current_user), db: DBSession = Depends(get_db)):
    project = owned_project(db, project_id, user)
    run = owned_run(db, data.run_id, user)
    if run.project_id != project_id or run.revision != project.revision or run.status != 'awaiting_approval' or not run.outputs.get('quality', {}).get('passed'):
        raise HTTPException(409, 'Yalnızca güncel, kontrolleri geçmiş video onaylanabilir.')
    if not db.scalar(select(Approval).where(Approval.run_id == run.id)):
        db.add(Approval(id=str(uuid4()), run_id=run.id, user_id=user.id, manifest=youtube.manifest(db, run)))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
    return {'approved': youtube.valid_approval(db, run), 'run_id': run.id, 'revision': run.revision}


@app.post('/api/v1/projects/{project_id}/feedback', status_code=202)
def submit_feedback(project_id: str, data: FeedbackRequest, user=Depends(current_user), db: DBSession = Depends(get_db)):
    from .feedback import create_feedback, serialize
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    result = create_feedback(db, owned_project(db, project_id, user), user, data)
    dispatch()
    return serialize(result)


@app.get('/api/v1/projects/{project_id}/feedback')
def list_feedback(project_id: str, user=Depends(current_user), db: DBSession = Depends(get_db)):
    from .db import Feedback
    from .feedback import serialize
    owned_project(db, project_id, user)
    return [serialize(item) for item in db.scalars(select(Feedback).where(Feedback.project_id==project_id,
        Feedback.user_id==user.id).order_by(Feedback.created.desc()).limit(20))]


@app.post('/api/v1/projects/{project_id}/feedback/{feedback_id}/answers', status_code=202)
def answer_feedback(project_id: str, feedback_id: str, data: FeedbackAnswer, user=Depends(current_user), db: DBSession = Depends(get_db)):
    from .db import Feedback
    from .feedback import serialize, source_check
    project = owned_project(db, project_id, user)
    item = db.scalar(select(Feedback).where(Feedback.id==feedback_id, Feedback.project_id==project_id,
        Feedback.user_id==user.id).with_for_update())
    if not item:
        raise HTTPException(404, 'Geri bildirim bulunamadı.')
    if item.status != 'needs_clarification' or not item.decision.get('clarification'):
        raise HTTPException(409, 'Bu geri bildirim yanıt beklemiyor.')
    source_check(db, project, user, item.source_run_id)
    item.answer, item.status, item.error = data.answer, 'queued', None
    db.commit()
    dispatch()
    return serialize(item)


@app.post('/api/v1/runs/{run_id}/answers', status_code=202)
def answer_run(run_id: str, data: FeedbackAnswer, user=Depends(current_user), db: DBSession = Depends(get_db)):
    run = owned_run(db, run_id, user, lock=True)
    project = db.get(Project, run.project_id)
    if run.status != 'waiting_input' or run.revision != project.revision:
        raise HTTPException(409, 'Bu üretim açıklama beklemiyor.')
    question = run.outputs.get('clarification', {}).get('question', '')
    run.outputs = {**run.outputs, '_brief_answer': {'question': question, 'answer': data.answer}}
    run.status, run.active_owner, run.error = 'queued', user.id, None
    db.commit()
    dispatch()
    return run_data(db, run)


@app.get('/api/v1/projects/{project_id}/publication')
def get_publication(project_id: str, user=Depends(current_user), db: DBSession = Depends(get_db)):
    project = owned_project(db, project_id, user)
    return project_data(db, project)['run']


@app.post('/api/v1/projects/{project_id}/publication', status_code=202)
def publish(project_id: str, data: Publish, user=Depends(current_user), db: DBSession = Depends(get_db)):
    owned_project(db, project_id, user)
    run = owned_run(db, data.run_id, user)
    if run.project_id != project_id or not youtube.valid_approval(db, run):
        raise HTTPException(409, 'Yayın için güncel video sürümünün onayı gerekli.')
    existing = db.scalar(select(Publication).where(Publication.run_id == run.id))
    if existing:
        if existing.status in ('failed', 'uncertain'):
            existing.status = 'queued'  # session is retained and probed, never replaced
            db.commit()
            dispatch()
        return publication_data(existing)
    if not db.get(YouTubeConnection, user.id):
        raise HTTPException(409, 'Önce Ayarlar ekranından YouTube hesabını bağla.')
    publish_at = None
    if data.publish_at:
        try:
            value = datetime.fromisoformat(data.publish_at.replace('Z', '+00:00'))
            if value.tzinfo is None or value.timestamp() < now() + 900:
                raise ValueError()
            publish_at = value.astimezone(timezone.utc).isoformat()
        except ValueError:
            raise HTTPException(422, 'Yayın zamanı saat dilimi içermeli ve en az 15 dakika ileride olmalı.') from None
    publication = Publication(id=str(uuid4()), project_id=project_id, run_id=run.id, publish_at=publish_at, made_for_kids=data.made_for_kids, synthetic_media=data.synthetic_media)
    db.add(publication)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return publication_data(db.scalar(select(Publication).where(Publication.run_id == run.id)))
    dispatch()
    return publication_data(publication)


@app.get('/api/v1/assets/{asset_id}')
def asset(asset_id: str, download: bool = False, user=Depends(current_user), db: DBSession = Depends(get_db)):
    file = db.get(Asset, asset_id)
    if not file:
        raise HTTPException(404, 'Dosya bulunamadı.')
    owned_project(db, file.project_id, user)
    path = media_path(file.path)
    if not path.is_file():
        raise HTTPException(404, 'Dosya diskte bulunamadı.')
    return FileResponse(path, media_type=file.mime, filename=path.name if download else None)


@app.post('/api/v1/projects/{project_id}/music', status_code=201)
def music(project_id: str, file: UploadFile = File(...), user=Depends(current_user), db: DBSession = Depends(get_db)):
    project = owned_project(db, project_id, user)
    if db.scalar(select(Run.id).where(Run.project_id == project_id)):
        raise HTTPException(409, 'Müzik yalnızca ilk üretim başlamadan eklenebilir.')
    suffix = Path(file.filename or '').suffix.lower()
    if suffix not in ('.mp3', '.wav', '.ogg', '.m4a'):
        raise HTTPException(422, 'MP3, WAV, OGG veya M4A dosyası seç.')
    check_disk()
    path = media_path(f'{project_id}/music-{uuid4()}{suffix}')
    path.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    with path.open('wb') as target:
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            if size > 30 * 1024 * 1024:
                target.close()
                path.unlink(missing_ok=True)
                raise HTTPException(413, 'Müzik dosyası en fazla 30 MB olabilir.')
            target.write(chunk)
    from .storage import file_hash
    record = Asset(id=str(uuid4()), project_id=project_id, revision=project.revision, kind='music', path=path.relative_to(settings().media_root.resolve()).as_posix(), mime=file.content_type or 'application/octet-stream', sha256=file_hash(path))
    db.add(record)
    project.music_asset = record.id
    db.commit()
    return {'id': record.id}


@app.get('/api/v1/youtube/status')
def youtube_status(user=Depends(current_user), db: DBSession = Depends(get_db)):
    return {'connected': bool(db.get(YouTubeConnection, user.id))}


@app.post('/api/v1/youtube/connect')
def connect(user=Depends(current_user), db: DBSession = Depends(get_db)):
    try:
        return {'url': youtube.authorize(db, user.id)}
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from None


@app.get('/api/v1/youtube/callback')
def oauth_callback(state: str = '', code: str = '', error: str = '', db: DBSession = Depends(get_db)):
    try:
        if error or not code:
            raise RuntimeError('YouTube izni verilmedi.')
        youtube.callback(db, state, code)
        return RedirectResponse(settings().app_origin + '/?youtube=connected')
    except (RuntimeError, httpx.RequestError) as exc:
        raise HTTPException(400, str(exc) if isinstance(exc, RuntimeError) else 'YouTube bağlantısı başarısız.') from None


@app.delete('/api/v1/youtube/connection')
def disconnect(user=Depends(current_user), db: DBSession = Depends(get_db)):
    connection = db.get(YouTubeConnection, user.id)
    if connection:
        db.delete(connection)
        db.commit()
    return {'ok': True}


@app.get('/api/v1/admin/metrics')
def metrics(user=Depends(admin), db: DBSession = Depends(get_db)):
    root = settings().media_root
    used = sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
    runs = db.scalars(select(Run)).all()
    completed = [r for r in runs if r.finished and r.started]
    lease = db.get(WorkerLease, 1)
    return {'disk_bytes': used, 'disk_limit_bytes': settings().max_disk_gb * 1024**3, 'queued': sum(r.status == 'queued' for r in runs), 'running': sum(r.status == 'running' for r in runs), 'failed': sum(r.status == 'failed' for r in runs), 'worker_busy': bool(lease and lease.expires > now()), 'average_queue_seconds': sum(r.started-r.created for r in completed)/len(completed) if completed else None, 'average_production_seconds': sum(r.finished-r.started for r in completed)/len(completed) if completed else None}

