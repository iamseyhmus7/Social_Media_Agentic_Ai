import json
import shutil
import subprocess
import time
import unicodedata
import wave
import re
import os
import signal
import array
import math
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from .config import settings
from .storage import check_disk, file_hash


class Cancelled(RuntimeError):
    pass


def command(args, cwd, check_cancel=lambda: None, timeout=1800):
    """No shell execution; drain to a bounded local log instead of a blocking PIPE."""
    args = list(args)
    if str(args[0]) == str(settings().ffprobe_bin) and '-threads' not in args:
        args[1:1] = ['-threads', '1']
    log = Path(cwd) / 'tool.log'
    with log.open('wb') as output:
        try:
            child = subprocess.Popen([str(a) for a in args], cwd=cwd, stdout=output, stderr=output, start_new_session=os.name != 'nt')
        except FileNotFoundError:
            name = Path(str(args[0])).name
            raise RuntimeError(f'Medya aracı bulunamadı ({name}); worker içindeki çalıştırılabilir dosya yolunu kontrol et.') from None
        start = time.monotonic()
        try:
            while child.poll() is None:
                check_cancel()
                if time.monotonic() - start > timeout:
                    raise RuntimeError('Medya aracı zaman aşımına uğradı.')
                time.sleep(0.3)
            if child.returncode:
                raise RuntimeError('Medya aracı başarısız. Worker içindeki tool.log dosyasını kontrol et.')
        finally:
            if child.poll() is None:
                if os.name != 'nt':
                    os.killpg(child.pid, signal.SIGTERM)
                else:
                    child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    if os.name != 'nt':
                        os.killpg(child.pid, signal.SIGKILL)
                    else:
                        child.kill()
                    child.wait()
    return log.read_text(encoding='utf-8', errors='replace')


def require_audio_tools():
    cfg = settings()
    for key, name in (('ffmpeg_bin', 'FFmpeg'), ('ffprobe_bin', 'FFprobe')):
        if not shutil.which(getattr(cfg, key)):
            raise RuntimeError(f'{name} bulunamadı. Yerel worker için {key.upper()} yolunu ayarla; ses API isteği gönderilmedi.')


def voice(text, target, check_cancel, *, voice_plan=None):
    check_cancel()
    require_audio_tools()
    cfg = settings()
    normalized = unicodedata.normalize('NFC', ' '.join(text.split()))
    if cfg.tts_provider == 'elevenlabs':
        from .media_providers import elevenlabs_audio
        mp3 = target.with_suffix('.mp3')
        try:
            if voice_plan:
                from .schemas import VoiceDecision
                decision = VoiceDecision.model_validate(voice_plan['decision'])
                audio = elevenlabs_audio(normalized, check_cancel, voice_id=voice_plan['voice_id'], voice_settings={
                    'stability': decision.stability, 'style': decision.style,
                    'similarity_boost': 0.75, 'use_speaker_boost': True,
                    **({'speed':voice_plan['speed']} if 'speed' in voice_plan else {}),
                })
            else:
                audio = elevenlabs_audio(normalized, check_cancel)
            mp3.write_bytes(audio)
            command([cfg.ffmpeg_bin, '-y', '-i', mp3.name, '-ac', '1', '-ar', '22050', '-c:a', 'pcm_s16le', target.name], target.parent, check_cancel)
        finally:
            mp3.unlink(missing_ok=True)
    else:
        raise RuntimeError('Seslendirme sağlayıcısı ElevenLabs olmalı.')
    check_cancel()
    with wave.open(str(target), 'rb') as wav:
        import audioop
        if audioop.rms(wav.readframes(wav.getnframes()), wav.getsampwidth()) < 10:
            raise RuntimeError('Üretilen ses dosyası sessiz; seslendirme kontrol edilmeli.')
        wav.rewind()
        return wav.getnframes() / wav.getframerate()


def fit_audio_speed(source, target, speed, check_cancel=lambda: None):
    """Fit a small timing overflow locally without changing pitch or dropping words."""
    if not 1 < speed <= 1.01:
        raise ValueError('Yerel ses süre ayarı en fazla yüzde bir olabilir.')
    command([settings().ffmpeg_bin, '-y', '-i', str(Path(source).resolve()),
             '-af', f'atempo={speed:.9f}', '-c:a', 'pcm_s16le', target.name],
            target.parent, check_cancel)
    with wave.open(str(target), 'rb') as wav:
        return wav.getnframes() / wav.getframerate()


