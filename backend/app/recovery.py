"""Durable, independently bounded recovery for measured production failures."""
import copy
import hashlib
import json
import random
from .db import DB, Run, now


def initial(outputs):
    value = copy.deepcopy(outputs.get('_recovery', {}))
    if value.get('version') != 1:
        value = {'version': 1, 'voice': {'text_used': len(outputs.get('_duration_repairs', [])),
                                      'speed_used': 0, 'history': []}}
    return value


def ensure(run_id):
    with DB() as db:
        run = db.get(Run, run_id)
        if run.outputs.get('_recovery', {}).get('version') != 1:
            run.outputs = {**run.outputs, '_recovery': initial(run.outputs)}
            db.commit()


def update(run_id, category, value):
    from .parallel_work import run_write_lock
    with run_write_lock, DB() as db:
        run = db.get(Run, run_id)
        recovery = initial(run.outputs)
        recovery[category] = value
        recovery['active'] = category
        run.outputs = {**run.outputs, '_recovery': recovery}
        db.commit()


def provider_wait(previous, stage, exc, timestamp=None, jitter=None):
    timestamp = now() if timestamp is None else timestamp
    # A successful completed stage ends an outage window. Restarting a worker does not.
    previous = previous if previous.get('stage') == stage else {}
    started = previous.get('started_at', timestamp)
    deadline = previous.get('deadline', started + 1800)
    cycles = previous.get('cycles', 0) + 1
    delay = min(300, 30 * 2 ** min(cycles - 1, 4))
    delay = min(300,delay + (random.uniform(0, min(10, delay * .1)) if jitter is None else jitter))
    delay = max(delay, getattr(exc, 'retry_after', None) or 0)
    automatic = timestamp < deadline
    return {'stage': stage, 'cycles': cycles, 'started_at': started, 'deadline': deadline,
            'retry_at': min(timestamp + delay, deadline) if automatic else None,
            'automatic': automatic, 'http_status': getattr(exc, 'http_status', None),
            'model': getattr(exc, 'model', None), 'request_id': getattr(exc, 'request_id', None)}


def task_budget(run_id, key, operation):
    """Count responses, not network outages; shared by nested specialist retries."""
    from .parallel_work import run_write_lock
    from .providers import InvalidModelOutput
    with run_write_lock, DB() as db:
        run = db.get(Run, run_id)
        ledger = dict(run.outputs.get('_inference_attempts', {}))
        used = ledger.get(key, 0)
        expanded=list(run.outputs.get('_inference_expanded',[]))
        if operation == 'expanded':
            return key in expanded
        if operation == 'expand':
            if key in expanded:
                return False
            run.outputs={**run.outputs,'_inference_expanded':[*expanded,key]}
            db.commit()
            return True
        if operation == 'check' and used >= 3:
            raise InvalidModelOutput('Bu görev için üç yanıt denemesi kullanıldı; geçerli çıktılar korundu.')
        if operation == 'consume':
            ledger[key] = used + 1
            run.outputs = {**run.outputs, '_inference_attempts': ledger}
            db.commit()


def localize_findings(report, durations):
    report=copy.deepcopy(report)
    localized=[]
    for finding in report.get('findings',[]):
        if finding.get('scene_index') is not None or finding.get('start_frame') is None:
            localized.append(finding)
            continue
        cursor=0
        matches=[]
        for index,duration in enumerate(durations):
            end=cursor+round(duration*30)
            if finding['start_frame']<end and (finding.get('end_frame') or finding['start_frame']+1)>cursor:
                matches.append({**finding,'scene_index':index})
            cursor=end
        localized.extend(matches or [finding])
    report['findings']=localized
    return report


