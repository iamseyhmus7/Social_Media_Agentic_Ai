from celery import Celery
import logging
from .config import settings

# HTTP URLs can contain provider query credentials (e.g. YouTube API keys).
logging.getLogger('httpx').setLevel(logging.WARNING)

app = Celery('sahne', broker=settings().broker_url)
app.conf.update(worker_prefetch_multiplier=1, task_acks_late=True, task_reject_on_worker_lost=True, broker_connection_retry_on_startup=True, beat_schedule={'durable-queue-drain': {'task': 'sahne.drain', 'schedule': 10.0}})


@app.task(name='sahne.drain')
def drain():
    from .worker import tick
    # One job per dispatch prevents a single message from holding the queue forever.
    tick()