def pad_silent_tail(source, target, seconds):
    """Fit a <=50 ms lower-bound gap without changing or overwriting speech."""
    if not 0 < seconds <= .050001:
        return None
    with wave.open(str(source), 'rb') as wav:
        params = wav.getparams()
        if params.sampwidth != 2 or params.comptype != 'NONE':
            return None
        pcm = wav.readframes(params.nframes)
    frames = math.ceil(seconds * params.framerate - 1e-7)
    with wave.open(str(target), 'wb') as wav:
        wav.setparams(params)
        wav.writeframes(pcm + b'\0' * frames * params.nchannels * params.sampwidth)
    return (params.nframes + frames) / params.framerate


def trim_silent_tail(source, target, seconds):
    """Remove at most 100 ms of near-zero PCM padding, retaining 50 ms of tail."""
    if not 0 < seconds <= .100001:
        return None
    with wave.open(str(source), 'rb') as wav:
        params = wav.getparams()
        if params.sampwidth != 2 or params.comptype != 'NONE':
            return None
        pcm = wav.readframes(params.nframes)
    samples = array.array('h', pcm)
    if sys.byteorder != 'little':
        samples.byteswap()
    silent = 0
    for value in reversed(samples):
        if abs(value) > 10:
            break
        silent += 1
    frames = math.ceil(seconds * params.framerate)
    if silent // params.nchannels < frames + math.ceil(.05 * params.framerate):
        return None
    kept = params.nframes - frames
    with wave.open(str(target), 'wb') as wav:
        wav.setparams(params)
        wav.writeframes(pcm[:kept * params.nchannels * params.sampwidth])
    return kept / params.framerate


def image(prompt, target, check_cancel):
    check_disk()
    check_cancel()
    if settings().image_provider == 'cloudflare':
        from .media_providers import cloudflare_image
        cloudflare_image(prompt, target, check_cancel)
        return
    if settings().image_provider != 'local':
        raise RuntimeError('Bilinmeyen IMAGE_PROVIDER; local veya cloudflare seçilmeli.')
    import torch
    from diffusers import StableDiffusionXLPipeline
    cfg = settings()
    use_gpu = cfg.image_device != 'cpu' and torch.cuda.is_available()
    dtype = torch.float16 if use_gpu else torch.float32
    pipe = StableDiffusionXLPipeline.from_pretrained(cfg.image_model, torch_dtype=dtype, use_safetensors=True)
    pipe.enable_attention_slicing()
    pipe.enable_vae_slicing()
    if use_gpu:
        pipe.enable_sequential_cpu_offload()
    else:
        pipe.to('cpu')

    def callback(_pipe, _step, _t, values):
        check_cancel()
        return values

    try:
        try:
            result = pipe(prompt=prompt, negative_prompt='text, watermark, logo, malformed anatomy, low quality', width=512, height=896, num_inference_steps=25, guidance_scale=9, callback_on_step_end=callback).images[0]
        except torch.cuda.OutOfMemoryError:
            del pipe
            torch.cuda.empty_cache()
            pipe = StableDiffusionXLPipeline.from_pretrained(cfg.image_model, torch_dtype=torch.float32, use_safetensors=True).to('cpu')
            pipe.enable_attention_slicing()
            result = pipe(prompt=prompt, width=512, height=896, num_inference_steps=25, guidance_scale=9, callback_on_step_end=callback).images[0]
        result.save(target)
    finally:
        del pipe
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


def timestamp(seconds):
    millis = max(0, round(seconds * 1000))
    hours, millis = divmod(millis, 3600000)
    minutes, millis = divmod(millis, 60000)
    secs, millis = divmod(millis, 1000)
    return f'{hours:02}:{minutes:02}:{secs:02},{millis:03}'


