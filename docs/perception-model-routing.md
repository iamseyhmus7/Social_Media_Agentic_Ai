# Visual inspection model routing

`EVREN_MEDIA_MODEL2` selects only `Video Editörü / Görsel inceleme`, the task that
reads three sampled frames and returns `ClipPerception` JSON. Empty values retain
the previous media/text-model selection. Scene editing, creative direction, other
media agents and Supervisor keep their existing model selection.

New runs save this setting in their configuration snapshot. Existing snapshots do
not change automatically. For the explicitly migrated Sakarya run, the new setting
is saved and previously completed MiMo observations remain reusable through an
explicit run-local `_perception_cache_reuse_models` allowlist. Cache keys continue
to include clip hash, perception schema and model identity: old observations are
never relabeled as Qwen outputs, and changed clips need a new inspection.

The isolated live check in `data/qa-perception-qwen-20261101/result.json` used three
frames from shot-001, received HTTP 200 from `qwen3-vl-30b` in 2.62 seconds and
passed the existing JSON validation. It did not replace any production result.
This is a single response measurement, not a general latency or availability SLA.

## Editor response waiting

`EDITOR_CALL_TIMEOUT_SECONDS=0` disables the editor's HTTP response/read deadline.
The editor no longer inherits the general 1800-second response limit in this mode.
Connection establishment (15 seconds), request writes (30 seconds), connection-pool
acquisition (15 seconds), user cancellation and transient HTTP-error handling remain
active. This does not prevent an upstream gateway from closing a request or returning
503. A request with no response can wait until cancelled or disconnected.

Existing runs retain their snapshot until explicitly migrated. The current Sakarya
run was migrated to zero without resetting recovery counters or changing its script,
source clips, completed scene decisions or render parts.

## Editorial output allocation

Editorial roles (excluding the separate sampled-frame perception role) do not send
`max_tokens` or an application thinking budget. Fixed 1536/2048/3072/4096 editorial
call-site caps were removed. The non-editor one-time expansion policy is unchanged.
The legacy short-response wording is removed from the outgoing editorial instruction
without changing task/cache identity, so completed scene decisions remain reusable.
JSON, source-range and render-format validation still apply.

The live Evren OpenAPI schema was inspected: public ChatCompletionRequest exposes
nullable `max_tokens`, but no public thinking/reasoning switch. InternalChatRequest
has separate controls; these are not assumed valid on the public endpoint. Model
thinking is therefore left to the provider. Provider-side context/output limits can
still truncate a response. Such truncation is recorded as `provider_output_limit`
instead of silently repeating the same uncapped request. Metrics include the actual
`requested_max_tokens` value (null for editorial calls).
