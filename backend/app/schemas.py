from typing import Literal, get_args
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator, ValidationInfo


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Login(Strict):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)


class NewUser(Login):
    password: str = Field(min_length=12, max_length=200)
    name: str = Field(min_length=1, max_length=100)
    role: Literal['admin', 'member'] = 'member'


class Registration(Login):
    password: str = Field(min_length=12, max_length=200)
    name: str = Field(min_length=1, max_length=100)

    @field_validator('email')
    @classmethod
    def valid_email(cls, value):
        import re
        value = value.strip().lower()
        if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', value):
            raise ValueError('Geçerli bir e-posta adresi gir.')
        return value

    @field_validator('name')
    @classmethod
    def valid_name(cls, value):
        if not value.strip():
            raise ValueError('Adını gir.')
        return value.strip()


class DeleteProjects(Strict):
    project_ids: list[str] = Field(min_length=1, max_length=100)


class NewProject(Strict):
    topic: str = Field(min_length=5, max_length=4000)
    audience: str = Field(default='Genel izleyici', max_length=300)
    tone: str = Field(default='İlgi çekici ve bilgilendirici', max_length=80)
    duration: Literal[30, 45, 60] | None = None


class Plan(Strict):
    goal: str = Field(min_length=3, max_length=1000)
    checks: list[str] = Field(min_length=1, max_length=8)


class RunOptions(Strict):
    script_only: bool = False
    image_model_policy: Literal['auto','klein','lucid'] = 'klein'


class Strategy(Strict):
    title: str = Field(min_length=3, max_length=200)
    angle: str = Field(min_length=5, max_length=1200)
    audience: str = Field(min_length=2, max_length=300)
    plan_revision_proposals: list[str] = Field(default_factory=list, max_length=6)


class Scene(Strict):
    title: str = Field(min_length=2, max_length=80)
    narration: str = Field(min_length=5, max_length=1200)
    visual_prompt: str = Field(min_length=10, max_length=1500)


class Script(Strict):
    hook: str = Field(min_length=3, max_length=300)
    scenes: list[Scene] = Field(min_length=3, max_length=8)
    cta: str = Field(min_length=3, max_length=800, description='Onaylı kapanışı yansıt; ayrı slogan veya seslendirilecek ek metin üretme.')


class StoryScene(Scene):
    action: str = Field(min_length=10, max_length=500)
    state_before: str = Field(min_length=3, max_length=400)
    state_after: str = Field(min_length=3, max_length=400)


class StoryScript(Script):
    format: Literal['narrative', 'educational', 'documentary', 'travel', 'advertisement', 'entertainment', 'explainer', 'other']
    continuity: str = Field(min_length=20, max_length=1500)
    scenes: list[StoryScene] = Field(min_length=5, max_length=8)


def timed_story_script(target):
    class TimedStory(StoryScript):
        @model_validator(mode='after')
        def word_budget(self):
            count = sum(len(s.narration.split()) for s in self.scenes)
            if abs(count - target) > 2:
                raise ValueError(f'Anlatım {target-2}–{target+2} kelime olmalı; {count} bulundu. Olayları ve sahne sayısını koru.')
            return self
    return TimedStory


class Copy(Strict):
    title: str = Field(min_length=3, max_length=100)
    description: str = Field(min_length=10, max_length=4500)
    hashtags: list[str] = Field(min_length=1, max_length=12)
    instagram: str = Field(min_length=5, max_length=2000)
    tiktok: str = Field(min_length=5, max_length=2000)


class PublicationCopy(Copy):
    hashtags: list[str] = Field(default_factory=list, max_length=12)


def script_with_word_target(target):
    class TimedScript(Script):
        scenes: list[Scene] = Field(min_length=3, max_length=8, description=f'Tüm narration alanlarında toplam {target-2}–{target+2} kelime kullan.')

        @model_validator(mode='after')
        def word_budget(self):
            count = sum(len(s.narration.split()) for s in self.scenes)
            if abs(count - target) > 2:
                raise ValueError(f'Anlatım {count} kelime; gereken aralık {target-2}–{target+2} kelime. Anlatım uzunluğunu düzelt.')
            return self
    return TimedScript


class ShotPlan(Strict):
    shot_id: str = Field(pattern=r'^shot-[0-9]{3}$')
    scene_index: int = Field(ge=0, le=7)
    duration_seconds: float = Field(gt=0, le=5)
    motion_prompt: str = Field(min_length=10, max_length=1800)
    camera: Literal['locked', 'push_in', 'pull_back', 'pan_left', 'pan_right'] = 'locked'


