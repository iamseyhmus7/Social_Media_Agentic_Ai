import wave
import pytest
from backend.app.schemas import AutoEditPlan, GraphicCue, RenderManifest
from backend.app.editorial_graphics import brief_sources, compile_cues, append_references
from backend.app.sound_design import create_cue_sound_design


SOURCES = brief_sources('Smithsonian: https://www.smithsonianjourneys.org/sphinx/\nNational Army Museum: https://collection.nam.ac.uk/detail.php?acc=1975-03-63-5-197')


def test_map_camera_requires_valid_coordinates_and_measured_time():
    data = {'kind':'map_flyover','scene_index':0,'start_frame':0,'frames':120,'title':'Bir efsanenin izinde',
            'location':{'latitude':29.98,'longitude':31.14,'label':'Giza','country':'Mısır','country_code':'EGY'},
            'reason':'Olayın geçtiği coğrafyaya yaklaşarak hikâyeyi konumlandırır.'}
    assert compile_cues({'graphics':[data]},[5],[])[0][0]['location']['country_code']=='EGY'
    with pytest.raises(ValueError): GraphicCue.model_validate({**data,'location':{**data['location'],'latitude':200}})
    with pytest.raises(ValueError): GraphicCue.model_validate({**data,'location':None})
    with pytest.raises(ValueError): compile_cues({'graphics':[data]},[3],[])


def cue(**changes):
    return {'kind': 'timeline', 'scene_index': 1, 'start_frame': 15, 'frames': 60,
            'events': [{'year': 1737, 'label': 'Norden’in tasviri'}, {'year': 1798, 'label': 'Mısır seferi'}],
            'reason': 'Anlatılan tarih çelişkisini karşılaştırır.', **changes}


def test_cues_follow_cumulative_measured_narration_frames():
    graphics, sounds = compile_cues({'graphics': [cue()], 'sound_cues': [{'kind': 'tick', 'scene_index': 1, 'start_frame': 30, 'frames': 6, 'reason': 'Kanıtın ortaya çıkışını vurgular.'}]}, [1.111, 3.333], SOURCES)
    assert graphics[0]['start_frame'] == 48
    assert sounds[0]['start_frame'] == 63
    manifest = RenderManifest(style='auto', duration_frames=133, clips=[{'file': 'shot-000.mp4', 'start_frame': 0, 'frames': 33, 'scene_index': 0}, {'file': 'shot-001.mp4', 'start_frame': 33, 'frames': 100, 'scene_index': 1}], graphics=graphics, sound_cues=sounds, sources=SOURCES)
    assert manifest.graphics[0].events[1].year - manifest.graphics[0].events[0].year == 61


@pytest.mark.parametrize('change', [{'scene_index': 7}, {'start_frame': 80}, {'frames': 120}])
def test_cues_cannot_escape_their_narration_scene(change):
    with pytest.raises(ValueError, match='sahne'):
        compile_cues({'graphics': [cue(**change)]}, [1, 3], SOURCES)


def test_manifest_cannot_accept_absolute_cue_in_another_scene():
    with pytest.raises(ValueError, match='sahne'):
        RenderManifest(style='auto', duration_frames=120, clips=[{'file': 'shot-000.mp4', 'start_frame': 0, 'frames': 30, 'scene_index': 0}, {'file': 'shot-001.mp4', 'start_frame': 30, 'frames': 90, 'scene_index': 1}], graphics=[cue(start_frame=0)])


def test_overlapping_graphics_and_unregistered_sources_are_rejected():
    with pytest.raises(ValueError, match='üst üste'):
        compile_cues({'graphics': [cue(), cue(start_frame=30)]}, [1, 3], SOURCES)
    card = cue(kind='source_card', events=[], source_ids=['source-99'])
    with pytest.raises(ValueError, match='kayıtlı'):
        compile_cues({'graphics': [card]}, [1, 3], SOURCES)


@pytest.mark.parametrize('changes', [
    {'events': [{'year': 1798, 'label': 'Sefer'}, {'year': 1737, 'label': 'Çizim'}]},
    {'events': [{'year': 1737, 'label': 'Çizim'}]},
    {'kind': 'source_card', 'events': []},
    {'kind': 'spotlight', 'events': []},
    {'kind': 'spotlight', 'events': [], 'region': {'x': .5, 'y': .85, 'width': .2, 'height': .2}},
    {'kind': 'kinetic_text', 'title': '', 'events': []},
    {'kind': 'arbitrary_code'},
])
def test_graphic_payloads_are_bounded_and_declarative(changes):
    with pytest.raises(ValueError):
        GraphicCue.model_validate(cue(**changes))