def subtitles(audio_paths, durations, target, check_cancel):
    check_cancel()
    signature = {'version': 1, 'model': 'faster-whisper/small/int8/tr',
                 'audio_hashes': [file_hash(path) for path in audio_paths], 'durations': durations}
    words_path, cache_path = target.with_suffix('.words.json'), target.with_suffix('.cache.json')
    if target.is_file() and words_path.is_file() and cache_path.is_file():
        try:
            cached = json.loads(cache_path.read_text(encoding='utf-8'))
            if (cached['input'] == signature and cached['srt_hash'] == file_hash(target)
                    and cached['words_hash'] == file_hash(words_path) and 0 < cached['count'] < 1000):
                return cached['count']
        except (OSError, ValueError, KeyError, TypeError):
            pass
    from faster_whisper import WhisperModel
    from huggingface_hub.errors import LocalEntryNotFoundError
    import numpy as np
    try:
        model = WhisperModel('small', device='cpu', compute_type='int8', local_files_only=True)
    except LocalEntryNotFoundError:
        model = WhisperModel('small', device='cpu', compute_type='int8')
    captions, transcripts, offset = [], [], 0.0
    for path, duration in zip(audio_paths, durations):
        check_cancel()
        # Decode with the same FFmpeg used for montage. Passing PCM directly
        # avoids incompatible PyAV decoder APIs and normalizes input to 16 kHz.
        pcm_path = target.parent / 'asr-input.wav'
        try:
            command([settings().ffmpeg_bin, '-y', '-i', path, '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', pcm_path.name], target.parent, check_cancel)
            with wave.open(str(pcm_path), 'rb') as wav:
                samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2').astype(np.float32) / 32768.0
        finally:
            pcm_path.unlink(missing_ok=True)
        segments, _ = model.transcribe(samples, language='tr', word_timestamps=True, vad_filter=False)
        emitted, scene_words = 0, []
        for segment in segments:
            words = segment.words or []
            for word in words:
                start, end = max(0, word.start), min(duration, word.end)
                text = word.word.strip().replace('\n', ' ').replace('-->', '→')
                if text and end > start:
                    probability = getattr(word, 'probability', None)
                    scene_words.append({'text': (' ' if scene_words else '') + text,
                                        'startMs': round(start * 1000, 3), 'endMs': round(end * 1000, 3),
                                        'timestampMs': round((start + end) * 500, 3),
                                        'confidence': float(probability) if probability is not None else None,
                                        'pageBreakAfter': False})
            for index in range(0, len(words), 5):
                batch = words[index:index + 5]
                text = ' '.join(w.word.strip() for w in batch).replace('\n', ' ').replace('-->', '→')
                start = max(0, batch[0].start)
                end = min(duration, batch[-1].end)
                if end > start and text.strip():
                    captions.append(f'{len(captions)+1}\n{timestamp(offset + start)} --> {timestamp(offset + end)}\n{text}\n')
                    emitted += 1
            check_cancel()
        if not emitted:
            raise RuntimeError('Bir sahnede Türkçe altyazı çıkarılamadı; ses veya senaryoyu revize et.')
        if scene_words:
            scene_words[-1]['pageBreakAfter'] = True
        transcripts.append({'duration_seconds': duration, 'words': scene_words})
        offset += duration
    target.write_text('\n'.join(captions), encoding='utf-8')
    # Preserve each source's own timing; timeline offsets are applied by the editor.
    words_path.write_text(json.dumps({'scenes': transcripts}, ensure_ascii=False), encoding='utf-8')
    cache_path.write_text(json.dumps({'input': signature, 'count': len(captions),
                                     'srt_hash': file_hash(target), 'words_hash': file_hash(words_path)}), encoding='utf-8')
    return len(captions)


def watermark(brand, target):
    from .storage import media_path
    canvas = Image.new('RGBA', (850, 150))
    left = 0
    if brand.get('logo_path'):
        logo = Image.open(media_path(brand['logo_path'])).convert('RGBA')
        logo.thumbnail((130, 130))
        canvas.alpha_composite(logo, (0, 0))
        left = 150
    if brand.get('name'):
        font = ImageFont.truetype(settings().subtitle_font_file, 36)
        ImageDraw.Draw(canvas).text((left, 35), brand['name'], font=font, fill=brand.get('color', '#7645ed'), stroke_width=1, stroke_fill='#17171d')
    canvas.save(target)