class MotionPlan(Strict):
    shots: list[ShotPlan] = Field(min_length=1, max_length=32)

    @model_validator(mode='after')
    def unique_shots(self):
        if len({s.shot_id for s in self.shots}) != len(self.shots):
            raise ValueError('Çekim kimlikleri benzersiz olmalı.')
        return self


class StoryShot(ShotPlan):
    reference_prompt: str = Field(min_length=20, max_length=1100)
    purpose: str = Field(min_length=5, max_length=300)
    expected_action: str = Field(min_length=5, max_length=400)
    state_before: str = Field(default='', max_length=500)
    state_after: str = Field(default='', max_length=500)
    preserve: str = Field(default='', max_length=500)
    continuity_group: str = Field(default='', max_length=80)
    image_model: Literal['klein', 'lucid'] = 'klein'
    model_reason: str = Field(default='', max_length=300)


class Storyboard(Strict):
    shots: list[StoryShot] = Field(min_length=1, max_length=32)
    visual_identity: str = Field(default='', max_length=2000)


class ImageReview(Strict):
    verdict: Literal['pass', 'uncertain', 'reject']
    findings: list[str] = Field(default_factory=list, max_length=8)
    correction: str = Field(default='', max_length=1000)


class SourceClipReview(ImageReview):
    repair_stage: Literal['visual','motion'] = 'motion'

    @field_validator('findings', mode='before')
    @classmethod
    def limit_findings(cls, value):
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            return value[:8]
        return value


class ReferencePatch(Strict):
    active: bool


class ShotChange(Strict):
    run_id: str
    action: Literal['image', 'motion', 'pin']
    instructions: str = Field(default='', max_length=1500)
    shot_ids: list[str] = Field(default_factory=list,max_length=32)


class MediaReviewAnswer(Strict):
    shot_id: str = Field(pattern=r'^shot-[0-9]{3}$')
    asset_id: str
    accept: bool


class ClipObservation(Strict):
    shot_id: str = Field(pattern=r'^shot-[0-9]{3}$')
    verdict: Literal['pass', 'uncertain', 'reject']
    observation: str = Field(min_length=10, max_length=500)


CameraKind = Literal['locked', 'push_in', 'pull_back', 'pan_left', 'pan_right', 'shake',
                     'tilt_up', 'tilt_down', 'roll_left', 'roll_right', 'snap_zoom', 'arc']
TransitionKind = Literal['cut', 'dissolve', 'push', 'reveal', 'whip', 'zoom', 'light_sweep',
                         'iris', 'diagonal_wipe', 'blur_dissolve', 'zoom_out', 'slide_up',
                         'wipe', 'flip', 'clock_wipe']
TypographyKind = Literal['rise', 'words', 'characters', 'mask', 'blur_in', 'elastic',
                         'typewriter', 'flip', 'tracking']
SceneTemplate = Literal['none', 'editorial', 'glass', 'blueprint', 'cinema']


class CameraMotion(Strict):
    kind: CameraKind = 'locked'
    strength: float = Field(default=.04, ge=0, le=.15)


class Object3D(Strict):
    kind: Literal['cube', 'sphere', 'torus', 'icosahedron']
    color: str = Field(default='#D5AD72', pattern=r'^#[0-9a-fA-F]{6}$')
    position: Literal['left', 'center', 'right'] = 'right'
    scale: float = Field(default=1, ge=.5, le=1.3)
    speed: float = Field(default=.4, ge=0, le=1)
    wireframe: bool = False


class SceneDesign(Strict):
    camera: CameraMotion = Field(default_factory=CameraMotion)
    layout: Literal['full', 'split', 'inset'] = 'full'
    secondary_shot_id: str | None = Field(default=None, pattern=r'^shot-[0-9]{3}$')
    typography: TypographyKind = 'rise'
    font_family: Literal['sans', 'serif'] = 'sans'
    text_style: Literal['solid', 'outline', 'extruded', 'accent'] = 'solid'
    template: SceneTemplate = 'none'
    object_3d: Object3D | None = None
    title_size: int = Field(default=64, ge=36, le=110)
    lighting: Literal['none', 'glow', 'sweep', 'gradient'] = 'none'
    particles: int = Field(default=0, ge=0, le=24)
    effects: list[Literal['color_grade', 'glow', 'vignette']] = Field(default_factory=list, max_length=3)
    effect_strength: float = Field(default=.35, ge=0, le=1)
    motion_blur: bool = False
    lottie_asset: Literal['none', 'pulse_ring', 'flow_arrow'] = 'none'
    annotation: Literal['none', 'underline', 'circle', 'highlight'] = 'none'
    annotation_text: str = Field(default='', max_length=24)

    @model_validator(mode='after')
    def secondary_required(self):
        if self.layout != 'full' and not self.secondary_shot_id:
            raise ValueError('Bölünmüş veya detay kadrajı ikinci bir doğrulanmış çekim gerektirir.')
        if self.motion_blur and self.effects:
            raise ValueError('Aynı çekimde effects ve motion_blur birlikte desteklenmiyor; birini seç veya farklı çekimlere uygula.')
        return self


