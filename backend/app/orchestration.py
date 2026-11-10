"""Versioned agent control over existing production tools; SQL is the durable state."""
import hashlib
import json
from pathlib import Path
from typing import Literal
from pydantic import create_model
from .config import settings
from .db import DB, Run, Project, Event, now
from .providers import Evren, ProviderError, ProviderTimeout
from .schemas import ProductionBrief, ExecutionPlan, CreativeBrief, SupervisorDecision, AgentAction, QualityReview, SCENE_CAPABILITIES
from .agents import LABELS
from .storage import workdir

DEPENDENCIES = {
    'strategy': (), 'script': ('strategy',), 'voice': ('script',),
    'visual': ('script', 'voice'), 'motion': ('visual', 'voice'),
    'editor': ('motion', 'voice', 'visual'), 'quality': ('editor',),
    'publisher': ('quality',),
}


class NeedsInput(RuntimeError):
    pass


class SourceRejected(RuntimeError):
    def __init__(self, findings):
        self.findings = findings
        super().__init__('Kaynak incelemesi düzeltme gerektiriyor.')


def record_rejection(run_id, error):
    from .pipeline import checkpoint
    checkpoint(run_id, 'quality', {'passed': False, 'findings': error.findings,
        'issues': [f['evidence'] for f in error.findings], 'summary': str(error)})


def mutate(run_id, update, message=None, stage='supervisor'):
    with DB() as db:
        run = db.get(Run, run_id)
        run.outputs = {**run.outputs, **update}
        run.updated = now()
        if message:
            db.add(Event(run_id=run_id, stage=stage, message=message))
        db.commit()


def state(run_id):
    from .pipeline import read, cancellation
    cancellation(run_id)
    return read(run_id)


def descendants(stages):
    result = set(stages)
    while True:
        expanded = result | {s for s, deps in DEPENDENCIES.items() if result.intersection(deps)}
        if expanded == result:
            return result
        result = expanded


def uses_streaming_editor(config):
    return (config.get('video_execution_policy') == 'planned_v1'
            and config.get('video_edit_policy') == 'scenes_v3'
            and config.get('editor_streaming_enabled'))


def ensure_agent_budget(run_id):
    """Once-only conservative repair from provably unrefunded legacy calls."""
    from .parallel_work import run_write_lock
    from sqlalchemy import select
    with run_write_lock, DB() as db:
        run = db.scalar(select(Run).where(Run.id == run_id).with_for_update())
        record = run.outputs.get('_decision_budget', {})
        if record.get('version') == 2:
            return record
        turns = run.outputs.get('_agent_turns', 0)
        metrics = run.outputs.get('_model_metrics', [])
        schemas = {'SupervisorDecision', 'ReadySupervisorDecision', 'TimingSupervisorDecision',
                   'CreativeBrief', 'ProductionBrief', 'ExecutionPlan'}
        evidence = [i for i, m in enumerate(metrics) if m.get('role') == 'Supervisor'
                    and m.get('schema') in schemas
                    and (m.get('status') in ('timeout', 'connection_failed')
                         or (m.get('status') == 'service_unavailable'
                             and m.get('http_status') in (500, 502, 503, 504)))]
        credit = min(turns, len(evidence))
        record = {'version': 2, 'legacy_before': turns, 'legacy_refunded': credit,
                  'legacy_after': turns-credit, 'legacy_evidence_indices': evidence,
                  'legacy_metrics_hash': hashlib.sha256(json.dumps(metrics, sort_keys=True).encode()).hexdigest(),
                  'transient_refunds': 0}
        run.outputs = {**run.outputs, '_agent_turns': turns-credit, '_decision_budget': record}
        db.commit()
        return record


def decision_call(run_id, request, *args, **kwargs):
    from .providers import TransientProviderError
    tick(run_id)
    try:
        return request(*args, **kwargs)
    except TransientProviderError:
        unanswered_turn(run_id)
        raise


def tick(run_id):
    from .parallel_work import run_write_lock
    state(run_id)
    ensure_agent_budget(run_id)
    with run_write_lock, DB() as db:
        from sqlalchemy import select
        run = db.scalar(select(Run).where(Run.id==run_id).with_for_update())
        count = run.outputs.get('_agent_turns', 0)
        run.outputs = {**run.outputs, '_agent_turns':count+1}
        db.commit()


def unanswered_turn(run_id):
    """Transport failures consume request retries, not creative decision turns."""
    from .parallel_work import run_write_lock
    from sqlalchemy import select
    with run_write_lock,DB() as db:
        run=db.scalar(select(Run).where(Run.id==run_id).with_for_update())
        if run:
            budget=dict(run.outputs.get('_decision_budget', {}))
            budget['transient_refunds']=budget.get('transient_refunds',0)+1
            run.outputs={**run.outputs,'_agent_turns':max(0,run.outputs.get('_agent_turns',0)-1),
                         '_decision_budget':budget}
            db.commit()


def tool_schema(name, description, properties=None, required=None):
    return {'name': name, 'description': description,
            'parameters': {'type': 'object', 'properties': properties or {},
                           'required': required or [], 'additionalProperties': False}}


def optimized(run):
    return run.outputs.get("_config", {}).get("video_execution_policy") == "planned_v1"


def model_supervisor(run):
    return run.outputs.get('_config', {}).get('supervisor_policy') in ('model_v2', 'model_v3', 'model_v4')


