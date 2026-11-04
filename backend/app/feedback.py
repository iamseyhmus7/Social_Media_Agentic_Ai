"""Natural-language feedback produces immutable, dependency-aware revisions."""
from uuid import uuid4
from sqlalchemy import select
from fastapi import HTTPException
from .db import DB, Feedback, Run, Project, User, now
from .providers import Evren, QuotaExceeded, TransientProviderError
from .schemas import FeedbackDecision, Reedit
from .config import use_run_settings, snapshot_settings
from .orchestration import descendants


def edit_context(source):
    """Describe rendered layers separately from generated source footage."""
    import json
    from .storage import workdir
    path = workdir(source.project_id, source.id) / 'render-manifest.json'
    if not path.is_file() or path.stat().st_size > 4_000_000:
        return {'available': False}
    try:
        manifest = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'available': False}
    lookup = {s['shot_id'] + '.mp4': s.get('scene_index')
              for s in source.outputs.get('motion', {}).get('plan', {}).get('shots', [])}
    return {'available': True, 'timebase_fps': manifest.get('fps', 30),
        'segments': [{'segment_index': i, 'scene_index': c.get('scene_index', lookup.get(c.get('file'))),
            'source_file': c.get('file'), 'start_frame': c.get('start_frame'), 'frames': c.get('frames'),
            'render_layers': {k: c[k] for k in ('design', 'title', 'transition') if k in c}}
            for i, c in enumerate(manifest.get('clips', [])[:64])],
        'graphics': manifest.get('graphics', [])[:24],
        'source_observations': source.outputs.get('editor', {}).get('report', {}).get('content_review', {}).get('observations', [])[:64]}


def serialize(item):
    result = {k: getattr(item, k) for k in ('id', 'status', 'prompt', 'answer', 'decision', 'run_id', 'error', 'source_run_id')}
    result['decision'] = {k: v for k, v in item.decision.items() if not k.startswith('_')}
    return result


def resume_provider_waits(db):
    """Persist provider backoff without making an outage a clarification question."""
    for item in db.scalars(select(Feedback).where(Feedback.status == 'waiting_provider').with_for_update()):
        waiting = item.decision.get('_provider_wait', {})
        if waiting.get('deadline', 0) <= now():
            item.status = 'failed'
            item.error = 'Model hizmeti için otomatik bekleme süresi doldu. Değişiklik isteği uygulanamadı; mevcut video korundu.'
        elif waiting.get('retry_at', float('inf')) <= now():
            item.status = 'queued'


def source_check(db, project, user, source_id):
    source = db.get(Run, source_id)
    if not source or source.user_id != user.id or source.project_id != project.id:
        raise HTTPException(404, 'Kaynak video bulunamadı.')
    if source.revision != project.revision:
        raise HTTPException(409, 'Video sürümü değişti; güncel videoyu aç.')
    if db.scalar(select(Run.id).where(Run.user_id == user.id, Run.active_owner.is_not(None))):
        raise HTTPException(409, 'Aktif üretim tamamlandıktan sonra geri bildirim gönderebilirsin.')
    if not source.outputs.get('editor', {}).get('video'):
        raise HTTPException(409, 'Geri bildirim için önce bir video üretilmeli.')
    return source


def create_feedback(db, project, user, data):
    # Serialize concurrent feedback submissions for this account.
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    existing = db.scalar(select(Feedback).where(Feedback.user_id == user.id, Feedback.request_id == data.request_id))
    if existing:
        if existing.project_id != project.id or existing.prompt != data.prompt or existing.source_run_id != data.run_id:
            raise HTTPException(409, 'İstek kimliği farklı bir geri bildirimde kullanılmış.')
        return existing
    source_check(db, project, user, data.run_id)
    if db.scalar(select(Feedback.id).where(Feedback.user_id==user.id, Feedback.status.in_(['queued', 'waiting_quota']))):
        raise HTTPException(409, 'Önceki geri bildirimin değerlendirilmesini bekle.')
    # A new command replaces an older suspended interpretation of this video.
    # It must never become an answer to that request or create duplicate revisions.
    for pending in db.scalars(select(Feedback).where(Feedback.user_id == user.id,
            Feedback.source_run_id == data.run_id,
            Feedback.status.in_(['waiting_provider', 'needs_clarification'])).with_for_update()):
        pending.status = 'superseded'
    item = Feedback(id=str(uuid4()), user_id=user.id, project_id=project.id,
        source_run_id=data.run_id, request_id=data.request_id, prompt=data.prompt)
    db.add(item)
    db.commit()
    return item


