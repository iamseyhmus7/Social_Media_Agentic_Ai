"""Visual evidence and validated editorial decisions, independent of style templates."""
import base64
import io
import json
import math
from PIL import Image, ImageDraw
from pydantic import model_validator, Field
from .schemas import AutoEditPlan, ClipObservation, SCENE_CAPABILITIES
from .config import settings
from . import media
from .storyboard import MAX_VISUAL_SECONDS


def verified_edit_base(run, folder, check):
    """Reuse sampled observations only for an unchanged, owned re-edit source."""
    if not run.outputs.get('_edit_only') or not run.outputs.get('_edit_source_run'):
        return None
    from .db import DB, Run, Asset
    from .storage import workdir, file_hash
    with DB() as db:
        source = db.get(Run, run.outputs['_edit_source_run'])
        if (not source or source.user_id != run.user_id or source.project_id != run.project_id
                or not source.outputs.get('quality', {}).get('passed')
                or source.outputs.get('script') != run.outputs.get('script')
                or source.outputs.get('voice', {}).get('durations') != run.outputs.get('voice', {}).get('durations')):
            return None
        path = workdir(source.project_id, source.id)/'edit-plan.json'
        if not path.is_file():
            return None
        try:
            plan = AutoEditPlan.model_validate_json(path.read_text(encoding='utf-8')).model_dump()
        except ValueError:
            return None  # Classic/dynamic source edits have no sampled auto review.
        old, current = source.outputs['motion']['clips'], run.outputs['motion']['clips']
        if set(old) != set(current):
            return None
        for key, clip in current.items():
            check()
            original, copied = db.get(Asset, old[key]['asset_id']), db.get(Asset, clip['asset_id'])
            if (not original or not copied or original.run_id != source.id or copied.run_id != run.id
                    or original.sha256 != copied.sha256 or file_hash(folder/clip['file']) != original.sha256):
                raise RuntimeError('Yeniden kurgu kaynağının klip özeti değişmiş; önceki görsel inceleme kullanılamadı.')
        run.outputs['_edit_review_source'] = source.id
        return plan


def scene_frames(durations):
    cursor, result = 0, []
    elapsed = 0.0
    for duration in durations:
        elapsed += duration
        end = round(elapsed * 30)
        result.append(end - cursor)
        cursor = end
    return result


def validate_decision(decision, shots, available, durations, *, enforce_reviews=True, sources=(), preferences=None, require_handles=False):
    lookup = {s['shot_id']: s for s in shots}
    observations = decision['observations']
    if len(observations) != len(lookup) or {o['shot_id'] for o in observations} != set(lookup):
        raise ValueError('Her kaynak çekim için tam bir görsel gözlem gerekli.')
    totals = [0] * len(durations)
    last_scene = -1
    previous_shot = None
    for item in decision['segments']:
        ident = item['shot_id']
        if ident not in lookup:
            raise ValueError('Kurgu yalnızca mevcut çekimleri kullanabilir.')
        if item['frames']>round(MAX_VISUAL_SECONDS*30):
            raise ValueError('Bir görsel ekranda en fazla 4 saniye kalabilir; farklı çekim seç.')
        if ident==previous_shot:
            raise ValueError('Ardışık parçalar aynı görseli sürdüremez; farklı çekime geç.')
        previous_shot=ident
        scene = lookup[ident]['scene_index']
        if not 0 <= scene < len(totals) or scene < last_scene:
            raise ValueError('Sesli anlatımın olay sırası korunmalı; çekimler yalnızca kendi sahnesinde düzenlenebilir.')
        if item['source_in_frame'] + item['frames'] > available[ident]:
            raise ValueError('Seçilen kaynak aralığı klibin süresini aşıyor; döngü veya donmuş kare kullanma.')
        if item['transition_frames'] >= item['frames']:
            raise ValueError('Geçiş süresi çekimden kısa olmalı.')
        totals[scene] += item['frames']
        last_scene = scene
    if totals != scene_frames(durations):
        raise ValueError(f'Her sahnenin toplam kare sayısı tam olarak {scene_frames(durations)} olmalı; {totals} bulundu.')
    if decision['segments'][0]['transition'] != 'cut':
        raise ValueError('İlk çekim cut ile başlamalı.')
    if require_handles:
        for index, segment in enumerate(decision['segments']):
            following = decision['segments'][index+1] if index+1<len(decision['segments']) else None
            handle = following['transition_frames'] if following and following['transition']!='cut' else 0
            if segment['source_in_frame']+segment['frames']+handle > available[segment['shot_id']]:
                raise ValueError('Geçiş için ek kaynak kare yetersiz; kesmeyi veya kaynak aralığını değiştir.')
            design = segment.get('design', {})
            secondary = design.get('secondary_shot_id')
            if secondary:
                if secondary not in lookup or lookup[secondary]['scene_index']!=lookup[segment['shot_id']]['scene_index']:
                    raise ValueError('İkinci kadraj aynı anlatım sahnesindeki doğrulanmış çekimden olmalı.')
                if segment['source_in_frame']+segment['frames']+handle>available[secondary]:
                    raise ValueError('İkinci kadrajın kaynak süresi yetersiz.')
    rejected = {o['shot_id'] for o in observations if o['verdict'] == 'reject'}
    if enforce_reviews and rejected & {s['shot_id'] for s in decision['segments']}:
        raise ValueError('Görsel olarak reddedilen çekim montaja alınamaz.')
    from .editorial_graphics import compile_cues
    compile_cues(decision, durations, sources)
    if preferences is not None:
        if not preferences.get('show_sources', False) and any(c['kind'] == 'source_card' for c in decision.get('graphics', [])):
            raise ValueError('Kullanıcı videoda kaynak kartı istemiyor; kaynakları yalnızca açıklamada tut.')
        if preferences.get('map_intro') and not any(c['kind'] == 'map_flyover' and c['scene_index'] == 0 and c['start_frame'] == 0 for c in decision.get('graphics', [])):
            raise ValueError('İlk sahne 0. karede başlayan map_flyover ile açılmalı.')
    return decision