def initial_brief(run_id):
    from .agent_progress import mark
    run, project, _ = state(run_id)
    if 'supervisor' in run.outputs:
        return
    mark(run_id,'supervisor','brief','Konu, hedef kitle ve üretim hedefleri belirleniyor')
    full_scope = run.outputs.get('_config', {}).get('supervisor_policy') in ('model_v3', 'model_v4')
    delegated = model_supervisor(run) and not full_scope
    schema = CreativeBrief if delegated else ProductionBrief if optimized(run) else CreativeBrief
    llm = Evren(timeout=settings().supervisor_timeout_seconds) if delegated else Evren()
    instruction = ('Genel amaçlı video yönetmenisin. Konuya uygun hedef kitle, ton, görsel dil ve '
        '30/45/60 saniyelik süre seç. Anlatı türünü kullanıcı isteğinden ve konudan seç. '
        'İstenen desteklenen süreyi koru; desteklenmeyen açık süre talebinde clarification ile soru sor. '
        'Yalnızca konu başlığı verilmesi soru sorma nedeni değildir. Kullanıcı belirtmedikçe estetik, '
        'altın renk, belgesel formatı, CTA veya sabit açılış dayatma. Kurgu yönünü mevcut '
        'editing_capabilities ile uygulanabilir tasarla; unavailable efektleri vaat etme.')
    from .script_editorial import spoken_standard_for
    instruction += ' Anlatım kalite standardı: ' + spoken_standard_for(run.outputs.get('_config',{}).get('engagement_policy',0))
    production_context = {}
    if run.outputs.get('_config', {}).get('script_editorial_policy', 0) >= 2:
        from .script_editorial import EditorialProductionBrief, EditorialCreativeBrief, AUTHORITY
        schema = EditorialProductionBrief if schema is ProductionBrief else EditorialCreativeBrief
        instruction += (' ' + AUTHORITY + ' editorial_direction içinde izleyici sorusunu, önemini, neden-sonuç odağını ve kapanış karşılığını belirle. '
            'critical_questions alanında bu konuya özgü soruları seç; core/supporting önceliğini ve '
            'answer_requirements ile anlaşılması gereken bağlantıyı yaz. Bunları kullanıcıya soru olarak yöneltme. '
            'story_question ile payoff aynı sorunun iki ucu olsun. Bir şeyin nasıl gerçekleştiği, neden gerçekleştiği '
            've sonradan nasıl değiştirildiği farklı sorularsa cevaplarını birbirinin yerine koyma. '
            'Önce ana soruya verilebilecek somut cevabı belirle; bu cevabı taşımayan merak vaadi kurma. '
            'Açılış, kapanış, causal_focus ve critical_questions alanlarını bu tek ana hatta göre tutarlı yaz. '
            'attention_allocation ile ana açıklamaya alan ayır. Toplam süreye sığmayan yan konuyu çıkar '
            'veya supporting düzeyine indir. Açılış vaadini ikinci bir konu ekleyerek dağıtma. '
            'Sahne sayısını açıklamanın ihtiyacına göre seç; eşit saniye veya kelime dağıtma. '
            'Emin olmadığın neden veya niyeti kesin öncül yapma. Çok etkenli sonucu tek etkene indirgeme. '
            'opening_direction içinde görünür eylemi, kısa ekran yazısını ve anlatıcı/ses vurgusunu birlikte planla. '
            'concrete_anchor için konuya uygun örnek seç; olguyu, yorumu ve temsili karşılaştırmayı ayır. '
            'pacing_direction içinde bilgi ve görüntü ilerleyişini tarif et. Gereksiz önsözü ve tekrarları çıkar. '
            'closing_direction ile son bilgiyi, görüntüyü ve ses bitişini belirle. Aynı kapanışın farklı, '
            'daha iddialı sloganlarını üretme. Görsellerde miktar, ölçek ve zaman ilişkilerini koru. '
            'Görsel planı hedef sahne sayısına göre kur; uzmanların gerekçeli değişikliğini değerlendir. '
            'checks alanını henüz yapılmamış kabul kontrolleri olarak yaz; ölçülmemiş ses/görüntü uyumunu '
            'doğrulanmış gibi sunma. Olgusal sınırları içerikte koru; bu denetim talimatlarını seslendirme. ')
        if settings().story_research_enabled:
            instruction += ('Tarihsel/bilimsel iddiada evidence_required=true, saf kurguda false seç. '
                'research_query için özel bilgi içermeyen kısa İngilizce konu sorgusu yaz. ')
    if run.outputs.get('_config', {}).get('script_editorial_policy', 0) >= 2 and not settings().story_research_enabled:
        from .script_editorial import MODEL_KNOWLEDGE
        instruction += ' ' + MODEL_KNOWLEDGE + ' evidence_required=false seç, research_query boş yaz; dış araştırma görevi planlama.'
    if run.outputs.get('_config',{}).get('engagement_policy',0):
        from .engagement import instruction_for
        instruction += ' Zorunlu üretim kuralı: ' + instruction_for(run.outputs['_config']['engagement_policy'])
    if run.outputs.get('_config', {}).get('supervisor_policy') == 'model_v4':
        production_context = {'audio_backend': {'provider':settings().tts_provider,
            'model':settings().elevenlabs_model if settings().tts_provider=='elevenlabs' else None,
            'voice_selection':'Seslendirme agentı doğrulanmış sağlayıcı seslerinden seçer.'}}
        instruction += (' Ses sağlayıcısı audio_backend ile belirlenmiştir; başka sağlayıcıya ait ses kimliği şart koşma. '
            'Sağlanan bilgi moduna göre tutarlılığı denetle; yapılmamış kontrol sonucunu uydurma.')
    brief = schema.model_validate(decision_call(run_id, llm.generate, schema, 'İçerik Stratejisti / Üretim özeti' if delegated else 'Supervisor', {
        'required_task_dependencies': DEPENDENCIES,
        'topic': project.topic, 'brand': run.outputs.get('_brand', {}),
        'editing_capabilities': SCENE_CAPABILITIES,
        **production_context,
        'requested_duration': run.outputs.get('_requested_duration'), 'clarification_answer': run.outputs.get('_brief_answer'),
        'instruction': instruction + (' Kısa yaz: tone en fazla 80 karakter. Ayrıntılı senaryo veya kurgu yazma.' if delegated else '')},
        **({'max_attempts':2,'max_output_tokens':1200,'repair_fields':True} if delegated else
           {'repair_fields':True} if full_scope else {}))).model_dump()
    if brief['clarification']:
        mutate(run_id, {'clarification': {'question': brief['clarification']}}, brief['clarification'])
        raise NeedsInput(brief['clarification'])
    with DB() as db:
        p = db.get(Project, project.id)
        p.duration, p.audience, p.tone = brief['duration'], brief['audience'], brief['tone']
        db.commit()
    plan = brief.pop('execution_plan', None)
    mutate(run_id, {'supervisor': brief, **({'_execution_plan': plan} if plan else {})}, 'Yaratıcı yön ve hedef süre belirlendi.')


def eligible(outputs):
    result = []
    for stage, deps in DEPENDENCIES.items():
        if stage in outputs or not all(d in outputs for d in deps):
            continue
        if stage == 'publisher' and not outputs['quality'].get('passed'):
            continue
        if stage == 'visual' and not voice_valid(outputs):
            continue
        result.append(stage)
    return result


