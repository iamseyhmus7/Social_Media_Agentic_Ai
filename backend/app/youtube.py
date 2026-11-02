import json
import secrets
from datetime import datetime, timezone
from urllib.parse import urlencode
from uuid import uuid4
import httpx
from cryptography.fernet import Fernet
from sqlalchemy import select
from .config import settings
from .db import DB, OAuthState, YouTubeConnection, Publication, Run, Project, Approval, Asset, now
from .storage import media_path, file_hash


def cipher():
    key = settings().token_encryption_key
    if not key:
        raise RuntimeError('TOKEN_ENCRYPTION_KEY yapılandırılmalı.')
    return Fernet(key.encode())


def authorize(db, user_id):
    cfg = settings()
    if not cfg.youtube_client_id or not cfg.youtube_client_secret:
        raise RuntimeError('YouTube OAuth istemci bilgileri yapılandırılmalı.')
    cipher()
    state = secrets.token_urlsafe(32)
    db.add(OAuthState(id=state, user_id=user_id, expires=now() + 600))
    db.commit()
    return 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode({'client_id': cfg.youtube_client_id, 'redirect_uri': cfg.youtube_redirect_uri, 'response_type': 'code', 'scope': 'https://www.googleapis.com/auth/youtube.upload', 'access_type': 'offline', 'prompt': 'consent', 'state': state})


def callback(db, state, code):
    entry = db.get(OAuthState, state)
    if not entry or entry.expires < now():
        raise RuntimeError('OAuth oturumu geçersiz veya süresi dolmuş.')
    user_id = entry.user_id
    db.delete(entry)
    db.commit()
    cfg = settings()
    with httpx.Client(timeout=30) as client:
        response = client.post('https://oauth2.googleapis.com/token', data={'client_id': cfg.youtube_client_id, 'client_secret': cfg.youtube_client_secret, 'redirect_uri': cfg.youtube_redirect_uri, 'code': code, 'grant_type': 'authorization_code'})
    if response.status_code != 200:
        raise RuntimeError('YouTube yetkilendirmesi tamamlanamadı.')
    token = response.json()
    if not token.get('refresh_token'):
        raise RuntimeError('YouTube yenileme tokenı alınamadı; izinleri yeniden bağla.')
    existing = db.get(YouTubeConnection, user_id)
    if not existing:
        existing = YouTubeConnection(user_id=user_id)
        db.add(existing)
    existing.encrypted_token = cipher().encrypt(json.dumps(token).encode()).decode()
    db.commit()


def access_token(db, user_id):
    connection = db.get(YouTubeConnection, user_id)
    if not connection:
        raise RuntimeError('Bu kullanıcı için YouTube bağlantısı yok.')
    token = json.loads(cipher().decrypt(connection.encrypted_token.encode()))
    cfg = settings()
    response = httpx.post('https://oauth2.googleapis.com/token', data={'client_id': cfg.youtube_client_id, 'client_secret': cfg.youtube_client_secret, 'refresh_token': token['refresh_token'], 'grant_type': 'refresh_token'}, timeout=30)
    if response.status_code != 200:
        raise RuntimeError('YouTube erişimi yenilenemedi; hesabı tekrar bağla.')
    return response.json()['access_token']


