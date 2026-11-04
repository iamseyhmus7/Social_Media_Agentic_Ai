import json
import zipfile
import hashlib
import os
from typing import TypedDict
from pydantic import ValidationError
from langgraph.graph import StateGraph, START, END
from .db import DB, Run, Project, User, Event, Asset, now
from . import media
from .providers import Evren, research, QuotaExceeded, trace_calls
from .schemas import Plan, Strategy, Script, StoryScript, Copy, PublicationCopy, script_with_word_target, timed_story_script
from .agents import LABELS, LEGACY_STAGES, STAGES as V2_STAGES
from .config import settings, use_run_settings
from .kaggle_provider import RemotePending
from .storage import workdir, register, media_path, check_disk, file_hash

STAGES = LEGACY_STAGES


class State(TypedDict):
    run_id: str
    next_stage: str


def checkpoint(run_id, stage, value, *, extra_outputs=None):
    with DB() as db:
        run = db.get(Run, run_id)
        run.outputs = {**run.outputs, **(extra_outputs or {}), stage: value}
        if run.outputs.get('_provider_wait',{}).get('stage') == stage:
            from .recovery import initial
            recovery=initial(run.outputs)
            recovery['provider']={**recovery.get('provider',{}),'status':'resolved','automatic':False,'retry_at':None}
            run.outputs={**run.outputs,'_provider_wait':{},'_recovery':recovery}
        run.updated = now()
        db.add(Event(run_id=run_id, stage=stage, message=LABELS[stage] + ' tamamlandı.'))
        db.commit()


def read(run_id):
    with DB() as db:
        run = db.get(Run, run_id)
        project = db.get(Project, run.project_id)
        user = db.get(User, run.user_id)
        return run, project, user


def cancellation(run_id):
    with DB() as db:
        run = db.get(Run, run_id)
        if not run or run.cancel_requested:
            raise media.Cancelled('Üretim kullanıcı tarafından durduruldu.')
        project = db.get(Project, run.project_id)
        if not project or run.revision != project.revision:
            raise media.Cancelled('Eski sürüme ait üretim sonucu kullanılmadı.')


def asset_path(asset_id):
    with DB() as db:
        return media_path(db.get(Asset, asset_id).path)