def voice_valid(outputs):
    voice = outputs.get('voice', {})
    target = outputs.get('supervisor', {}).get('duration', 45)
    duration = voice.get('duration', 0)
    return 30 <= duration <= 60 and abs(duration - target) <= 2


def voice_timing(outputs):
    target = outputs.get('supervisor', {}).get('duration', 45)
    measured = outputs.get('voice', {}).get('duration')
    low, high = max(30, target - 2), min(60, target + 2)
    return {'target_seconds':target, 'measured_seconds':measured,
        'accepted_min_seconds':low, 'accepted_max_seconds':high,
        'problem':None if measured is None or low <= measured <= high else
            'too_short' if measured < low else 'too_long',
        'difference_from_target_seconds':round(measured-target,6) if measured is not None else None,
        'previous_repairs':outputs.get('_duration_repairs', []),
        'repair_counts':outputs.get('_repair_counts', {})}


def fit_voice_boundary(run_id):
    """Fit small PCM boundary differences before asking the model to rewrite speech."""
    from .pipeline import asset_path, cancellation
    from . import media
    from .storage import register
    run, _, _ = state(run_id)
    timing = voice_timing(run.outputs)
    if any(k in run.outputs for k in ('visual','motion','editor')):
        return
    voice = run.outputs.get('voice', {})
    if not voice.get('audios') or len(voice['audios']) != len(voice.get('durations', [])):
        return
    if timing['problem'] == 'too_long':
        excess = timing['measured_seconds'] - timing['accepted_max_seconds']
        # Half a second is an editorial fit, not a new creative draft. Keep a
        # small encoding margin and never stretch speech by more than 1%.
        speed = timing['measured_seconds'] / (timing['accepted_max_seconds'] - .02)
        if not 0 < excess <= .500001 or speed > 1.01 or voice.get('boundary_speed_adjustment'):
            return
        audios, durations = [], []
        for index, ident in enumerate(voice['audios']):
            cancellation(run_id)
            source = asset_path(ident)
            target = source.with_name(source.stem + '-boundary-fit.wav')
            duration = media.fit_audio_speed(source, target, speed, lambda:cancellation(run_id))
            with DB() as db:
                audios.append(register(db, db.get(Run, run_id), target, 'audio'))
            durations.append(duration)
        total = round(sum(durations), 9)
        if not timing['accepted_min_seconds'] <= total <= timing['accepted_max_seconds']:
            return  # Preserve the original checkpoint if the measured fit failed.
        with DB() as db:
            current = db.get(Run, run_id)
            current.outputs = {**current.outputs, 'voice':{**voice, 'audios':audios,
                'durations':durations, 'duration':total, 'boundary_speed_adjustment':{
                    'speed':speed, 'original_audios':voice['audios'],
                    'original_durations':voice['durations'], 'original_duration':voice['duration']}}}
            db.add(Event(run_id=run_id, stage='voice', message=
                f'Küçük süre aşımı yerel kurgu ayarıyla giderildi: {voice["duration"]:.2f} → {total:.2f} sn; '
                f'ses hızı %{(speed-1)*100:.2f} artırıldı, metin ve özgün kayıtlar korundu; yeni ses API isteği yapılmadı.'))
            db.commit()
        return
    if timing['problem'] != 'too_short':
        return
    gap = timing['accepted_min_seconds'] - timing['measured_seconds']
    if not 0 < gap <= .050001:
        return
    cancellation(run_id)
    source = asset_path(voice['audios'][-1])
    target = source.with_name(source.stem + '-boundary-pad.wav')
    duration = media.pad_silent_tail(source, target, gap)
    if duration is None:
        return
    cancellation(run_id)
    audios, durations = list(voice['audios']), list(voice['durations'])
    added = duration - durations[-1]
    durations[-1] = duration
    total = round(sum(durations), 9)
    if not timing['accepted_min_seconds'] <= total <= timing['accepted_max_seconds'] or not 0 < added <= .050001:
        target.unlink(missing_ok=True)
        return
    with DB() as db:
        current = db.get(Run, run_id)
        audios[-1] = register(db, current, target, 'audio')
        current.outputs = {**current.outputs, 'voice':{**voice, 'audios':audios,
            'durations':durations, 'duration':total,
            'boundary_padding_added_seconds':round(added,9),
            'boundary_original_audio':voice['audios'][-1]}}
        db.add(Event(run_id=run_id, stage='voice', message=
            f'Ses sınırı yerel düzeltildi: sona {added:.3f} saniye sessizlik eklendi; anlatım ve önceki çıktılar korundu.'))
        db.commit()


