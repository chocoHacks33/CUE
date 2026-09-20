# C-lane · Feature freeze

_Branch `person-c-stage-4`, based on `origin/codex/stage-3-integration`._

After this commit only bug fixes. Any new feature request is deferred
to post-demo.

## In (frozen surface)

**Public API**
- `cue_api.c_lane.CLane` — the 8-method façade documented in
  `docs/C-INTEGRATION.md`.
- `cue_api.c_lane_live.LiveLane` — the async runner + four Protocols
  (`PcmSource`, `CameraStateProvider`, `DecisionSender`, `AckReceiver`)
  and one adapter (`DeepgramSession`).
- `cue_api.policy.wire.to_wire(record)` and `DecisionEvent` — the
  camelCase wire shape A's transport carries.
- `cue_api.semantics.parser.parse(...)` — with `programme`, `roster`,
  `context`, `hard_timeout_s` kwargs.
- `cue_api.policy.log.DecisionRecord` — including the `latencies_ms`
  timeline (`final_ms`, `cue_decide_ms`, `_identity`).

**Scripts**
- `scripts/live_lane.py` — single-laptop end-to-end runner.
- `scripts/release_eval.py` — dev + held-out; prompt-hash ledger.
- `scripts/latency_run.py` — 12-sentence live latency probe.
- `scripts/soak_c_lane.py` — real-time replay soak.
- `scripts/latency_report.py` — post-run aggregation.
- `scripts/run_semantic.py` — unchanged CLI; supports per-case roster /
  programme.

**Datasets**
- `scripts/data/adversarial.json` — 62 cases (dev set).
- `scripts/data/heldout.json` — 40 cases, **do not tune against this**.

**Safety invariants** (all covered by tests)
- Parser timeout / HTTP 429 / malformed / refusal → safe HOLD.
- Deepgram down → SPEECH_DOWN → auto TAKE blocked; manual TAKE still
  works; only explicit RESUME_AUTO clears the pause.
- Reconnect with a new `audio_epoch` → stale messages dropped.
- Duplicate final `Results` frame → exactly one decision.
- Camera-state older than `camera_state_max_age_s` → no named TAKE.
- Unhealthy live → WIDE → SLATE fallback.
- Burst of many utterances → one in-flight + latest pending, rest
  dropped.
- Cue tagged with a stale `mode_revision` → rejected.
- Missing or `applied=False` ACK → `current_camera` unchanged.
- Prompt injection in the transcript → HOLD (deterministic guard).

## Out (deliberately cut)

- **Programme editor UI.** `ProgrammeContext` is threaded into the
  parser but there is no producer-facing editor. For the demo the
  segment is hard-coded or empty.
- **B's face identity in AUTO.** LiveLane defaults to `role_based=True`
  until B publishes a validated join. Flipping to identity mode is one
  parameter but out of scope this stage.
- **Multiple concurrent events.** CLane is single-event; no
  multi-session state or scheduling.
- **Deepgram callback / Callback URL.** We only use the streaming WS,
  not the callback delivery mode.
- **Speaker diarisation.** Deepgram provides it; C does not consume it.
  Only the host mic is transcribed.
- **Retry / backoff for the OpenAI parser.** One attempt per utterance,
  hard timeout 2.5 s, then safe HOLD. No exponential-backoff logic.
- **Custom TTS or captions styling.** The desk prototype has captions;
  the wire event carries `plainReason` for D to render if wanted.

## Known limits

1. **Live latency floor** for nova-3 with endpointing=300ms is roughly
   `endpointing_ms + processing`. Sub-endpointing readings mean the
   calculation is wrong. Flux (v2) is faster but not yet the pinned
   ASR — see `docs/C-INTEGRATION.md` Stage-3 section for the switch.
2. **`_identity` sentinel lives in `latencies_ms`.** That is a
   deliberate side-door — I did not want to change `DecisionRecord`'s
   shape at freeze time. Consumers read
   `latencies_ms.get("_identity")` (1.0 = ROLE_BASED, 0.0 = identity).
3. **Memory measurement in soak is Unix-only.** On Windows the memory
   invariant is skipped; the Mac soak must confirm the 50 MB / 20 min
   ceiling.
4. **`resource_from_session_decision` uses `dataclasses.asdict` on the
   camera considerations.** If A's camera-state dict grows in size the
   `cameras_considered` payload grows with it. No cap today.
5. **Prompt hash is over the raw SYSTEM template.** If the roster JSON
   or ProgrammeContext contents change but the template is unchanged,
   the hash stays the same. The `release_eval.py` ledger is
   *prompt-shape* awareness, not full-behaviour awareness.

## Bug-fix policy (post-freeze)

- Fixes must include a failing offline test that reproduces the bug
  first. Commit the test, then the fix. No fix without a test.
- Any change that touches `cue_api.semantics.parser.SYSTEM` must be
  followed by `python scripts/release_eval.py --acknowledge-retune` and
  the new heldout numbers pasted into `C-release-eval.md`.
- The held-out set is never opened by editors. Only measurement code
  reads it.
