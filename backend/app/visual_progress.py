"""Progress comes from validated revision outputs, never from cloned asset totals."""
def visual_progress(outputs):
    visual=outputs.get('visual')
    if visual:
        images=visual.get('images',[])
        count=len(visual.get('shot_images') or images)
        return {'completed':count,'total':count,'unit':'shots' if visual.get('shot_images') else 'scenes',
            'scene_images':{str(i):ident for i,ident in enumerate(images)}}
    if '_visual_progress' in outputs:
        return outputs['_visual_progress']
    shots=outputs.get('_storyboard',{}).get('shots',[])
    return {'completed':0,'total':len(shots) or len(outputs.get('script',{}).get('scenes',[])),
        'unit':'shots' if shots else 'scenes','scene_images':{}}
