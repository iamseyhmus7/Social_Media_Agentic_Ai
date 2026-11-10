"""Bounded, best-effort mirroring of one exact Kaggle session into worker logs.

Raw logs stay in the private run directory; they never enter public run_data.
The cursor survives worker restarts. Log failures never submit/cancel a job.
"""
import base64
import hashlib
import json
import logging
import math
import re
import time
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)
MAX_BYTES = 4 * 1024 * 1024
MAX_LINE = 4096
PREVIEW_PREFIX = '[SahnePreview] '
PREVIEW_CHUNK = 2048
ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')


def redact(value, secrets=()):
    text = ANSI.sub('', str(value))
    for secret in sorted((s for s in secrets if isinstance(s,str) and s), key=len, reverse=True):
        text = text.replace(secret, '[redacted]')
    text = re.sub(r'https?://[^\s<>"\x27]+', '[url]', text)
    text = re.sub(r'(?i)(bearer\s+)[^\s,;"\x27]+', r'\1[redacted]', text)
    text = re.sub(r'(?i)((?:api[_-]?key|token|password|secret)\s*[=:]\s*)[^\s,;]+', r'\1[redacted]', text)
    return ''.join(c for c in text if c in '\n\t\r' or ord(c)>=32)[:MAX_LINE]


def send(client, method, request, *, timeout=(3,5)):
    # The generated SDK method has no timeout argument. Use its own authenticated
    # prepared request/session, retaining its CA/proxy settings and TLS checks.
    transport = client.kernels.kernels_api_client._client
    transport._init_session()
    prepared = transport._prepare_request('kernels.KernelsApiService', method, request)
    options = transport._session.merge_environment_settings(prepared.url, {}, True, None, None)
    options['timeout'] = timeout
    transport._session.max_redirects = 4
    response = transport._session.send(prepared, **options)
    try:
        response.raise_for_status()
    except Exception:
        response.close()
        raise
    return response


def resolve_session(client, kernel, owner):
    from kagglesdk.kernels.types.kernels_api_service import ApiDownloadKernelOutputRequest
    parts = kernel.split('/')
    if (len(parts)!=3 or parts[0]!=owner or not re.fullmatch(r'[\w-]+',parts[1])
            or not parts[2].isdigit() or int(parts[2])<1):
        raise ValueError('An owned, versioned kernel is required for logs')
    request = ApiDownloadKernelOutputRequest()
    request.owner_slug, request.kernel_slug = parts[:2]
    request.version_number = int(parts[2])
    response = send(client,'DownloadKernelOutput',request)
    try:
        for item in [*response.history,response]:
            url = urlparse(item.url)
            match = re.fullmatch(r'/(?:api/)?v1/kernels/output/download_zip/(\d+)',url.path)
            if match and url.hostname in ('api.kaggle.com','www.kaggle.com'):
                return int(match.group(1))
    finally:
        response.close()
    raise ValueError('Exact Kaggle session is not available yet')


def read_records(response, *, budget=4.0, max_bytes=MAX_BYTES, completion=None):
    """Yield complete SSE events, or the persisted JSON log after termination.

    A quiet SSE read timeout is normal. Complete events already received must
    still be committed instead of disappearing with the timeout exception.
    """
    started=time.monotonic(); total=0; buffer=bytearray()
    is_json='application/json' in response.headers.get('Content-Type','')
    try:
        for chunk in response.iter_content(chunk_size=1024):
            if not chunk: continue
            total+=len(chunk)
            if total>max_bytes: raise ValueError('Kaggle log replay exceeds the byte limit')
            buffer.extend(chunk)
            while not is_json and b'\n' in buffer:
                end=buffer.index(b'\n')
                line=bytes(buffer[:end]).decode('utf-8',errors='replace').strip()
                del buffer[:end+1]
                if line.startswith('data:'):
                    payload=line[5:].lstrip()
                    if payload=='END_OF_LOG':
                        if completion is not None:completion['complete']=True
                        return
                    try: record=json.loads(payload)
                    except ValueError: record={'data':payload}
                    if isinstance(record,dict): yield record
            if time.monotonic()-started>budget: return
    except (TimeoutError,ConnectionError):
        return
    except Exception as exc:
        from requests.exceptions import ConnectionError as RequestsConnectionError, ReadTimeout
        if isinstance(exc,(RequestsConnectionError,ReadTimeout)): return
        raise
    if is_json and buffer:
        records=json.loads(buffer)
        if isinstance(records,list):
            for record in records:
                if isinstance(record,dict): yield record
    if completion is not None:completion['complete']=True