def manifest(db, run):
    import hashlib
    files = db.scalars(select(Asset).where(Asset.run_id == run.id)).all()
    referenced = {run.outputs.get('editor', {}).get('video'), run.outputs.get('editor', {}).get('subtitle'), run.outputs.get('visual', {}).get('cover')}
    hashes = sorted((a.id, a.sha256) for a in files if a.id in referenced)
    return hashlib.sha256(json.dumps({'revision': run.revision, 'run_id': run.id, 'files': hashes, 'copy': run.outputs.get('publisher')}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def valid_approval(db, run):
    project = db.get(Project, run.project_id)
    approval = db.scalar(select(Approval).where(Approval.run_id == run.id))
    return bool(project.revision == run.revision and approval and approval.manifest == manifest(db, run) and run.outputs.get('quality', {}).get('passed'))


def upload(publication_id):
    with DB() as db:
        publication = db.get(Publication, publication_id)
        if not publication or publication.video_id or publication.status not in ('queued', 'uploading', 'uncertain'):
            return
        run = db.get(Run, publication.run_id)
        if not valid_approval(db, run):
            publication.status, publication.error = 'cancelled', 'Onay güncel sürümle eşleşmiyor.'
            db.commit()
            return
        try:
            publication.status = 'uploading'
            db.commit()
            asset = db.get(Asset, run.outputs['editor']['video'])
            path = media_path(asset.path)
            if file_hash(path) != asset.sha256:
                raise RuntimeError('Onaylanan video dosyası değişmiş; yayın durduruldu.')
            token = access_token(db, run.user_id)
            size = path.stat().st_size
            headers = {'Authorization': f'Bearer {token}'}
            with httpx.Client(timeout=120) as client:
                if not publication.upload_url:
                    copy = run.outputs['publisher']
                    status = {'privacyStatus': 'private' if publication.publish_at else 'public', 'selfDeclaredMadeForKids': publication.made_for_kids, 'containsSyntheticMedia': publication.synthetic_media}
                    if publication.publish_at:
                        status['publishAt'] = publication.publish_at
                    response = client.post('https://www.googleapis.com/upload/youtube/v3/videos', params={'uploadType': 'resumable', 'part': 'snippet,status'}, headers={**headers, 'X-Upload-Content-Length': str(size), 'X-Upload-Content-Type': 'video/mp4'}, json={'snippet': {'title': copy['title'], 'description': copy['description'] + '\n\n' + ' '.join(copy['hashtags']), 'tags': [h.lstrip('#') for h in copy['hashtags']], 'defaultLanguage': 'tr', 'categoryId': '22'}, 'status': status})
                    if response.status_code >= 400 or 'location' not in response.headers:
                        raise RuntimeError(f'YouTube yükleme oturumu açılamadı (HTTP {response.status_code}).')
                    publication.upload_url = response.headers['location']
                    publication.status = 'uploading'
                    db.commit()  # Must persist session before sending any video bytes.
                else:
                    response = client.put(publication.upload_url, headers={**headers, 'Content-Length': '0', 'Content-Range': f'bytes */{size}'})
                    if response.status_code in (200, 201):
                        publication.video_id = response.json()['id']
                        publication.status, publication.error = 'scheduled' if publication.publish_at else 'published', None
                        db.commit()
                        return
                    if response.status_code != 308:
                        raise RuntimeError('Önceki yüklemenin sonucu doğrulanamadı. Yeni video başlatılmadı; YouTube kanalını kontrol et.')
                    publication.offset = int(response.headers.get('range', 'bytes=0--1').rsplit('-', 1)[-1]) + 1 if 'range' in response.headers else 0
                    db.commit()
                with path.open('rb') as handle:
                    handle.seek(publication.offset)
                    while publication.offset < size:
                        db.refresh(run)
                        if not valid_approval(db, run):
                            raise RuntimeError('Yükleme sırasında onay geçersizleşti.')
                        chunk = handle.read(8 * 1024 * 1024)
                        start = publication.offset
                        response = client.put(publication.upload_url, headers={**headers, 'Content-Type': 'video/mp4', 'Content-Range': f'bytes {start}-{start + len(chunk) - 1}/{size}'}, content=chunk)
                        if response.status_code in (200, 201):
                            publication.video_id = response.json()['id']
                            publication.status = 'scheduled' if publication.publish_at else 'published'
                            publication.offset, publication.error = size, None
                            db.commit()
                            return
                        if response.status_code != 308:
                            raise RuntimeError(f'YouTube yükleme yanıtı belirsiz (HTTP {response.status_code}); mevcut oturum korunuyor.')
                        end = int(response.headers['range'].rsplit('-', 1)[-1]) + 1
                        if end <= start:
                            raise RuntimeError('YouTube yüklemesi ilerlemedi; mevcut oturum korunuyor.')
                        publication.offset = end
                        handle.seek(end)
                        db.commit()
                raise RuntimeError('Yükleme tamamlandı ancak video kimliği doğrulanamadı.')
        except Exception as exc:
            publication.status = 'uncertain' if publication.upload_url else 'failed'
            publication.error = str(exc) if isinstance(exc, RuntimeError) else f'YouTube işlemi tamamlanamadı ({type(exc).__name__}); mevcut oturum korunuyor.'
            db.commit()