def stage_fingerprint(run, stage):
    data = {k: run.outputs.get(k) for k in DEPENDENCIES[stage]}
    data.update(stage=stage, revision=run.revision, feedback=run.outputs.get('_feedback'),
                repair=run.outputs.get('_repair_counts'), script=run.outputs.get('script'),
                config=run.outputs.get('_config'))
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def specialist(run_id, stage):
    """Only this specialist's named production tool can cause effects."""
    from .pipeline import run_stage
    from .agent_progress import mark,START
    mark(run_id,stage,'start',START.get(stage,'Kalite kontrolü hazırlanıyor'))
    role = LABELS[stage]
    with DB() as db:
        current = db.get(Run, run_id)
        current.stage, current.updated = stage, now()
        db.commit()
    run, _, _ = state(run_id)
    from .human_review import enabled
    if enabled(run) and stage in ('editor', 'quality', 'publisher'):
        return planned_specialist(run_id, stage)
    if optimized(run):
        return planned_specialist(run_id, stage)
    execution_tool = 'review_quality' if stage == 'quality' else 'produce_' + stage
    tools = [tool_schema('inspect_state', 'Görev girdilerini ve tamamlanmış çıktı özetini incele.'),
             tool_schema(execution_tool, 'Mevcut doğrulanan üretim aracını çalıştır; sonuç kalıcı kaydedilir.'),
             tool_schema('finish', 'Başarıyla tamamlanmış görevi Supervisor’a geri ver.')]
    if stage == 'editor':
        tools += [tool_schema('plan_preview', 'Kaynakları incele, doğrulanan yaratıcı kurgu planını ve 540x960 önizlemesini üret.'),
                  tool_schema('inspect_preview', 'Önizlemedeki gerçek kareleri görsel olarak değerlendir.'),
                  tool_schema('revise_plan', 'Önizleme hatalarına göre yalnız kurgu planını yeniden hazırla.')]
    for _ in range(settings().agent_task_max_turns):
        run, project, _ = state(run_id)
        key = stage + ':' + stage_fingerprint(run, stage)
        journal = run.outputs.get('_agent_actions', {})
        prior = journal.get(key, {})
        # Completion is verified from both the output and the action receipt.
        if stage in run.outputs and prior.get('status') == 'complete':
            return
        decision = AgentAction.model_validate(decision_call(run_id, Evren().choose_action, role, {
            'task': stage, 'topic': project.topic, 'brief': run.outputs.get('supervisor'),
            'feedback': run.outputs.get('_feedback'),
            'inputs': {k: run.outputs[k] for k in DEPENDENCIES[stage] if k in run.outputs},
            'tool_observations': prior, 'has_output': stage in run.outputs,
            'preview': run.outputs.get('_editor_preview'), 'preview_review': run.outputs.get('_editor_preview_review'),
            'instruction': f'Görevi {execution_tool} ile gerçekleştir. Başarılı çıktı varsa finish; '
            'tekrar çalıştırma. Editörde önce plan_preview, sonra inspect_preview; hata varsa revise_plan, '
            'hata yoksa produce_editor ile final render. inspect_state aynı girdiyi tekrar döndürür.'}, tools))
        if decision.arguments or decision.tool not in {t['name'] for t in tools}:
            raise ProviderError('Agent izinli ve parametresiz görev aracını seçmeli.')
        if decision.tool == 'finish':
            if stage not in run.outputs:
                raise ProviderError('Agent araç sonucu olmadan görevi tamamlayamaz.')
            return
        if decision.tool == 'inspect_state':
            if prior.get('inspected'):
                raise ProviderError('Agent ilerleme sağlamayan aynı incelemeyi tekrarladı.')
            prior = {**prior, 'inspected': True}
        elif decision.tool == 'plan_preview':
            if run.outputs.get('_editor_preview'):
                raise ProviderError('Mevcut önizleme yeniden oluşturulamaz; incele veya planı düzelt.')
            try:
                run_stage(run_id, stage, preview_only=True)
            except SourceRejected as exc:
                record_rejection(run_id, exc)
                return
            continue
        elif decision.tool == 'inspect_preview':
            if not run.outputs.get('_editor_preview') or run.outputs.get('_editor_preview_review'):
                raise ProviderError('Önce yeni bir önizleme hazırlanmalı; aynı inceleme tekrarlanamaz.')
            report = review_quality(run_id, preview=True)
            mutate(run_id, {'_editor_preview_review': report})
            if any(f['severity']=='error' and f['repair_stage']!='editor' for f in report.get('findings', [])):
                from .pipeline import checkpoint
                checkpoint(run_id, 'quality', report)
                return
            continue
        elif decision.tool == 'revise_plan':
            review = run.outputs.get('_editor_preview_review', {})
            if review.get('passed', True):
                raise ProviderError('Önizleme hata raporu olmadan aynı plan tekrar üretilemez.')
            mutate(run_id, {'_last_quality': review})
            invalidate(run_id, ['editor'], repair=True)
            continue
        else:
            from .human_review import enabled
            if stage == 'editor' and not enabled(run):
                preview = run.outputs.get('_editor_preview', {})
                if not run.outputs.get('_editor_preview_review', {}).get('passed'):
                    raise ProviderError('Final render öncesinde görsel önizleme değerlendirmesi gerekli.')
                from .storage import file_hash
                folder = workdir(project.id,run.id)
                if preview.get('manifest_hash')!=file_hash(folder/'render-manifest.json') or preview.get('preview_hash')!=file_hash(folder/'visual-preview.mp4'):
                    raise ProviderError('İncelenen önizleme veya kurgu planı değişti; final render durduruldu.')
            mutate(run_id, {'_agent_actions': {**journal, key: {**prior, 'status': 'started'}}},
                   decision.reason, stage)
            if stage == 'quality':
                report = review_quality(run_id)
                from .pipeline import checkpoint
                checkpoint(run_id, 'quality', report)
            else:
                try:
                    run_stage(run_id, stage)
                except SourceRejected as exc:
                    record_rejection(run_id, exc)
                    return
            run, _, _ = state(run_id)
            # Reload: nested media tools may have journalled their own progress.
            journal = run.outputs.get('_agent_actions', {})
            prior = {**prior, 'status': 'complete', 'output_stage': stage}
        mutate(run_id, {'_agent_actions': {**journal, key: prior}})
        if prior.get('status') == 'complete':
            return
    raise ProviderError(f'{role} araç turu sınırına ulaştı; tamamlanan çıktılar korundu.')


def planned_specialist(run_id, stage):
    from .pipeline import run_stage, checkpoint
    from .human_review import enabled
    for _ in range(settings().agent_task_max_turns):
        run, project, _ = state(run_id)
        if stage in run.outputs:
            return
        key = stage + ':' + stage_fingerprint(run, stage)
        journal = run.outputs.get('_agent_actions', {})
        mutate(run_id, {'_agent_actions': {**journal, key: {'status':'started'}}})
        try:
            if stage == 'editor' and not enabled(run):
                if not run.outputs.get('_editor_preview'):
                    run_stage(run_id, stage, preview_only=True)
                run, _, _ = state(run_id)
                if not run.outputs.get('_editor_preview_review'):
                    review = review_quality(run_id, preview=True)
                    mutate(run_id, {'_editor_preview_review':review})
                run, _, _ = state(run_id)
                review = run.outputs['_editor_preview_review']
                if not review['passed']:
                    if any(f['severity']=='error' and f['repair_stage']!='editor' for f in review.get('findings', [])):
                        checkpoint(run_id, 'quality', review)
                        return
                    mutate(run_id, {'_last_quality':review})
                    invalidate(run_id, ['editor'], repair=True)
                    continue
                from .preview import verify_preview
                verify_preview(workdir(project.id,run.id), run.outputs['_editor_preview'])
            if stage == 'quality':
                checkpoint(run_id, stage, review_quality(run_id))
            else:
                run_stage(run_id, stage)
        except SourceRejected as exc:
            record_rejection(run_id, exc)
            return
        run, _, _ = state(run_id)
        mutate(run_id, {'_agent_actions': {**run.outputs.get('_agent_actions', {}),
            key: {'status':'complete', 'output_stage':stage}}})
        return
    raise ProviderError('Editör düzeltme sınırına ulaştı; çıktılar korundu.')