def shot_request(folder):
    try:
        request=json.loads((folder/'inputs'/'wan-request.json').read_text(encoding='utf-8'))
        return {shot['shot_id']:shot for shot in request['shots']
                if re.fullmatch(r'shot-[0-9]{3}',shot['shot_id'])}
    except (OSError,ValueError,KeyError,TypeError):
        return {}


def clip_events(message, shots):
    for line in message.splitlines():
        if not line.startswith('[Sahne] '):
            continue
        try:
            event,_=json.JSONDecoder().raw_decode(line[8:])
        except ValueError:
            continue
        if isinstance(event,dict) and event.get('event')=='clip_ready':
            shot=event.get('shot_id')
            if isinstance(shot,str) and shot in shots:
                yield shot


def receive_preview(folder, line, shots, ready):
    try:
        if len(line)>MAX_LINE:
            return None
        packet=json.loads(line[len(PREVIEW_PREFIX):])
        shot,digest=packet['shot_id'],packet['sha256']
        index,total=packet['index'],packet['total']
        if shot not in shots or shot not in ready or not re.fullmatch(r'[a-f0-9]{64}',digest):
            return None
        if type(index)!=int or type(total)!=int or not 0<=index<total<=24:
            return None
        data=base64.b64decode(packet['data'],validate=True)
        if not 0<len(data)<=PREVIEW_CHUNK or (index+1<total and len(data)!=PREVIEW_CHUNK):
            return None
    except (KeyError,TypeError,ValueError):
        return None
    root=folder/'previews'
    root.mkdir(exist_ok=True)
    target=root/(shot+'.mp4')
    partial=target.with_suffix('.part')
    if target.is_file():
        return (shot,target) if index+1==total and hashlib.sha256(target.read_bytes()).hexdigest()==digest else None
    offset=index*PREVIEW_CHUNK
    size=partial.stat().st_size if partial.is_file() else 0
    if size==offset:
        with partial.open('ab') as handle:
            handle.write(data)
    elif size<offset or size<offset+len(data):
        return None
    if index+1<total:
        return None
    payload=partial.read_bytes()
    if len(payload)!=offset+len(data) or payload[4:8]!=b'ftyp' or hashlib.sha256(payload).hexdigest()!=digest:
        partial.unlink(missing_ok=True)
        return None
    partial.replace(target)
    return shot,target


def publish_clip_previews(job, folder, shots, ready, previews):
    from sqlalchemy import select
    from .db import DB, Event, RemoteJob, Run, now
    from .parallel_work import run_write_lock
    from .storage import register
    with run_write_lock, DB() as db:
        run=db.scalar(select(Run).where(Run.id==job.run_id).with_for_update())
        if not run:
            return
        remote=db.get(RemoteJob,job.id)
        if not remote or remote.status=='discarded' or remote.created < run.outputs.get('_motion_preview_since',0):
            return
        assets={shot:register(db,run,path,'clip_preview',commit=False) for shot,path in previews.items()}
        previous=remote.result.get('live_clips',{})
        live={**previous}
        for shot in ready:
            live[shot]={**live.get(shot,{}),'duration_seconds':shots[shot]['duration_seconds']}
            if shot in assets:
                live[shot]['asset_id']=assets[shot]
        if live==previous:
            return
        remote.result={**remote.result,'live_clips':live}
        run.updated=now()
        db.add(Event(run_id=run.id,stage='motion',message=f'Kaggle: {len(live)} çekim tamamlandı.'))
        db.commit()


