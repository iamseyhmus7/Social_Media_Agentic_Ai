# Automatic production recovery

Recovery state is versioned JSON in `Run.outputs._recovery`; no SQL migration is required.
The run API exposes it as `recovery`, while keeping the existing run statuses.

* Voice timing accepts the intersection of target ±2 seconds and 30–60 seconds.
  The recovery target is the midpoint (59 seconds for a 60-second brief).
* The supervisor delegates narration-only patches to the script agent using measured
  speech rate. Scene structure, visual instructions and the selected narrator remain intact.
* At most one supported provider speed adjustment (baseline ±5%) and two narration
  patches are allowed. V4 dialogue has no verified speed adapter and goes directly to text.
  Old `_duration_repairs` entries count toward the two text attempts on first resume.
* New audio filenames include their synthesis input hash. Fixed render assets are
  archived before invalidation; their old asset IDs remain readable.
* Provider 500/502/503/504 and network failures use a durable 30-minute wait window,
  exponential backoff with jitter, and `Retry-After`. The worker never dispatches an
  expired window. An explicit user retry starts a new window; restarting a worker does not.
* Production retries are owned by the scheduler. Nested batch retries are disabled;
  successful sibling scene checkpoints remain usable. Provider/model requests are serialized.
* Each inference task has a persisted three-response budget. Transport failures are
  free. Non-editor output token limits can double once, to at most 8192 tokens, after truncation. Editorial calls send no application output token cap.
  Invalid fields are patched; malformed JSON or a returned schema retries only that task.
* Exhausted content/quality recovery enters `waiting_input`; an exhausted service
  window stays `waiting_provider` with `automatic: false`. Credentials, auth errors and
  quota waits do not enter the transient-service loop.
* Technical checks archive a distinct log and render hash. Black/silent intervals are
  localized against measured scene durations; render errors go to the editor. A source
  repair requires the existing source-review evidence. Editor/media repairs have two turns.

## Acceptance

`backend/tests/test_recovery.py` covers measured voice recovery, legacy migration,
speed/cache identity, cancellation, scheduler deadlines, response budgets, render
history, and current-render evidence. When available, the read-only Sakarya snapshot
also exercises its real 61.68-second measurement and existing repair history offline.

`python -m scripts.accept_voice_recovery --snapshot <snapshot.json> --live` performs
one isolated real-provider acceptance run, including narration correction and TTS.
It writes a separate SQLite database, media and `result.json` under `.cache` and
never resumes the original production or publishes a video. Real-provider execution
requires explicit authorization for transmitting the snapshot and incurring API cost.

No Docker deployment is performed by these scripts. Running services continue using
their existing image until a separate deployment. Provider-side 503 availability
cannot be fixed by this application's retry policy.

## Decision budget accounting

All model decision entry points use the same reservation/refund wrapper. A transient
provider error (500/502/503/504, response/connection timeout or connection failure)
refunds its reserved agent turn. Successful decisions and nontransport failures keep
their existing accounting. Provider recovery windows and task response budgets are
independent; the agent decision limit is not raised or disabled.

Before its next decision, a legacy run receives a version-2 decision-budget record.
Only known previously unrefunded Supervisor schemas and recorded transient failures
are credited, once. The original count, credit, metric indices and metrics hash are
retained for audit. Previously refunded expert calls, quota/auth errors, invalid JSON
and uncertain history are excluded. Completed artifacts and other recovery counters
are not changed.