def feedback_decision(source, prompt, answer='', previous_question=''):
    inputs = source.outputs
    current_edit = edit_context(source)
    with use_run_settings(inputs.get('_config', {})):
        result = FeedbackDecision.model_validate(Evren().generate(FeedbackDecision, 'Supervisor', {
            'feedback': prompt, 'clarification_answer': answer,
            'previous_question': previous_question,
            'script': inputs.get('script'), 'brief': inputs.get('supervisor'),
            'quality': inputs.get('quality'),
            'current_edit': current_edit,
            'instruction': 'Kullanıcının mevcut video için değişiklik isteğini yorumla. '
            'stages yalnızca doğrudan değişecek uzmanlar; bağımlılıkları kod ekler. '
            'Altyazı/kesme/geçiş=editor, anlatıcı=voice, görüntü=visual, kaynak hareket=motion, '
            'anlatılan bilgi=script veya strategy, paylaşım metni=publisher. Bunlar örnektir; anlamı değerlendir. '
            'Önce current_edit içinden değişecek öğenin kaynak klibe mi render katmanına mı ait olduğunu belirle. '
            'design/object_3d, grafik, yazı, yerleşim ve efekt Remotion katmanıdır; bunları kaldırmak/değiştirmek için editor seç. '
            'Render katmanı değişiminde visual veya motion seçme; mevcut kaynakları koru. '
            'visual yalnız kaynak resmin içeriği değişecekse, motion yalnız kaynak klibin hareketi değişecekse seç. '
            'Kaldır talebini yeni görsel veya nesne üretme talebine genişletme. İstenmeyen alanları koru. '
            'segment_index ile scene_index farklıdır; görünen planları zaman çizelgesindeki gerçek scene_index ile eşleştir. '
            'Belirsiz daha güzel olsun talebinde clarification ile kısa soru sor. Açık talepte soru sorma. '
            'scene_indices yalnız açıkça belirlenen sahneler (0 tabanlı); genel değişimde boş liste. '
            'Kullanıcı süre değişikliği istemediyse target_duration=null bırak. Süre değişiyorsa 30/45/60 değerlerinden birini ve script görevini seç. '
            'Desteklenmeyen açık süre talebinde veya belirsiz süre tercihinde kısa açıklama sor. '
            'instructions somut düzenleme yönergesi içersin. Birden fazla talebi birlikte değerlendir.'})).model_dump()
    return result


