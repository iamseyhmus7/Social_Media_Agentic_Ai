"""Conservative, atomic reservations shared by every model on a CF account.

This is an application ledger, not a claim to know usage by other applications.
Uncertain requests retain their reservation: a lost response may have been billed.
"""
import hashlib
import math
from datetime import datetime, timezone, timedelta
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from .config import settings
from .db import DB, CloudflareBudget
from .providers import QuotaExceeded


def key():
    account = hashlib.sha256(settings().cloudflare_account_id.encode()).hexdigest()[:32]
    return account + ':' + datetime.now(timezone.utc).date().isoformat()


def estimate(model, width, height, steps=25, reference_sizes=()):
    if model == 'klein':
        return math.ceil(1363.64 + max(0, math.ceil(width*height/1048576)-1)*181.82
                         + sum(math.ceil(w*h/1048576)*181.82 for w,h in reference_sizes))
    if model == 'lucid':
        return math.ceil(width/512)*math.ceil(height/512)*636 + steps*12
    return math.ceil(width/512)*math.ceil(height/512)*4.8 + steps*9.6


def reserve(amount):
    ident = key()
    with DB() as db:
        if not db.get(CloudflareBudget, ident):
            db.add(CloudflareBudget(id=ident, used=0, blocked=False))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
        updated = db.execute(update(CloudflareBudget).where(CloudflareBudget.id==ident,
            CloudflareBudget.blocked.is_(False),
            CloudflareBudget.used + amount <= settings().cloudflare_daily_neurons)
            .values(used=CloudflareBudget.used+amount)).rowcount
        db.commit()
    if not updated:
        raise QuotaExceeded('Uygulamanın günlük ücretsiz görsel bütçesi tahmini bu istek için yetersiz. Bütçe Türkiye saatiyle 03.00’te yenilenir. Hazır görseller korundu.')
    return ident


def block(ident):
    with DB() as db:
        db.execute(update(CloudflareBudget).where(CloudflareBudget.id==ident).values(blocked=True))
        db.commit()


def report():
    with DB() as db:
        item = db.get(CloudflareBudget, key())
        used, blocked = (item.used, item.blocked) if item else (0, False)
    tomorrow = datetime.now(timezone.utc).date() + timedelta(days=1)
    return {'estimated_reserved_neurons':used, 'daily_limit':settings().cloudflare_daily_neurons,
        'remaining_estimate':0 if blocked else max(0,settings().cloudflare_daily_neurons-used),
        'provider_blocked':blocked, 'scope':'cloudflare_account_all_models',
        'source':'application_reservations_not_provider_balance',
        'external_usage_included':False, 'resets_at':tomorrow.isoformat()+'T00:00:00Z'}
