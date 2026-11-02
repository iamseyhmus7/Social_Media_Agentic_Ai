"""Scene-local editorial cues become absolute only after narration is measured."""
import re
from urllib.parse import urlsplit
from .schemas import EvidenceSource, GraphicCue, SoundCue, validate_scene_cues


def brief_sources(topic):
    """References supplied in the brief; never invented or fetched by the editor."""
    result, seen = [], set()
    for match in re.finditer(r'https://[^\s<>\[\]"“”]+', topic):
        url = match.group().rstrip('.,;!?)')
        if url in seen:
            continue
        prefix = topic[topic.rfind('\n', 0, match.start())+1:match.start()].strip()
        label = prefix.rstrip('|: ').strip() if prefix.endswith(('|', ':')) and len(prefix) <= 92 else urlsplit(url).hostname.removeprefix('www.')
        source = EvidenceSource(id=f'source-{len(result)+1:02}', label=label, url=url)
        result.append(source.model_dump())
        seen.add(url)
        if len(result) == 8:
            break
    return result


def compile_cues(decision, durations, sources):
    from .automatic_edit import scene_frames
    spans, cursor = {}, 0
    for i, frames in enumerate(scene_frames(durations)):
        spans[i] = (cursor, cursor + frames)
        cursor += frames
    graphics = [GraphicCue.model_validate(c) for c in decision.get('graphics', [])]
    sounds = [SoundCue.model_validate(c) for c in decision.get('sound_cues', [])]
    validate_scene_cues(graphics, sounds, spans, {s['id'] for s in sources}, relative=True)
    return tuple([{**c.model_dump(), 'start_frame': spans[c.scene_index][0]+c.start_frame} for c in cues]
                 for cues in (graphics, sounds))


def append_references(description, sources):
    if not sources or (len(description) <= 4500 and all(s['url'] in description for s in sources)):
        return description
    block = '\n\nKaynaklar:\n' + '\n'.join(s['label'] + ': ' + s['url'] for s in sources)
    if len(block) > 4500:
        raise ValueError('Kaynak bağlantıları açıklama sınırını aşıyor.')
    return description[:4500-len(block)].rstrip() + block
