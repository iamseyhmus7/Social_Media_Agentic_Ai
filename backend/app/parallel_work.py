"""Bounded task parallelism with run settings, tracing and cancellation preserved."""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from contextvars import copy_context
from threading import Event, RLock
import time

run_write_lock = RLock()


def pause(seconds, check):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        check()
        time.sleep(min(.25,max(0,end-time.monotonic())))


def settled_map(items, action, workers, check, *, on_success=None, on_error=None, delays=(5,15), sleeper=pause, budget_seconds=600, retry_errors=None):
    """Drain independent work before retrying only transient failures in later rounds."""
    from .providers import TransientProviderError
    from .providers import _budget
    if _budget.get() is not None:
        delays=()  # Durable scheduler owns retries during a production run.
    retryable=retry_errors or (TransientProviderError,)
    pending=list(enumerate(items))
    results={};fatal=[]
    deadline=time.monotonic()+budget_seconds
    next_delay=0
    retry=[]
    for round_index in range(len(delays)+1):
        if time.monotonic()>=deadline:break
        if round_index:
            sleeper(max(delays[round_index-1],next_delay),check)
        retry=[]
        with ThreadPoolExecutor(max_workers=workers if not round_index else 1,thread_name_prefix='editor-model') as pool:
            iterator=iter(pending);futures={}
            def submit():
                try:index,item=next(iterator)
                except StopIteration:return
                if time.monotonic()>=deadline:
                    retry.append((index,item,TransientProviderError('Bu turdaki bekleme bütçesi doldu.')))
                    return
                context=copy_context()
                futures[pool.submit(context.run,action,item)]=(index,item)
            for _ in range(workers if not round_index else 1):submit()
            try:
                while futures:
                    check()
                    ready,_=wait(futures,timeout=.25,return_when=FIRST_COMPLETED)
                    for future in ready:
                        index,item=futures.pop(future)
                        try:value=future.result()
                        except retryable as exc:
                            retry.append((index,item,exc))
                            if on_error:on_error(item,exc,round_index+1)
                        except Exception as exc:
                            from .media import Cancelled
                            if isinstance(exc,Cancelled):raise
                            fatal.append(exc)
                            if on_error:on_error(item,exc,round_index+1)
                        else:
                            results[index]=value
                            if on_success:
                                try:on_success(item,value)
                                except Exception as exc:
                                    from .media import Cancelled
                                    if isinstance(exc,Cancelled):raise
                                    fatal.append(exc)
                                    if on_error:on_error(item,exc,round_index+1)
                        submit()
            finally:
                for future in futures:future.cancel()
            retry.extend((index,item,TransientProviderError('Bu turdaki bekleme bütçesi doldu.')) for index,item in iterator)
        pending=[(i,item) for i,item,_ in sorted(retry,key=lambda row:row[0])]
        next_delay=max((getattr(exc,'retry_after',None) or 0 for _,_,exc in retry),default=0)
        if not pending:break
    if fatal:raise fatal[0]
    if pending and retry and _budget.get() is not None:
        raise retry[0][2]
    if pending:
        raise TransientProviderError('Model hizmeti bekleniyor; yalnız tamamlanmamış işler kaldı: '+str([item for _,item in pending]))
    return [results[i] for i in range(len(items))]


def retry_inference(action,check):
    return settled_map([0],lambda _:action(),1,check)[0]


def editor_progress(run_id, group, item, status, detail=''):
    if not run_id:return
    from sqlalchemy import select
    from .db import DB,Run,Event
    with run_write_lock,DB() as db:
        run=db.scalar(select(Run).where(Run.id==run_id).with_for_update())
        if not run:return
        progress=dict(run.outputs.get('_editor_progress',{}))
        entries=dict(progress.get(group,{}))
        entries[str(item)]={'status':status,'detail':detail[:240]}
        progress[group]=entries
        run.outputs={**run.outputs,'_editor_progress':progress}
        if status in ('ready','rendered','retry'):
            db.add(Event(run_id=run_id,stage='editor',message=f'Editör {group} {item}: {status}'+(' · '+detail[:180] if detail else '')))
        db.commit()


def bounded_map(items, action, workers, check):
    iterator=iter(enumerate(items))
    results={}
    stopped=Event()
    pool=ThreadPoolExecutor(max_workers=workers,thread_name_prefix='editor')
    pending={}
    def invoke(item):
        check()
        if stopped.is_set():
            raise RuntimeError('Parallel work cancelled')
        return action(item)
    def submit_one():
        try:
            index,item=next(iterator)
        except StopIteration:
            return
        context=copy_context()
        pending[pool.submit(context.run,invoke,item)]=index
    try:
        for _ in range(workers):submit_one()
        while pending:
            check()
            ready,_=wait(pending,timeout=.25,return_when=FIRST_COMPLETED)
            for future in ready:
                index=pending.pop(future)
                results[index]=future.result()
                submit_one()
        return [results[i] for i in range(len(results))]
    finally:
        stopped.set()
        for future in pending:future.cancel()
        pool.shutdown(wait=True,cancel_futures=True)
