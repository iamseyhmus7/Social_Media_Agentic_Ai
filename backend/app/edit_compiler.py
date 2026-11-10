"""Allocate exact measured narration budgets without asking a model to do arithmetic."""
import math
from .storyboard import MAX_VISUAL_SECONDS


class SceneBudgetError(ValueError):
    def __init__(self, scene_index, message):
        self.scene_index = scene_index
        super().__init__(message)


def allocate(total, weights, lower, upper):
    if (not weights or any(a>b for a,b in zip(lower,upper))
            or sum(lower) > total or sum(upper) < total):
        raise ValueError('Seçilen kaynaklar bu sahnenin kare bütçesini karşılamıyor; kaynak aralığı veya çekim seçimi düzeltilmeli.')
    result = list(lower)
    remaining = total-sum(result)
    active = {i for i in range(len(weights)) if result[i] < upper[i]}
    while remaining:
        mass = sum(weights[i] for i in active)
        shares = {i:remaining*weights[i]/mass for i in active}
        increments = {i:min(upper[i]-result[i], math.floor(shares[i])) for i in active}
        if not any(increments.values()):
            index = max(active, key=lambda i:(shares[i],-i))
            increments[index] = 1
        for i,count in increments.items():
            result[i] += count
            remaining -= count
        active = {i for i in active if result[i] < upper[i]}
    return result


def compile_segments(segments, shots, available, budgets, *, require_first_cut=True, boundary_reserve=0, last_handle_reserve=0):
    lookup = {s['shot_id']:s['scene_index'] for s in shots}
    indices = [lookup.get(s['shot_id'],-1) for s in segments]
    if -1 in indices or indices != sorted(indices):
        scene = next((v for v in indices if v >= 0),0)
        raise SceneBudgetError(scene,'Çekimler mevcut kaynaklardan ve anlatım sırasına uygun seçilmeli.')
    compiled = []
    for scene,total in enumerate(budgets):
        positions = [i for i,v in enumerate(indices) if v == scene]
        try:
            if not positions:
                raise ValueError('Sahne için çekim seçilmedi.')
            lower,upper,weights = [],[],[]
            for index in positions:
                segment = segments[index]
                if index and segments[index-1]['shot_id']==segment['shot_id']:
                    raise ValueError('Ardışık parçalar farklı görseller kullanmalı.')
                following = segments[index+1] if index+1<len(segments) else None
                handle = following['transition_frames'] if following and following['transition']!='cut' else 0
                if following and lookup[following['shot_id']]!=scene:
                    handle=max(handle,boundary_reserve)
                if following is None:
                    handle=max(handle,last_handle_reserve)
                capacity = available[segment['shot_id']]
                secondary = segment.get('design',{}).get('secondary_shot_id')
                if secondary:
                    if lookup.get(secondary) != scene:
                        raise ValueError('İkinci kadraj aynı anlatım sahnesinden seçilmeli.')
                    capacity = min(capacity,available[secondary])
                lower.append(segment['transition_frames']+1)
                upper.append(min(round(MAX_VISUAL_SECONDS*30),capacity-segment['source_in_frame']-handle))
                weights.append(segment['duration_weight'])
            sizes = allocate(total,weights,lower,upper)
            for position,size in zip(positions,sizes):
                compiled.append({k:v for k,v in segments[position].items() if k!='duration_weight'} | {'frames':size})
        except (ValueError,KeyError) as exc:
            raise SceneBudgetError(scene,str(exc)) from None
    if not compiled or (require_first_cut and compiled[0]['transition']!='cut'):
        raise SceneBudgetError(0,'İlk çekim cut ile başlamalı.')
    return compiled
