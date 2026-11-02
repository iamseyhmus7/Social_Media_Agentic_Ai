"""Model-free regression against Diffusers' real I2V timestep handling."""
import pytest

diffusers = pytest.importorskip('diffusers')
torch = pytest.importorskip('torch')
np = pytest.importorskip('numpy')
from diffusers import FlowMatchEulerDiscreteScheduler
from diffusers.pipelines.ltx.pipeline_ltx_image2video import retrieve_timesteps
from backend.kaggle.generate import distilled_scheduler


def test_distilled_schedule_works_with_pipeline_supplied_sigmas():
    sigmas = np.linspace(1, 1 / 8, 8)
    expected = torch.tensor([1000, 993.75, 987.5, 981.25, 975, 909.375, 725, 421.875])
    # This was the failing production call: the 0.35.2 pipeline passes both.
    with pytest.raises(ValueError, match='Only one'):
        retrieve_timesteps(FlowMatchEulerDiscreteScheduler(), 8, 'cpu',
                           timesteps=expected.tolist(), sigmas=sigmas)
    scheduler = distilled_scheduler(FlowMatchEulerDiscreteScheduler, {'sampler': 'LinearQuadratic'})
    timesteps, count = retrieve_timesteps(scheduler, 8, 'cpu', sigmas=sigmas, mu=1.0)
    assert count == 8
    torch.testing.assert_close(timesteps, expected)
    torch.testing.assert_close(scheduler.sigmas[:-1], expected / 1000)
    assert scheduler.sigmas[-1] == 0
    # Pipeline reuse must reset scheduler state for every shot.
    scheduler._step_index = 5
    retrieve_timesteps(scheduler, 8, 'cpu', sigmas=sigmas)
    assert scheduler.step_index is None


def test_distilled_schedule_rejects_an_incompatible_step_count():
    scheduler = distilled_scheduler(FlowMatchEulerDiscreteScheduler, {'sampler': 'LinearQuadratic'})
    with pytest.raises(ValueError, match='eight-step'):
        retrieve_timesteps(scheduler, 50, 'cpu', sigmas=[1] * 50)
