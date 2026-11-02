from copy import deepcopy
import pytest
from backend.app.storyboard import allocation, direct_story
from backend.app.automatic_edit import scene_frames, validate_decision
from backend.app.schemas import AutoEditPlan, Revision


def test_story_allocation_covers_measured_audio_and_has_distinct_references():
    durations = [4.2, 6.1, 3.8, 5.2, 4.8, 6.0]
    class LLM:
        def generate(self, schema, role, context):
            return {'shots': [{**s, 'scene_index': 7, 'duration_seconds': 1, 'reference_prompt': 'A woman wearing a red coat in a small apartment.', 'motion_prompt': 'The woman turns her head toward the table.', 'purpose': 'Nesneyi fark etme', 'expected_action': 'Kadın masaya bakıyor.'} for s in context['allocation']]}
    plan = direct_story(LLM(), {'continuity': 'fixed character'}, durations)
    assert len(plan['shots']) >= 9
    assert [s['image_index'] for s in plan['shots']] == list(range(len(plan['shots'])))
    for i, duration in enumerate(durations):
        assert sum(s['duration_seconds'] for s in plan['shots'] if s['scene_index'] == i) == pytest.approx(duration)
    assert all(s['duration_seconds'] <= 4.8 for s in plan['shots'])


def edit_fixture():
    shots = [{'shot_id': 'shot-000', 'scene_index': 0}, {'shot_id': 'shot-001', 'scene_index': 0}, {'shot_id': 'shot-002', 'scene_index': 1}]
    payload = {'observations': [{'shot_id': s['shot_id'], 'verdict': 'pass', 'observation': 'Kadın masaya doğru bakıyor.'} for s in shots], 'segments': [{'shot_id': ident, 'source_in_frame': 0, 'frames': frames, 'reason': 'Eylem ve tepkiyi aynı olay içinde bağlıyor.'} for ident, frames in [('shot-001', 45), ('shot-000', 75), ('shot-002', 60)]], 'rationale': 'Önce bakış ve eylem, ardından olayın sonucu gösterilir.'}
    return shots, AutoEditPlan.model_validate(payload).model_dump(), {'shot-000': 90, 'shot-001': 90, 'shot-002': 65}, [4, 2]


def test_auto_edit_allows_content_driven_reordering_and_trims():
    shots, plan, available, durations = edit_fixture()
    assert validate_decision(plan, shots, available, durations)
    assert scene_frames([1.111, 2.222, 3.333]) == [33, 67, 100]


def test_editor_honors_map_opening_and_no_source_cards():
    shots, plan, available, durations = edit_fixture()
    with pytest.raises(ValueError,match='map_flyover'):
        validate_decision(plan, shots, available, durations, preferences={'map_intro':True})
    plan['graphics']=[{'kind':'source_card','scene_index':0,'start_frame':0,'frames':60,'source_ids':['source-01'],'reason':'Tarihsel kanıtın kaynağını görünür kılar.'}]
    with pytest.raises(ValueError,match='kaynak kartı'):
        validate_decision(plan, shots, available, durations, preferences={'show_sources':False},sources=[{'id':'source-01'}])


@pytest.mark.parametrize('failure', ['bounds', 'timing', 'order', 'rejected', 'unobserved', 'unknown'])
def test_auto_edit_rejects_ungrounded_or_unsynchronized_timeline(failure):
    shots, plan, available, durations = edit_fixture()
    if failure == 'bounds': plan['segments'][0]['source_in_frame'] = 50
    if failure == 'timing': plan['segments'][0]['frames'] -= 1
    if failure == 'order': plan['segments'].reverse()
    if failure == 'rejected': plan['observations'][0]['verdict'] = 'reject'
    if failure == 'unobserved': plan['observations'].pop()
    if failure == 'unknown': plan['segments'][0]['shot_id'] = 'shot-999'
    with pytest.raises(ValueError): validate_decision(plan, shots, available, durations)
