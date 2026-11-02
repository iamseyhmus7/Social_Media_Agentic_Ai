"""Critical-frame receipts bind review to code, timeline and actual media bytes."""
import json
import hashlib
from .storage import file_hash
from .config import settings


def critical_frames(manifest):
    end = manifest['duration_frames'] - 1
    frames = {0, end}
    for clip in manifest['clips']:
        start = clip['start_frame']
        frames.add(start + clip['frames']//2)
        frames.update((start-1, start, start+clip['transition_frames']//2,
                       start+clip['transition_frames']))
    for cue in manifest.get('graphics', []):
        start = cue.get('start_frame', 0)
        # Compiled cues use global frames.
        frames.update((start, start+cue['frames']//2, start+cue['frames']-1))
    # Caption text pages change at roughly 900ms; highlighted words alone do not
    # require duplicating every otherwise identical page in the visual request.
    page_start = -1000
    for word in manifest.get('words', []):
        if word['startMs'] >= page_start + 900:
            page_start = word['startMs']
            frames.add(round(page_start * .03))
    return sorted(f for f in frames if 0 <= f <= end)


def renderer_hash():
    root = settings().remotion_root.resolve()/'production'
    files = sorted(p for p in root.iterdir() if p.suffix in ('.jsx','.js','.mjs','.json') and p.is_file())
    return hashlib.sha256(''.join(p.name+file_hash(p) for p in files).encode()).hexdigest()


def fingerprint(folder):
    return {'manifest_hash':file_hash(folder/'render-manifest.json'), 'renderer_hash':renderer_hash(),
            'sources':{p.name:file_hash(p) for p in sorted((folder/'render-inputs').iterdir()) if p.is_file()}}


def verify_preview(folder, receipt):
    if any(receipt.get(k) != v for k,v in fingerprint(folder).items()):
        raise RuntimeError('İncelenen plan, kaynak veya renderer değişti; yeni önizleme gerekli.')
    path = folder/'preview-frames.json'
    if receipt.get('preview_hash') != file_hash(path):
        raise RuntimeError('Önizleme kare listesi değişti.')
    items = json.loads(path.read_text(encoding='utf-8'))
    manifest = json.loads((folder/'render-manifest.json').read_text(encoding='utf-8'))
    if [i['frame'] for i in items] != critical_frames(manifest):
        raise RuntimeError('Kritik önizleme kareleri eksik.')
    for item in items:
        image = (folder/item['file']).resolve()
        if not image.is_relative_to(folder.resolve()) or file_hash(image) != item['sha256']:
            raise RuntimeError('İncelenen önizleme görüntüsü değişti.')
    return items


def render_motion_windows(folder, receipt, windows, check):
    from .schemas import MotionWindow
    from .remotion_renderer import render_visual
    verify_preview(folder,receipt)
    windows=[MotionWindow.model_validate(w).model_dump() for w in windows]
    duration=json.loads((folder/'render-manifest.json').read_text(encoding='utf-8'))['duration_frames']
    if not 1<=len(windows)<=3 or any(w['end_frame']>=duration for w in windows):
        raise RuntimeError('Hareket inceleme kesitleri geçersiz.')
    if any(b['start_frame']<=a['end_frame'] for a,b in zip(windows,windows[1:])):
        raise RuntimeError('Hareket kesitleri sıralı ve örtüşmesiz olmalı.')
    key=hashlib.sha256(json.dumps([receipt,windows],sort_keys=True).encode()).hexdigest()
    target=folder/('preview-motion-'+key+'.mp4')
    marker=target.with_suffix('.json')
    if marker.is_file() and target.is_file() and json.loads(marker.read_text()).get('sha256')==file_hash(target):
        return target
    (folder/'preview-windows-request.json').write_text(json.dumps(windows),encoding='utf-8')
    cfg=settings()
    render_visual([cfg.node_bin,cfg.remotion_root.resolve()/'production/render.mjs',folder/'render-manifest.json',
        folder/'render-inputs',target,cfg.remotion_browser_executable,'preview_windows'],folder,check)
    marker.write_text(json.dumps({'sha256':file_hash(target),'windows':windows}),encoding='utf-8')
    return target