SCENE_CAPABILITIES = {
    'camera': list(get_args(CameraKind)),
    'transitions': list(get_args(TransitionKind)),
    'layout': ['full', 'split', 'inset'], 'typography': list(get_args(TypographyKind)),
    'font_family': ['sans', 'serif'], 'text_style': ['solid', 'outline', 'extruded', 'accent'],
    'templates': list(get_args(SceneTemplate)),
    'objects_3d': ['cube', 'sphere', 'torus', 'icosahedron'],
    'lighting': ['none', 'glow', 'sweep', 'gradient'], 'particles_max': 24,
    'effects': ['color_grade', 'glow', 'vignette'],
    'effect_strength': '0–1; restrained default 0.35',
    'motion_blur': 'optional; camera/footage only, keep captions sharp; cannot share a segment with effects; choose one or use separate segments',
    'lottie_assets': ['none', 'pulse_ring', 'flow_arrow'],
    'annotation': ['none', 'underline', 'circle', 'highlight'],
    'annotation_text': 'optional short verbatim word/phrase from clip.title; empty emphasizes its first word',
    'editing_guidance': 'Select effects for narrative purpose, not a quota. Lottie assets are local symbolic graphics; annotations emphasize clip.title. All timing is in 30-fps editorial ticks, independently of output FPS.',
    'unavailable': ['arbitrary_3d_models', 'optical_morph', 'depth_parallax', 'generated_code'],
}


class SegmentDirection(Strict):
    shot_id: str = Field(pattern=r'^shot-[0-9]{3}$')
    transition: TransitionKind = 'cut'
    title: str = Field(default='', max_length=65)
    transition_frames: int = Field(default=7, ge=3, le=18)
    punch_in: bool = False
    source_in_frame: int = Field(ge=0)
    reason: str = Field(min_length=10, max_length=400)
    design: SceneDesign = Field(default_factory=SceneDesign)


class AutoSegment(SegmentDirection):
    frames: int = Field(gt=0, le=1815)


class WeightedSegment(SegmentDirection):
    duration_weight: float = Field(gt=0, le=100, allow_inf_nan=False)


class EvidenceSource(Strict):
    id: str = Field(pattern=r'^source-[0-9]{2}$')
    label: str = Field(min_length=1, max_length=90)
    url: str = Field(min_length=10, max_length=1000)

    @field_validator('url')
    @classmethod
    def public_reference(cls, value):
        from urllib.parse import urlsplit
        parts = urlsplit(value)
        if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
            raise ValueError('Kaynak yalnızca kimlik bilgisi içermeyen HTTPS bağlantısı olabilir.')
        return value


class GraphicPalette(Strict):
    background: str = Field(default='#132434', pattern=r'^#[0-9a-fA-F]{6}$')
    accent: str = Field(default='#D5AD72', pattern=r'^#[0-9a-fA-F]{6}$')
    text: str = Field(default='#F5F0E5', pattern=r'^#[0-9a-fA-F]{6}$')


class TimelineEvent(Strict):
    year: int = Field(ge=-10000, le=3000)
    label: str = Field(min_length=1, max_length=45)


class SpotlightRegion(Strict):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=0.7)
    height: float = Field(gt=0, le=0.6)

    @model_validator(mode='after')
    def safe_region(self):
        if self.x-self.width/2 < .07 or self.x+self.width/2 > .86 or self.y-self.height/2 < .12 or self.y+self.height/2 > .71:
            raise ValueError('Vurgu bölgesi görüntünün güvenli alanında olmalı.')
        return self


class MapLocation(Strict):
    latitude: float = Field(ge=-80, le=80)
    longitude: float = Field(ge=-180, le=180)
    label: str = Field(min_length=1, max_length=40)
    country: str = Field(default='', max_length=35)
    country_code: str = Field(default='', pattern=r'^([A-Z]{3})?$')


