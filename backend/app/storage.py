import hashlib
import mimetypes
import shutil
from pathlib import Path
from uuid import uuid4
from sqlalchemy import select
from .config import settings
from .db import Asset


def media_path(relative):
    root = settings().media_root.resolve()
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError('Geçersiz dosya yolu.')
    return candidate


def workdir(project_id, run_id):
    path = media_path(f'{project_id}/{run_id}')
    path.mkdir(parents=True, exist_ok=True)
    return path


def file_hash(path):
    sha = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            sha.update(chunk)
    return sha.hexdigest()


def register(db, run, path, kind):
    relative = Path(path).resolve().relative_to(settings().media_root.resolve()).as_posix()
    existing = db.scalar(select(Asset).where(Asset.run_id == run.id, Asset.path == relative))
    if existing:
        existing.sha256 = file_hash(path)
        db.commit()
        return existing.id
    asset = Asset(id=str(uuid4()), project_id=run.project_id, run_id=run.id, revision=run.revision, kind=kind, path=relative, mime=mimetypes.guess_type(str(path))[0] or 'application/octet-stream', sha256=file_hash(path))
    db.add(asset)
    db.commit()
    return asset.id


def check_disk():
    root = settings().media_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    used = sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
    if used >= settings().max_disk_gb * 1024**3 or shutil.disk_usage(root).free < 512 * 1024**2:
        raise RuntimeError('Medya depolama sınırına ulaşıldı veya diskte yeterli boş alan yok.')
    return used
