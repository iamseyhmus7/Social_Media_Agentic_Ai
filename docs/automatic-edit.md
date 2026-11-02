# Content-driven production

New web productions default to `auto`. Existing classic, dynamic and editorial runs retain their original renderer and immutable assets. Re-edit creates a new unapproved revision and never generates new Kaggle clips.

The script now carries a content format, shared continuity description and 5–8 event scenes with visible action and before/after state. The narration-duration correction keeps these fields. After measuring speech, the video agent assigns short shots to each scene; each shot gets its own initial-frame prompt, purpose and expected action. Timing and reference indices are assigned by code, not trusted to the language model.

The visual stage creates one reference per shot. `visual.images` remains one representative image per narration scene for backward-compatible UI/cover use; `visual.shot_images` maps the complete storyboard. Kaggle uses `image_index` for new shots, falling back to `scene_index` for legacy jobs. The model remains LTX 0.9.6 on Kaggle; rendering remains local Remotion/FFmpeg.

The automatic editor receives labelled contact sheets of three sampled frames from every real clip. It returns observations plus a source-range timeline and editorial reasons. There are no mandatory teaser, chapter card or transition quotas. Source ranges must fit decoded clips, every scene must match the measured narration-frame budget, narrative scene order is preserved, and every source must be reviewed. Clear rejected shots stop the montage with a visible explanation. Uncertain observations are exposed for human review; sampled frames do not certify continuous movement, sound, or identity consistency.

For a re-edit of a completed auto production, identical script/durations and owned clip hashes allow reuse of the previous sampled observations. The agent receives the prior source ranges and observations as text, without retransmitting or decoding all clip contact sheets. Existing observations remain immutable, and all new source ranges, timing and graphic preferences are still validated. Changed clips stop cache reuse; sources without a reusable auto review follow the full visual-review path. Provider HTTP 5xx errors are reported as service failures rather than API-key errors.

Reference generation currently uses prompt-only Cloudflare Schnell. Repeating character and setting descriptions is a continuity aid, not reference-image identity conditioning or a guarantee of the same face across shots. The live story test must assess that limitation explicitly. No character training, lip-sync or automatic paid-provider fallback was added.

The shared Remotion automatic composition executes validated segments, source trims, optional shot text and motivated cut/dissolve/push/reveal/whip decisions. It does not synthesize character actions. Original-speed voice and final file checks remain unchanged. No executable agent-generated code is run.

Pilot: “Kayıp Anahtar”, realistic 30-second story, one red-coated woman searching for a key in one apartment. Initiate through the authenticated web form; inspect story, measured voice, shot count, actual motion, visual review, render metrics and final decode. Do not approve or publish automatically.

## Documentary graphics and narration captions

Automatic plans may now select `kinetic_text`, `timeline`, `spotlight`, and `source_card` graphics, plus original `tick`, `whoosh`, and `impact` sound cues. Their start frames are relative to a narration scene in the edit decision, then compiled to absolute render frames using cumulative measured speech durations. Cues must fit their scene, graphics cannot overlap, and spotlight regions stay above the subtitle area. Date comparisons use ordered numeric years; the renderer calculates the difference. Graphics and sounds are optional, without template quotas.

Source cards are shown only when the user enables `show_sources`; they are off by default. They reference a server-owned registry extracted from explicit HTTPS links in the project brief. Full links remain in the publication description and ZIP metadata. The editor cannot invent URLs. This registry does not independently fact-check page contents. Historical generated footage remains labelled `Canlandırma` and must not be presented as archival evidence.

Re-edit accepts editorial instructions and an optional `map_intro`. The agent selects a typed `map_flyover` cue with bounded coordinates and a location label; a requested map must begin at frame zero and fit its narration scene. The reusable map uses local public-domain Natural Earth countries/rivers and a deterministic perspective camera, without remote tiles or WebGL. It locates the story; it does not claim to prove a rumour's historical origin. DM Sans fonts and their OFL licence are embedded locally. Close ASR spelling errors can be aligned against the original script while preserving measured word times.

Automatic rendering now displays narration-aligned highlighted captions using existing ASR word timestamps; old manifests without words retain sentence-caption support. Footage trims never retime narration or its captions. Original sound effects occupy only the chosen windows, leaving deliberate pauses silent. Classic, dynamic and editorial behavior remains available.

The one-off graphic-layout inspection scripts and derived forest-clip frames were removed after validation. Production acceptance runs through the authenticated web application with new project media. Caption pagination checks remain in `scripts/check-auto-captions.mjs`.

For source-only local updates with unchanged dependency manifests, `deploy/Dockerfile.source-overlay` can extend an already provisioned image via `RUNTIME_IMAGE`. Build the worker from the existing worker image and API/beat from the existing API image, then recreate services with `--no-build`. This preserves installed media dependencies and Remotion 4.0.538; dependency changes still require the main Dockerfile.