class GraphicCue(Strict):
    kind: Literal['kinetic_text', 'timeline', 'spotlight', 'source_card', 'map_flyover']
    scene_index: int = Field(ge=0, le=7)
    start_frame: int = Field(default=0, ge=0, le=1815)
    frames: int = Field(ge=15, le=1815)
    title: str = Field(default='', max_length=90)
    detail: str = Field(default='', max_length=160)
    events: list[TimelineEvent] = Field(default_factory=list, max_length=4)
    region: SpotlightRegion | None = None
    location: MapLocation | None = None
    source_ids: list[str] = Field(default_factory=list, max_length=3)
    reason: str = Field(min_length=10, max_length=400)

    @model_validator(mode='after')
    def appropriate_payload(self):
        if (self.kind == 'map_flyover') != (self.location is not None):
            raise ValueError('Harita kamerası geçerli bir konum gerektirir; diğer grafiklerde konum kullanılamaz.')
        if self.kind == 'map_flyover' and self.frames < 90:
            raise ValueError('Harita açılışı en az üç saniye sürmeli.')
        if self.kind == 'timeline':
            years = [e.year for e in self.events]
            if len(years) < 2 or years != sorted(set(years)):
                raise ValueError('Zaman çizelgesi en az iki farklı, sıralı tarih gerektirir.')
        elif self.events:
            raise ValueError('Tarihler yalnızca zaman çizelgesinde kullanılabilir.')
        if (self.kind == 'spotlight') != (self.region is not None):
            raise ValueError('Vurgu maskesi açık bir görüntü bölgesi gerektirir.')
        if self.kind == 'source_card' and not self.source_ids:
            raise ValueError('Kaynak kartı kayıtlı kaynak gerektirir.')
        if self.kind == 'source_card' and self.frames < 60:
            raise ValueError('Kaynak kartı en az iki saniye görünür kalmalı.')
        if self.kind == 'kinetic_text' and not self.title.strip():
            raise ValueError('Hareketli metnin başlığı boş olamaz.')
        return self


class SoundCue(Strict):
    kind: Literal['tick', 'whoosh', 'impact']
    scene_index: int = Field(ge=0, le=7)
    start_frame: int = Field(ge=0, le=1815)
    frames: int = Field(ge=3, le=30)
    gain: float = Field(default=0.06, gt=0, le=0.15)
    reason: str = Field(min_length=10, max_length=400)


def validate_scene_cues(graphics, sounds, spans, source_ids, *, relative):
    intervals = []
    for cue in [*graphics, *sounds]:
        if cue.scene_index not in spans:
            raise ValueError('Grafik/ses işareti mevcut bir anlatım sahnesine bağlı olmalı.')
        start, end = spans[cue.scene_index]
        offset = cue.start_frame + (start if relative else 0)
        if offset < start or offset + cue.frames > end:
            raise ValueError('Grafik/ses işareti ölçülen sahne süresini aşıyor.')
        if isinstance(cue, GraphicCue):
            if not set(cue.source_ids).issubset(source_ids):
                raise ValueError('Grafik yalnızca kayıtlı kaynakları kullanabilir.')
            intervals.append((offset, offset + cue.frames))
    intervals.sort()
    if any(b[0] < a[1] for a, b in zip(intervals, intervals[1:])):
        raise ValueError('Grafikler okunabilirlik için aynı anda üst üste gelemez.')


class AudioMix(Strict):
    narration_gain: float = Field(default=1, ge=.4, le=1.5)
    music_gain: float = Field(default=.08, ge=0, le=.25)
    effects_gain: float = Field(default=1, ge=0, le=1)


EDIT_RATIONALE_MAX_LENGTH = 4096
EDIT_CREATIVE_DIRECTION_MAX_LENGTH = 4096


class EditDirection(Strict):
    opening_title: str = Field(default='', max_length=58)
    ending_title: str = Field(default='', max_length=45)
    rationale: str = Field(min_length=20, max_length=EDIT_RATIONALE_MAX_LENGTH)
    graphics: list[GraphicCue] = Field(default_factory=list, max_length=24)
    sound_cues: list[SoundCue] = Field(default_factory=list, max_length=24)
    palette: GraphicPalette = Field(default_factory=GraphicPalette)
    creative_direction: str = Field(default='', max_length=EDIT_CREATIVE_DIRECTION_MAX_LENGTH)
    caption_size: int = Field(default=58, ge=36, le=76)
    audio_mix: AudioMix = Field(default_factory=AudioMix)
    captions_enabled: bool = True


class AutoEditPlan(EditDirection):
    observations: list[ClipObservation] = Field(min_length=1, max_length=32)
    segments: list[AutoSegment] = Field(min_length=1, max_length=64)


class EditDecisionV2(EditDirection):
    version: Literal[2] = 2
    observations: list[ClipObservation] = Field(min_length=1, max_length=32)
    segments: list[WeightedSegment] = Field(min_length=1, max_length=64)


