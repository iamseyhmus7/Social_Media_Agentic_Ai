"""Measured optional optimizations and an explicit required-parallel policy."""
import json
from pathlib import Path
from .storage import file_hash
from .config import settings

PROFILE = 'dual_fp32_group_v2'
PARALLEL_PROFILE = 'dual_fp32_sequential_v1'


def engine_hash():
    return file_hash(Path(__file__).resolve().parents[1]/'kaggle'/'generate.py')


def certificate_path():
    return settings().media_root.resolve().parent/'gpu-profile-certificate.json'


def selected_profile():
    if settings().kaggle_motion_profile == 'dual_required':
        # Explicit parallel policy uses the established memory-saving offload on each GPU.
        return PARALLEL_PROFILE
    if settings().kaggle_motion_profile not in ('certified_auto',PROFILE):
        return 'legacy_fp32'
    try:
        certificate=json.loads(certificate_path().read_text(encoding='utf-8'))
        if (certificate['engine_hash']==engine_hash() and certificate['profile']==PROFILE
                and certificate['outputs_valid'] is True and certificate['clip_count']==4
                and certificate['speedup']>=.20):
            return PROFILE
    except (OSError,ValueError,KeyError,TypeError):
        pass
    return 'legacy_fp32'


def evaluate(result, outputs_valid, measured_engine_hash, candidate_profile=PROFILE):
    profiles=result.get('profiles',{})
    old,new=profiles.get('legacy_fp32',{}),profiles.get(candidate_profile,{})
    valid=outputs_valid and result.get('runtime',{}).get('gpu_count',0)>=2
    for profile in (old,new):
        valid=valid and len(profile.get('clips',{}))==2 and not profile.get('errors') and not profile.get('oom') and not profile.get('worker_error')
        valid=valid and all(c.get('finite') and c.get('pixel_std',0)>.01 and c.get('width')==480 and c.get('height')==832 and c.get('fps')==24 for c in profile.get('clips',{}).values())
    old_seeds=sorted(c['seed'] for c in old.get('clips',{}).values())
    new_seeds=sorted(c['seed'] for c in new.get('clips',{}).values())
    valid=bool(valid and old_seeds==new_seeds and len(set(old_seeds))==2)
    baseline=old.get('wall_seconds',0)
    candidate=new.get('wall_seconds',0)
    speedup=1-candidate/baseline if baseline>0 and candidate>0 else 0
    return {'engine_hash':measured_engine_hash,'profile':candidate_profile,'outputs_valid':valid,
            'clip_count':sum(len(p.get('clips',{})) for p in (old,new)),
            'baseline_seconds':baseline,'candidate_seconds':candidate,'speedup':speedup,
            'enabled':valid and speedup>=.2 and measured_engine_hash==engine_hash()}
