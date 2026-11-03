from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from contextvars import ContextVar
from contextlib import contextmanager
from typing import Literal
from .schemas import VoiceProfile


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    database_url: str = Field(default='sqlite:///./data/sahne.db', repr=False)
    media_root: Path = Path('data/media')
    queue_mode: str = 'local'
    broker_url: str = 'redis://localhost:6379/0'
    app_origin: str = 'http://127.0.0.1:5173'
    cookie_secure: bool = False
    allow_registration: bool = True
    token_encryption_key: str = Field(default='', repr=False)
    evren_api_key: str = Field(default='', repr=False)
    evren_base_url: str = ''
    evren_model: str = ''
    evren_media_model: str = ''
    evren_media_model2: str = ''
    evren_supervisor_model: str = ''
    agent_protocol: str = 'structured_actions'
    video_execution_policy: str = 'planned_v1'
    supervisor_policy: str = 'model_v4'
    supervisor_timeout_seconds: int = Field(default=180, ge=15, le=600)
    kaggle_motion_profile: str = 'dual_required'
    engagement_policy: int = 1
    script_editorial_policy: int = 2
    video_edit_policy: str = 'scenes_v3'
    editor_parallelism: int = Field(default=3, ge=1, le=4)
    # Zero disables only the editor's response/read deadline.
    editor_call_timeout_seconds: int = Field(default=0, ge=0)
    editor_streaming_enabled: bool = True
    video_review_policy: Literal['technical_only', 'model'] = 'technical_only'
    agent_max_turns: int = Field(default=80, ge=12, le=160)
    agent_task_max_turns: int = Field(default=12, ge=3, le=24)
    evren_response_timeout_seconds: int = Field(default=1800, ge=120, le=7200)
    evren_audio_input_verified: bool = False
    evren_video_input_verified: bool = False
    evren_protocol: str = 'unconfigured'
    evren_contract_verified: bool = False
    evren_completions_path: str = '/chat/completions'
    image_model: str = 'segmind/SSD-1B'
    image_device: str = 'auto'
    video_provider: str = 'none'
    editor_provider: str = 'ffmpeg'
    kaggle_username: str = ''
    kaggle_api_token: str = Field(default='', repr=False)
    kaggle_key: str = Field(default='', repr=False)
    kaggle_model_source: str = ''
    kaggle_runtime_source: str = ''
    kaggle_poll_seconds: int = Field(default=30, ge=10, le=300)
    kaggle_timeout_seconds: int = Field(default=7200, ge=300, le=43200)
    remotion_root: Path = Path('remotion')
    node_bin: str = 'node'
    remotion_browser_executable: str = ''
    remotion_render_concurrency: int = Field(default=2,ge=1,le=4)
    remotion_output_fps: Literal[30, 60] = 60
    image_provider: str = 'local'
    cloudflare_account_id: str = ''
    cloudflare_api_token: str = Field(default='', repr=False)
    cloudflare_image_steps: int = 4
    tts_provider: Literal['elevenlabs'] = 'elevenlabs'
    elevenlabs_api_key: str = Field(default='', repr=False)
    elevenlabs_voice_id: str = ''
    elevenlabs_model: str = 'eleven_v4'
    elevenlabs_voice_profiles: list[VoiceProfile] = Field(default_factory=list)
    elevenlabs_voice_source: str = 'api'
    elevenlabs_free_voices_only: bool = True
    elevenlabs_turkish_only: bool = True
    elevenlabs_preview_checks: int = Field(default=3, ge=0, le=5)
    elevenlabs_casting_enabled: bool = True
    ffmpeg_bin: str = 'ffmpeg'
    ffprobe_bin: str = 'ffprobe'
    subtitle_font: str = 'DejaVu Sans'
    subtitle_font_file: str = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
    youtube_client_id: str = ''
    youtube_client_secret: str = Field(default='', repr=False)
    youtube_redirect_uri: str = 'http://127.0.0.1:5173/api/v1/youtube/callback'
    youtube_api_key: str = Field(default='', repr=False)
    rss_feeds: str = ''
    story_research_enabled: bool = False
    story_research_user_agent: str = ''
    max_disk_gb: float = 20
    session_hours: int = 24


@lru_cache
def _base_settings():
    return Settings()


_run_settings = ContextVar('run_settings', default=None)


def settings():
    return _run_settings.get() or _base_settings()


def snapshot_settings():
    c = settings()
    result = {key: getattr(c, key) for key in ('evren_model', 'evren_media_model', 'agent_protocol', 'agent_max_turns', 'agent_task_max_turns', 'evren_audio_input_verified', 'evren_video_input_verified', 'image_provider', 'image_model', 'image_device', 'tts_provider', 'elevenlabs_model', 'elevenlabs_voice_source', 'elevenlabs_voice_id', 'video_provider', 'editor_provider', 'kaggle_username', 'kaggle_runtime_source', 'cloudflare_image_steps')}
    result['elevenlabs_voice_profiles'] = [p.model_dump() for p in c.elevenlabs_voice_profiles]
    result.update(video_execution_policy=c.video_execution_policy, kaggle_motion_profile=c.kaggle_motion_profile, video_edit_policy=c.video_edit_policy, editor_parallelism=c.editor_parallelism, editor_call_timeout_seconds=c.editor_call_timeout_seconds, remotion_render_concurrency=c.remotion_render_concurrency)
    result.update(supervisor_policy=c.supervisor_policy, supervisor_timeout_seconds=c.supervisor_timeout_seconds)
    result['editor_streaming_enabled'] = c.editor_streaming_enabled
    result['remotion_output_fps'] = c.remotion_output_fps
    result['video_review_policy'] = c.video_review_policy
    result['engagement_policy'] = c.engagement_policy
    result['script_editorial_policy'] = c.script_editorial_policy
    result['story_research_enabled'] = c.story_research_enabled
    result['elevenlabs_turkish_only'] = c.elevenlabs_turkish_only
    result['evren_media_model2'] = c.evren_media_model2
    result['evren_supervisor_model'] = c.evren_supervisor_model or c.evren_model
    result.update(elevenlabs_free_voices_only=c.elevenlabs_free_voices_only, elevenlabs_casting_enabled=c.elevenlabs_casting_enabled, elevenlabs_preview_checks=c.elevenlabs_preview_checks)
    return result


@contextmanager
def use_run_settings(snapshot):
    values = dict(snapshot)
    values.setdefault('video_execution_policy', 'legacy')
    values.setdefault('supervisor_policy', 'planned_v1')
    values.setdefault('editor_streaming_enabled', False)
    values.setdefault('video_review_policy', 'model')
    values.setdefault('evren_supervisor_model', values.get('evren_model', _base_settings().evren_model))
    values.setdefault('kaggle_motion_profile', 'legacy_fp32')
    values.setdefault('engagement_policy', 0)
    values.setdefault('script_editorial_policy', 0)
    values.setdefault('story_research_enabled', False)
    values.setdefault('elevenlabs_turkish_only', False)
    values.setdefault('evren_media_model2', '')
    values.setdefault('video_edit_policy', 'weighted_v2')
    values.setdefault('editor_parallelism', 1)
    values.setdefault('remotion_render_concurrency', 2)
    values.setdefault('remotion_output_fps', 30)
    if 'elevenlabs_voice_profiles' in values:
        values['elevenlabs_voice_profiles'] = [VoiceProfile.model_validate(p) for p in values['elevenlabs_voice_profiles']]
    token = _run_settings.set(_base_settings().model_copy(update=values))
    try:
        yield
    finally:
        _run_settings.reset(token)
