# Incremental editor and renderer

The Supervisor still selects each expert. Within the editor, independent model
jobs drain before failed inference jobs are retried. HTTP 500/502/503/504 and
read/connect timeouts are transient; authentication, quota and contract errors
are not silently retried. Retry rounds wait 5/15 seconds (or a longer numeric
Retry-After) and reduce model concurrency to one. A batch has a 600 second
scheduling budget; already running HTTP requests retain their own timeout.

Successful perceptions and scene decisions are durable and content keyed. Scene
requests use compact schemas with the same validation constraints. The editor's
default per-request response timeout is 300 seconds. A transport failure does
not consume a creative-decision turn.

Invalid scene candidates are saved separately from validated decisions. A later
repair request sends only invalid top-level fields and retains the other creative
choices. Exhausted scene-schema corrections join the deferred queue after other
scenes; they use the same bounded scheduling budget. A Chrome chunk-frame timeout
retries only that encoded range once with the identical manifest.

The renderer has a separate single-worker queue (two Remotion frame workers).
The shared look and measured 30 FPS narration budgets are fixed first. A scene
reserves up to 18 source frames at its outgoing boundary. Its interior renders
as soon as that scene is validated. The first 18 frames of a later scene wait
only for its immediate predecessor. Scene 4 interiors can therefore render while
scene 3 is unavailable. Private placeholder scenes are never part of an allowed
render range. The immutable global time base keeps captions, overlays and source
trims aligned. Visible-input hashes exclude unrelated unresolved scenes.

Each encoded H.264 chunk has a source/code/range fingerprint, frame-count check
and file hash. Final assembly orders these inclusive frame ranges and copies the
video streams without rendering already completed frames again. Original-speed
audio is mixed once after preview acceptance. Final technical validation and
the existing Supervisor-selected MiMo quality step remain required, followed by
human publishing approval. Legacy model-review runs cover sampled rendered frames and
the complete audio mix; a whole-video proxy is additionally sent only if the
provider's video-input contract was already verified.

2026-10-28: New runs use `VIDEO_REVIEW_POLICY=technical_only`. After rendering,
only deterministic file, video, audio and subtitle checks run. No model preview,
final quality inference or Supervisor approval is requested. The existing script
and assets are packaged locally, then the video enters `awaiting_approval` for
the owner. Publication still requires explicit current-version approval and a
separate publish action. Older snapshots retain their model-review policy unless
explicitly migrated; completed clips and encoded chunks remain reusable.

Persistent compiled code uses a Docker named volume on Linux storage. Private
media and resumable chunks stay in their owning production directory.

Exhausted transient batches enter `waiting_provider`, preserving checkpoints and
rendered parts. There are at most three automatic recovery cycles (30/60/120
seconds between cycles); after that a user can explicitly continue the missing
work. Successful independent jobs are never repeated merely because another
job failed. Permanent errors retain the existing targeted correction flow.

Validation: isolated two-second Remotion fixture, global-frame transition/caption
checks, 60 output frames at 1080x1920/30 FPS, complete FFmpeg decode, resumed output
reuse, SSIM 0.997793 against a monolithic render. This is a component check, not
an end-to-end production latency guarantee or a claim that an external provider
cannot time out.