class EditLook(Strict):
    opening_title: str = Field(default='', max_length=58)
    ending_title: str = Field(default='', max_length=45)
    rationale: str = Field(min_length=20, max_length=EDIT_RATIONALE_MAX_LENGTH)
    palette: GraphicPalette = Field(default_factory=GraphicPalette)
    creative_direction: str = Field(default='', max_length=EDIT_CREATIVE_DIRECTION_MAX_LENGTH)
    caption_size: int = Field(default=58, ge=36, le=76)
    audio_mix: AudioMix = Field(default_factory=AudioMix)
    captions_enabled: bool = True


class ShotSuitability(Strict):
    shot_id: str = Field(pattern=r'^shot-[0-9]{3}$')
    verdict: Literal['pass','uncertain','reject']
    reason: str = Field(min_length=10,max_length=200)


class DraftRegion(Strict):
    x: float = Field(ge=0,le=1)
    y: float = Field(ge=0,le=1)
    width: float = Field(gt=0,le=.7)
    height: float = Field(gt=0,le=.6)


class GraphicIntent(GraphicCue):
    region: DraftRegion | None = None


class SceneEditDecision(Strict):
    reviews: list[ShotSuitability] = Field(min_length=1,max_length=32)
    segments: list[WeightedSegment] = Field(min_length=1,max_length=16)
    graphics: list[GraphicIntent] = Field(default_factory=list,max_length=4)
    sound_cues: list[SoundCue] = Field(default_factory=list,max_length=4)


class ClipPerception(Strict):
    observation: str = Field(min_length=10, max_length=4096)
    visible_defects: str = Field(default='', max_length=2048)
    motion_uncertainty: str = Field(min_length=5, max_length=1024)


class SceneEditRepair(Strict):
    segments: list[WeightedSegment] = Field(min_length=1, max_length=16)


class SceneCueRepair(Strict):
    graphics: list[GraphicCue] = Field(default_factory=list, max_length=24)
    sound_cues: list[SoundCue] = Field(default_factory=list, max_length=24)


class EditShot(Strict):
    shot_id: str = Field(pattern=r'^shot-[0-9]{3}$')
    transition: Literal['cut', 'dissolve', 'push', 'reveal', 'whip'] = 'cut'
    title: str = Field(default='', max_length=65)
    transition_frames: int = Field(default=7, ge=3, le=18)
    punch_in: bool = False


class EditPlan(Strict):
    shots: list[EditShot] = Field(min_length=1, max_length=32)
    opening_title: str = Field(default='', max_length=58)
    ending_title: str = Field(default='', max_length=45)


class DynamicEditPlan(EditPlan):
    opening_title: str = Field(min_length=5, max_length=58)
    ending_title: str = Field(min_length=5, max_length=45)

    @model_validator(mode='after')
    def controlled_rhythm(self):
        if any(s.transition not in ('cut', 'push', 'dissolve') for s in self.shots):
            raise ValueError('Kelime vurgulu kurgu yalnızca cut, push ve dissolve kullanır.')
        if self.shots[0].transition != 'cut':
            raise ValueError('İlk çekim cut olmalı.')
        if sum(s.transition == 'push' for s in self.shots) > 2:
            raise ValueError('En fazla iki push geçişi kullanılabilir.')
        if sum(s.transition == 'dissolve' for s in self.shots) > 1:
            raise ValueError('En fazla bir dissolve geçişi kullanılabilir.')
        if any(s.transition == 'push' and not 6 <= s.transition_frames <= 9 for s in self.shots):
            raise ValueError('Push geçişleri 6–9 kare olmalı.')
        if any(s.transition == 'dissolve' and not 9 <= s.transition_frames <= 12 for s in self.shots):
            raise ValueError('Dissolve geçişi 9–12 kare olmalı.')
        if sum(s.punch_in for s in self.shots) > 4:
            raise ValueError('En fazla dört çekimde kadraj kesmesi kullanılabilir.')
        return self


class EditorialChapter(Strict):
    scene_index: int = Field(ge=0, le=7)
    title: str = Field(min_length=2, max_length=32)
    phrase: str = Field(min_length=2, max_length=32)


