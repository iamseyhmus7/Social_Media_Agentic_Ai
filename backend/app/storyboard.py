"""Measured narration owns timing; the director owns shot-specific story content."""
import math
from .schemas import Storyboard, StoryShot
from .providers import ProviderError

MAX_VISUAL_SECONDS = 4.0


def allocation(durations):
    counts = [max(1, math.ceil(d / MAX_VISUAL_SECONDS)) for d in durations]
    target = min(32, max(sum(counts), math.ceil(sum(durations) / 3.6)))
    while sum(counts) < target:
        index = max(range(len(durations)), key=lambda i: durations[i] / counts[i])
        counts[index] += 1
    if sum(counts) > 32:
        raise ProviderError('Anlatım en fazla 32 çekime bölünebilir.')
    return [{'shot_id': f'shot-{n:03}', 'scene_index': i, 'duration_seconds': durations[i] / counts[i]}
            for n, i in enumerate(i for i, count in enumerate(counts) for _ in range(count))]


def direct_story(llm, script, durations, *, handles=False, context=None):
    from .config import settings
    slots = allocation(durations)
    expected = {s['shot_id'] for s in slots}
    from pydantic import model_validator
    class DirectedBoard(Storyboard):
        @model_validator(mode='after')
        def exact_shots(self):
            if len(self.shots) != len(slots) or {s.shot_id for s in self.shots} != expected:
                raise ValueError('Allocation listesindeki her shot_id tam bir kez bulunmalı.')
            return self
    role = 'Görsel Tasarımcı / Çekim yönetmeni' if settings().visual_policy=='references_v1' else 'Video Üretim Agentı / Çekim yönetmeni'
    plan = llm.generate(DirectedBoard, role, {
        'script': script, 'allocation': slots, 'creative_context': context or {},
        'visual_contract': ('visual_identity ortak karakter/kıyafet/mekân/ışık tarifidir. Her çekimde state_before, '
            'state_after, preserve ve ilgili çekimlerde aynı continuity_group kimliğini ver. '
            'image_model daima klein; tek model kullanılır, karşılaştırma veya alternatif üretim yapılmaz. '
            'model_reason kısa seçim gerekçesidir. Tek basit özne eylemi seç; kamera hareketi eylemin yerine geçmez. '
            'Gerçekçi kaynak görsele kurgu grafikleri, torus/küre/blueprint dekorasyonu taşıma; yalnız anlatım gerektiriyorsa çizim seç. '
            'Reklam/ürün/logo özellikleri ekleme.' if settings().visual_policy=='references_v1' else ''),
        'instruction': 'Her allocation için ayrı bir başlangıç görseli ve çekim tasarla. Ekrandaki bir görsel en fazla 4 saniye kalabilir. '
        'Anlatım sahnesi sürse bile farklı ve ilgili bir çekime geç. Aynı sahnede birden fazla çekim varsa farklı ama devam eden eylem/tepki/ayrıntı açıları seç; aynı görseli tekrar etme. '
        'reference_prompt İngilizce tek başlangıç karesidir: karakterin sabit görünüşü, kıyafeti, mekânın düzeni, nesnelerin durumu ve kadrajı açıkça tarif et. '
        'Her prompt bağımsız üretileceğinden continuity bilgisini her birinde tekrarla. İlk kare eylemin ÖNCESİNİ göstersin. '
        'motion_prompt İngilizce, bu sürede gerçekleşebilecek tek basit gözle görülür eylemi anlatsın. Karmaşık el/nesne etkileşimini basit çekimlere böl. '
        'purpose ve expected_action Türkçe olsun. İlk çekim ilk saniyede hook vaadini görünür kılsın: '
        'güçlü bir eylem/tepki/ayrıntı, belirgin tek odak ve anında anlaşılır çelişki kullan; boş genel planla başlama. '
        'Kurgusal hikâyede kamera hareketi karakter eyleminin yerini tutmaz. '
        'Belgesel/eğitici formatta insanlar veya uydurma olaylar zorunlu değildir: mimari ayrıntı, nesne, çevre hareketi ve ölçülü kamera hareketi uygundur. '
        'Kanıt veya arşiv çizimi uydurma; temsili canlandırmayı gerçek belge gibi üretme. Tarih ve yazılar sonradan Remotion ile eklenecek. '
        'Neden-sonuç sırasını, bakış/hareket yönünü, nesne konumunu koru. Yazı, logo veya çoklu panel isteme. 9:16 dikey kadraj.'})
    by_id = {s['shot_id']: s for s in plan['shots']}
    return {'visual_identity':plan.get('visual_identity',''), 'shots': [{**by_id[slot['shot_id']], **slot,
        'duration_seconds': min(5, slot['duration_seconds']+.6) if handles else slot['duration_seconds'],
        'image_index': i} for i, slot in enumerate(slots)]}