def invalidate(run_id, stages, *, repair=False, scenes=None, replacement_script=None, recovery_voice=None, voice_plan_override=None):
    """Invalidate dependencies, never delete source assets or completed files."""
    from .schemas import timed_story_script
    run, project, _ = state(run_id)
    stages = set(stages)
    counts = dict(run.outputs.get('_repair_counts', {}))
    category = 'script' if 'script' in stages else 'media' if stages & {'visual', 'motion', 'voice'} else 'editor'
    limit = 2 if category in ('editor','media') else 1
    if repair and counts.get(category, 0) >= limit:
        raise NeedsInput(f'{category} onarım sınırına ulaştı; tamamlanan çıktılar ve mevcut hata bilgileri korundu. Yalnız bu aşamada düzeltme gerekli.')
    scenes = list(dict.fromkeys(scenes or []))
    if any(i < 0 or i >= len(run.outputs.get('script', {}).get('scenes', [])) for i in scenes):
        raise ProviderError('Düzeltme sahne referansı geçersiz.')
    if stages & {'visual', 'motion'}:
        shots = run.outputs.get('motion', {}).get('plan', {}).get('shots', [])
        selected = [s for s in shots if not scenes or s['scene_index'] in scenes]
        if repair and len(selected) > 3:
            raise ProviderError('Medya onarımı en fazla üç çekim içerebilir; daha dar düzeltme gerekli.')
    if run.outputs.get('_edit_only') and stages - {'editor', 'publisher'}:
        raise ProviderError('Yalnızca kurgu talebi yeni kaynak medya üretemez.')
    replacement = {'script': replacement_script} if replacement_script is not None else {}
    if replacement_script is None and 'script' in stages and 'voice' in run.outputs and not voice_valid(run.outputs):
        measured = max(1, run.outputs['voice']['duration'])
        words = sum(len(s['narration'].split()) for s in run.outputs['script']['scenes'])
        target = round(words * min(59, max(31, project.duration)) / measured)
        replacement['script'] = decision_call(run_id, Evren().generate, timed_story_script(target), 'Senaryo Yazarı', {
            'script': run.outputs['script'], 'required_words': target,
            'instruction': 'Yalnızca anlatım uzunluğunu hedef kelime sayısına düzelt. Sahne sayısını, '
            'bilgiyi, görsel yönergeleri ve sürekliliği koru. Ses hızlandırılmayacak.'})
    removed = descendants(stages)
    folder = workdir(project.id, run.id)
    # Version each edit attempt rather than silently reusing an obsolete manifest.
    if 'editor' in removed:
        plan = folder/'edit-plan.json'
        if plan.exists():
            previous = folder/f"edit-plan-before-{sum(counts.values())}-{run.outputs.get('_agent_turns',0)}.json"
            plan.replace(previous)
    outputs = {k: v for k, v in run.outputs.items() if k not in removed}
    if removed.intersection(run.outputs):
        outputs['_output_history'] = [*outputs.get('_output_history', []),
            {'stages':{k:run.outputs[k] for k in removed if k in run.outputs},'created':now()}]
    if 'visual' in removed:
        outputs.pop('_visual_progress',None)
    if 'voice' in removed:
        outputs.pop('_voice_progress',None)
    if run.outputs.get('quality'):
        outputs['_last_quality'] = run.outputs['quality']
    if 'editor' in removed:
        outputs.pop('_editor_progress',None)
        outputs.pop('_editor_preview', None)
        outputs.pop('_editor_preview_review', None)
    if 'motion' in removed:
        outputs.pop('_motion_plan', None)
        outputs['_motion_preview_since']=now()
    if 'visual' in stages:
        outputs.pop('_storyboard', None)
    if 'visual' in removed and 'visual' in run.outputs:
        outputs['_reuse_visual'] = run.outputs['visual']
    if 'motion' in removed and 'motion' in run.outputs:
        outputs['_reuse_motion'] = run.outputs['motion']
    if 'voice' in removed and 'voice' in run.outputs:
        outputs['_reuse_voice'] = run.outputs['voice']
    if 'script' in stages:
        outputs.pop('_storyboard', None)
        outputs.pop('_motion_plan', None)
    if 'voice' in stages:
        for key in ('_voice_plan', '_voice_casting_state', 'voice_casting'):
            outputs.pop(key, None)
        for marker in folder.glob('voice-*.complete.json'):
            marker.replace(marker.with_suffix('.before-repair.json'))
    outputs['_changed_scenes'] = scenes
    outputs['_repair_stages'] = sorted(stages)
    if stages & {'visual', 'motion'}:
        outputs['_motion_session'] = 'repair-' + str(run.outputs.get('_agent_turns', 0))
    if repair:
        counts[category] = counts.get(category, 0) + 1
        from .recovery import initial
        recovery=initial(run.outputs)
        recovery.update(active='media',media={'kind':category,'action':'repair_'+next(iter(sorted(stages))),
            'status':'repairing','used':counts[category],'remaining':max(0,limit-counts[category])})
        outputs['_recovery']=recovery
    outputs.update(replacement, _repair_counts=counts)
    if replacement.get('script'):
        outputs['_duration_repairs'] = [*outputs.get('_duration_repairs', []),
            {**voice_timing(run.outputs), 'requested_words':sum(len(s['narration'].split()) for s in replacement['script']['scenes'])}][-3:]
    if recovery_voice is not None:
        from .recovery import initial
        recovery=initial(run.outputs)
        recovery.update(active='voice',voice=recovery_voice)
        outputs['_recovery']=recovery
        outputs['_pending_voice_repair']=False
    if voice_plan_override is not None:
        outputs['_voice_plan']=voice_plan_override
    with DB() as db:
        current = db.get(Run, run_id)
        # Fixed render filenames may be produced again; old asset IDs keep their bytes.
        from .db import Asset
        from .storage import media_path
        from .config import settings
        from shutil import copy2
        from uuid import uuid4
        archive = folder / ('history-' + uuid4().hex)
        identifiers = []
        for stage, fields in (('editor',('video','subtitle')),('publisher',('package',)),('visual',('cover',))):
            if stage in removed:
                identifiers += [run.outputs.get(stage,{}).get(key) for key in fields]
        for identifier in filter(None,identifiers):
            asset = db.get(Asset,identifier)
            source = media_path(asset.path) if asset else None
            if source and source.is_file():
                archive.mkdir(exist_ok=True)
                target_file=archive/source.name
                copy2(source,target_file)
                asset.path=target_file.resolve().relative_to(settings().media_root.resolve()).as_posix()
        # The repair model recorded new metrics/turns while this snapshot was in flight.
        for key in ('_model_metrics', '_agent_turns', '_inference_attempts', '_inference_expanded'):
            if key in current.outputs:
                outputs[key] = current.outputs[key]
        current.outputs = outputs
        db.commit()


