"""Only validated decisions and private, local assets reach the renderer."""
import json
import re
import shutil
import unicodedata
from difflib import SequenceMatcher
from .config import settings
from .schemas import EditPlan, DynamicEditPlan, EditorialEditPlan, RenderManifest, CaptionWord
from . import media
from .storage import media_path


def caption_items(srt):
    def seconds(value):
        h, m, s = value.replace(',', '.').split(':')
        return int(h) * 3600 + int(m) * 60 + float(s)
    items = []
    for block in re.split(r'\n\s*\n', srt.read_text(encoding='utf-8').strip()):
        lines = block.splitlines()
        if len(lines) >= 3 and ' --> ' in lines[1]:
            start, end = lines[1].split(' --> ')
            items.append({'start': seconds(start), 'end': seconds(end), 'text': ' '.join(lines[2:])})
    return items


def align_script_words(words, narration):
    """Correct close ASR spellings against the spoken script without moving time."""
    merged = []
    for word in words:
        item = dict(word)
        if merged and item['text'].strip().startswith(("'", '’')):
            merged[-1]['text'] += item['text'].strip()
            merged[-1]['endMs'] = item['endMs']
        else:
            merged.append(item)
    normalize = lambda value: ''.join(c for c in unicodedata.normalize('NFKD', value.casefold()) if c.isalnum())
    reference = narration.split()
    actual, expected = [normalize(w['text']) for w in merged], [normalize(w) for w in reference]
    for operation, a, b, x, y in SequenceMatcher(None, actual, expected, autojunk=False).get_opcodes():
        if b-a != y-x or operation not in ('equal', 'replace'):
            continue
        if operation == 'replace' and not all(SequenceMatcher(None, actual[i], expected[j]).ratio() >= .65 for i,j in zip(range(a,b),range(x,y))):
            continue
        for i,j in zip(range(a,b),range(x,y)):
            merged[i]['text'] = (' ' if i else '') + reference[j]
    return merged


def word_items(srt, durations, script=None):
    data = json.loads(srt.with_suffix('.words.json').read_text(encoding='utf-8'))
    if len(data['scenes']) != len(durations):
        raise RuntimeError('Kelime zamanları kaynak seslerle eşleşmiyor.')
    words, offset = [], 0.0
    for index, (scene, duration) in enumerate(zip(data['scenes'], durations)):
        if abs(scene['duration_seconds'] - duration) > 0.001:
            raise RuntimeError('Kelime zamanları ölçülen anlatım süresiyle eşleşmiyor.')
        reference = script.get('scenes', []) if script else []
        scene_words = align_script_words(scene['words'], reference[index]['narration']) if index < len(reference) else scene['words']
        for item in scene_words:
            word = CaptionWord.model_validate(item).model_dump()
            if word['endMs'] > duration * 1000 + 1:
                raise RuntimeError('Kaynak kelime zamanı ses süresini aşıyor.')
            for key in ('startMs', 'endMs', 'timestampMs'):
                if word[key] is not None:
                    word[key] += offset
            words.append(word)
        offset += duration * 1000
    return words


def render_visual(args, folder, check):
    """Retry one isolated process for browser startup or chunk-frame timeout."""
    args=list(args)
    if len(args)==6:args.append('final')
    if len(args)==7:args.append(str(settings().remotion_render_concurrency))
    for attempt in range(2):
        try:
            media.command(args, folder, check, timeout=3600)
            return
        except media.Cancelled:
            raise
        except RuntimeError:
            log = folder / 'tool.log'
            details = log.read_text(encoding='utf-8', errors='replace') if log.is_file() else ''
            frame_timeout = 'chunk' in args and 'waiting for the page to render the React component at frame' in details
            if 'TimeoutError' not in details or not ('while trying to connect to the browser!' in details or frame_timeout):
                raise
            kind='frame' if frame_timeout else 'browser'
            log_name=f'render-{kind}-attempt-{attempt+1}.log'
            shutil.copyfile(log, folder / log_name)
            if attempt:
                if frame_timeout:
                    frame=re.search(r'at frame (\d+)',details)
                    location=f' {frame.group(1)}. karede' if frame else ''
                    raise RuntimeError(f'Remotion render parçası{location} iki denemede de zaman aşımına uğradı. Ayrıntılar {log_name} dosyasında; kaynak medya korundu.') from None
                raise RuntimeError(f'Remotion, iki açılış denemesinde de Chrome render tarayıcısına bağlanamadı. Ayrıntılar {log_name} dosyasında; kaynak medya korundu.') from None
            check()
            if frame_timeout:
                args[-1]='1'  # Retry the exact range with fewer concurrent browser pages.
                print('Remotion kare hazırlama zaman aşımı: aynı parça tek render sayfasıyla bir kez yeniden deneniyor.',flush=True)
            else:
                print('Remotion Chrome açılışı zaman aşımına uğradı; aynı kurgu ve kaynaklarla bir kez yeniden deneniyor.', flush=True)