def process_feedback(feedback_id):
    with DB() as db:
        item = db.get(Feedback, feedback_id)
        if not item or item.status != 'queued':
            return
        source = db.get(Run, item.source_run_id)
        prompt, answer = item.prompt, item.answer
        inputs = source.outputs
    try:
        result = feedback_decision(source, prompt, answer, item.decision.get('clarification', ''))
        with DB() as db:
            item = db.scalar(select(Feedback).where(Feedback.id==feedback_id).with_for_update())
            if item.status != 'queued':
                return
            item.decision = result
            item.error = None
            if result['clarification']:
                item.status = 'needs_clarification'
                db.commit()
                return
            user = db.scalar(select(User).where(User.id==item.user_id).with_for_update())
            project = db.scalar(select(Project).where(Project.id==item.project_id).with_for_update())
            source_check(db, project, user, item.source_run_id)
            scenes = list(dict.fromkeys(result['scene_indices']))
            if any(i < 0 or i >= len(inputs['script']['scenes']) for i in scenes):
                raise RuntimeError('Geri bildirim geçersiz bir sahneye yönlendirildi.')
            from .reedit import create_reedit
            if result['target_duration'] is not None and result['target_duration'] != project.duration:
                project.duration = result['target_duration']
                result['stages'] = list(dict.fromkeys([*result['stages'], 'script']))
                result['scene_indices'] = []
                scenes = []
            removed = descendants(result['stages'])
            run = create_reedit(db, project, user, Reedit(run_id=item.source_run_id,
                instructions=result['instructions']), commit=False, preserve_editor='editor' not in removed)
            outputs = dict(run.outputs)
            for stage in ('voice', 'visual', 'motion'):
                if stage in removed:
                    outputs['_reuse_'+stage] = outputs[stage]
            if 'voice' in removed:
                from .audio_reuse import voice_config
                outputs['_reuse_voice_settings']={'config':voice_config(inputs.get('_config',{})),
                    'plan':inputs.get('_voice_plan') or inputs.get('voice',{}).get('selection')}
            if 'publisher' in result['stages']:
                outputs['_previous_copy']={k:v for k,v in inputs.get('publisher',{}).items()
                    if k in ('title','description','hashtags','instagram','tiktok')}
            outputs = {k: v for k, v in outputs.items() if k not in removed}
            # Old runs may not have a creative brief; the v3 Supervisor derives it.
            if 'visual_direction' not in outputs.get('supervisor', {}):
                outputs.pop('supervisor', None)
            elif result['target_duration'] is not None:
                outputs['supervisor'] = {**outputs['supervisor'], 'duration': result['target_duration']}
            if outputs.get('visual', {}).get('storyboard'):
                outputs['_storyboard'] = outputs['visual']['storyboard']
            if 'script' in removed:
                outputs.pop('_storyboard', None)
            outputs.update(_feedback={'prompt': prompt, **result}, _changed_scenes=scenes,
                _repair_stages=result['stages'], _edit_only=not bool(set(result['stages'])-{'editor','publisher'}),
                _config=snapshot_settings(), _requested_duration=project.duration, _previous_script=inputs['script'])
            from .audio_reuse import voice_config
            if ('voice' in result['stages'] or ('voice' in removed and
                    voice_config(inputs.get('_config',{}))!=voice_config(outputs['_config']))):
                for key in ('_voice_plan', '_voice_casting_state', 'voice_casting'):
                    outputs.pop(key, None)
            run.outputs, run.pipeline_version = outputs, 3
            item.status, item.run_id = 'applied', run.id
            db.commit()
    except TransientProviderError as exc:
        from .recovery import provider_wait
        with DB() as db:
            item = db.get(Feedback, feedback_id)
            if item.status != 'queued':
                return
            waiting = provider_wait(item.decision.get('_provider_wait', {}), 'feedback', exc)
            item.decision = {**item.decision, '_provider_wait': waiting}
            item.status = 'waiting_provider' if waiting['automatic'] else 'failed'
            item.error = 'Model hizmeti geçici olarak kullanılamıyor. İsteğin kaydedildi; değerlendirme otomatik devam edecek.' if waiting['automatic'] else 'Model hizmeti için otomatik bekleme süresi doldu. Mevcut video korundu.'
            db.commit()
    except QuotaExceeded as exc:
        with DB() as db:
            item = db.get(Feedback, feedback_id)
            item.status, item.error = 'waiting_quota', str(exc)
            db.commit()
    except Exception as exc:
        with DB() as db:
            item = db.get(Feedback, feedback_id)
            item.status = 'failed'
            item.error = str(exc) if isinstance(exc, (RuntimeError, HTTPException)) else 'Geri bildirim değerlendirmesi başarısız oldu.'
            db.commit()
