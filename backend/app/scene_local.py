"""Validate one immutable editorial scene before any frame is rendered."""
from copy import deepcopy
from .edit_compiler import compile_segments,SceneBudgetError
from .schemas import SceneEditRepair,SceneCueRepair


def compile_local(scene,result,shots,available,budgets):
    local=[{**s,'scene_index':0} for s in shots if s['scene_index']==scene]
    return compile_segments(result['segments'],local,available,[budgets[scene]],
        require_first_cut=scene==0,last_handle_reserve=18 if scene<len(budgets)-1 else 0)


def finalize_scene(scene,result,shots,available,budgets,durations,sources,preferences,llm,check):
    result=deepcopy(result)
    ids={s['shot_id'] for s in shots if s['scene_index']==scene}
    for attempt in range(3):
        check()
        try:
            compiled=compile_local(scene,result,shots,available,budgets)
            break
        except SceneBudgetError as exc:
            if attempt==2:raise
            fixed=llm.generate(SceneEditRepair,'Video Editörü / Yerel kaynak düzeltmesi',{
                'scene_index':scene,'error':str(exc),'frame_budget':budgets[scene],
                'boundary_handle_reserve':18 if scene<len(budgets)-1 else 0,
                'sources':{ident:available[ident] for ident in ids},'current_segments':result['segments'],
                'instruction':'Yalnız bu sahnenin kaynak aralığı/seçimini düzelt. Her parça en fazla 4 saniye olsun; '
                'art arda aynı çekimi kullanma. Yeterli farklı kaynak seç. Sondaki kaynak geçiş rezervini koru. Başka sahneye dokunma.'},
                max_attempts=2,repair_fields=True,compact_schema=True)
            if any(s['shot_id'] not in ids or (s.get('design',{}).get('secondary_shot_id') and s['design']['secondary_shot_id'] not in ids) for s in fixed['segments']):
                raise ValueError('Yerel düzeltme başka sahne kaynağı kullanamaz.')
            result['segments']=fixed['segments']
    for cue in result['graphics']:
        region=cue.get('region')
        if region:
            left=max(.070001,region['x']-region['width']/2);right=min(.859999,region['x']+region['width']/2)
            top=max(.120001,region['y']-region['height']/2);bottom=min(.709999,region['y']+region['height']/2)
            if right>left and bottom>top:
                cue['region']={'x':(left+right)/2,'y':(top+bottom)/2,'width':min(.7,right-left),'height':min(.6,bottom-top)}
            else:
                fixed=llm.generate(SceneCueRepair,'Video Editörü / Yerel grafik düzeltmesi',{
                    'scene_index':scene,'cue':cue,'frame_budget':budgets[scene],
                    'instruction':'Yalnız bu grafik için görünür güvenli görüntü bölgesi seç.'},
                    max_attempts=2,repair_fields=True,compact_schema=True)
                if len(fixed['graphics'])!=1 or fixed['graphics'][0]['scene_index']!=scene or fixed['sound_cues']:
                    raise ValueError('Grafik düzeltmesi başka sahneyi değiştiremez.')
                cue.update(fixed['graphics'][0])
    from .planned_edit import repair_cues
    repair_cues(result,durations,sources,preferences,llm,check,bounded=True,scene_indices=[scene])
    rejected={r['shot_id'] for r in result['reviews'] if r['verdict']=='reject'}
    used={s['shot_id'] for s in result['segments']}|{s.get('design',{}).get('secondary_shot_id') for s in result['segments']}
    if rejected&used:
        from .orchestration import SourceRejected
        raise SourceRejected([{'kind':'source','severity':'error','scene_index':scene,'start_frame':None,'end_frame':None,
            'evidence':r['reason'],'repair_stage':'motion'} for r in result['reviews'] if r['shot_id'] in rejected&used])
    return result,compiled