def render_production(run, project, folder, images, audios, durations, srt, check, llm, context, music, brand, *, preview_only=False):
    holder=[]
    try:
        return _render_production(run,project,folder,images,audios,durations,srt,check,llm,context,music,brand,preview_only=preview_only,stream_holder=holder)
    finally:
        for renderer in holder:renderer.close()


def _render_production(run, project, folder, images, audios, durations, srt, check, llm, context, music, brand, *, preview_only=False, stream_holder):
    cfg = settings()
    root = cfg.remotion_root.resolve() / 'production'
    if not shutil.which(cfg.node_bin) or not (root / 'node_modules/@remotion/renderer').is_dir():
        raise RuntimeError('Remotion worker bağımlılıkları hazır değil. Media Docker imajını yeniden oluştur.')
    motion = run.outputs.get('motion', {})
    shots = motion.get('plan', {}).get('shots')
    if not shots:
        if cfg.video_provider == 'kaggle':
            raise RuntimeError('Hareketli klipler olmadan montaj başlatılamaz.')
        shots = [{'shot_id': f'shot-{i:03}', 'scene_index': i, 'duration_seconds': d} for i, d in enumerate(durations)]
    style = run.outputs.get('_edit_style', 'classic')
    from .editorial_graphics import brief_sources, compile_cues
    sources = brief_sources(project.topic) if style == 'auto' else []
    graphics, sound_cues = [], []
    stream=None
    if style == 'auto':
        from .automatic_edit import prepare_automatic
        public = folder / 'render-inputs'
        public.mkdir(exist_ok=True)
        for shot in shots:
            ident = shot['shot_id']
            shutil.copyfile(folder / motion['clips'][ident]['file'], public / (ident + '.mp4'))
        if run.outputs.get('_config',{}).get('editor_streaming_enabled',False):
            from .streaming_render import SceneRenderQueue
            from .automatic_edit import scene_frames
            logo=''
            if brand.get('logo_path'):
                from PIL import Image
                logo='brand-logo.png'
                Image.open(media_path(brand['logo_path'])).convert('RGBA').save(public/logo)
            base={'version':2,'style':'auto','duration_frames':sum(scene_frames(durations)),
                'captions':caption_items(srt),'words':word_items(srt,durations,run.outputs['script']),
                'sources':sources,'brand':brand.get('name',''),'logo':logo,'color':brand.get('color','#A98BFF'),
                'reconstruction_label':''}
            stream=SceneRenderQueue(run,folder,public,shots,durations,base,check)
            stream_holder.append(stream)
        decision, clips = prepare_automatic(run, folder, shots, durations, llm, check, sources=sources, brief=project.topic,
            **({'on_scene':stream.on_scene} if stream else {}))
        graphics, sound_cues = compile_cues(decision, durations, sources)
        cursor = sum(c['frames'] for c in clips)
    else:
        instruction = 'Her shot_id tam bir kez ve aynı sırayla bulunmalı. Anlatımın süresini veya sırasını değiştirme.'
        if style == 'editorial':
            instruction += (' Profesyonel bir kısa film montaj liderisin. Altyazı şablonu değil, görsel hikâye kurgula. '
                            'İlk 3 saniyede üç farklı sahneden çekimle teaser montajı için teaser_shots seç. '
                            'intro_beats: her biri en fazla 20 karakter olan üç kısa vurgu; senaryonun fikrini açsın, düz sahne adları olmasın. '
                            'opening_title güçlü bir film başlığı, ending_title anlamlı bir son cümle olsun. '
                            'Her senaryo sahnesi için chapters içinde aynı scene_index ile kısa title ve yaratıcı phrase yaz. '
                            'Sahne değişimlerinde reveal (12–18 kare) ve whip (8–12 kare), ara çekimlerde anlamlı cut kullan. '
                            'Her yere efekt veya yazı koyma. Çekimlerde detay/genel kadraj kesmeleri için punch_in seç. '
                            'Anlatıya uygun vurgu ve sessizlik alanları bırak; gerçek dışı vaat ekleme.')
        elif style == 'dynamic':
            instruction += (' Dinamik sosyal medya kurgusu: opening_title ile 3–6 kelimelik güçlü bir açılış, ending_title ile kısa bir kapanış yaz. '
                            'Her çekime başlık koyma; title çoğunlukla boş olmalı. Çoğunlukla cut kullan; sahne değişimlerinde en fazla iki push '
                            '(6–9 kare) ve yalnızca uygun yerde bir dissolve (9–12 kare) seç. 2–4 çekimde punch_in=true ile yaklaşık ortada kadraj kesmesi seç. '
                            'İlk çekimin geçişi cut olmalı. Rastgele efekt veya iddialı sağlık vaatleri kullanma.')
        else:
            instruction += ' Yalnızca cut veya dissolve geçişi ve kısa Türkçe başlık seç; punch_in=false olmalı.'
        schema = EditorialEditPlan if style == 'editorial' else DynamicEditPlan if style == 'dynamic' else EditPlan
        plan_path = folder / 'edit-plan.json'
        if plan_path.is_file():
            # A run's style and inputs are immutable. Resume its validated decision;
            # a style change always creates a new run with no copied edit plan.
            decision = schema.model_validate_json(plan_path.read_text(encoding='utf-8')).model_dump()
        else:
            decision = schema.model_validate(llm.generate(schema, 'Video Editörü', {**{k: v for k, v in context.items() if k != 'completed'}, 'script': run.outputs['script'], 'shots': shots, 'style': style, 'instruction': instruction})).model_dump()
        if [s['shot_id'] for s in decision['shots']] != [s['shot_id'] for s in shots]:
            raise RuntimeError('Video Editörü çekim sırasını korumadı; montaj durduruldu.')
        if style == 'editorial':
            lookup = {s['shot_id']: s for s in shots}
            if (any(s not in lookup for s in decision['teaser_shots'])
                    or len({lookup[s]['scene_index'] for s in decision['teaser_shots']}) < min(3, len(durations))
                    or sorted(c['scene_index'] for c in decision['chapters']) != list(range(len(durations)))):
                raise RuntimeError('Profesyonel kurgu planı gerçek sahneleri ve açılış çekimlerini kapsamıyor.')
        if style == 'dynamic' and (not decision['opening_title'] or not decision['ending_title']
                                   or sum(s['transition'] == 'push' for s in decision['shots']) > 2):
            raise RuntimeError('Dinamik kurgu planında açılış/kapanış veya geçiş sınırı uygun değil.')
        decision['shots'][0]['transition'] = 'cut'
        public = folder / 'render-inputs'
        public.mkdir(exist_ok=True)
        clips, cursor, elapsed = [], 0, 0.0
        for shot, edit in zip(shots, decision['shots']):
            ident = shot['shot_id']
            moving = motion.get('mode') == 'video'
            source = folder / motion['clips'][ident]['file'] if moving else images[shot['scene_index']]
            filename = ident + ('.mp4' if moving else '.png')
            shutil.copyfile(source, public / filename)
            elapsed += shot['duration_seconds']
            end = round(elapsed * 30)
            clips.append({'file': filename, 'kind': 'clip' if moving else 'image', 'start_frame': cursor, 'frames': end - cursor,
                          'transition': edit['transition'], 'title': edit['title'], 'transition_frames': edit['transition_frames'],
                          'punch_in': edit['punch_in'] if style in ('dynamic', 'editorial') else False,
                          'scene_index': shot['scene_index']})
            cursor = end
    logo = ''
    if brand.get('logo_path'):
        from PIL import Image
        logo = 'brand-logo.png'
        Image.open(media_path(brand['logo_path'])).convert('RGBA').save(public / logo)
    manifest = RenderManifest.model_validate(dict(version=2 if getattr(run, 'pipeline_version', 2)>=3 else 1, duration_frames=cursor, clips=clips, captions=caption_items(srt),
                              words=word_items(srt, durations, run.outputs['script']) if style in ('dynamic', 'editorial', 'auto') else [], style=style,
                              opening_title=decision['opening_title'], ending_title=decision['ending_title'],
                              intro_beats=decision.get('intro_beats', []), teaser_shots=decision.get('teaser_shots', []),
                              chapters=decision.get('chapters', []),
                              graphics=graphics, sound_cues=sound_cues, sources=sources,
                              palette=decision.get('palette', {}),
                              reconstruction_label='',
                              caption_size=decision.get('caption_size', 58),
                              audio_mix=decision.get('audio_mix', {}),
                              captions_enabled=decision.get('captions_enabled', True),
                              brand=brand.get('name', ''), logo=logo, color=brand.get('color', '#A98BFF')), context={'verified_media_files':[p.name for p in public.iterdir() if p.is_file()]}).model_dump()
    (folder / 'edit-plan.json').write_text(json.dumps(decision, ensure_ascii=False), encoding='utf-8')
    manifest_path = folder / 'render-manifest.json'
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
    if stream:stream.finish(manifest)
    planned = getattr(run, 'pipeline_version', 2)>=3 and run.outputs.get('_config', {}).get('video_execution_policy') == 'planned_v1'
    if preview_only:
        from .storage import file_hash
        if planned:
            from .preview import critical_frames, fingerprint, verify_preview
            (folder/'preview-request.json').write_text(json.dumps(critical_frames(manifest)), encoding='utf-8')
            render_visual([cfg.node_bin, root/'render.mjs', manifest_path, public, folder/'preview-frames.json',
                           cfg.remotion_browser_executable, 'preview_frames'], folder, check)
            receipt = {**fingerprint(folder), 'preview_hash':file_hash(folder/'preview-frames.json'),
                       'width':1080, 'height':1920, 'duration_frames':cursor, 'kind':'critical_frames'}
            verify_preview(folder, receipt)
            return receipt
        render_visual([cfg.node_bin, root / 'render.mjs', manifest_path, public, folder / 'visual-preview.mp4', cfg.remotion_browser_executable, 'preview'], folder, check)
        return {'manifest_hash': file_hash(manifest_path), 'preview_hash': file_hash(folder/'visual-preview.mp4'),
                'width':540, 'height':960, 'duration_frames':cursor}
    from .human_review import enabled as human_review_enabled
    if planned and not human_review_enabled(run):
        from .preview import verify_preview
        verify_preview(folder, run.outputs.get('_editor_preview', {}))
    if not stream:
        render_visual([cfg.node_bin, root / 'render.mjs', manifest_path, public, folder / 'visual-edit.mp4', cfg.remotion_browser_executable], folder, check)
    # Audio stays at its original speed. The concat demuxer uses measured WAV durations.
    for i, audio in enumerate(audios):
        shutil.copyfile(audio, folder / f'mix-{i}.wav')
    (folder / 'audio-concat.txt').write_text('\n'.join(f"file 'mix-{i}.wav'" for i in range(len(audios))))
    media.command([cfg.ffmpeg_bin, '-y', '-f', 'concat', '-safe', '1', '-i', 'audio-concat.txt', '-c:a', 'pcm_s16le', 'narration.wav'], folder, check)
    args = [cfg.ffmpeg_bin, '-y', '-i', 'visual-edit.mp4', '-i', 'narration.wav']
    has_effects = style == 'editorial' or (style == 'auto' and sound_cues)
    if has_effects:
        from .sound_design import create_sound_design, create_cue_sound_design
        if style == 'auto':
            create_cue_sound_design(cursor / 30, sound_cues, folder / 'sound-design.wav')
        else:
            create_sound_design(cursor / 30, [0.6, 1.25, 2.0, 3.1] + [c['start_frame'] / 30 for c in clips[1:] if c['transition'] != 'cut'], folder / 'sound-design.wav')
        args += ['-i', 'sound-design.wav']
    if music:
        args += ['-stream_loop', '-1', '-i', music]
    mix = manifest['audio_mix']
    filters = [f"[1:a]volume={mix['narration_gain']}[voice]"]
    labels = ['[voice]']
    if has_effects:
        filters.append(f"[2:a]volume={mix['effects_gain']}[fx]")
        labels.append('[fx]')
    if music:
        index = 3 if has_effects else 2
        filters.append(f"[{index}:a]volume={mix['music_gain']}[music]")
        labels.append('[music]')
    filters.append(''.join(labels)+f"amix=inputs={len(labels)}:duration=first:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11[a]")
    args += ['-filter_complex', ';'.join(filters), '-map', '0:v', '-map', '[a]']
    args += ['-c:v', 'copy', '-c:a', 'aac', '-ar', '48000', '-ac', '2', '-movflags', '+faststart', 'video.mp4']
    media.command(args, folder, check)
    report = media.validate_final(folder, srt, check, target=project.duration)
    if stream:report['streaming_render']={'method':'ordered_cached_frame_ranges','manifest':'visual-parts-complete.json','audio_speed_changed':False}
    if style == 'auto':
        report['content_review'] = {'method': 'reused_sampled_review' if run.outputs.get('_edit_review_source') else 'three_sampled_frames_per_clip', 'source_run': run.outputs.get('_edit_review_source'), 'observations': decision['observations'], 'rationale': decision['rationale'], 'requires_human_review': True}
        report['graphics'] = {'count': len(graphics), 'sound_cues': len(sound_cues), 'sources': sources,
                             'reconstruction_label': manifest['reconstruction_label']}
    return report

