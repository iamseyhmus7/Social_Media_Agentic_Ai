"""Private, finite Kaggle jobs. Never expose a notebook as a public web server."""
import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlparse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .config import settings
from .db import DB, RemoteJob, Run, Event, now
from .providers import ProviderError, QuotaExceeded
from .storage import workdir, file_hash

RUNTIME_VERSION = 'ltx-096-v1'
ENGINE_REVISION = 'ltx096-diffusers0352-r8-dual'
PENDING = ('prepared', 'submitting', 'pending', 'queued', 'running', 'collecting')


class RemotePending(Exception):
    pass


def configured():
    c = settings()
    return bool(re.fullmatch(r'[a-zA-Z0-9_-]{3,40}', c.kaggle_username) and (c.kaggle_api_token or c.kaggle_key))


def safe_error(exc):
    from requests.exceptions import RequestException
    code = getattr(getattr(exc, 'response', None), 'status_code', None)
    if code == 429:
        return QuotaExceeded('Kaggle kota veya istek sınırı. İş tekrar gönderilmeden bekletildi.')
    if code in (401, 403):
        return ProviderError('Kaggle erişimi reddedildi. Sunucudaki kimliği ve hesabın GPU erişimini kontrol et.')
    if (isinstance(exc, (RequestException, TimeoutError, ConnectionError)) and code is None) or (code is not None and code >= 500):
        return RemotePending()
    return ProviderError('Kaggle bağlantısı tamamlanamadı. Mevcut uzak iş kaydı korunuyor; bağlantı tekrar kontrol edilecek.')


