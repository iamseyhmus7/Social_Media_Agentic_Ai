import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.app.config import settings, snapshot_settings, use_run_settings
from backend.app.schemas import RenderManifest, SceneDesign
from backend.app.streaming_render import SceneRenderQueue, visible_signature


def test_output_fps_does_not_retime_editorial_captions():
    manifest = RenderManifest.model_validate({
        'output_fps': 60, 'duration_frames': 90,
        'clips': [{'file': 'shot-000.mp4', 'kind': 'clip', 'start_frame': 0, 'frames': 90}],
        'captions': [{'start': 2, 'end': 3, 'text': 'Son saniye'}],
    })
    assert manifest.fps == 30 and manifest.duration_frames / manifest.fps == 3
    with pytest.raises(ValidationError):
        RenderManifest.model_validate({**manifest.model_dump(), 'output_fps': 24})


def test_old_run_keeps_30_fps_and_new_snapshot_records_output_choice():
    with use_run_settings({}):
        assert settings().remotion_output_fps == 30
    with use_run_settings({'remotion_output_fps': 60}):
        assert snapshot_settings()['remotion_output_fps'] == 60


def test_fps_change_invalidates_render_chunk_cache():
    manifest = {'clips': [{'file': 'shot-000.mp4', 'start_frame': 0, 'frames': 30}],
                'duration_frames': 30, 'output_fps': 30}
    before = visible_signature(manifest, 0, 29, {'shot-000.mp4': 'hash'}, 'renderer')
    manifest['output_fps'] = 60
    assert before != visible_signature(manifest, 0, 29, {'shot-000.mp4': 'hash'}, 'renderer')


def test_stream_inspection_checks_native_60fps_frame_count(tmp_path, monkeypatch):
    queue = object.__new__(SceneRenderQueue)
    queue.cfg = SimpleNamespace(ffprobe_bin='ffprobe')
    queue.check = lambda: None
    from backend.app import streaming_render
    monkeypatch.setattr(streaming_render.media, 'command', lambda *a, **kw: None)
    path = tmp_path / 'video.mp4'
    probe = {'streams': [{'codec_type': 'video', 'width': 1080, 'height': 1920,
                          'avg_frame_rate': '60/1', 'nb_read_frames': '60'}]}
    (tmp_path / 'tool.log').write_text(json.dumps(probe))
    queue.inspect(path, 30, 60)
    probe['streams'][0]['nb_read_frames'] = '30'
    (tmp_path / 'tool.log').write_text(json.dumps(probe))
    with pytest.raises(RuntimeError):
        queue.inspect(path, 30, 60)


def test_pro_tools_reject_unregistered_assets_and_unbounded_effects():
    SceneDesign(effects=['color_grade', 'glow'], annotation='circle', lottie_asset='flow_arrow')
    SceneDesign(motion_blur=True, annotation='circle', lottie_asset='flow_arrow')
    with pytest.raises(ValidationError, match='birlikte desteklenmiyor'):
        SceneDesign(effects=['glow'], motion_blur=True)
    for payload in ({'lottie_asset': 'https://example.test/file.json'},
                    {'effect_strength': 2}, {'effects': ['generated_shader']}):
        with pytest.raises(ValidationError):
            SceneDesign.model_validate(payload)


def test_final_quality_accepts_selected_fps_and_keeps_repair_ticks(tmp_path, monkeypatch):
    from backend.app import media
    data = {'streams': [
        {'codec_type': 'video', 'width': 1080, 'height': 1920,
         'codec_name': 'h264', 'avg_frame_rate': '60/1'},
        {'codec_type': 'audio', 'codec_name': 'aac'}], 'format': {'duration': '30'}}
    srt = tmp_path / 'captions.srt'
    srt.write_text('1\n00:00:00,000 --> 00:00:01,000\nMerhaba', encoding='utf-8')
    def command(args, folder, *a, **kw):
        if str(args[0]) == settings().ffprobe_bin:
            (folder / 'tool.log').write_text(json.dumps(data), encoding='utf-8')
        return ''
    monkeypatch.setattr(media, 'command', command)
    assert media.validate_final(tmp_path, srt, lambda: None, expected_fps=60)['passed']
    assert not media.validate_final(tmp_path, srt, lambda: None, expected_fps=30)['passed']