class EditorialEditPlan(EditPlan):
    opening_title: str = Field(min_length=5, max_length=58)
    ending_title: str = Field(min_length=5, max_length=45)
    intro_beats: list[str] = Field(min_length=3, max_length=3)
    teaser_shots: list[str] = Field(min_length=3, max_length=3)
    chapters: list[EditorialChapter] = Field(min_length=1, max_length=8)

    @model_validator(mode='after')
    def editorial_bounds(self):
        if self.shots[0].transition != 'cut':
            raise ValueError('İlk çekim cut olmalı.')
        if any(not text.strip() or len(text) > 20 for text in self.intro_beats):
            raise ValueError('Üç açılış vurgusu 1–20 karakter olmalı.')
        if len(set(self.teaser_shots)) != 3:
            raise ValueError('Açılış montajı üç farklı çekim gerektirir.')
        if len({c.scene_index for c in self.chapters}) != len(self.chapters):
            raise ValueError('Sahne başlıkları tekrarlanamaz.')
        if any(s.transition == 'whip' and not 8 <= s.transition_frames <= 12 for s in self.shots):
            raise ValueError('Whip 8–12 kare olmalı.')
        if any(s.transition == 'reveal' and not 12 <= s.transition_frames <= 18 for s in self.shots):
            raise ValueError('Reveal 12–18 kare olmalı.')
        if len(self.shots) >= 3 and not {'whip', 'reveal'}.issubset({s.transition for s in self.shots}):
            raise ValueError('Profesyonel kurgu hem maskeli reveal hem whip geçişi gerektirir.')
        if sum(s.transition == 'whip' for s in self.shots) > 2 or sum(s.transition == 'reveal' for s in self.shots) > 3:
            raise ValueError('Geçiş sayısı anlatı sınırını aşıyor.')
        return self


class RenderClip(Strict):
    file: str = Field(pattern=r'^shot-[0-9]{3}\.(mp4|png)$')
    kind: Literal['clip', 'image'] = 'clip'
    start_frame: int = Field(ge=0)
    frames: int = Field(gt=0)
    transition: TransitionKind = 'cut'
    title: str = Field(default='', max_length=65)
    transition_frames: int = Field(default=7, ge=3, le=18)
    punch_in: bool = False
    scene_index: int = Field(default=0, ge=0, le=7)
    source_in_frame: int = Field(default=0, ge=0)
    design: SceneDesign = Field(default_factory=SceneDesign)
    secondary_file: str = Field(default='', pattern=r'^(|shot-[0-9]{3}\.mp4)$')
    secondary_source_in_frame: int = Field(default=0, ge=0)
    handle_frames: int = Field(default=0, ge=0, le=18)


class CaptionWord(Strict):
    """The JSON Caption contract used by @remotion/captions (milliseconds)."""
    text: str = Field(min_length=1, max_length=150)
    startMs: float = Field(ge=0, le=61000)
    endMs: float = Field(gt=0, le=61000)
    timestampMs: float | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    pageBreakAfter: bool = False

    @model_validator(mode='after')
    def ordered(self):
        if self.endMs <= self.startMs:
            raise ValueError('Kelimenin bitişi başlangıcından sonra olmalı.')
        return self


class RenderCaption(Strict):
    start: float = Field(ge=0, le=61)
    end: float = Field(gt=0, le=61)
    text: str = Field(min_length=1, max_length=500)

    @model_validator(mode='after')
    def ordered(self):
        if self.end <= self.start:
            raise ValueError('Altyazı bitişi başlangıçtan sonra olmalı.')
        return self