class KaggleGateway:
    def __init__(self):
        c = settings()
        if not configured():
            raise ProviderError('Kaggle için KAGGLE_USERNAME ve KAGGLE_API_TOKEN sunucuda yapılandırılmalı.')
        if c.kaggle_api_token:
            os.environ['KAGGLE_API_TOKEN'] = c.kaggle_api_token
        if c.kaggle_key:
            os.environ['KAGGLE_USERNAME'] = c.kaggle_username
            os.environ['KAGGLE_KEY'] = c.kaggle_key
        from kaggle.api.kaggle_api_extended import KaggleApi
        self.api = KaggleApi()
        try:
            self.api.authenticate()
        except Exception as exc:
            raise safe_error(exc) from None

    def status(self, kernel):
        try:
            response = self.api.kernels_status(kernel)
            value = response.status
            return str(getattr(value, 'name', getattr(value, 'value', value))).lower().split('.')[-1]
        except Exception as exc:
            if getattr(getattr(exc, 'response', None), 'status_code', None) == 404:
                return 'missing'
            # Kaggle intentionally masks a missing private notebook as 403.
            # Confirm absence against our authenticated notebook inventory.
            if isinstance(exc, ValueError) and kernel.split('/')[0] == settings().kaggle_username:
                try:
                    slug = kernel.split('/')[1]
                    matches = self.api.kernels_list(mine=True, search=slug, page_size=100)
                    if not any(getattr(item, 'ref', '') == '/'.join(kernel.split('/')[:2]) for item in matches):
                        return 'missing'
                except Exception:
                    pass
            raise safe_error(exc) from None

    def upload(self, folder):
        ref = json.loads((folder / 'dataset-metadata.json').read_text())['id']
        try:
            try:
                state = self.api.dataset_status(ref)
                status = str(getattr(state, 'status', state)).lower()
                if 'error' in status:
                    raise ProviderError('Kaggle girdi paketi hazırlanamadı.')
                if status not in ('ready', 'complete', 'completed'):
                    raise RemotePending()
                return
            except Exception as exc:
                code = getattr(getattr(exc, 'response', None), 'status_code', None)
                if code in (401, 403):
                    matches = self.api.dataset_list(mine=True, search=ref.split('/')[1]) or []
                    if any(getattr(item, 'ref', '') == ref for item in matches):
                        raise
                elif code != 404:
                    raise
            result = self.api.dataset_create_new(str(folder), public=False, quiet=True, convert_to_csv=False)
            if getattr(result, 'error', None):
                raise ProviderError('Kaggle özel girdi paketi kabul edilmedi.')
            raise RemotePending()
        except RemotePending:
            raise
        except ProviderError:
            raise
        except Exception as exc:
            raise safe_error(exc) from None

    def cancel(self, kernel):
        """Resolve the exact version's session via the official download API.

        The SDK's cancellation endpoint needs a numeric session ID. Its
        output redirect supplies that ID even while the job is running.
        Stream and close the response; do not download the output archive.
        """
        from kagglesdk.kernels.types.kernels_api_service import ApiDownloadKernelOutputRequest, ApiCancelKernelSessionRequest
        parts = kernel.split('/')
        if len(parts) not in (2, 3) or parts[0] != settings().kaggle_username:
            raise ProviderError('Yalnızca bu hesaba ait kayıtlı Kaggle işi durdurulabilir.')
        try:
            request = ApiDownloadKernelOutputRequest()
            request.owner_slug, request.kernel_slug = parts[:2]
            if len(parts) == 3:
                request.version_number = int(parts[2])
            with self.api.build_kaggle_client() as client:
                response = client.kernels.kernels_api_client.download_kernel_output(request)
                session = None
                try:
                    for redirect in [*response.history, response]:
                        url = urlparse(redirect.url)
                        match = re.fullmatch(r'/api/v1/kernels/output/download_zip/(\d+)', url.path)
                        # Current API redirects may omit /api in their base URL.
                        match = match or re.fullmatch(r'/v1/kernels/output/download_zip/(\d+)', url.path)
                        if match and url.hostname in ('www.kaggle.com', 'api.kaggle.com'):
                            session = int(match.group(1))
                finally:
                    response.close()
                if session is None:
                    raise ProviderError('Kaggle oturumu henüz çözümlenemedi. Durdurma isteği tekrar kontrol edilecek.')
                cancel = ApiCancelKernelSessionRequest()
                cancel.kernel_session_id = session
                result = client.kernels.kernels_api_client.cancel_kernel_session(cancel)
                if result.error_message:
                    raise ProviderError('Kaggle durdurma isteğini henüz doğrulamadı.')
        except ProviderError:
            raise
        except Exception as exc:
            raise safe_error(exc) from None

    def submit(self, folder, gpu=True):
        try:
            r = self.api.kernels_push(str(folder), acc='NvidiaTeslaT4' if gpu else None, timeout=str(settings().kaggle_timeout_seconds))
            if getattr(r, 'error', None):
                raise ProviderError('Kaggle işi kabul edilmedi. GPU kotası ve hesap erişimini kontrol et.')
            return getattr(r, 'version_number', None)
        except ProviderError:
            raise
        except Exception as exc:
            raise safe_error(exc) from None

    def collect(self, kernel, folder):
        try:
            token = None
            for _ in range(10):
                _, token = self.api.kernels_output(kernel, str(folder), file_pattern=r'(^|/)(result\.json|shot-[0-9]{3}\.mp4)$', force=True, quiet=True, page_token=token, page_size=200)
                if not token:
                    return
            raise ProviderError('Kaggle çıktı listesi beklenen sınırı aştı.')
        except ProviderError:
            raise
        except Exception as exc:
            raise safe_error(exc) from None