def supervisor_decision(run_id, run, context):
    """Retry only an unanswered routing inference, never a production tool."""
    active = model_supervisor(run)
    schema = SupervisorDecision
    if context['voice_duration_problem']:
        schema = create_model('TimingSupervisorDecision', __base__=SupervisorDecision,
            action=(Literal['repair'], ...),stage=(Literal['script'], ...))
    if (context['eligible_stages'] and not context['voice_duration_problem']
            and (not context['quality'] or context['quality'].get('passed'))):
        # Validate against this checkpoint, not the global list of stage names.
        # Evren repairs an invalid routing response before any tool is dispatched.
        schema = create_model('ReadySupervisorDecision', __base__=SupervisorDecision,
            action=(Literal['dispatch'], ...),
            stage=(Literal[tuple(context['eligible_stages'])], ...))
    from .providers import _budget
    for attempt in range(2 if active and _budget.get() is None else 1):
        state(run_id)
        llm = Evren(timeout=settings().supervisor_timeout_seconds) if active else Evren()
        try:
            return SupervisorDecision.model_validate(decision_call(run_id, llm.generate, schema, 'Supervisor', context,
                **({'max_attempts':2,'max_output_tokens':600,'repair_fields':False} if active else {})))
        except ProviderTimeout:
            if not active or attempt or _budget.get() is not None:
                raise
            mutate(run_id, {}, 'Supervisor yanıtı zaman aşımına uğradı; yalnız karar çağrısı bir kez yeniden deneniyor. Tamamlanan üretim araçları tekrarlanmayacak.')


def supervise(run_id):
    from .agent_progress import mark
    mark(run_id,'supervisor','coordination','Tamamlanan görevler inceleniyor; sıradaki iş seçiliyor')
    from .human_review import enabled, complete
    from .recovery import ensure, repair_voice, initial, update
    ensure(run_id)
    run, _, _ = state(run_id)
    if enabled(run) and 'editor' in run.outputs:
        if not run.outputs['editor']['report'].get('passed'):
            from .recovery import localize_findings
            report=localize_findings(run.outputs['editor']['report'],run.outputs.get('voice',{}).get('durations',[]))
            if run.outputs.get('_repair_counts', {}).get('editor', 0) >= 2:
                update(run_id,'media',{'kind':'technical','action':'needs_input','status':'exhausted','used':2,'remaining':0,'findings':report.get('findings',[])})
                raise NeedsInput('İki kurgu onarımı tamamlandı; mevcut render ve teknik bulgular korundu.')
            used=run.outputs.get('_repair_counts',{}).get('editor',0)+1
            update(run_id,'media',{'kind':'technical','action':'repair_editor','status':'repairing','used':used,'remaining':2-used,'findings':report.get('findings',[])})
            mutate(run_id, {'_last_quality':report})
            invalidate(run_id, ['editor'], repair=True)
            return 'editor'
        complete(run_id)
        return 'done'
    with DB() as db:
        current = db.get(Run, run_id)
        current.stage, current.updated = 'supervisor', now()
        db.commit()
    if run.outputs.get('_script_only') and 'script' in run.outputs:
        raise NeedsInput('Senaryo hazır. Yalnız senaryo seçildiği için ses, görsel ve video üretimi başlatılmadı.')
    initial_brief(run_id)
    fit_voice_boundary(run_id)
    run, project, _ = state(run_id)
    ready = eligible(run.outputs)
    report = run.outputs.get('quality', {})
    bad_voice = 'voice' in run.outputs and not voice_valid(run.outputs)
    # An owned shot-change command has already selected its single repair task.
    # Dispatch that validated task directly; no model routing round is needed.
    requested=run.outputs.get('_repair_stages',[])
    if run.outputs.get('_shot_requests') and len(requested)==1 and requested[0] in ready and not bad_voice:
        selected=requested[0]
        mutate(run_id,{'_supervisor_dispatch':{'stage':selected,'fingerprint':stage_fingerprint(run,selected)},
            'orchestration':{'stage':selected,'action':'dispatch','reason':'İstenen çekim düzeltmesi hazır girdilerle uygulanıyor.','protocol':'shot_change_v1'}})
        return selected
    if bad_voice and run.outputs.get('_pending_voice_repair'):
        repair_voice(run_id)
        mutate(run_id, {'_pending_voice_repair':False})
        return 'supervisor'
    if not bad_voice and 'voice' in run.outputs:
        recovery = initial(run.outputs)['voice']
        if recovery.get('status') == 'repairing':
            update(run_id, 'voice', {**recovery, 'status':'resolved', 'measurement':voice_timing(run.outputs)})
    receipt = run.outputs.get('_supervisor_dispatch', {})
    pending = receipt.get('stage')
    if (model_supervisor(run) and not bad_voice and (not report or report.get('passed'))
            and pending in ready and receipt.get('fingerprint') == stage_fingerprint(run, pending)):
        # The agent already selected this unfinished task. A remote poll is not a new routing decision.
        return pending
    if optimized(run) and not model_supervisor(run) and not bad_voice and (not report or report.get('passed')):
        plan = run.outputs.get('_execution_plan')
        if not plan:
            plan = decision_call(run_id, Evren().generate, ExecutionPlan, 'Supervisor', {
                'brief': run.outputs['supervisor'], 'feedback': run.outputs.get('_feedback'),
                'required_task_dependencies': DEPENDENCIES,
                'instruction': 'Bağımlılık sırasına uygun sekiz uzman görevi için bir yürütme planı oluştur.'})
            mutate(run_id, {'_execution_plan': plan})
        plan = ExecutionPlan.model_validate(plan)
        if run.outputs.get('publisher') and report.get('passed'):
            return 'done'
        selected = next((t.stage for t in plan.tasks if t.stage in ready
                        and all(d in run.outputs for d in t.depends_on)), None)
        if not selected:
            raise ProviderError('Doğrulanmış planda hazır görev yok; yeniden planlama gerekli.')
        mutate(run_id, {'orchestration': {'stage': selected, 'action': 'dispatch',
            'reason': 'Doğrulanmış yürütme planındaki sıradaki hazır görev.', 'protocol': 'planned_v1'}})
        return selected
    decision = supervisor_decision(run_id, run, {
        'topic': project.topic, 'creative_brief': run.outputs['supervisor'],
        'completed': list(k for k in DEPENDENCIES if k in run.outputs),
        'eligible_stages': ready, 'quality': report, 'feedback': run.outputs.get('_feedback'),
        'feedback_progress': {
            'completed_requested_stages': [s for s in run.outputs.get('_feedback', {}).get('stages', []) if s in run.outputs],
            'pending_requested_stages': [s for s in run.outputs.get('_feedback', {}).get('stages', []) if s not in run.outputs],
        },
        'voice_duration_problem': bad_voice,
        'voice_timing': voice_timing(run.outputs),
        'voice_recovery': initial(run.outputs)['voice'],
        'voice_narration_words': sum(len(s.get('narration','').split()) for s in run.outputs.get('script',{}).get('scenes',[])),
        'voice_speed': (run.outputs.get('_voice_plan') or {}).get('speed',1.0),
        'instruction': 'Sıradaki uygun uzmanı dispatch ile seç. Kalite hatasında yalnız sorumlu stage '
        've gerekirse scene_indices ile repair seç. Ses süresi hatasında script onar. '
        'publisher tamamlanmış ve kalite passed ise finish. Önkoşulları atlama; aynı işi tekrarlama. '
        'dispatch için yalnız eligible_stages içinden seç. completed ve feedback_progress güncel sürümün '
        'kalıcı sonuçlarıdır; geri bildirimde adı geçen tamamlanmış görevi yeniden başlatma. '
        'voice_timing ölçümlerini kullan: too_short ise anlatımı uzat, too_long ise kısalt; '
        'kısa sesi uzun diye açıklama. Önceki düzeltme sonuçlarını dikkate al. '
        'Yalnız görev koordinasyonu yap; yaratıcı içerik yazma. reason tek kısa cümle olsun.'})
    mutate(run_id, {'orchestration': {'stage': decision.stage, 'action': decision.action,
        'reason': decision.reason, 'protocol': settings().agent_protocol}}, decision.reason)
    if decision.action == 'finish':
        if not (run.outputs.get('quality', {}).get('passed') and run.outputs.get('publisher')):
            raise ProviderError('Supervisor kalite ve paket tamamlanmadan üretimi bitiremez.')
        return 'done'
    if decision.action == 'repair':
        if not bad_voice and (not report or report.get('passed')):
            raise ProviderError('Kalite bulgusu olmadan otomatik onarım başlatılamaz.')
        if bad_voice and decision.stage != 'script':
            raise ProviderError('Anlatım süresi senaryo üzerinden düzeltilmeli.')
        errors = [f for f in report.get('findings', []) if f['severity'] == 'error']
        if not bad_voice and decision.stage not in {f['repair_stage'] for f in errors}:
            raise ProviderError('Supervisor kalite raporundaki sorumlu uzmanı seçmeli.')
        if bad_voice:
            mutate(run_id, {'_pending_voice_repair':True})
            repair_voice(run_id)
            mutate(run_id, {'_pending_voice_repair':False})
        else:
            invalidate(run_id, [decision.stage], repair=True, scenes=decision.scene_indices)
        return 'supervisor'
    if bad_voice or (report and not report.get('passed')):
        raise ProviderError('Kalite sorunu çözülmeden yeni üretim görevi başlatılamaz; onarım gerekli.')
    if decision.stage not in ready:
        raise ProviderError('Supervisor tamamlanmış veya önkoşulları eksik görevi seçti.')
    if model_supervisor(run):
        mutate(run_id, {'_supervisor_dispatch':{'stage':decision.stage,
            'fingerprint':stage_fingerprint(run, decision.stage), 'reason':decision.reason}})
    return decision.stage