def retime_storyboard(board, durations):
    if not board or {s['scene_index'] for s in board['shots']} != set(range(len(durations))):
        return None
    result = []
    for shot in board['shots']:
        count = sum(s['scene_index']==shot['scene_index'] for s in board['shots'])
        seconds = durations[shot['scene_index']]/count
        if seconds > MAX_VISUAL_SECONDS:
            return None
        result.append({**shot, 'duration_seconds': min(5, seconds+.6)})
    return {'shots': result}


def enforce_storyboard_cadence(llm, board, script, durations):
    """Keep existing shot IDs/prompts; add only missing views to unfinished plans."""
    groups=[[s for s in board['shots'] if s['scene_index']==i] for i in range(len(durations))]
    if any(not group for group in groups):
        raise ProviderError('Çekim planı bütün anlatım sahnelerini kapsamalı.')
    missing=[]
    next_id=max(int(s['shot_id'].split('-')[1]) for s in board['shots'])+1
    for i,group in enumerate(groups):
        required=max(len(group),math.ceil(durations[i]/MAX_VISUAL_SECONDS))
        for _ in range(required-len(group)):
            missing.append({'shot_id':f'shot-{next_id:03}','scene_index':i,
                'duration_seconds':durations[i]/required})
            next_id+=1
    if not missing:return board
    if len(board['shots'])+len(missing)>32:
        raise ProviderError('Dört saniye kuralı için gereken çekim sayısı 32 sınırını aşıyor.')
    from pydantic import model_validator
    class AdditionalViews(Storyboard):
        @model_validator(mode='after')
        def exact_additions(self):
            if len(self.shots)!=len(missing) or {s.shot_id for s in self.shots}!={s['shot_id'] for s in missing}:
                raise ValueError('Yalnız allocation içindeki yeni çekimleri tam bir kez hazırla.')
            return self
    plan=AdditionalViews.model_validate(llm.generate(AdditionalViews,'Görsel Tasarımcı / Çekim yönetmeni',{
        'script':script,'existing_storyboard':board,'allocation':missing,
        'instruction':'Mevcut çekimleri ve senaryo metnini değiştirme. Yalnız allocation için farklı, ilgili başlangıç görselleri tasarla. '
        'Her görsel ekranda en fazla 4 saniye kalır. Mevcut görselin kopyası yerine aynı olayın farklı eylem/tepki/nesne ayrıntısını seç. '
        'Karakter, kıyafet, mekân ve neden-sonuç devamlılığını koru. reference_prompt ve motion_prompt İngilizce; '
        'purpose ve expected_action Türkçe. Yazı/logo/panel ekleme, image_model klein olsun.'},max_attempts=2,repair_fields=True))
    by_id={s.shot_id:s.model_dump() for s in plan.shots}
    for slot in missing:groups[slot['scene_index']].append({**by_id[slot['shot_id']],**slot})
    shots=[]
    for i,group in enumerate(groups):
        seconds=durations[i]/len(group)
        for shot in group:
            # Source handles are trimmed away by the editor; they are not screen time.
            shots.append({**shot,'duration_seconds':min(5,seconds+.6),'image_index':len(shots)})
    return {**board,'shots':shots}


def revise_storyboard(llm, previous, script, durations, scenes, feedback, quality):
    retimed = retime_storyboard(previous, durations)
    if not retimed:
        return None
    proposed = Storyboard.model_validate(llm.generate(Storyboard, 'Video Üretim Agentı', {
        'previous': {'shots':[{k:v for k,v in shot.items() if k in StoryShot.model_fields}
                              for shot in retimed['shots']]},
        'script': script, 'changed_scenes': scenes,
        'feedback': feedback, 'quality': quality,
        'instruction': 'Yalnız istenen sahnelerin görsel/hareket yönergelerini düzelt. Kimlikleri ve süreleri koru. '
        'scene_indices boşsa tüm sahneleri değerlendir. Mevcut kareyi değiştirmeden yalnız hareket de düzeltilebilir.'}))
    by_id = {s.shot_id:s.model_dump() for s in proposed.shots}
    if set(by_id) != {s['shot_id'] for s in previous['shots']}:
        raise ProviderError('Düzeltme çekim kimliklerini korumalı.')
    return {'shots': [{**s, **{k:by_id[s['shot_id']][k] for k in ('reference_prompt','motion_prompt','camera','purpose','expected_action')}}
        if not scenes or s['scene_index'] in scenes else s for s in retimed['shots']]}