def prepare_automatic(run, folder, shots, durations, llm, check, *, sources=(), brief='', on_scene=None):
    cfg = settings()
    preferences = run.outputs.get('_edit_preferences', {})
    if getattr(run, 'pipeline_version', 2)>=3 and run.outputs.get('_config', {}).get('video_execution_policy') == 'planned_v1':
        from .planned_edit import prepare_decision
        available = {s['shot_id']:math.floor(run.outputs['motion']['clips'][s['shot_id']]['report']['duration']*30+.001) for s in shots}
        decision = prepare_decision(run, folder, shots, durations, available, llm, check, sources, brief, preferences,on_scene=on_scene)
        return assemble_decision(run, decision, shots)

    motion = run.outputs['motion']
    base = verified_edit_base(run, folder, check)
    available, inputs = {}, []
    evidence = folder / 'edit-evidence'
    evidence.mkdir(exist_ok=True)
    for shot in shots:
        check()
        ident = shot['shot_id']
        item = motion['clips'][ident]
        seconds = item['report']['duration']
        available[ident] = math.floor(seconds * 30 + 0.001)
        if base:
            continue
        sheet = Image.new('RGB', (720, 440), '#111419')
        draw = ImageDraw.Draw(sheet)
        for index, fraction in enumerate((0.05, 0.5, 0.92)):
            timestamp = min(seconds - 0.08, seconds * fraction)
            path = evidence / f'{ident}-{index}.jpg'
            media.command([cfg.ffmpeg_bin, '-y', '-ss', str(timestamp), '-i', folder / item['file'], '-frames:v', '1', '-vf', 'scale=240:416', str(path)], folder, check, timeout=60)
            with Image.open(path) as source:
                sheet.paste(source, (index * 240, 24))
            draw.text((index * 240 + 5, 5), f'{ident} | {timestamp:.2f}s', fill='white')
        sheet.save(evidence / f'{ident}.jpg', quality=85)
        buffer = io.BytesIO()
        sheet.save(buffer, format='JPEG', quality=80)
        inputs.append({'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + base64.b64encode(buffer.getvalue()).decode(), 'detail': 'high'}})
    class GroundedEdit(AutoEditPlan):
        @model_validator(mode='after')
        def timeline(self):
            validate_decision(self.model_dump(), shots, available, durations, enforce_reviews=False, sources=sources, preferences=preferences, require_handles=getattr(run, 'pipeline_version', 2)>=3)
            return self
    schema = GroundedEdit
    if base:
        validate_decision({**base, 'graphics': [], 'sound_cues': []}, shots, available, durations, sources=sources)
        class ReusedEdit(GroundedEdit):
            observations: list[ClipObservation] = Field(default_factory=lambda: base['observations'])

            @model_validator(mode='before')
            @classmethod
            def preserve_sampled_observations(cls, value):
                return {**value, 'observations': base['observations']} if isinstance(value, dict) else value
        schema = ReusedEdit
    path = folder / 'edit-plan.json'
    if path.is_file():
        decision = schema.model_validate_json(path.read_text(encoding='utf-8')).model_dump()
    else:
        review_instruction = ('Bu bir yeniden kurgudur; görsel eki yok. Kaynak kliplerin dosya özetleri aynı ve önceki örnek-kare gözlemleri sunucuda korunuyor. '
            'Önceki gözlemleri yeniden yazma veya dinlediğini/gördüğünü yeniden iddia etme; observations alanını döndürmene gerek yok. '
            'previous_edit içindeki gözlemleri ve geçerli kaynak aralıklarını temel al; yeni kullanıcı tercihlerine göre grafik, tipografi, kesme ve geçişleri düzenle. '
            'Var olan doğru kare bütçelerini korumak önceliklidir. ' if base else
            'Görüntüler shots sırasındadır; her görsel aynı klibin zaman etiketli başlangıç/orta/son karelerini gösterir. '
            'Önce her çekimde GÖRDÜĞÜN karakter/nesne/eylemi observations içinde değerlendir. Promptu gerçekleşmiş olay gibi anlatma. '
            'Açık yanlış özne, yanlış olay veya ağır anatomik hata reject; örnek karelerden hareket/kimlik doğrulanamıyorsa uncertain. '
            'Bu örnekler kesintisiz hareket veya ses doğrulaması değildir. uncertain sonucu kullanıcıya açıkça bırakılacak. ')
        decision = llm.generate(schema, 'Video Editörü / Görsel kurgu yönetmeni', {
            'script': run.outputs['script'], 'brief': brief, 'sources': sources, 'edit_preferences': preferences,
            'creative_brief': run.outputs.get('supervisor'), 'brand': run.outputs.get('_brand'),
            'feedback': run.outputs.get('_feedback'),
            'previous_quality_findings': run.outputs.get('_last_quality'),
            'supported_scene_design': SCENE_CAPABILITIES,
            'previous_edit': {k: base[k] for k in ('observations', 'segments')} if base else None,
            'shots': shots, 'source_available_frames_30fps': available,
            'required_scene_frames_30fps': scene_frames(durations),
            'instruction': review_instruction +
            'Sonra senaryoyla uyumlu segments zaman çizelgesi kur. Her segment kaynak klipten bir aralık: source_in_frame ve frames 30fps biriminde. '
            'Anlatım orijinal hızında ve sabit: her sahnenin toplam frames değeri required_scene_frames_30fps ile TAM eşleşmeli. '
            'Aynı sahnenin çekimlerini seçebilir, kısaltabilir, eylem/tepki/ayrıntıya göre sıralayabilirsin. Olay sırasını veya neden-sonucu bozma. '
            'Klibin mevcut süresini aşma. Geçiş varsa önceki segmentin source_in_frame+frames+geçiş süresi kaynak sınırında olmalı. Ek kare yoksa cut seç. Yeni 3D/paralaks/morph veya kod üretme. İkincil kadraj aynı sahneden olmalı ve aynı source_in_frame ile yeterli süresi bulunmalı. '
            'Açılış en güçlü uygun eylemle doğrudan başlasın; zorunlu teaser veya başlık kartı yok. '
            'Hareket devamında cut, zaman/duygu değişiminde gerektiğinde dissolve, gerçekten yönlü hareket varsa whip/push, anlamlı mekân açılımında reveal seç. '
            'Efekt sayısı kotası yok; her geçişin reason alanında içerik gerekçesi olmalı. title ve opening_title/ending_title gerektiğinde boş kalsın. '
            'Karakterin elini/nesneyi kırpan punch_in kullanma; görüntü zaten yakınsa büyütme. Türkçe rationale ile bütün kurgunun mantığını açıkla. '
            'graphics ve sound_cues içerikten seçilir, zorunlu efekt kotası yoktur. Her işaret scene_index, sahne başlangıcına göre start_frame ve frames içerir; '
            'işaretin tamamı required_scene_frames_30fps sınırları içinde kalmalı. Aynı anda en fazla bir grafik; aralarında okunabilir süre bırak. '
            'Grafik türleri: kinetic_text (kısa güçlü title, isteğe bağlı detail), timeline (2–4 artan yıl ve kısa etiket içeren events), '
            'spotlight (gerçek karedeki ayrıntıyı çevreleyen region: normalize merkez x/y ve width/height; x sınırı .07–.86, y .12–.71), '
            'source_card (yalnızca verilen sources kimliklerinden source_ids, kısa title/detail); yalnızca edit_preferences.show_sources=true ise kullan. '
            'map_flyover: location içinde latitude/longitude, Türkçe label/country, üç harfli country_code (örn EGY) kullan. En az 90 kare. '
            'Harita açılışı istenmişse ilk sahnenin 0. karesinde 110–145 karelik map_flyover seç; sahne süresini aşma. '
            'Başlangıçtaki geniş coğrafyadan olay mekânına kamera yaklaşır; konumu ve başlığı senaryoya göre seç. '
            'Mekânı söylentinin tarihsel çıkış yeri diye sunma: yalnızca olayın geçtiği doğrulanmış yer olarak işaretle. '
            'Kaynak yoksa kaynak kartı kullanma; kaynak uydurma. '
            'Tarih karşılaştırmalarını yalnızca brief/senaryodaki tarihlerle oluştur. timeline iki tarih arasındaki farkı kendi hesaplar. '
            'Tarihsel iddia bir efsane olarak anlatılıyorsa ilgili görüntülerde kısa Efsane başlığı kullan; üretilmiş görüntüyü arşiv belgesi olarak sunma. '
            'Bilgilendirici belgeselde grafikler kanıtın anlaşılmasına hizmet etsin. Kaynak kartları için en az 60 kare ayır. '
            'sound_cues türleri tick/whoosh/impact, gain en fazla .15, frames 3–30; yalnızca anlamlı keşif/geçişte ölçülü kullan. '
            'palette renklerini marka, yaratıcı brief ve içeriğe göre seç; zorunlu renk veya estetik yok. '
            'Tipografi, kamera, yerleşim, ışık ve parçacıkları her segmentin design alanında anlatım ihtiyacına göre seç. '
            'Açılış ve kapanışı içerik belirler; gerektiğinde başlıkları boş bırak. '
            'Başlık/grafik varsa aynı anda opening_title veya çekim title ile tekrarlama. Kullanıcının edit_preferences.instructions yönergesini uygula.'}, media_inputs=inputs)
        decision = schema.model_validate(decision).model_dump()
        path.write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding='utf-8')
    return assemble_decision(run, decision, shots)


def assemble_decision(run, decision, shots):
    used = {s['shot_id'] for s in decision['segments']}
    used.update(s.get('design',{}).get('secondary_shot_id') for s in decision['segments'])
    rejected = [o for o in decision['observations'] if o['verdict'] == 'reject' and o['shot_id'] in used]
    if rejected:
        if getattr(run, 'pipeline_version', 2) >= 3:
            from .orchestration import SourceRejected
            raise SourceRejected([{'kind':'source','severity':'error','scene_index':next(s['scene_index'] for s in shots if s['shot_id']==o['shot_id']),'start_frame':None,'end_frame':None,'evidence':o['observation'],'repair_stage':'motion'} for o in rejected])
        raise RuntimeError('Görsel içerik incelemesi montajı durdurdu. ' + ' '.join(o['shot_id'] + ': ' + o['observation'] for o in rejected)[:1200])
    lookup = {s['shot_id']: s for s in shots}
    cursor, clips = 0, []
    for segment in decision['segments']:
        shot = lookup[segment['shot_id']]
        clips.append({k: segment[k] for k in ('source_in_frame', 'frames', 'transition', 'transition_frames', 'title', 'punch_in', 'design')} |
                     {'file': segment['shot_id'] + '.mp4', 'kind': 'clip', 'scene_index': shot['scene_index'], 'start_frame': cursor})
        secondary=segment['design'].get('secondary_shot_id')
        if secondary:
            clips[-1].update(secondary_file=secondary+'.mp4',secondary_source_in_frame=segment['source_in_frame'])
        cursor += segment['frames']
    for index, clip in enumerate(clips[:-1]):
        following=clips[index+1]
        clip['handle_frames']=following['transition_frames'] if following['transition']!='cut' and getattr(run, 'pipeline_version', 2)>=3 else 0
    return decision, clips
