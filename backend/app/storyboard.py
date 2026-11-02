"""Measured narration owns timing; the director owns shot-specific story content."""
import math
from .schemas import Storyboard, StoryShot
from .providers import ProviderError


def allocation(durations):
    counts = [max(1, math.ceil(d / 4.8)) for d in durations]
    target = min(32, max(sum(counts), math.ceil(sum(durations) / 3.6)))
    while sum(counts) < target:
        index = max(range(len(durations)), key=lambda i: durations[i] / counts[i])
        counts[index] += 1
    if sum(counts) > 32:
        raise ProviderError('Anlatım en fazla 32 çekime bölünebilir.')
    return [{'shot_id': f'shot-{n:03}', 'scene_index': i, 'duration_seconds': durations[i] / counts[i]}
            for n, i in enumerate(i for i, count in enumerate(counts) for _ in range(count))]


def direct_story(llm, script, durations, *, handles=False, context=None):
    slots = allocation(durations)
    expected = {s['shot_id'] for s in slots}
    from pydantic import model_validator
    class DirectedBoard(Storyboard):
        @model_validator(mode='after')
        def exact_shots(self):
            if len(self.shots) != len(slots) or {s.shot_id for s in self.shots} != expected:
                raise ValueError('Allocation listesindeki her shot_id tam bir kez bulunmalı.')
            return self
    plan = llm.generate(DirectedBoard, 'Video Üretim Agentı / Çekim yönetmeni', {
        'script': script, 'allocation': slots, 'creative_context': context or {},
        'instruction': 'Her allocation için bir çekim tasarla. Aynı sahnede birden fazla çekim varsa farklı ama devam eden eylem/tepki/ayrıntı açıları seç; aynı görseli tekrar etme. '
        'reference_prompt İngilizce tek başlangıç karesidir: karakterin sabit görünüşü, kıyafeti, mekânın düzeni, nesnelerin durumu ve kadrajı açıkça tarif et. '
        'Her prompt bağımsız üretileceğinden continuity bilgisini her birinde tekrarla. İlk kare eylemin ÖNCESİNİ göstersin. '
        'motion_prompt İngilizce, bu sürede gerçekleşebilecek tek basit gözle görülür eylemi anlatsın. Karmaşık el/nesne etkileşimini basit çekimlere böl. '
        'purpose ve expected_action Türkçe olsun. Kurgusal hikâyede kamera hareketi karakter eyleminin yerini tutmaz. '
        'Belgesel/eğitici formatta insanlar veya uydurma olaylar zorunlu değildir: mimari ayrıntı, nesne, çevre hareketi ve ölçülü kamera hareketi uygundur. '
        'Kanıt veya arşiv çizimi uydurma; temsili canlandırmayı gerçek belge gibi üretme. Tarih ve yazılar sonradan Remotion ile eklenecek. '
        'Neden-sonuç sırasını, bakış/hareket yönünü, nesne konumunu koru. Yazı, logo veya çoklu panel isteme. 9:16 dikey kadraj.'})
    by_id = {s['shot_id']: s for s in plan['shots']}
    return {'shots': [{**by_id[slot['shot_id']], **slot,
        'duration_seconds': min(5, slot['duration_seconds']+.6) if handles else slot['duration_seconds'],
        'image_index': i} for i, slot in enumerate(slots)]}


def retime_storyboard(board, durations):
    if not board or {s['scene_index'] for s in board['shots']} != set(range(len(durations))):
        return None
    result = []
    for shot in board['shots']:
        count = sum(s['scene_index']==shot['scene_index'] for s in board['shots'])
        seconds = durations[shot['scene_index']]/count
        if seconds > 5:
            return None
        result.append({**shot, 'duration_seconds': min(5, seconds+.6)})
    return {'shots': result}


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