def cover(source, title, target, brand):
    font_path = settings().subtitle_font_file
    if not Path(font_path).exists():
        raise RuntimeError('Türkçe destekleyen font bulunamadı. SUBTITLE_FONT_FILE ayarla.')
    img = Image.open(source).convert('RGB').resize((1080, 1920))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(font_path, 70)
    words, lines, line = title.split(), [], ''
    for word in words:
        candidate = f'{line} {word}'.strip()
        if draw.textlength(candidate, font=font) > 920:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    label = '\n'.join(lines[:5])
    top = 1920 - len(lines[:5]) * 88 - 180
    draw.rectangle((45, top - 35, 1035, 1840), fill='#15161d')
    draw.multiline_text((80, top), label, font=font, fill='white', spacing=15)
    if brand.get('name'):
        draw.text((80, 90), brand['name'], font=ImageFont.truetype(font_path, 40), fill=brand.get('color', '#7645ed'), stroke_width=1, stroke_fill='black')
    if brand.get('logo_path'):
        from .storage import media_path
        logo = Image.open(media_path(brand['logo_path'])).convert('RGBA')
        logo.thumbnail((170, 170))
        img.paste(logo, (80, 180), logo)
    img.save(target)


def render(folder, images, audios, durations, srt, check_cancel, music=None, brand=None):
    cfg = settings()
    if not shutil.which(cfg.ffmpeg_bin) or not shutil.which(cfg.ffprobe_bin):
        raise RuntimeError('FFmpeg/ffprobe kurulu değil veya PATH içinde bulunamıyor.')
    for index, (image_path, audio_path, duration) in enumerate(zip(images, audios, durations)):
        check_disk()
        args = [cfg.ffmpeg_bin, '-y', '-loop', '1', '-i', image_path, '-i', audio_path,
                '-vf', "scale=1152:2048:force_original_aspect_ratio=increase,crop=1152:2048,zoompan=z='min(zoom+0.00025,1.08)':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s=1080x1920:fps=30,fade=t=in:st=0:d=0.15,fade=t=out:st=" + str(max(0, duration - 0.15)) + ':d=0.15',
                '-t', str(duration), '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '21', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-ar', '48000', '-ac', '2', f'segment-{index}.mp4']
        command(args, folder, check_cancel)
    (folder / 'concat.txt').write_text('\n'.join(f"file 'segment-{i}.mp4'" for i in range(len(images))), encoding='utf-8')
    command([cfg.ffmpeg_bin, '-y', '-f', 'concat', '-safe', '1', '-i', 'concat.txt', '-c', 'copy', 'joined.mp4'], folder, check_cancel)
    if Path(cfg.subtitle_font_file).exists():
        shutil.copyfile(cfg.subtitle_font_file, folder / 'subtitle-font.ttf')
    args = [cfg.ffmpeg_bin, '-y', '-i', 'joined.mp4']
    vf = f"subtitles=filename=captions.srt:fontsdir=.:force_style='FontName={cfg.subtitle_font},FontSize=16,PrimaryColour=&HFFFFFF,OutlineColour=&H151515,BorderStyle=1,Outline=2,Shadow=0,MarginV=65,Alignment=2'"
    filters = [f'[0:v]{vf}[captioned]']
    if music:
        args += ['-stream_loop', '-1', '-i', music]
        filters += ['[1:a]volume=0.08[bg]', '[0:a][bg]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11[audio]']
    else:
        filters += ['[0:a]loudnorm=I=-16:TP=-1.5:LRA=11[audio]']
    video_label = '[captioned]'
    if brand and (brand.get('name') or brand.get('logo_path')):
        watermark(brand, folder / 'watermark.png')
        args += ['-i', 'watermark.png']
        index = 2 if music else 1
        filters += [f'[captioned][{index}:v]overlay=70:70[video]']
        video_label = '[video]'
    args += ['-filter_complex', ';'.join(filters), '-map', video_label, '-map', '[audio]']
    args += ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '21', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-movflags', '+faststart', 'video.mp4']
    command(args, folder, check_cancel)
    return validate_final(folder, srt, check_cancel)


def inspect_clip(path, expected_duration, check_cancel):
    cfg = settings()
    command([cfg.ffprobe_bin, '-v', 'error', '-print_format', 'json', '-show_format', '-show_streams', str(path)], path.parent, check_cancel, timeout=60)
    data = json.loads((path.parent / 'tool.log').read_text())
    video = next((s for s in data['streams'] if s['codec_type'] == 'video'), {})
    duration = float(data['format']['duration'])
    if (video.get('width'), video.get('height')) != (480, 832) or video.get('avg_frame_rate') != '24/1' or video.get('codec_name') != 'h264' or duration + 0.05 < expected_duration or duration > 5.1:
        raise RuntimeError('Hareketli klibin kadrajı veya süresi uygun değil.')
    command([cfg.ffmpeg_bin, '-v', 'error', '-xerror', '-threads', '2', '-i', str(path), '-f', 'null', '-'], path.parent, check_cancel, timeout=120)
    return {'duration': duration, 'width': video['width'], 'height': video['height'], 'decoded': True}