class RenderManifest(Strict):
    # Read legacy manifests; the removed overlay flag has no rendering effect.
    social_cta: bool = Field(default=False, exclude=True)
    version: Literal[1, 2] = 1
    fps: Literal[30] = 30
    # Editing ticks remain 30 FPS; only the renderer output clock changes.
    output_fps: Literal[30, 60] = 30
    width: Literal[1080] = 1080
    height: Literal[1920] = 1920
    duration_frames: int = Field(gt=0, le=1815)
    clips: list[RenderClip] = Field(min_length=1, max_length=64)
    captions: list[RenderCaption] = Field(default_factory=list, max_length=500)
    brand: str = Field(default='', max_length=80)
    logo: Literal['', 'brand-logo.png'] = ''
    color: str = Field(default='#A98BFF', pattern=r'^#[0-9a-fA-F]{6}$')
    style: Literal['classic', 'dynamic', 'editorial', 'auto'] = 'classic'
    opening_title: str = Field(default='', max_length=58)
    ending_title: str = Field(default='', max_length=45)
    words: list[CaptionWord] = Field(default_factory=list, max_length=1000)
    intro_beats: list[str] = Field(default_factory=list, max_length=3)
    teaser_shots: list[str] = Field(default_factory=list, max_length=3)
    chapters: list[EditorialChapter] = Field(default_factory=list, max_length=8)
    graphics: list[GraphicCue] = Field(default_factory=list, max_length=24)
    sound_cues: list[SoundCue] = Field(default_factory=list, max_length=24)
    sources: list[EvidenceSource] = Field(default_factory=list, max_length=8)
    palette: GraphicPalette = Field(default_factory=GraphicPalette)
    reconstruction_label: Literal['', 'Canlandırma'] = ''
    caption_size: int = Field(default=58, ge=36, le=76)
    audio_mix: AudioMix = Field(default_factory=AudioMix)
    captions_enabled: bool = True

    @model_validator(mode='after')
    def complete_timeline(self, info: ValidationInfo):
        cursor = 0
        for clip in self.clips:
            if clip.start_frame != cursor:
                raise ValueError('Zaman çizelgesi kesintisiz olmalı.')
            cursor += clip.frames
        if cursor != self.duration_frames:
            raise ValueError('Çekimler toplam süreyi karşılamalı.')
        if self.version == 2:
            known_files = {c.file for c in self.clips} | set((info.context or {}).get('verified_media_files',()))
            for index, clip in enumerate(self.clips):
                following = self.clips[index+1] if index+1<len(self.clips) else None
                expected = following.transition_frames if following and following.transition!='cut' else 0
                if clip.handle_frames != expected:
                    raise ValueError('Geçiş kaynak kareleri zaman çizelgesiyle eşleşmiyor.')
                if clip.design.layout!='full' and clip.secondary_file not in known_files:
                    raise ValueError('İkincil kadraj doğrulanmış medya listesinde bulunmalı.')
        spans = {}
        for clip in self.clips:
            start, _ = spans.get(clip.scene_index, (clip.start_frame, 0))
            spans[clip.scene_index] = (start, clip.start_frame + clip.frames)
        if len({s.id for s in self.sources}) != len(self.sources):
            raise ValueError('Kaynak kimlikleri benzersiz olmalı.')
        validate_scene_cues(self.graphics, self.sound_cues, spans, {s.id for s in self.sources}, relative=False)
        if any(c.end > self.duration_frames / self.fps + 0.1 for c in self.captions):
            raise ValueError('Altyazı video süresini aşıyor.')
        if self.style == 'dynamic' and not self.words:
            raise ValueError('Dinamik kurgu gerçek kelime zamanları gerektirir.')
        if any(w.endMs > self.duration_frames / self.fps * 1000 + 100 for w in self.words):
            raise ValueError('Kelime zamanı video süresini aşıyor.')
        if any(b.startMs < a.startMs for a, b in zip(self.words, self.words[1:])):
            raise ValueError('Kelime zamanları sıralı olmalı.')
        if self.style == 'editorial':
            if len(self.intro_beats) != 3 or len(self.teaser_shots) != 3 or not self.chapters:
                raise ValueError('Profesyonel kurgu açılış montajı ve sahne anlatısı gerektirir.')
            if any(ident not in {c.file.rsplit('.', 1)[0] for c in self.clips} for ident in self.teaser_shots):
                raise ValueError('Açılış montajı yalnızca doğrulanmış çekimleri kullanabilir.')
        return self


class VoiceProfile(Strict):
    key: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,40}$')
    name: str = Field(min_length=1, max_length=100)
    voice_id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,100}$')
    description: str = Field(min_length=5, max_length=600)


class VoiceDecision(Strict):
    profile_key: str = Field(min_length=1, max_length=40)
    reason: str = Field(min_length=5, max_length=600)
    stability: float = Field(ge=0.3, le=0.85)
    style: float = Field(ge=0, le=0.6)


class VoiceShortlist(Strict):
    profile_keys: list[str] = Field(min_length=1, max_length=5)


class VoiceAudition(Strict):
    heard: bool
    transcript_excerpt: str = Field(max_length=600)
    suitability: float = Field(ge=0, le=1)
    reason: str = Field(min_length=5, max_length=600)
    issues: list[str] = Field(max_length=8)


class VoiceCandidateReview(VoiceAudition):
    profile_key: str = Field(min_length=1, max_length=40)
    language: Literal['tr', 'other', 'unknown']


class VoiceCastingDecision(Strict):
    reviews: list[VoiceCandidateReview] = Field(min_length=2, max_length=5)
    decision: VoiceDecision


class Revision(Strict):
    script: StoryScript | Script


class Reedit(Strict):
    run_id: str
    style: Literal['classic', 'dynamic', 'editorial', 'auto'] = 'auto'
    instructions: str = Field(default='', max_length=2500)
    map_intro: bool = False
    show_sources: bool = False


class Approve(Strict):
    run_id: str


class Publish(Approve):
    publish_at: str | None = None
    made_for_kids: bool = False
    synthetic_media: bool = True


class Brand(Strict):
    name: str = Field(default='', max_length=80)
    color: str = Field(default='#7645ed', pattern=r'^#[0-9a-fA-F]{6}$')


class CreativeBrief(Strict):
    goal: str = Field(min_length=5, max_length=1000)
    audience: str = Field(min_length=2, max_length=300)
    tone: str = Field(min_length=2, max_length=80)
    duration: Literal[30, 45, 60]
    visual_direction: str = Field(min_length=10, max_length=1500)
    checks: list[str] = Field(min_length=1, max_length=8)
    clarification: str = Field(default='', max_length=500)