def run_stage(run_id, stage, *, preview_only=False):
    cancellation(run_id)
    run, project, user = read(run_id)
    if stage in run.outputs:
        # Cached stage outputs are durable checkpoints, not in-memory chat history.
        return
    if run.outputs.get('_script_only') and stage not in ('supervisor', 'strategy', 'script'):
        from .orchestration import NeedsInput
        raise NeedsInput('Yalnız senaryo üretiminde medya aşamaları çalıştırılamaz.')
    with DB() as db:
        current = db.get(Run, run_id)
        current.stage, current.updated = stage, now()
        db.add(Event(run_id=run_id, stage=stage, message=LABELS[stage] + ' çalışıyor.'))
        db.commit()
    accepted_plan_updates = {}
    brand = run.outputs.get('_brand', user.brand)
    context = {'topic': project.topic, 'audience': project.audience, 'tone': project.tone, 'duration_seconds': project.duration, 'brand': brand, 'creative_brief': run.outputs.get('supervisor'), 'feedback': run.outputs.get('_feedback'), 'completed': {k:v for k,v in run.outputs.items() if not k.startswith('_')}}
    if run.outputs.get('_config', {}).get('video_execution_policy') == 'planned_v1':
        needed = {'strategy':(), 'script':('strategy',), 'voice':('script',), 'visual':('script',),
                  'motion':('script',), 'editor':('script',), 'publisher':('strategy', 'script')}
        context['completed'] = {k:run.outputs[k] for k in needed.get(stage, ()) if k in run.outputs}
    if run.outputs.get('_previous_script'):
        context['previous_script'] = run.outputs['_previous_script']
    folder = workdir(project.id, run.id)
    check = lambda: cancellation(run_id)
    if run.pipeline_version >= 3:
        class MeteredEvren(Evren):
            def generate(self, *args, **kwargs):
                from .orchestration import decision_call
                return decision_call(run_id, super().generate, *args, **kwargs)
        llm = MeteredEvren()
    else:
        llm = Evren()
    if stage == 'supervisor':
        value = llm.generate(Plan, 'Supervisor', context)
    elif stage == 'strategy':
        from .orchestration import mutate
        from .script_editorial import AUTHORITY
        sources = run.outputs.get('_strategy_research')
        if sources is None:
            sources = research(project.topic)
            mutate(run_id, {'_strategy_research':sources})
        if run.outputs.get('_config', {}).get('script_editorial_policy',0) >= 2:
            from .providers import research_story
            direction = (context.get('creative_brief') or {}).get('editorial_direction',{})
            story_sources = run.outputs.get('_story_research')
            if not settings().story_research_enabled:
                from .script_editorial import MODEL_KNOWLEDGE
                story_sources = {'sources':[], 'verification_scope':'model_knowledge_only', 'notice':'Dış kaynak araştırması yapılmadı; içerik LLM bilgisiyle hazırlanır.'}
                mutate(run_id, {'_story_research':story_sources})
                context['knowledge_policy'] = MODEL_KNOWLEDGE
            if story_sources is None:
                story_sources = research_story(direction.get('research_query','')) if direction.get('evidence_required') else {'sources':[], 'verification_scope':'fiction_or_nonfactual_content'}
                if story_sources.get('sources') or not direction.get('evidence_required'):
                    mutate(run_id, {'_story_research':story_sources})
            if settings().story_research_enabled and direction.get('evidence_required') and not story_sources.get('sources'):
                from .providers import ProviderError
                raise ProviderError('Supervisor kaynaklı olgusal anlatım istedi; kaynak metni alınamadı. Kaynak erişimi sağlandıktan sonra yeniden dene. Medya üretimi başlamadı.')
            sources = {**sources, 'evidence_sources':[{k:v for k,v in source.items() if k!='text'} for source in story_sources.get('sources',[])], 'verification_scope':story_sources.get('verification_scope')}
            context.update(authority=AUTHORITY, story_research=story_sources,
                instructions='Ortak planı uygula; plan değişikliğini tek başına yürürlüğe koyma. Ana merakı ve somut anlatı açısını geliştir. Açılışta sorulan soruya kapanışın gerçekten cevap verdiğini değerlendir; başka sorunun cevabını yerine koyma. Süreyi dağıtan yan konuyu büyütme. Eksik veya yanıltıcı varsayımı plan_revision_proposals içinde gerekçelendir; onayı supervisora bırak. Şüpheli ayrıntıyı daha kesin veya daha iddialı başlıkla büyütme. knowledge_policy uygula; başlığı kanıt sayma. Kapanışa yeni iddia veya slogan ekleme. Talimatları ve araştırma notlarını anlatıya taşıma.')
        value = {**llm.generate(Strategy, 'İçerik Stratejisti', {**context, 'research': sources}), 'research': sources}
        with DB() as db:
            db.get(Project, project.id).title = value['title']
            db.commit()
    elif stage == 'script':
        automatic = run.outputs.get('_edit_style') == 'auto'
        if automatic:
            context = {**context, 'format_guidance': 'Kullanıcı isteği ve yaratıcı brief için uygun formatı seç: reklam, anlatı, eğitim, belgesel, seyahat, eğlence, açıklayıcı veya other. Türler hazır kurgu şablonu değildir. Tarihsel iddiayı, ürün vaadini veya kaynağı uydurma. Görsel promptlarında basılı metin üretme; metni editör ekler. Geri bildirim varsa istenmeyen sahne değişikliklerinden kaçın.'}
        from .engagement import engaging_script, INSTRUCTION
        script_schema = StoryScript if automatic else Script
        if run.outputs.get('_config',{}).get('engagement_policy',0):
            script_schema = engaging_script(script_schema)
            context = {**context, 'mandatory_engagement': INSTRUCTION}
        script_instructions = f'Türkçe konuşma için yaklaşık {round(min(59, max(31, project.duration)) * 2.2)} kelime hedefle. Görsel promptları İngilizce, tutarlı sinematik stilde ve yalnızca 9:16 dikey kadraj için yaz. Sahne başlıkları Türkçe olsun. ' + ('İçeriğe uygun format seç. 30 saniyede 5–6, 45–60 saniyede 7–8 kısa olay adımı oluştur. Hikâyede neden-sonuç, görünür karakter/nesne eylemleri ve anlamlı sonuç olsun. continuity içinde karakterin değişmeyen fiziksel görünüşünü/kıyafetini, mekânı, nesneleri ve görsel dili İngilizce tanımla. Her sahnenin action, state_before ve state_after alanlarını doldur. İlk anlatım doğrudan olayın içine girsin. Zorunlu hook yönergelerini uygula; son sahnede anlamlı kapanış yaz. Otomatik beğeni veya takip çağrısı ekleme.' if automatic else 'Hook ilk sahnenin anlatımında yer alsın. Son sahnede anlamlı kapanış yaz; otomatik beğeni veya takip çağrısı ekleme.')
        policy = run.outputs.get('_config', {}).get('script_editorial_policy', 0)
        if policy >= 2 and not run.outputs.get('_previous_script'):
            from .script_editorial import generate_editorial_script_v2
            from .orchestration import mutate
            context['story_research'] = (run.outputs.get('_story_research', {}) if settings().story_research_enabled else {'sources':[], 'verification_scope':'model_knowledge_only'})
            # scene_count belongs to supervisor; remove the old competing generic quota.
            script_instructions = script_instructions.replace('30 saniyede 5–6, 45–60 saniyede 7–8 kısa olay adımı oluştur.', 'Supervisor editorial_direction.scene_count sayısını aynen uygula.')
            value, audit = generate_editorial_script_v2(llm, script_schema, context, script_instructions,
                progress=run.outputs.get('_script_editorial'),
                save=lambda progress:mutate(run_id, {'_script_editorial':progress}))
            actual_count = len(value['scenes'])
            planned = context['creative_brief']['editorial_direction']
            accepted_direction = {**planned, **audit.get('accepted_editorial_direction', {}), 'scene_count':actual_count}
            changed_plan_fields = [key for key in accepted_direction if accepted_direction[key] != planned.get(key)]
            if changed_plan_fields:
                accepted_plan_updates = {
                    'supervisor':{**context['creative_brief'], 'editorial_direction':accepted_direction},
                    '_supervisor_plan_updates':[*run.outputs.get('_supervisor_plan_updates', []), *[{
                        'field':key,'previous':planned.get(key),'accepted':accepted_direction[key],
                        'reason':audit['reviews'][-1]['reason']} for key in changed_plan_fields]][-20:]}
        elif policy and not run.outputs.get('_previous_script'):
            from .script_editorial import generate_editorial_script
            value, audit = generate_editorial_script(llm, script_schema, context, script_instructions)
            from .orchestration import mutate
            mutate(run_id, {'_script_editorial': audit})
        else:
            from .script_editorial import SPOKEN_STANDARD
            value = llm.generate(script_schema, 'Senaryo Yazarı', {**context, 'spoken_standard': SPOKEN_STANDARD, 'instructions': script_instructions})
        previous, changed = run.outputs.get('_previous_script'), run.outputs.get('_changed_scenes', [])
        if previous and changed:
            if len(value['scenes']) != len(previous['scenes']):
                raise RuntimeError('Hedefli senaryo revizyonu sahne sayısını korumalı.')
            value['scenes'] = [s if i in changed else previous['scenes'][i] for i,s in enumerate(value['scenes'])]
            value = (StoryScript if automatic else Script).model_validate(value).model_dump()
    elif stage == 'visual':
        images = []
        scenes = run.outputs['script']['scenes']
        board = None
        if run.outputs.get('_edit_style') == 'auto':
            from .storyboard import direct_story, revise_storyboard
            board = run.outputs.get('_storyboard')
            if not board:
                from .storyboard import retime_storyboard
                previous = run.outputs.get('_reuse_visual', {}).get('storyboard')
                if previous and set(run.outputs.get('_repair_stages', [])) & {'visual', 'motion'}:
                    board = revise_storyboard(llm, previous, run.outputs['script'], run.outputs['voice']['durations'],
                        run.outputs.get('_changed_scenes', []), run.outputs.get('_feedback', {}), run.outputs.get('quality', {}))
                board = board or (retime_storyboard(previous, run.outputs['voice']['durations']) if previous and 'script' not in run.outputs.get('_repair_stages', []) else None)
                board = board or direct_story(llm, run.outputs['script'], run.outputs['voice']['durations'], handles=run.pipeline_version>=3, context=context if run.pipeline_version>=3 else None)
                with DB() as db:
                    current = db.get(Run, run_id)
                    current.outputs = {**current.outputs, '_storyboard': board}
                    db.commit()
            scenes = [{'visual_prompt': s['reference_prompt']} for s in board['shots']]
        from .orchestration import mutate
        progress={'completed':0,'total':len(scenes),'unit':'shots' if board else 'scenes','scene_images':{}}
        mutate(run_id,{'_visual_progress':progress})
        def image_ready(index, ident):
            scene_index=board['shots'][index]['scene_index'] if board else index
            progress['scene_images'].setdefault(str(scene_index),ident)
            progress['completed']=index+1
            mutate(run_id,{'_visual_progress':progress})
        for i, scene in enumerate(scenes):
            check_disk()
            target = folder / f'scene-{i}.png'
            if board and run.pipeline_version >= 3:
                previous = run.outputs.get('_reuse_visual', {})
                old = next((s for s in previous.get('storyboard', {}).get('shots', []) if s['shot_id']==board['shots'][i]['shot_id']), None)
                current = board['shots'][i]
                changed = run.outputs.get('_changed_scenes', [])
                force = 'visual' in run.outputs.get('_repair_stages', []) and (not changed or current['scene_index'] in changed)
                if old and old['reference_prompt']==current['reference_prompt'] and not force:
                    ident = previous.get('shot_images', {}).get(current['shot_id'])
                    if ident:
                        images.append(ident)
                        image_ready(i,ident)
                        continue
            # A complete file + journal permits retry within an interrupted stage.
            journal = folder / f'scene-{i}.complete'
            if not target.exists() or not journal.exists():
                prompt = scene['visual_prompt'].replace('16:9', '9:16 vertical')
                color_hint = '' if board else f", coherent color palette {brand.get('color', '#7645ed')}"
                media.image(prompt + ', vertical portrait framing, keep subject centrally composed' + color_hint, target, check)
                journal.write_text('complete')
            with DB() as db:
                asset_id = register(db, run, target, 'image')
                db.add(Event(run_id=run.id, stage=stage, message=f'Görsel hazır: {i+1} / {len(scenes)}'))
                db.commit()
            images.append(asset_id)
            image_ready(i,asset_id)
        target = folder / 'cover.png'
        media.cover(asset_path(images[0]), project.title, target, brand)
        with DB() as db:
            cover_id = register(db, run, target, 'cover')
        value = {'images': images, 'cover': cover_id}
        if board:
            value['shot_images'] = dict(zip((s['shot_id'] for s in board['shots']), images))
            value['images'] = [images[next(j for j, s in enumerate(board['shots']) if s['scene_index'] == i)] for i in range(len(run.outputs['script']['scenes']))]
            value['storyboard'] = board
    elif stage == 'voice':
        from .voice_selection import select_voice
        voice_plan = select_voice(run_id, context, llm, check)
        from .audio_reuse import input_key, reusable_audio
        audios, durations, input_keys = [], [], []
        for i, scene in enumerate(run.outputs['script']['scenes']):
            check()
            identity=input_key(scene['narration'],settings(),voice_plan)
            input_keys.append(identity)
            reused=reusable_audio(run.outputs,i,identity)
            if reused:
                with DB() as db:
                    asset=db.get(Asset,reused[0])
                    source=media_path(asset.path) if asset else None
                    verified=source is not None and source.is_file() and file_hash(source)==asset.sha256
                if verified:
                    audios.append(reused[0]);durations.append(reused[1])
                    continue
            target = folder / (f'voice-{i}-{identity[:16]}.wav' if run.outputs.get('_recovery',{}).get('version') == 1 else f'voice-{i}.wav')
            legacy_identity = hashlib.sha256(json.dumps({'text': scene['narration'], 'provider': settings().tts_provider, 'model': settings().elevenlabs_model, 'voice': voice_plan or settings().elevenlabs_voice_id}, sort_keys=True).encode()).hexdigest()
            journal = target.with_suffix('.complete.json')
            saved = json.loads(journal.read_text()) if journal.is_file() else {}
            if target.is_file() and saved.get('input') in (identity,legacy_identity) and saved.get('sha256') == file_hash(target):
                duration = saved['duration']
            else:
                duration = media.voice(scene['narration'], target, check, voice_plan=voice_plan)
                journal.write_text(json.dumps({'input': identity, 'sha256': file_hash(target), 'duration': duration}))
            with DB() as db:
                asset_id = register(db, run, target, 'audio')
            audios.append(asset_id)
            durations.append(duration)
        value = {'audios': audios, 'durations': durations, 'duration': sum(durations), 'provider': settings().tts_provider,
                 'input_keys':input_keys,'reused_count':sum(ident in run.outputs.get('_reuse_voice',{}).get('audios',[]) for ident in audios)}
        value['generated_count']=len(audios)-value['reused_count']
        if voice_plan:
            value['selection'] = voice_plan
    elif stage == 'motion':
        if settings().video_provider == 'none':
            value = {'mode': 'image', 'clips': []}
        elif settings().video_provider == 'kaggle':
            from .kaggle_provider import generate_clips, ENGINE_REVISION
            from .motion import create_motion_plan
            plan = run.outputs.get('_motion_plan')
            if not plan:
                plan = run.outputs['visual'].get('storyboard') or create_motion_plan(llm, context, run.outputs['voice']['durations'], [asset_path(i) for i in run.outputs['visual']['images']])
                if run.pipeline_version>=3 and 'motion' in run.outputs.get('_repair_stages', []) and 'visual' not in run.outputs.get('_repair_stages', []) and all('reference_prompt' in shot for shot in plan['shots']):
                    from .storyboard import revise_storyboard
                    revised = revise_storyboard(llm, plan, run.outputs['script'], run.outputs['voice']['durations'],
                        run.outputs.get('_changed_scenes', []), run.outputs.get('_feedback', {}), run.outputs.get('_last_quality', {}))
                    if revised:
                        refs = {s['shot_id']:s['reference_prompt'] for s in plan['shots']}
                        plan = {'shots': [{**s, 'reference_prompt': refs[s['shot_id']]} for s in revised['shots']]}
                from .gpu_profile import selected_profile
                profile = selected_profile()
                with DB() as db:
                    current = db.get(Run, run_id)
                    current.outputs = {**current.outputs, '_motion_profile':profile, '_motion_plan': plan, '_motion_engine': ENGINE_REVISION}
                    db.commit()
                run.outputs = {**run.outputs, '_motion_profile':profile, '_motion_plan': plan, '_motion_engine': ENGINE_REVISION}
            reference_ids = ([run.outputs['visual']['shot_images'][s['shot_id']] for s in plan['shots']]
                             if run.outputs['visual'].get('shot_images') else run.outputs['visual']['images'])
            if run.pipeline_version >= 3:
                from .motion import generate_missing_clips
                if not run.outputs['visual'].get('shot_images'):
                    reference_ids = [run.outputs['visual']['images'][s['scene_index']] for s in plan['shots']]
                clips = generate_missing_clips(run, folder, plan, reference_ids, check)
            else:
                clips = generate_clips(run, folder, plan, [asset_path(i) for i in reference_ids], check)
            with DB() as db:
                for shot in plan['shots']:
                    item = clips[shot['shot_id']]
                    item['asset_id'] = register(db, run, folder / item['file'], 'clip')
            value = {'mode': 'video', 'provider': 'kaggle', 'model': 'LTX-Video 2B distilled 0.9.6', 'plan': plan, 'clips': clips, 'content_review': 'Hareket planı ve dosyalar doğrulandı. Görsel tutarlılık ve içerik doğruluğu kullanıcı incelemesini bekler.'}
        else:
            raise RuntimeError('VIDEO_PROVIDER none veya kaggle olmalı.')
    elif stage == 'editor':
        images = [asset_path(i) for i in run.outputs['visual']['images']]
        audios = [asset_path(i) for i in run.outputs['voice']['audios']]
        durations = run.outputs['voice']['durations']
        srt = folder / 'captions.srt'
        count = media.subtitles(audios, durations, srt, check)
        music = str(asset_path(project.music_asset)) if project.music_asset else None
        if run.pipeline_version >= 2 and settings().editor_provider == 'remotion':
            from .remotion_renderer import render_production
            report = render_production(run, project, folder, images, audios, durations, srt, check, llm, context, music, brand, preview_only=preview_only)
            if preview_only:
                from .orchestration import mutate
                mutate(run_id, {'_editor_preview': report}, 'Kurgu önizlemesi hazırlandı.', 'editor')
                return
        elif run.pipeline_version >= 2 and settings().video_provider == 'kaggle' and not run.outputs.get('_edit_only') and not run.outputs.get('_script_only'):
            raise RuntimeError('Hareketli üretim için EDITOR_PROVIDER=remotion yapılandırılmalı.')
        else:
            report = media.render(folder, images, audios, durations, srt, check, music, brand)
        with DB() as db:
            video_id = register(db, run, folder / 'video.mp4', 'video')
            captions_id = register(db, run, srt, 'subtitle')
        value = {'video': video_id, 'subtitle': captions_id, 'caption_count': count, 'report': report, 'provider': settings().editor_provider if run.pipeline_version >= 2 else 'ffmpeg'}
    elif stage == 'quality':
        report = run.outputs['editor']['report']
        value = report
    elif stage == 'publisher':
        from .human_review import enabled as human_review_enabled
        if 'publisher' in run.outputs.get('_feedback',{}).get('stages',[]):
            value=PublicationCopy.model_validate(llm.generate(PublicationCopy,'Yayıncı',{
                'topic':project.topic,'script':run.outputs['script'],
                'previous_copy':run.outputs.get('_previous_copy',{}),'feedback':run.outputs['_feedback'],
                'instruction':'Kullanıcının paylaşım metni değişikliğini uygula; değişmesi istenmeyen alanları koru. '
                'Yeni olgusal iddia ekleme. Etiket istenmiyorsa hashtags boş liste olabilir. '
                'Bu görev yalnız paylaşım metnini düzenler; videoyu yeniden üretme veya yayınlama.'},repair_fields=True)).model_dump()
            value.update(method='user_requested_copy_revision',requires_human_review=True)
        elif human_review_enabled(run):
            narration = ' '.join(s['narration'] for s in run.outputs['script']['scenes'])
            value = {'title': project.title[:100], 'description': narration[:4500],
                     'hashtags': [], 'instagram': narration[:2000], 'tiktok': narration[:2000],
                     'method': 'existing_content_package', 'requires_human_review': True}
        else:
            value = llm.generate(Copy, 'Yayıncı', {k: v for k, v in context.items() if k != 'completed'} | {'script': run.outputs['script'], 'strategy': run.outputs.get('strategy', {}), 'instruction': 'Yalnızca bu videonun paylaşım metinlerini hazırla. Kısa ve somut yaz.'})
        if run.outputs.get('_edit_style') == 'auto':
            from .editorial_graphics import brief_sources, append_references
            value['description'] = append_references(value['description'], brief_sources(project.topic))
        package = folder / 'share-package.zip'
        metadata = folder / 'publication.json'
        metadata.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        with zipfile.ZipFile(package, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(asset_path(run.outputs['editor']['video']), 'video.mp4')
            archive.write(asset_path(run.outputs['editor']['subtitle']), 'captions.srt')
            archive.write(asset_path(run.outputs['visual']['cover']), 'cover.png')
            archive.write(metadata, 'publication.json')
        with DB() as db:
            value['package'] = register(db, run, package, 'package')
    else:
        raise RuntimeError('Bilinmeyen görev.')
    check()
    if accepted_plan_updates:
        checkpoint(run_id, stage, value, extra_outputs=accepted_plan_updates)
    else:
        checkpoint(run_id, stage, value)


def build_graph(version=1):
    if version >= 3:
        from .orchestration import build_agent_graph
        return build_agent_graph()
    stages = V2_STAGES if version >= 2 else STAGES
    graph = StateGraph(State)
    for stage in stages:
        def node(state, _stage=stage):
            run_stage(state['run_id'], _stage)
            return state
        graph.add_node(stage, node)
    graph.add_edge(START, stages[0])
    links = [('supervisor', 'strategy'), ('strategy', 'script'), ('script', 'voice'), ('editor', 'quality')]
    links += [('visual', 'motion'), ('motion', 'editor')] if version >= 2 else [('visual', 'editor')]
    for a, b in links:
        graph.add_edge(a, b)

    def route_voice(state):
        run, project, _ = read(state['run_id'])
        duration = run.outputs['voice'].get('duration', 45)
        # A sub-50 ms boundary overrun can be codec padding, not excess speech.
        # Keep originals and journals intact; accept only measured silent tails.
        excess = duration - (project.duration + 2)
        if version >= 2 and 0 < excess <= .050001 and 'visual' not in run.outputs and 'editor' not in run.outputs:
            voice = run.outputs['voice']
            for index, identifier in enumerate(voice.get('audios', [])):
                cancellation(run.id)
                source = asset_path(identifier)
                fitted = source.with_name(source.stem + '-boundary.wav')
                measured = media.trim_silent_tail(source, fitted, excess + .05)
                if measured is None:
                    continue
                audios, durations = list(voice['audios']), list(voice['durations'])
                removed = durations[index] - measured
                durations[index] = measured
                with DB() as db:
                    audios[index] = register(db, db.get(Run, run.id), fitted, 'audio')
                updated_voice = {**voice, 'audios': audios, 'durations': durations, 'duration': sum(durations),
                                 'boundary_padding_removed_seconds': removed}
                checkpoint(run.id, 'voice', updated_voice)
                with DB() as db:
                    current = db.get(Run, run.id)
                    current.outputs = {k: v for k, v in current.outputs.items() if k != 'quality'}
                    db.add(Event(run_id=run.id, stage='voice', message=f'Sınır aşımı giderildi: yalnızca {removed:.3f} saniye dosya sonu sessizliği kaldırıldı; anlatım hızı korundu.'))
                    db.commit()
                duration = updated_voice['duration']
                break
        if 30 <= duration <= 60 and (version < 2 or abs(duration - project.duration) <= 2):
            return 'visual'
        if run.outputs.get('_edit_only'):
            raise RuntimeError('Kaynak anlatım hedef süreye uymuyor; ses ve klipler değiştirilmedi.')
        checkpoint(run.id, 'quality', {'passed': False, 'duration': duration, 'issues': [f'Anlatım süresi {duration:.3f} saniye. Hedef {project.duration} saniye; tolerans ±2 saniye, toplam sınır 30–60 saniye.']})
        return 'repair'

    def route_quality(state):
        run, _, _ = read(state['run_id'])
        from .human_review import enabled as human_review_enabled
        if human_review_enabled(run) and not run.outputs['quality']['passed']:
            raise RuntimeError('Video teknik kontrolden geçmedi; içerik otomatik yeniden üretilmedi. ' + ' '.join(run.outputs['quality'].get('issues', [])))
        if run.outputs.get('_edit_only') and not run.outputs['quality']['passed']:
            raise RuntimeError('Yeni kurgu teknik kontrolden geçmedi. Kaynak ses ve klipler korunuyor; otomatik GPU üretimi yapılmadı. ' + ' '.join(run.outputs['quality'].get('issues', [])))
        return 'publisher' if run.outputs['quality']['passed'] else 'repair'

    def repair(state):
        run, project, user = read(state['run_id'])
        attempts = run.outputs.get('_repair_attempts', 0)
        report = run.outputs.get('quality', {})
        if attempts >= 1:
            raise RuntimeError('Supervisor bir otomatik revizyon denedi ancak kalite kontrolü geçilemedi: ' + ' '.join(report.get('issues', [])))
        with DB() as db:
            current = db.get(Run, run.id)
            current.stage, current.updated = 'supervisor', now()
            db.add(Event(run_id=run.id, stage='supervisor', message='Ölçülen ses süresine göre tek senaryo revizyonu hazırlanıyor.'))
            db.commit()
        words = sum(len(s['narration'].split()) for s in run.outputs['script']['scenes'])
        aim = min(59, max(31, project.duration))
        measured = max(1, run.outputs.get('voice', {}).get('duration', project.duration))
        target_words = round(words * aim / measured)
        revised = Evren().generate(timed_story_script(target_words) if run.outputs.get('_edit_style') == 'auto' else script_with_word_target(target_words), 'Supervisor / Senaryo revizyonu', {'topic': project.topic, 'script': run.outputs['script'], 'quality_report': report, 'target_seconds': project.duration, 'measured_seconds': measured, 'current_narration_words': words, 'required_narration_words': target_words, 'instruction': f'Toplam sahne anlatımı yaklaşık {target_words} kelime olmalı (±2 kelime). Mevcut anlatım {words} kelime ile {measured:.2f} saniye sürdü. Aynı anlatıcıyla {aim} saniyeye ulaşmak için gerçek bilgi veya betimleme ekleyerek kelime sayısını bu hedefe getir; sadece kelimeleri eşanlamlılarıyla değiştirme. Görsel yönergeleri 9:16 dikey olmalı. Olayları, karakteri, sahne sayısını ve varsa action/state_before/state_after/continuity alanlarını koru; yalnızca anlatım uzunluğunu düzelt. Hikâyede reklam CTA ekleme.'})
        folder = workdir(project.id, run.id)
        # Only stage completion markers are invalidated. No media directory deletion.
        for marker in folder.glob('scene-*.complete'):
            marker.unlink()
        with DB() as db:
            current = db.get(Run, run.id)
            current.outputs = {**{k: v for k, v in current.outputs.items() if k in ('supervisor', 'strategy', '_config', '_brand', '_voice_plan', '_voice_casting_state', 'voice_casting', '_motion_session', '_edit_style')}, 'script': revised, '_repair_attempts': attempts + 1}
            db.add(Event(run_id=run.id, stage='supervisor', message='Kalite sonucu üzerine bir otomatik senaryo revizyonu başlatıldı.'))
            db.commit()
        return state

    graph.add_node('repair', repair)
    graph.add_conditional_edges('voice', route_voice, {'visual': 'visual', 'repair': 'repair'})
    graph.add_conditional_edges('quality', route_quality, {'publisher': 'publisher', 'repair': 'repair'})
    graph.add_edge('repair', 'voice')
    graph.add_edge(stages[-1], END)
    return graph.compile()


def save_model_metric(run_id, metric):
    from .parallel_work import run_write_lock
    from sqlalchemy import select
    with run_write_lock, DB() as db:
        current = db.scalar(select(Run).where(Run.id==run_id).with_for_update())
        current.outputs = {**current.outputs, '_model_metrics':
            (current.outputs.get('_model_metrics', []) + [{**metric, 'stage':current.stage}])[-500:]}
        waiting=current.outputs.get('_provider_wait',{})
        if (metric.get('status')=='passed' and waiting.get('stage')==current.stage
                and (not waiting.get('model') or waiting['model']==metric.get('model'))):
            from .recovery import initial
            recovery=initial(current.outputs)
            recovery['provider']={**recovery.get('provider',{}),'status':'resolved','automatic':False,'retry_at':None}
            current.outputs={**current.outputs,'_provider_wait':{},'_recovery':recovery}
        db.commit()


def execute(run_id):
    diagnostic = None
    with DB() as db:
        run = db.get(Run, run_id)
        if not run or run.status != 'queued':
            return
        run.status, run.updated, run.error = 'running', now(), None
        run.outputs = {**run.outputs, '_worker_runtime': {
            'pid': os.getpid(), 'pipeline_code': hashlib.sha256(execute.__code__.co_code).hexdigest()[:16],
            'validation_diagnostics': 'validation_failure' in execute.__code__.co_names,
            'started': now()}}
        run.started = run.started or now()
        db.commit()
    try:
        check_disk()
        from .recovery import ensure, task_budget
        ensure(run_id)
        with use_run_settings(run.outputs.get('_config', {})), trace_calls(lambda metric: save_model_metric(run_id, metric), check_cancel=lambda: cancellation(run_id), budget=lambda key,op:task_budget(run_id,key,op)):
            if run.pipeline_version >= 2 and settings().video_provider == 'kaggle' and not run.outputs.get('_edit_only') and not run.outputs.get('_script_only'):
                from .kaggle_provider import configured
                if not configured():
                    raise RuntimeError('Kaggle kimliği yapılandırılmadı. KAGGLE_USERNAME ve KAGGLE_API_TOKEN sunucuda gerekli.')
            build_graph(run.pipeline_version).invoke({'run_id': run_id}, config={'recursion_limit': 200 if run.pipeline_version >= 3 else 40})
        status, error = 'awaiting_approval', None
    except RemotePending:
        status, error = 'waiting_remote', None
    except media.Cancelled as exc:
        status, error = 'cancelled', str(exc)
    except QuotaExceeded as exc:
        status, error = 'waiting_quota', str(exc)
    except (ImportError, ModuleNotFoundError) as exc:
        status, error = 'failed', 'Yerel medya bağımlılığı eksik: ' + (exc.name or 'bilinmiyor') + '. requirements-media.txt kurulmalı.'
    except ValidationError as exc:
        from .diagnostics import validation_failure, failure_message
        with DB() as db:
            failure_stage = db.get(Run, run_id).stage
        diagnostic = validation_failure(exc, failure_stage)
        status, error = 'failed', failure_message(diagnostic)
    except Exception as exc:
        # Credentials/provider bodies are never exposed as traceback or API errors.
        from .orchestration import NeedsInput
        from .providers import TransientProviderError, InvalidModelOutput
        if isinstance(exc,TransientProviderError):
            status='waiting_provider'
            with DB() as db:
                current=db.get(Run,run_id)
                previous=current.outputs.get('_provider_wait',{})
                from .recovery import provider_wait, initial
                waiting=provider_wait(previous,current.stage,exc)
                recovery=initial(current.outputs)
                recovery.update(active='provider',provider={'kind':'service_unavailable','action':'wait',**waiting})
                current.outputs={**current.outputs,'_provider_wait':waiting,'_recovery':recovery}
                db.commit()
        elif isinstance(exc, NeedsInput) and run.outputs.get('_script_only'):
            with DB() as db:
                completed = db.get(Run, run_id)
                script_ready = bool(completed.outputs.get('script'))
            status = 'script_ready' if script_ready else 'waiting_input'
        elif isinstance(exc,InvalidModelOutput):
            status='failed'
            from .recovery import update
            update(run_id,'model_output',{'kind':'invalid_output','action':'retry','status':'exhausted','remaining':0,
                'task_key':getattr(exc,'task_key',None)})
        else:
            status = 'waiting_input' if isinstance(exc, NeedsInput) else 'failed'
        error = None if status == 'script_ready' else str(exc) if isinstance(exc, RuntimeError) else f'Üretim sırasında beklenmeyen hata ({type(exc).__name__}); tamamlanan aşamalar korundu.'
    with DB() as db:
        run = db.get(Run, run_id)
        run.status, run.error, run.updated = status, error, now()
        if diagnostic:
            from .diagnostics import log_failure
            diagnostic['created'] = now()
            run.outputs = {**run.outputs, '_diagnostics': [*run.outputs.get('_diagnostics', []), diagnostic][-20:]}
            log_failure(run_id, diagnostic)
        if status == 'script_ready':
            run.stage = 'script'
        if status not in ('waiting_remote','waiting_provider'):
            run.active_owner = None
            run.finished = now()
        elif status=='waiting_provider':
            run.finished=None
        db.add(Event(run_id=run_id, stage=run.stage, message=error or ('Senaryo hazır; seçimin gereği ses ve görsel üretimi yapılmadı.' if status == 'script_ready' else 'Kaggle işi takip ediliyor; sonuç hazır olduğunda üretim otomatik devam edecek.' if status == 'waiting_remote' else 'Video inceleme ve yayın onayı için hazır.')))
        db.commit()