def validate_final(folder, srt, check_cancel, target=None, expected_fps=30):
    cfg = settings()
    command([cfg.ffprobe_bin, '-v', 'quiet', '-print_format', 'json', '-show_format', '-show_streams', 'video.mp4'], folder, check_cancel, timeout=60)
    data = json.loads((folder / 'tool.log').read_text(encoding='utf-8'))
    video = next((s for s in data['streams'] if s['codec_type'] == 'video'), {})
    audio = next((s for s in data['streams'] if s['codec_type'] == 'audio'), {})
    duration = float(data['format']['duration'])
    issues = []
    if (video.get('width'), video.get('height')) != (1080, 1920):
        issues.append('Çözünürlük 1080 × 1920 değil.')
    if video.get('codec_name') != 'h264' or audio.get('codec_name') != 'aac':
        issues.append('H.264/AAC video ve ses akışı doğrulanamadı.')
    if not 30 <= duration <= 60.5:
        issues.append(f'Seslendirme süresi {duration:.1f} saniye; 30–60 saniyeye uygun senaryo gerekli.')
    if target is not None and abs(duration - target) > 2:
        issues.append('Son video hedef süreden iki saniyeden fazla sapıyor.')
    if video.get('avg_frame_rate') != f'{expected_fps}/1':
        issues.append(f'Son video {expected_fps} FPS değil.')
    if not srt.read_text(encoding='utf-8').strip():
        issues.append('Altyazı boş.')
    signal_log = command([cfg.ffmpeg_bin, '-hide_banner', '-xerror', '-err_detect', 'explode', '-threads', '2', '-i', 'video.mp4', '-vf', 'blackdetect=d=0.6:pix_th=0.1', '-af', 'silencedetect=noise=-50dB:d=2.0', '-f', 'null', '-'], folder, check_cancel)
    if signal_log is None:
        signal_log = (folder / 'tool.log').read_text(encoding='utf-8', errors='replace')
    from uuid import uuid4
    check_id = uuid4().hex
    (folder / f'quality-{check_id}.log').write_text(signal_log, encoding='utf-8')
    findings = []
    for match in re.finditer(r'black_start:\s*([\d.]+)\s+black_end:\s*([\d.]+)', signal_log):
        findings.append({'kind':'technical','severity':'error','scene_index':None,
            'start_frame':int(float(match[1])*30),'end_frame':math.ceil(float(match[2])*30),
            'repair_stage':'editor','evidence':f'Güncel render siyah görüntü: {match[1]}–{match[2]} sn.'})
    for match in re.finditer(r'silence_start:\s*([\d.]+)', signal_log):
        end=re.search(r'silence_end:\s*([\d.]+)',signal_log[match.end():])
        findings.append({'kind':'audio','severity':'error','scene_index':None,
            'start_frame':int(float(match[1])*30),'end_frame':math.ceil((float(end[1]) if end else duration)*30),
            'repair_stage':'editor','evidence':f'Güncel render sessizlik: {match[1]} sn.'})
    if 'black_start:' in signal_log:
        issues.append('Videoda uzun boş/siyah sahne algılandı.')
    if 'silence_start:' in signal_log:
        issues.append('Videoda iki saniyeden uzun sessizlik algılandı.')
    caption_lines = [line for line in srt.read_text(encoding='utf-8').splitlines() if line and '-->' not in line and not line.isdigit()]
    if any(len(line) > 90 for line in caption_lines):
        issues.append('Altyazı satırı güvenli okunabilirlik sınırını aşıyor.')
    return {'passed': not issues, 'duration': duration, 'width': video.get('width'), 'height': video.get('height'), 'fps': expected_fps, 'issues': issues,
            'findings':findings,'check_id':check_id,'render_hash':file_hash(folder/'video.mp4') if (folder/'video.mp4').exists() else None,
            'limits': ['Estetik ve doğruluk için kullanıcı incelemesi gerekir.', 'Altyazı zamanları ASR tahminidir; stüdyoda kontrol edilmelidir.']}