def repair_voice(run_id):
    """Execute the supervisor's measured timing repair, preserving voice identity."""
    from pydantic import BaseModel, ConfigDict, Field
    from .orchestration import state, voice_timing, invalidate, mutate, NeedsInput, decision_call, fit_voice_boundary
    from .providers import Evren
    from .config import settings
    from .media_providers import supports_voice_speed
    fit_voice_boundary(run_id)
    run, _, _ = state(run_id)
    timing = voice_timing(run.outputs)
    if not timing['problem']:
        return
    recovery = initial(run.outputs)['voice']
    low, high = timing['accepted_min_seconds'], timing['accepted_max_seconds']
    aim = (low + high) / 2
    measured = timing['measured_seconds']
    plan = copy.deepcopy(run.outputs.get('_voice_plan'))
    current_speed = (plan or {}).get('speed', 1.0)
    baseline = recovery.get('baseline_speed', current_speed)
    speed = round(current_speed * measured / aim, 4)
    speed_ok = (supports_voice_speed(settings()) and plan is not None and
                .95 * baseline <= speed <= 1.05 * baseline and abs(speed-current_speed) > .001)
    recovery.update(baseline_speed=baseline, measurement=timing,
                    used=recovery.get('speed_used', 0)+recovery.get('text_used', 0),
                    remaining=max(0, 1-recovery.get('speed_used', 0))+max(0, 2-recovery.get('text_used', 0)))
    if speed_ok and not recovery.get('speed_used', 0):
        plan['speed'] = speed
        recovery.update(speed_used=1, action='adjust_speed', status='repairing')
        recovery['history'].append({'action': 'adjust_speed', 'before_seconds': measured, 'speed': speed})
        recovery.update(used=recovery.get('text_used',0)+1,remaining=max(0,2-recovery.get('text_used',0)))
        invalidate(run_id, ['voice'], repair=False, recovery_voice=recovery, voice_plan_override=plan)
        mutate(run_id, {'_voice_plan': plan}, f'Ses süresi düzeltiliyor: sağlayıcı konuşma hızı {speed:.3f}.', 'voice')
    else:
        if recovery.get('text_used', 0) >= 2:
            recovery.update(action='needs_input', status='exhausted', remaining=0)
            update(run_id, 'voice', recovery)
            raise NeedsInput(f'Ses süresi düzeltmeleri tamamlandı: {recovery.get("speed_used",0)} hız, '
                f'{recovery["text_used"]} metin denemesi; son süre {measured:.2f} sn, '
                f'kabul aralığı {low}–{high} sn. Çıktılar korundu.')
        original = run.outputs['script']
        words = sum(len(s['narration'].split()) for s in original['scenes'])
        target = max(1, round(words * aim / measured))
        if target == words:
            target += -1 if timing['problem'] == 'too_long' else 1
        class Patch(BaseModel):
            model_config = ConfigDict(extra='forbid')
            narrations: list[str] = Field(min_length=len(original['scenes']), max_length=len(original['scenes']))
        from pydantic import model_validator
        class TimedPatch(Patch):
            @model_validator(mode='after')
            def budget(self):
                count = sum(len(s.split()) for s in self.narrations)
                if any(not s.strip() for s in self.narrations):
                    raise ValueError('Sahne anlatımı boş bırakılamaz.')
                if abs(count-target) > 1:
                    raise ValueError(f'Toplam anlatım {target-1}–{target+1} kelime olmalı; {count} bulundu.')
                if self.narrations == [s['narration'] for s in original['scenes']]:
                    raise ValueError('Aynı metin tekrar edilemez; ölçülen süreyi düzelt.')
                if run.outputs.get('_config',{}).get('engagement_policy',0):
                    from .engagement import validate_engagement
                    candidate=copy.deepcopy(original)
                    for scene,text in zip(candidate['scenes'],self.narrations):
                        scene['narration']=text
                    validate_engagement(candidate)
                return self
        from .script_editorial import SPOKEN_STANDARD
        patch = decision_call(run_id, Evren().generate, TimedPatch, 'Senaryo Yazarı / Süre düzeltme', {
            'spoken_standard': SPOKEN_STANDARD,
            'script': original, 'measured_seconds': measured, 'scene_seconds': run.outputs['voice']['durations'],
            'required_words': target, 'target_seconds': aim, 'history': recovery['history'],
            'preserve_hook': bool(run.outputs.get('_config',{}).get('engagement_policy',0)),
            'instruction': 'Yalnız sırayla sahne anlatımlarını döndür. Gerçek ölçüme göre anlatımı '
            + ('kısalt. ' if timing['problem']=='too_long' else 'uzat. ')
            + 'Tarihî bilgileri, olayları, karakterleri ve anlamı koru; yeni olgusal iddia ekleme. '
            'Sahne sayısını koru; her narration boş olmayan bir cümle olmalı. '
            'preserve_hook doğruysa ilk hook cümlesini aynen koru. Kelime hedefi ±1.'},
            max_attempts=3, repair_fields=True)
        revised = copy.deepcopy(original)
        changed = []
        for index, (scene, narration) in enumerate(zip(revised['scenes'], patch['narrations'])):
            if scene['narration'] != narration:
                changed.append(index)
            scene['narration'] = narration
        fingerprint = hashlib.sha256(json.dumps(patch['narrations'], ensure_ascii=False).encode()).hexdigest()
        if fingerprint in [h.get('fingerprint') for h in recovery['history']]:
            raise NeedsInput('Süre düzeltmesi önceki etkisiz metni tekrarladı; çıktılar korundu.')
        recovery.update(text_used=recovery.get('text_used',0)+1, action='revise_narration', status='repairing')
        recovery['history'].append({'action':'revise_narration', 'before_seconds':measured,
                                    'requested_words':target, 'fingerprint':fingerprint})
        recovery.update(used=recovery.get('text_used',0)+recovery.get('speed_used',0),remaining=max(0,2-recovery.get('text_used',0)))
        invalidate(run_id, ['script'], repair=False, replacement_script=revised, scenes=changed, recovery_voice=recovery)
        mutate(run_id, {}, f'Ses süresi düzeltiliyor: {measured:.2f} sn ölçümüne göre {target} kelime hedeflendi.', 'voice')
    recovery['used'] = recovery.get('speed_used',0)+recovery.get('text_used',0)
    recovery['remaining'] = (0 if recovery.get('speed_used') else int(speed_ok)) + max(0,2-recovery.get('text_used',0))
    update(run_id, 'voice', recovery)