def sync_logs(api, job, folder, status, cfg):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    state_path=folder/'remote-log-state.json';log_path=folder/'remote.log.jsonl'
    kernel=job.kernel+(f'/{job.version}' if job.version else '')
    activity=None
    try: state=json.loads(state_path.read_text(encoding='utf-8'))
    except (OSError,ValueError): state={}
    if state.get('kernel')!=kernel: state={'kernel':kernel,'cursor':0}
    terminal=status in ('complete','completed','failed','error','cancelled','canceled','cancel_acknowledged')
    if state.get('finished') or (time.time()<state.get('next_read',0) and not terminal): return
    # A lost submission reply must not attach this run to an unverified latest version.
    if not job.version: return
    secrets=[value for key,value in cfg.model_dump().items()
             if any(word in key for word in ('key','token','password','secret')) and isinstance(value,str) and value]
    previous_error=state.get('error')
    shots=shot_request(folder)
    ready=set(state.get('ready_shots',[])).intersection(shots)
    if shots and 'ready_shots' not in state and log_path.is_file():
        # Recover completed shots for jobs submitted before previews were added.
        with log_path.open(encoding='utf-8') as old:
            for line in old:
                try: ready.update(clip_events(json.loads(line).get('message',''),shots))
                except ValueError: continue
    previews={}
    try:
        with api.build_kaggle_client() as client:
            if not state.get('session_id'):
                state['session_id']=resolve_session(client,kernel,cfg.kaggle_username)
            from kagglesdk.kernels.types.kernels_api_service import ApiGetKernelSessionLogsStreamRequest
            request=ApiGetKernelSessionLogsStreamRequest()
            request.kernel_session_id=state['session_id']
            request.wait_for_logs_url_seconds=1
            response=send(client,'GetKernelSessionLogsStream',request,timeout=(3,3))
            try:
                completion={}
                cursor=state.get('cursor',0)
                # Recover the cursor from the append-only file if a process died
                # after writing a line but before committing its state file.
                if log_path.is_file():
                    with log_path.open('rb') as existing:
                        existing.seek(max(0,log_path.stat().st_size-32768))
                        tail=existing.read().splitlines()
                    for line in reversed(tail):
                        try: cursor=max(cursor,json.loads(line)['index']+1);break
                        except (ValueError,KeyError,TypeError): continue
                with log_path.open('a',encoding='utf-8') as target:
                    for index,record in enumerate(read_records(response,completion=completion)):
                        if index<cursor: continue
                        lines=[]
                        for line in str(record.get('data','')).splitlines():
                            if line.startswith(PREVIEW_PREFIX):
                                preview=receive_preview(folder,line,shots,ready)
                                if preview:
                                    previews[preview[0]]=preview[1]
                            else:
                                lines.append(line)
                                ready.update(clip_events(line,shots))
                        message=redact('\n'.join(lines),secrets)
                        from .agent_progress import kaggle_activity
                        activity=kaggle_activity(message) or activity
                        stamp=record.get('time')
                        if not isinstance(stamp,(int,float)) or not math.isfinite(stamp):stamp=None
                        stream=record.get('stream_name','stdout')
                        item={'index':index,'time':stamp,'stream':stream if stream in ('stdout','stderr') else 'other',
                              'message':message}
                        if message:
                            target.write(json.dumps(item,ensure_ascii=False)+'\n');target.flush()
                        state['cursor']=index+1
                        if message.strip():
                            for line in message.replace('\r','\n').splitlines():
                                logger.info('Kaggle run=%s job=%s t=%s %s | %s',job.run_id,job.id,item['time'],item['stream'],line)
            finally: response.close()
        if activity:
            from .agent_progress import mark
            mark(job.run_id,'motion',**activity)
        if ready and (previews or ready!=set(state.get('ready_shots',[]))):
            publish_clip_previews(job,folder,shots,ready,previews)
        state['ready_shots']=sorted(ready)
        if not state.get('connected'):
            logger.info('Kaggle run=%s job=%s log bağlantısı kuruldu (oturum=%s)',job.run_id,job.id,state['session_id'])
        state.update(connected=True,error=None,next_read=time.time()+20,finished=terminal and completion.get('complete',False))
    except Exception as exc:
        # Never print exception text: SDK errors may contain signed URLs/tokens.
        error=type(exc).__name__
        if previous_error!=error:
            logger.warning('Kaggle run=%s job=%s günlük alınamadı (%s); üretim takibi sürüyor',job.run_id,job.id,error)
        state.update(error=error,next_read=time.time()+60)
    temporary=state_path.with_suffix('.partial')
    temporary.write_text(json.dumps(state),encoding='utf-8');temporary.replace(state_path)