def build_agent_graph():
    from langgraph.graph import StateGraph, START, END
    from .pipeline import State
    graph = StateGraph(State)
    def supervisor_node(value):
        return {**value, 'next_stage': supervise(value['run_id'])}
    graph.add_node('supervisor', supervisor_node)
    for stage in DEPENDENCIES:
        def node(value, selected=stage):
            specialist(value['run_id'], selected)
            return value
        graph.add_node(stage, node)
        graph.add_edge(stage, 'supervisor')
    graph.add_edge(START, 'supervisor')
    graph.add_conditional_edges('supervisor', lambda s: s['next_stage'],
        {**{s: s for s in DEPENDENCIES}, 'supervisor': 'supervisor', 'done': END})
    return graph.compile()


def review_quality(run_id, *, preview=False):
    from .agent_progress import mark
    mark(run_id,'editor','quality','Kurgu önizlemesi inceleniyor' if preview else 'Görüntü, ses ve son video kontrolleri yapılıyor')
    """Review actual rendered evidence, separately from the editing decision."""
    import base64
    from . import media
    from .pipeline import cancellation
    run, project, _ = state(run_id)
    from .human_review import enabled, technical_report
    if enabled(run):
        if preview:
            raise ProviderError('Bu üretimde model önizleme incelemesi kapalı; final teknik kontrolleri kullanılmalı.')
        return technical_report(run)
    folder = workdir(project.id, run.id)
    check = lambda: cancellation(run_id)
    manifest = json.loads((folder/'render-manifest.json').read_text(encoding='utf-8'))
    video = folder/('visual-preview.mp4' if preview else 'video.mp4')
    frames = {0, manifest['duration_frames']-1}
    for clip in manifest['clips']:
        start = clip['start_frame']
        frames.add(start+clip['frames']//2)
        if start:
            frames.update((start-1, start, start+clip['transition_frames']//2,
                           min(manifest['duration_frames']-1, start+clip['transition_frames'])))
    items = None
    if preview and optimized(run):
        from .preview import verify_preview
        items = verify_preview(folder, run.outputs['_editor_preview'])
        frames = {i['frame'] for i in items}
    inputs = []
    for index, frame in enumerate(sorted(frames)):
        check()
        if items is not None:
            path = folder/items[index]['file']
            # Full-resolution render evidence, resized only for model transport.
            import io
            from PIL import Image
            buffer = io.BytesIO()
            with Image.open(path) as image:
                image.resize((270,480)).save(buffer,format='JPEG',quality=85)
            content = buffer.getvalue()
        else:
            path = folder/f'quality-{index:03}.jpg'
            media.command([settings().ffmpeg_bin, '-y', '-ss', str(frame/30), '-i', video,
                '-frames:v', '1', '-vf', 'scale=270:480', path], folder, check, timeout=60)
            content = path.read_bytes()
        inputs.append({'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,'+
            base64.b64encode(content).decode(), 'detail':'high'}})
    # Text labels live in context because the provider accepts only media blocks.
    media_inputs = [item for item in inputs if item['type'] == 'image_url']
    streaming=run.outputs.get('_config',{}).get('editor_streaming_enabled',False)
    audio_seconds=manifest['duration_frames']/30 if streaming else 8
    audio_sampled = settings().evren_audio_input_verified and not preview
    if audio_sampled:
        path = folder/'quality-audio.wav'
        media.command([settings().ffmpeg_bin, '-y', '-i', folder/'video.mp4', '-t', str(audio_seconds),
            '-vn', '-ar', '16000', '-ac', '1', path], folder, check, timeout=60)
        media_inputs.append({'type':'input_audio','input_audio':{'format':'wav',
            'data':base64.b64encode(path.read_bytes()).decode()}})
    full_video_review=False
    streaming=run.outputs.get('_config',{}).get('editor_streaming_enabled',False)
    if not preview and streaming and settings().evren_video_input_verified:
        proxy=folder/'quality-overview.mp4'
        media.command([settings().ffmpeg_bin,'-y','-i',video,'-vf','scale=270:480,fps=12',
            '-c:v','libx264','-preset','veryfast','-crf','30','-maxrate','700k','-bufsize','1400k',
            '-c:a','aac','-b:a','64k','-movflags','+faststart',proxy],folder,check,timeout=120)
        if proxy.stat().st_size<=8*1024*1024:
            media_inputs.append({'type':'video_url','video_url':{'url':'data:video/mp4;base64,'+base64.b64encode(proxy.read_bytes()).decode()}})
            full_video_review=True
    from .schemas import PreviewQualityReview
    schema = PreviewQualityReview if preview and optimized(run) and settings().evren_video_input_verified else QualityReview
    def request_review():
        return decision_call(run_id, Evren(timeout=settings().editor_call_timeout_seconds if streaming else None).generate, schema, 'Video Editörü' if preview else 'Kalite kontrolü', {
        'script': run.outputs['script'], 'brief': run.outputs['supervisor'],
        'sampled_frames': sorted(frames), 'manifest': manifest, 'audio_sample_seconds': audio_seconds if audio_sampled else 0,
        'full_video_proxy':{'included':full_video_review,'fps':12,'width':270,'height':480},
        'motion_window_capability': 'Gerekli hareket incelemesi için en fazla üç sıralı/örtüşmesiz iki saniyelik motion_windows iste; gerekmiyorsa boş bırak.' if schema is PreviewQualityReview else 'Video girdisi doğrulanmadı; yalnız örnek kareler incelenebilir.',
        'instruction': 'Bunlar SON renderın belirtilen sıradaki gerçek örnek kareleridir. '
        'Metin taşması, okunabilirlik, yanlış özne, kaynak ve görsel süreklilik sorunlarını kanıtıyla yaz. '
        'Sabit bir estetik veya efekt kotası dayatma. Örnek karelerle kesintisiz hareketi veya sesi '
        'doğruladığını iddia etme. Ses ekinin gerçek kapsamı audio_sample_seconds alanındadır; bunun dışındaki sesi dinlediğini iddia etme. '
        'anlaşılabilirlik ve bastırılan anlatımı değerlendir. Baştan sona anlatı mantığını, sahne sırasını, '
        'anlatım-görsel uyumunu, gereksiz tekrarları ve kapanış bütünlüğünü değerlendir. '
        'Tam video proxy eklendiyse tüm zaman aralığını kapsayan 12 FPS düşük çözünürlüklü incelemedir; '
        'özgün FPS/çözünürlük ayrıntısını veya bağımsız tarihsel doğrulamayı yaptığını iddia etme. '
        'Belirsizlik warning; açık hata error. Her hata sorumlu repair_stage içersin.'},
        media_inputs=media_inputs,**({'max_attempts':2,'max_output_tokens':3072,'repair_fields':True} if streaming else {}))
    if streaming:
        from .parallel_work import retry_inference
        review=schema.model_validate(retry_inference(request_review,check)).model_dump()
    else:review=schema.model_validate(request_review()).model_dump()
    if review.get('motion_windows'):
        from .preview import render_motion_windows
        target = render_motion_windows(folder,run.outputs['_editor_preview'],review['motion_windows'],check)
        motion_review = QualityReview.model_validate(decision_call(run_id, Evren().generate, QualityReview,'Video Editörü',{
            'initial_review':review,'original_timeline_windows':review['motion_windows'],
            'instruction':'Bu kısa video belirtilen gerçek zaman çizelgesi kesitlerinin birleşimidir. '
            'Yalnız bu kesitlerdeki hareket/geçiş sorunlarını incele; örnek dışı hareket veya ses doğrulaması iddia etme.'},
            media_inputs=[{'type':'video_url','video_url':{'url':'data:video/mp4;base64,'+
                base64.b64encode(target.read_bytes()).decode()}}])).model_dump()
        review['findings'] += motion_review['findings']
        review['motion_review'] = motion_review['summary']
    technical = {'passed':True,'issues':[]} if preview else run.outputs['editor']['report']
    findings = review['findings'] + [{'kind': 'technical', 'severity': 'error', 'scene_index': None,
        'start_frame': None, 'end_frame': None, 'evidence': issue, 'repair_stage': 'editor'}
        for issue in technical.get('issues', [])]
    return {**technical, **review, 'findings': findings,
        'passed': technical.get('passed', False) and not any(f['severity']=='error' for f in findings),
        'method': 'rendered_full_video_and_sampled_frames' if full_video_review else 'rendered_sampled_frames_full_audio' if streaming and audio_sampled else 'rendered_sampled_frames', 'sampled_frames': sorted(frames), 'requires_human_review': True}