def stage_job(run, folder, manifest, *, bootstrap=False, attempt=0, runtime_source=''):
    c = settings()
    digest = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    with DB() as db:
        existing = db.scalar(select(RemoteJob).where(RemoteJob.run_id == run.id, RemoteJob.input_hash == digest, RemoteJob.attempt == attempt))
        if existing:
            job = existing
            if job.status == 'not_submitted':
                if db.scalar(select(RemoteJob.id).where(RemoteJob.account_slot == c.kaggle_username)):
                    raise RemotePending()
                job.status, job.account_slot = 'prepared', c.kaggle_username
                try:
                    db.commit()
                except IntegrityError:
                    db.rollback()
                    raise RemotePending() from None
            ident = job.id
            slug = job.kernel.split('/')[1]
            if (folder / 'kaggle' / ident / 'kernel-metadata.json').is_file():
                return job
        else:
            if db.scalar(select(RemoteJob.id).where(RemoteJob.account_slot == c.kaggle_username)):
                raise RemotePending()
            ident = str(uuid4())
            slug = f'sahne-{RUNTIME_VERSION}' if bootstrap else 'sahne-' + ident.replace('-', '')
            job = RemoteJob(id=ident, run_id=run.id, input_hash=digest, attempt=attempt, kernel=c.kaggle_username + '/' + slug, account_slot=c.kaggle_username)
            db.add(job)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                raise RemotePending() from None
    root = folder / 'kaggle' / ident
    root.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).resolve().parents[1] / 'kaggle' / ('prepare_runtime.py' if bootstrap else 'generate.py')
    shutil.copyfile(source, root / 'run.py')
    sources = []
    if not bootstrap:
        inputs = root / 'inputs'
        inputs.mkdir(exist_ok=True)
        for image in manifest['images']:
            shutil.copyfile(folder / image, inputs / image)
        (inputs / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        dataset_slug = 'sahne-input-' + ident.replace('-', '')
        (inputs / 'dataset-metadata.json').write_text(json.dumps({'id': c.kaggle_username + '/' + dataset_slug, 'title': dataset_slug, 'licenses': [{'name': 'other'}]}))
        sources = [c.kaggle_username + '/' + dataset_slug]
    (root / 'kernel-metadata.json').write_text(json.dumps({'id': job.kernel, 'title': slug, 'code_file': 'run.py', 'language': 'python', 'kernel_type': 'script', 'is_private': True, 'enable_gpu': not bootstrap, 'enable_internet': bootstrap, 'dataset_sources': sources, 'kernel_sources': [runtime_source] if runtime_source else [], 'model_sources': []}), encoding='utf-8')
    return job


def advance_job(job, folder, gateway, *, bootstrap=False):
    expired = now() - job.created > settings().kaggle_timeout_seconds + 900
    # Network failures and input preparation must back off durably too. A lost
    # upload reply is resolved by checking the same dataset on the next poll.
    with DB() as db:
        db.get(RemoteJob, job.id).next_poll = now() + settings().kaggle_poll_seconds
        db.commit()
    root = folder / 'kaggle' / job.id
    ref = job.kernel + (f'/{job.version}' if job.version else '')
    try:
        status = gateway.status(ref)
    except RemotePending:
        if expired:
            raise ProviderError('Kaggle işi süre sınırını aştı. Uzak iş doğrulanmadan tekrar gönderilmeyecek.') from None
        raise
    # A worker may have been offline while the finite GPU job finished. Its
    # completed output remains recoverable without submitting another job.
    terminal = ('complete', 'completed', 'error', 'failed', 'cancelled', 'canceled', 'cancel_acknowledged')
    if expired and status not in terminal:
        raise ProviderError('Kaggle işi süre sınırını aştı. Uzak iş doğrulanmadan tekrar gönderilmeyecek.')
    if status == 'missing':
        if job.status != 'prepared':
            # A lost submit response must not create another execution.
            if now() - job.created > 900:
                raise ProviderError('Kaggle gönderimi doğrulanamadı. Yinelenen GPU işi önlemek için otomatik tekrar durduruldu.')
            raise RemotePending()
        if not bootstrap:
            gateway.upload(root / 'inputs')
        with DB() as db:
            db.get(RemoteJob, job.id).status = 'submitting'
            db.commit()
        version = gateway.submit(root, gpu=not bootstrap)
        with DB() as db:
            current = db.get(RemoteJob, job.id)
            current.status, current.version, current.next_poll = 'pending', version, now() + settings().kaggle_poll_seconds
            db.commit()
        raise RemotePending()
    if status in ('complete', 'completed'):
        if bootstrap:
            result = {'runtime_source': job.kernel}
        else:
            target = root / 'output'
            gateway.collect(ref, target)
            file = target / 'result.json'
            if not file.is_file() or file.stat().st_size > 256_000:
                raise ProviderError('Kaggle sonuç manifesti eksik veya geçersiz.')
            result = json.loads(file.read_text())
        with DB() as db:
            current = db.get(RemoteJob, job.id)
            current.status, current.result, current.account_slot = 'complete', result, None
            db.commit()
        return result
    if status in ('error', 'failed', 'cancelled', 'canceled', 'cancel_acknowledged'):
        with DB() as db:
            current = db.get(RemoteJob, job.id)
            current.status, current.account_slot = 'failed', None
            current.error = 'Kaggle işi tamamlanamadı. GPU erişimini ve çalışma paketi uyumunu kontrol et.'
            db.commit()
        raise ProviderError('Kaggle işi tamamlanamadı. Sağlayıcı hata ayrıntıları anahtar güvenliği için arayüze taşınmadı.')
    with DB() as db:
        current = db.get(RemoteJob, job.id)
        current.status, current.next_poll = 'running' if status == 'running' else 'pending', now() + settings().kaggle_poll_seconds
        db.commit()
    raise RemotePending()


def generate_clips(run, folder, plan, image_paths, check_cancel):
    from . import media
    check_cancel()
    gateway = KaggleGateway()
    c = settings()
    runtime = c.kaggle_runtime_source
    if not runtime:
        runtime = c.kaggle_username + '/sahne-' + RUNTIME_VERSION
        if gateway.status(runtime) not in ('complete', 'completed'):
            bootstrap = stage_job(run, folder, {'runtime': RUNTIME_VERSION}, bootstrap=True)
            advance_job(bootstrap, folder, gateway, bootstrap=True)
    images = []
    for index, path in enumerate(image_paths):
        name = f'reference-{index}.png'
        shutil.copyfile(path, folder / name)
        images.append(name)
    manifest = {'version': 1, 'run_id': run.id, 'revision': run.revision, 'runtime': RUNTIME_VERSION, 'images': images, 'image_hashes': [file_hash(p) for p in image_paths], 'shots': plan['shots']}
    # Existing jobs keep their original identity across a deployment. A retry
    # of a failed run can explicitly adopt a corrected engine without paying
    # again for speech and reference images.
    if run.outputs.get('_motion_engine'):
        manifest['engine'] = run.outputs['_motion_engine']
    if run.outputs.get('_motion_profile'):
        manifest['profile'] = run.outputs['_motion_profile']
    if run.outputs.get('_motion_session'):
        manifest['session'] = run.outputs['_motion_session']
    valid = {}
    for attempt in range(2):
        pending = [s for s in manifest['shots'] if s['shot_id'] not in valid]
        request = {**manifest, 'shots': pending, 'attempt': attempt}
        job = stage_job(run, folder, request, attempt=attempt, runtime_source=runtime)
        result = job.result if job.status == 'complete' else advance_job(job, folder, gateway)
        if result.get('run_id') != run.id or result.get('revision') != run.revision:
            raise ProviderError('Kaggle sonucu güncel üretimle eşleşmiyor.')
        if result.get('fatal') == 'inference_configuration':
            raise ProviderError('Kaggle model çağrısı yapılandırma hatası nedeniyle durdu. Aynı ayarlarla GPU düzeltme denemesi yapılmadı; hazır ses ve görseller korundu.')
        output = folder / 'kaggle' / job.id / 'output'
        for shot in pending:
            check_cancel()
            ident = shot['shot_id']
            path = output / (ident + '.mp4')
            metadata = result.get('clips', {}).get(ident, {})
            if not path.is_file() or metadata.get('sha256') != file_hash(path):
                continue
            try:
                report = media.inspect_clip(path, shot['duration_seconds'], check_cancel)
            except RuntimeError:
                continue
            target = folder / (ident + '.mp4')
            shutil.copyfile(path, target)
            valid[ident] = {'file': target.name, 'scene_index': shot['scene_index'], 'duration_seconds': shot['duration_seconds'], 'report': report}
        if len(valid) == len(plan['shots']):
            return valid
    raise ProviderError('Bir düzeltme denemesinden sonra bazı hareketli çekimler doğrulanamadı. Başarılı klipler korundu.')