def test_sources_preserve_explicit_labels_links_and_deduplicate():
    assert SOURCES[0]['label'] == 'Smithsonian'
    assert SOURCES[1]['label'] == 'National Army Museum'
    assert len(brief_sources('https://example.org/ https://example.org/')) == 1
    with pytest.raises(ValueError):
        brief_sources('https://user:password@example.org/')
    description = append_references('Kaynaklı bir belgesel.', SOURCES)
    assert all(s['url'] in description for s in SOURCES)
    assert append_references(description, SOURCES) == description
    assert len(append_references('a'*4500, SOURCES)) <= 4500


def test_old_plans_and_classic_manifest_still_work_without_cues():
    plan = AutoEditPlan(observations=[{'shot_id': 'shot-000', 'verdict': 'pass', 'observation': 'Görüntüde bir bina görülüyor.'}], segments=[{'shot_id': 'shot-000', 'source_in_frame': 0, 'frames': 30, 'reason': 'Sahneyi kesintisiz gösterir.'}], rationale='Kaynak sahne anlatımını kesintisiz destekliyor.')
    assert plan.graphics == [] and plan.sound_cues == []
    for style in ('classic', 'auto'):
        manifest = RenderManifest(style=style, duration_frames=30, clips=[{'file': 'shot-000.mp4', 'start_frame': 0, 'frames': 30}])
        assert manifest.sources == []


def test_original_sound_cues_leave_pauses_silent_and_keep_duration(tmp_path):
    np = pytest.importorskip('numpy')
    target = tmp_path / 'cues.wav'
    create_cue_sound_design(3, [{'kind': 'tick', 'start_frame': 30, 'frames': 6, 'gain': .06}], target)
    with wave.open(str(target)) as wav:
        assert wav.getnframes() == 3*24000
        data = np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2')
    assert np.count_nonzero(data[:24000]) == 0
    assert np.count_nonzero(data[24000:28800]) > 0
    assert np.count_nonzero(data[28800:]) == 0
    assert np.max(np.abs(data.astype(float))) < .15*32767


def test_auto_renderer_passes_graphics_words_and_original_speed_audio(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    from backend.app import remotion_renderer as renderer, automatic_edit, sound_design
    from backend.app.config import settings
    root = tmp_path/'remotion'
    (root/'production/node_modules/@remotion/renderer').mkdir(parents=True)
    monkeypatch.setattr(settings(), 'remotion_root', root)
    monkeypatch.setattr(renderer.shutil, 'which', lambda _: '/node')
    folder = tmp_path/'run'
    folder.mkdir()
    (folder/'shot-000.mp4').write_bytes(b'owned clip')
    audio = folder/'voice.wav'
    audio.write_bytes(b'owned narration')
    srt = folder/'captions.srt'
    srt.write_text('1\n00:00:00,000 --> 00:00:01,000\nKanıt\n', encoding='utf-8')
    srt.with_suffix('.words.json').write_text(json.dumps({'scenes': [{'duration_seconds': 3, 'words': [{'text': 'Kanıt', 'startMs': 0, 'endMs': 1000}]}]}))
    decision = {'opening_title': '', 'ending_title': '', 'observations': [], 'rationale': 'Kaynak bilgisiyle desteklenen görsel anlatım.',
                'graphics': [cue(scene_index=0, start_frame=0, frames=90)],
                'sound_cues': [{'kind': 'tick', 'scene_index': 0, 'start_frame': 15, 'frames': 6, 'gain': .06, 'reason': 'Kanıtın ortaya çıkışını vurgular.'}]}
    clips = [{'file': 'shot-000.mp4', 'scene_index': 0, 'start_frame': 0, 'frames': 90}]
    monkeypatch.setattr(automatic_edit, 'prepare_automatic', lambda *a, **k: (decision, clips))
    monkeypatch.setattr(sound_design, 'create_cue_sound_design', lambda duration, cues, target: target.write_bytes(b'original effects'))
    run = SimpleNamespace(outputs={'_edit_style': 'auto', 'script': {'format': 'documentary'}, 'motion': {'plan': {'shots': [{'shot_id': 'shot-000', 'scene_index': 0}]}, 'clips': {'shot-000': {'file': 'shot-000.mp4'}}}})
    commands = []
    monkeypatch.setattr(renderer.media, 'command', lambda args, *a, **k: commands.append(args))
    monkeypatch.setattr(renderer.media, 'validate_final', lambda *a, **k: {'passed': True})
    project = SimpleNamespace(duration=3, topic='Smithsonian: https://www.smithsonianjourneys.org/sphinx/')
    report = renderer.render_production(run, project, folder, [], [audio], [3], srt, lambda: None, None, {}, None, {})
    manifest = json.loads((folder/'render-manifest.json').read_text(encoding='utf-8'))
    assert manifest['graphics'][0]['start_frame'] == 0
    assert manifest['words'][0]['text'] == 'Kanıt'
    assert manifest['reconstruction_label'] == ''
    assert report['graphics']['sound_cues'] == 1
    assert '-c:v' in commands[-1] and 'atempo' not in str(commands)
