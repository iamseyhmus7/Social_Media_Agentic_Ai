"""Delete owned, inactive content and its private media as one batch."""
import logging
import shutil
from uuid import UUID, uuid4
from fastapi import HTTPException
from sqlalchemy import select, delete
from .config import settings
from .db import Project, Run, Feedback, RemoteJob, Asset, Event, Approval, Publication, User


def purge_pending_content():
    """Retry only quarantines whose project deletion has committed."""
    from .db import DB
    root = settings().media_root.resolve()
    trash = root / '.deleted-content'
    if not trash.is_dir() or trash.is_symlink() or trash.resolve() != trash:
        return
    for folder in list(trash.iterdir())[:10]:
        try:
            if folder.is_symlink() or folder.resolve() != folder or not folder.is_dir() or str(UUID(folder.name)) != folder.name:
                continue
            children = list(folder.iterdir())
            if any(p.is_symlink() or not p.is_dir() or str(UUID(p.name)) != p.name for p in children):
                continue
            with DB() as db:
                if any(db.get(Project, p.name) is not None for p in children):
                    continue
            if folder.resolve().parent == trash.resolve():
                shutil.rmtree(folder)
        except (OSError, ValueError):
            logging.getLogger(__name__).warning('Content quarantine cleanup will retry')


def delete_content(db, user, project_ids):
    ids = sorted(set(project_ids))
    if not ids or len(ids) > 100:
        raise HTTPException(422, '1–100 içerik seçmelisin.')
    try:
        if any(str(UUID(ident)) != ident for ident in ids):
            raise ValueError()
    except ValueError:
        raise HTTPException(404, 'İçerik bulunamadı.') from None
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    projects = list(db.scalars(select(Project).where(Project.id.in_(ids), Project.user_id == user.id)
                              .order_by(Project.id).with_for_update()))
    if len(projects) != len(ids):
        raise HTTPException(404, 'İçerik bulunamadı veya sana ait değil.')
    runs = list(db.scalars(select(Run).where(Run.project_id.in_(ids)).with_for_update()))
    run_ids = [r.id for r in runs]
    if any(r.status in ('queued', 'running', 'waiting_remote', 'waiting_provider') or r.active_owner for r in runs):
        raise HTTPException(409, 'Seçilen içerikte aktif üretim var. Önce durdurulmasını bekle.')
    if db.scalar(select(RemoteJob.id).where(RemoteJob.run_id.in_(run_ids), RemoteJob.account_slot.is_not(None))):
        raise HTTPException(409, 'Kaggle işi henüz kapanmadı; tamamlandıktan sonra silebilirsin.')
    if db.scalar(select(Feedback.id).where(Feedback.project_id.in_(ids), Feedback.status.in_(['queued', 'running']))):
        raise HTTPException(409, 'Seçilen içerikte geri bildirim işleniyor; tamamlanmasını bekle.')
    if db.scalar(select(Publication.id).where(Publication.project_id.in_(ids), Publication.status.in_(['queued', 'uploading', 'uncertain']))):
        raise HTTPException(409, 'Seçilen içerikte etkin veya sonucu belirsiz yayın işlemi var.')
    root = settings().media_root.resolve()
    sources = []
    for ident in ids:
        source = root / ident
        if source.is_symlink() or source.resolve() != source:
            raise HTTPException(409, 'İçeriğin medya yolu güvenli değil; silinmedi.')
        if source.exists() and not source.is_dir():
            raise HTTPException(409, 'İçeriğin medya dizini geçersiz; silinmedi.')
        sources.append(source)
    quarantine = root / '.deleted-content' / str(uuid4())
    if quarantine.parent.resolve() != root / '.deleted-content':
        raise HTTPException(409, 'Geçersiz geçici silme dizini.')
    moved = []
    total_bytes = 0
    try:
        for source in sources:
            if source.exists():
                quarantine.mkdir(parents=True, exist_ok=True)
                total_bytes += sum(p.stat().st_size for p in source.rglob('*') if p.is_file() and not p.is_symlink())
                destination = quarantine / source.name
                source.rename(destination)
                moved.append((source, destination))
        for model, predicate in [
            (Feedback, Feedback.project_id.in_(ids)),
            (Approval, Approval.run_id.in_(run_ids)),
            (Publication, Publication.project_id.in_(ids)),
            (Event, Event.run_id.in_(run_ids)),
            (RemoteJob, RemoteJob.run_id.in_(run_ids)),
            (Asset, Asset.project_id.in_(ids)),
            (Run, Run.project_id.in_(ids)),
            (Project, Project.id.in_(ids)),
        ]:
            db.execute(delete(model).where(predicate), execution_options={'synchronize_session': False})
        db.commit()
    except BaseException:
        db.rollback()
        for source, destination in reversed(moved):
            if destination.exists() and not source.exists():
                destination.rename(source)
        if quarantine.exists() and not any(quarantine.iterdir()):
            quarantine.rmdir()
        raise
    pending = False
    if quarantine.exists():
        try:
            shutil.rmtree(quarantine)
        except OSError:
            pending = True
            logging.getLogger(__name__).exception('Deleted content media cleanup pending')
    return {'deleted_ids': ids, 'deleted_count': len(ids), 'media_bytes': total_bytes,
            'storage_cleanup_pending': pending}
