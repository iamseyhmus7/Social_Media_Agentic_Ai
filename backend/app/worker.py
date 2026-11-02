"""One shared database lease serializes heavy work across local and Celery workers."""
import argparse
import threading
import time
import os
from contextlib import contextmanager
from uuid import uuid4
from sqlalchemy import select, update
from .config import settings
from .db import DB, WorkerLease, Run, RemoteJob, Publication, Event, init_db, now
from .pipeline import execute
from .youtube import upload


@contextmanager
def lease():
    # All pilot workers share MEDIA_ROOT. The OS lock remains exclusive even if a
    # heartbeat stalls; process death releases it without unsafe lease stealing.
    root = settings().media_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    lock = (root / '.worker.lock').open('a+b')
    try:
        if (root / '.worker.lock').stat().st_size == 0:
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        yield False
        return
    token = str(uuid4())
    with DB() as db:
        claimed = db.execute(update(WorkerLease).where(WorkerLease.id == 1, WorkerLease.expires < now()).values(token=token, expires=now() + 120)).rowcount
        db.commit()
    if not claimed:
        lock.close()
        yield False
        return
    stopped = threading.Event()

    def heartbeat():
        while not stopped.wait(10):
            with DB() as db:
                db.execute(update(WorkerLease).where(WorkerLease.id == 1, WorkerLease.token == token).values(expires=now() + 120))
                db.commit()
    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        yield True
    finally:
        stopped.set()
        thread.join(timeout=15)
        with DB() as db:
            db.execute(update(WorkerLease).where(WorkerLease.id == 1, WorkerLease.token == token).values(token=None, expires=0))
            db.commit()
        lock.close()


def tick():
    with lease() as acquired:
        if not acquired:
            return False
        from .content_deletion import purge_pending_content
        purge_pending_content()
        from .db import Feedback
        with DB() as db:
            pending_feedback = db.scalar(select(Feedback.id).where(Feedback.status=='queued').order_by(Feedback.created))
        if pending_feedback:
            from .feedback import process_feedback
            process_feedback(pending_feedback)
            return True
        with DB() as db:
            # Any running job belongs to an expired lease. Preserve checkpoints and
            # require explicit retry; never repeat an uncertain external upload.
            for run in db.scalars(select(Run).where(Run.status == 'running')):
                if run.pipeline_version >= 2:
                    run.status = 'queued'
                    message = 'Worker yeniden başladı; kayıtlı kontrol noktasından devam ediliyor.'
                else:
                    run.status, run.active_owner, run.error = 'failed', None, 'Worker kesintisi algılandı. Tamamlanan çıktılar korundu; yeniden deneyebilirsin.'
                    message = run.error
                db.add(Event(run_id=run.id, stage=run.stage, message=message))
            for publication in db.scalars(select(Publication).where(Publication.status == 'uploading')):
                publication.status = 'uncertain'
                publication.error = 'Worker kesintisi: mevcut YouTube yükleme oturumu doğrulanmadan yeni yükleme yapılmayacak.'
            db.commit()
            publication = db.scalar(select(Publication).where(Publication.status == 'queued').order_by(Publication.id))
            if publication:
                publication_id = publication.id
            else:
                publication_id = None
            # A remote wait never holds this lease between polls. Canceled jobs keep
            # their account slot until Kaggle confirms they have actually stopped.
            abandoned = db.scalars(select(RemoteJob).join(Run).where(RemoteJob.account_slot.is_not(None), Run.status.in_(['cancelled', 'failed', 'waiting_quota']), RemoteJob.next_poll <= now())).all()
            for job in abandoned:
                from .kaggle_provider import KaggleGateway
                from .config import use_run_settings
                try:
                    parent = db.get(Run, job.run_id)
                    with use_run_settings(parent.outputs.get('_config', {})):
                        gateway = KaggleGateway()
                        ref = job.kernel + (f'/{job.version}' if job.version else '')
                        state = gateway.status(ref)
                        if parent.status == 'cancelled' and state in ('running', 'queued', 'pending'):
                            gateway.cancel(ref)
                    if state == 'missing' and job.status == 'prepared':
                        job.account_slot, job.status = None, 'not_submitted'
                    elif state in ('complete', 'completed', 'failed', 'error', 'cancelled', 'canceled', 'cancel_acknowledged'):
                        job.account_slot, job.status = None, 'discarded'
                    job.next_poll = now() + 60
                except Exception:
                    job.next_poll = now() + 60
            for candidate in db.scalars(select(Run).where(Run.status=='waiting_provider')):
                waiting_state=candidate.outputs.get('_provider_wait',{})
                if waiting_state.get('automatic') and waiting_state.get('deadline',float('inf'))<=now():
                    from .recovery import initial
                    waiting_state={**waiting_state,'automatic':False,'retry_at':None}
                    recovery=initial(candidate.outputs)
                    recovery.update(active='provider',provider={'kind':'service_unavailable','action':'needs_input',**waiting_state})
                    candidate.outputs={**candidate.outputs,'_provider_wait':waiting_state,'_recovery':recovery}
                    db.add(Event(run_id=candidate.id,stage=candidate.stage,message='Servis için 30 dakikalık otomatik takip süresi doldu; çıktılar korundu.'))
                if waiting_state.get('automatic') and waiting_state.get('retry_at',float('inf'))<=now():
                    candidate.status='queued'
            waiting = db.scalars(select(Run).where(Run.status == 'waiting_remote').order_by(Run.created)).all()
            occupied = db.scalar(select(RemoteJob).where(RemoteJob.account_slot.is_not(None)))
            for candidate in waiting:
                if occupied and occupied.run_id != candidate.id:
                    continue
                future = db.scalar(select(RemoteJob.id).where(RemoteJob.run_id == candidate.id, RemoteJob.account_slot.is_not(None), RemoteJob.next_poll > now()))
                if not future:
                    candidate.status = 'queued'
            db.commit()
            run = db.scalar(select(Run).where(Run.status == 'queued').order_by(Run.created))
            run_id = run.id if run else None
        if publication_id:
            upload(publication_id)
            return True
        if run_id:
            execute(run_id)
            return True
    return False


def dispatch():
    if settings().queue_mode == 'celery':
        try:
            from .celery_app import drain
            drain.delay()
        except Exception:
            # DB is the source of truth. Beat will redispatch when broker returns.
            pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    init_db()
    while True:
        busy = tick()
        if args.once:
            break
        if not busy:
            time.sleep(2)


if __name__ == '__main__':
    main()