StageName = Literal['strategy', 'script', 'voice', 'visual', 'motion', 'editor', 'quality', 'publisher']


class ExecutionTask(Strict):
    stage: StageName
    depends_on: list[StageName] = Field(default_factory=list, max_length=8)
    goal: str = Field(min_length=5, max_length=240)


class ExecutionPlan(Strict):
    version: Literal[1] = 1
    tasks: list[ExecutionTask] = Field(min_length=8, max_length=8)

    @model_validator(mode='after')
    def valid_graph(self):
        required = {'strategy':set(), 'script':{'strategy'}, 'voice':{'script'},
            'visual':{'script','voice'}, 'motion':{'visual','voice'}, 'editor':{'motion','voice','visual'},
            'quality':{'editor'}, 'publisher':{'quality'}}
        names = [t.stage for t in self.tasks]
        if len(set(names))!=8 or set(names)!=set(required):
            raise ValueError('Her mevcut uzman görevi tam bir kez bulunmalı.')
        done=set()
        for task in self.tasks:
            if not required[task.stage].issubset(task.depends_on) or not set(task.depends_on).issubset(done):
                raise ValueError('Görevler bağımlılıklara uygun sıralanmalı; döngü veya atlanan önkoşul olamaz.')
            done.add(task.stage)
        return self


class ProductionBrief(CreativeBrief):
    execution_plan: ExecutionPlan | None = None

    @model_validator(mode='after')
    def plan_when_ready(self):
        if not self.clarification and self.execution_plan is None:
            raise ValueError('Açıklama gerekmiyorsa yürütme planı gerekli.')
        return self


class SupervisorDecision(Strict):
    action: Literal['dispatch', 'repair', 'finish']
    stage: Literal['strategy', 'script', 'voice', 'visual', 'motion', 'editor', 'quality', 'publisher'] = 'editor'
    reason: str = Field(min_length=5, max_length=700)
    scene_indices: list[int] = Field(default_factory=list, max_length=8)


class AgentAction(Strict):
    tool: str = Field(min_length=1, max_length=64)
    arguments: dict = Field(default_factory=dict)
    reason: str = Field(min_length=5, max_length=500)


class FeedbackRequest(Strict):
    run_id: str
    prompt: str = Field(min_length=3, max_length=4000)
    request_id: str = Field(min_length=8, max_length=80)


class FeedbackAnswer(Strict):
    answer: str = Field(min_length=1, max_length=4000)


class FeedbackDecision(Strict):
    clarification: str = Field(default='', max_length=500)
    summary: str = Field(min_length=5, max_length=1000)
    stages: list[Literal['strategy', 'script', 'voice', 'visual', 'motion', 'editor', 'publisher']] = Field(default_factory=list, max_length=7)
    scene_indices: list[int] = Field(default_factory=list, max_length=8)
    instructions: str = Field(default='', max_length=4000)
    target_duration: Literal[30, 45, 60] | None = None

    @model_validator(mode='after')
    def actionable(self):
        if not self.clarification and not self.stages:
            raise ValueError('Değişiklik için en az bir görev veya açıklama sorusu gerekli.')
        return self


class QualityIssue(Strict):
    kind: Literal['technical', 'editing', 'text', 'audio', 'source', 'content']
    severity: Literal['warning', 'error']
    scene_index: int | None = Field(default=None, ge=0, le=7)
    start_frame: int | None = Field(default=None, ge=0, le=1815)
    end_frame: int | None = Field(default=None, ge=0, le=1815)
    evidence: str = Field(min_length=5, max_length=700)
    repair_stage: Literal['editor', 'voice', 'visual', 'motion', 'script', 'strategy'] = 'editor'

    @model_validator(mode='after')
    def frame_order(self):
        if self.start_frame is not None and self.end_frame is not None and self.end_frame < self.start_frame:
            raise ValueError('Kalite bulgusunun kare aralığı sıralı olmalı.')
        return self


class QualityReview(Strict):
    summary: str = Field(min_length=5, max_length=1000)
    findings: list[QualityIssue] = Field(default_factory=list, max_length=24)


class MotionWindow(Strict):
    start_frame: int = Field(ge=0, le=1814)
    end_frame: int = Field(ge=0, le=1814)

    @model_validator(mode='after')
    def short_window(self):
        if not 0 <= self.end_frame-self.start_frame < 60:
            raise ValueError('Hareket inceleme kesiti en fazla iki saniye olabilir.')
        return self


class PreviewQualityReview(QualityReview):
    motion_windows: list[MotionWindow] = Field(default_factory=list, max_length=3)

