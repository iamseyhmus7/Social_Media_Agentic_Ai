import pytest
from pydantic import ValidationError

from backend.app.schemas import AutoEditPlan, EditLook


@pytest.mark.parametrize('length', [1201, 1575, 4096])
def test_valid_look_survives_final_plan_assembly(length):
    look = EditLook(rationale='r' * length, creative_direction='c' * length)
    plan = AutoEditPlan.model_validate({
        **look.model_dump(),
        'observations': [{'shot_id': 'shot-000', 'verdict': 'pass',
                          'observation': 'The source matches the scene.'}],
        'segments': [{'shot_id': 'shot-000', 'source_in_frame': 0, 'frames': 30,
                      'reason': 'The source matches the narration.'}],
    })
    assert plan.rationale == look.rationale
    assert plan.creative_direction == look.creative_direction


@pytest.mark.parametrize('field', ['rationale', 'creative_direction'])
def test_look_rejects_text_beyond_final_plan_limit(field):
    with pytest.raises(ValidationError):
        EditLook.model_validate({'rationale': 'A valid editorial rationale.', field: 'x' * 4097})
