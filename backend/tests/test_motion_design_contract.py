import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.schemas import SCENE_CAPABILITIES, RenderManifest, SceneDesign


def test_planner_capabilities_match_renderer_registry():
    source = (Path(__file__).resolve().parents[2] / 'remotion/production/motion-design.mjs').read_text()
    for key, export in [('camera', 'cameras'), ('transitions', 'transitions'),
                        ('typography', 'typography'), ('templates', 'templates'),
                        ('objects_3d', 'objects3d')]:
        values = re.search(r'export const ' + export + r'=(\[.*?\]);', source)[1]
        assert SCENE_CAPABILITIES[key] == json.loads(values.replace("'", '"'))


@pytest.mark.parametrize('transition', SCENE_CAPABILITIES['transitions'])
def test_new_transitions_preserve_timeline_and_source_handles(transition):
    handle = 0 if transition == 'cut' else 12
    manifest = RenderManifest.model_validate({
        'version': 2, 'style': 'auto', 'duration_frames': 90,
        'clips': [
            {'file': 'shot-000.mp4', 'start_frame': 0, 'frames': 45,
             'handle_frames': handle, 'transition': 'cut'},
            {'file': 'shot-001.mp4', 'start_frame': 45, 'frames': 45,
             'transition': transition, 'transition_frames': 12,
             'design': {'camera': {'kind': 'arc'}, 'typography': 'flip',
                        'font_family': 'serif', 'template': 'glass',
                        'object_3d': {'kind': 'torus'}}},
        ],
    })
    assert sum(c.frames for c in manifest.clips) == 90
    assert manifest.clips[0].handle_frames == handle
    assert manifest.reconstruction_label == ''


@pytest.mark.parametrize('object_3d', [
    {'kind': 'download_model', 'url': 'https://example.test/model.glb'},
    {'kind': 'cube', 'scale': 100},
    {'kind': 'torus', 'speed': 100},
    {'kind': 'sphere', 'color': 'url(https://example.test)'},
])
def test_3d_objects_cannot_load_arbitrary_assets_or_exceed_bounds(object_3d):
    with pytest.raises(ValidationError):
        SceneDesign(object_3d=object_3d)


def test_legacy_scene_uses_existing_2d_defaults():
    design = SceneDesign.model_validate({'camera': {'kind': 'push_in'}, 'typography': 'rise'})
    assert design.object_3d is None
    assert design.template == 'none'
    assert design.font_family == 'sans'
