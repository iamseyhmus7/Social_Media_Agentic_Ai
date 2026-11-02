"""Compare spoken content and synthesis settings, excluding editorial metadata."""
import hashlib
import json
import unicodedata


def voice_config(cfg):
    keys=('tts_provider','elevenlabs_model','elevenlabs_voice_id')
    return {key:cfg.get(key) if isinstance(cfg,dict) else getattr(cfg,key) for key in keys}


def input_key(text, cfg, plan=None):
    cfg=voice_config(cfg)
    decision=(plan or {}).get('decision',{})
    effective_settings=None
    if plan:
        effective_settings={'stability':decision.get('stability')}
        if plan.get('speed',1.0) != 1.0:
            effective_settings['speed']=plan['speed']
        if cfg['elevenlabs_model']!='eleven_v4':
            effective_settings['style']=decision.get('style')
    value={'text':unicodedata.normalize('NFC',' '.join(text.split())),
        'provider':cfg['tts_provider'],'model':cfg['elevenlabs_model'],
        'voice_id':plan['voice_id'] if plan else cfg['elevenlabs_voice_id'],
        'settings':effective_settings}
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def reusable_audio(outputs,index,key):
    old=outputs.get('_reuse_voice',{})
    if index>=len(old.get('audios',[])) or index>=len(old.get('durations',[])):
        return None
    requested='voice' in outputs.get('_repair_stages',[])
    changed=outputs.get('_changed_scenes',[])
    if requested and (not changed or index in changed):
        return None
    keys=old.get('input_keys',[])
    if index<len(keys):
        previous_key=keys[index]
    else:
        previous=outputs.get('_previous_script',{}).get('scenes',[])
        source=outputs.get('_reuse_voice_settings')
        if not source or index>=len(previous):
            return None  # Unknown legacy synthesis settings cannot prove equivalence.
        if not all(source.get('config',{}).get(k) is not None for k in ('tts_provider','elevenlabs_model','elevenlabs_voice_id')):
            return None
        previous_key=input_key(previous[index]['narration'],source['config'],source.get('plan'))
    return (old['audios'][index],old['durations'][index]) if previous_key==key else None
