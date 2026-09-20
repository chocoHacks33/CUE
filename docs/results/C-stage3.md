# C-lane · Stage 3 status

_Branch `person-c-stage-3`, based on `origin/codex/stage-2-integration`._

## Base decision

`origin/codex/stage-2-integration` is the newest team integration branch
that contains my Stage 2 delivery (commit `ae9d360`). It also contains
A's Stage 2 control transport (`control.py`, `control_socket.py`,
`control_contracts.py`, `camera_health.py`, `readiness.py`) and B's Stage
2 vision-on-backend consolidation (`cue_api.guests.*`).

I did **not** base on `codex/person-a-stage-3-prep` or
`codex/b-stage-3-prep` because both of those branches delete a large
chunk of my Stage 2 (`c_lane.py`, `policy/*.py`, `semantics/queue.py`,
`speech/deepgram_stream.py`, and their tests). A rebase onto the
validated commit that reconciles those deletions is **PENDING**; I will
rebase once A and B publish a merged integration branch that keeps my
Stage 2 files.

Teammate additions since my last base that touch my lane:

| From | Files | Impact on C |
|---|---|---|
| A (Stage 2) | `cue_api.control{,_contracts,_metrics,_socket}`, `camera_health`, `readiness` | `ControlStore.policy_take(...) → RenderCommand`; the `RenderCommand` envelope is what D consumes. My `DecisionEvent` is upstream of that — the LiveLane `sender` is where A's transport plugs in. |
| A (Stage 2) | `cue_api.media_contracts.DecodedAudioChunk` | Unchanged from Stage 1: still my PCM ingress contract. |
| B (Stage 2) | `cue_api.guests.contracts.{VisualObservation, CameraObservationView, ObservationSnapshot}` | These map into my `cameras` dict via a `CameraStateProvider`. B's `ObservationStore.snapshot(...)` returns `ObservationSnapshot`; the caller (A or C) folds it into the `cameras` dict. |
| D (Stage 3) | `apps/web/src/compositor/controlAdapter.ts`, `switching.test.ts` updates | D's compositor already consumes A's `RenderCommand`. My `DecisionEvent` shape is fully compatible with A's `to_camel` alias generator. |

## What went in

| Purpose | File(s) |
|---|---|
| Live async runner | `apps/api/src/cue_api/c_lane_live.py` |
| Parser hardening (programme context, duplicate names, role holders, bounded context, hard timeout, safe HOLD, `CUE_MODEL` refusal) | `apps/api/src/cue_api/semantics/parser.py` |
| 16 new dev cases (duplicate names, roles, programme segments, split corrections, extra injections, questions/hypotheticals) | `scripts/data/adversarial.json` |
| Runner: mic → Deepgram → LiveLane → stdout / JSONL | `scripts/live_lane.py` |
| Runner: unchanged CLI, now threads per-case `roster` / `programme` / `context`; reports wrong SHOW cuts on their own summary line | `scripts/run_semantic.py` |
| Latency aggregator (`final_ms`, `cue_decide_ms`, `ack_ms`, `total_ms`) p50 / p95 | `scripts/latency_report.py` |
| Tests (offline, fake parse_fn + fake DG + fake PCM) | `apps/api/tests/test_c_lane_live.py`, `test_no_double_cuts.py`, `test_parser_hardening.py`, `test_latency_report.py` |
| Doc updates | `docs/C-INTEGRATION.md` (Stage 3 live-lane section), `docs/results/C-stage3.md` (this file) |

## Live lane architecture

```
A.PcmSource            (async iterable of DecodedAudioChunk)
    -> PcmContinuityGuard + resample-to-16k-mono
    -> connection.send_media(bytes)                 (Deepgram v1)
    -> connection.on(Message) -> LiveLane.on_deepgram_message
    -> CLane.on_transcript_message()
    -> semantics.parser.parse (OpenAI, CUE_MODEL pinned)
    -> policy.session.DirectorSession
    -> policy.log.DecisionRecord (+ latency trace)
    -> policy.wire.to_wire(record) -> DecisionEvent
    -> sender.send(event, decision_seq)             (D's transport)
D.AckReceiver.wait_ack() -> LiveLane -> CLane.on_ack()
```

All external dependencies are typed as local `typing.Protocol`s so no
A/B/D file needs to import `cue_api.c_lane_live` and vice-versa. Fakes
for those Protocols back every test.

## Parser hardening (rules verified offline)

* Programme context (`segment`, `segment_roles`, `programme_revision`)
  is threaded into the prompt AND stamped onto every `Cue`.
* Duplicate first name detection: `_duplicate_first_names()` scans the
  roster. A bare first-name reference to an ambiguous roster entry
  collapses to `target_guest_ids=[]`, `temporal_intent=UNCERTAIN`,
  `action=HOLD`.
* Full name / unique alias resolves the ambiguity to a single guest.
* Role phrases resolve to a single roster id **only when the current
  programme segment lists exactly one holder** for that role. Multiple
  holders → HOLD.
* Group cues with `temporal_intent=NOW` become WIDE.
* Past / negated / uncertain temporal intents never cut, regardless of
  what the model returned.
* Context to the LLM is bounded to the last three utterances.
* OpenAI call runs in a `ThreadPoolExecutor` future with a hard
  timeout (default 2.5 s). Timeout, refusal or schema error all
  collapse to a safe HOLD cue whose `evidence_text` names the failure.
* `CUE_MODEL` is required. If unset the parser returns a safe HOLD
  with reason `"CUE_MODEL not set"` — never a default model call.

## No double cuts (offline proof)

`apps/api/tests/test_no_double_cuts.py`:

* `test_split_correction_yields_one_take` feeds the assembler two
  Deepgram `Results` frames for one utterance, `speech_final=True` only
  on the second. Assembler joins them; SemanticQueue calls the injected
  `parse_fn` which returns `target_guest_ids=["daniel"]`. Exactly one
  `TAKE` on `CAM-GUEST` emits.
* `test_late_cue_after_manual_hold_is_rejected_by_mode_revision`
  presses `HOLD` (bumping `mode_revision`), then submits a cue tagged
  with the old revision. No `TAKE` to `CAM-GUEST` emits.

## Latency trace

`DecisionRecord.latencies_ms` now carries a per-decision timeline:

| Key              | Definition                                                           |
|------------------|----------------------------------------------------------------------|
| `final_ms`       | `audio_seconds_sent - transcript_span.ended_at` (audio-time)         |
| `cue_decide_ms`  | wall-clock: last Deepgram final → decision emitted                   |
| `ack_ms`         | filled by `latency_report.py` from a paired ACK log                  |
| `_identity`      | `1.0` for role_based, `0.0` for identity-driven                      |

`python scripts/latency_report.py <decisions.jsonl> [--acks acks.jsonl]`
prints p50 / p95 for each hop. `--json` emits machine-readable output.

## Tests

```
apps/api/tests/
├── test_c_lane_live.py        3 tests   PCM pump, decision emit + latency, continuity drop
├── test_no_double_cuts.py     2 tests   correction, late-cue mode_revision reject
├── test_parser_hardening.py  14 tests   dup names, role holders, temporal gates, bounded ctx, safe HOLD, hard timeout
└── test_latency_report.py     6 tests   aggregation, ACK index, empty buckets, jsonl junk lines
```

`python -m pytest -q`: **444 passed, 2 skipped, 2 warnings** (Stage 2
baseline was 415; the +29 are all from Stage 3).

`python -m ruff check .`: **All checks passed.**

## NOT RUN offline (needs OpenAI key or a Mac)

* Live semantic run — `scripts/run_semantic.py --models <id> --set dev`
  end-to-end pass rate. Requires `OPENAI_API_KEY` and `CUE_MODEL`.
  I extended the dev set with 16 new adversarial cases but have not
  measured pass rate on the model with them.
* Live end-to-end lane — `scripts/live_lane.py --source mic`. Requires
  both keys and a working mic. My desk prototype exercises the
  Deepgram + assembler halves; LiveLane's async wiring is offline-tested
  with fakes but has not been run against the real Deepgram v1 endpoint
  through this file yet.
* Real latency numbers — `scripts/latency_report.py` output on a live
  decision log. Aggregation logic is unit-tested with synthetic data.
* Rebase onto a validated commit that reconciles A's / B's stage-3-prep
  file deletions.

## Commands for A or D to run on the Mac

```bash
# Everything runs from apps/api's venv.
cd apps/api && python -m pip install -e ".[dev]"

# 1. Smoke test the OpenAI + Deepgram credentials.
cd .. && python scripts/smoke_api.py

# 2. Dev-set semantic pass rate (extend --repeat if you want variance).
cd .. && python scripts/run_semantic.py \
    --models "$CUE_MODEL" --set dev
# Sends results_dev_<model>_<ts>.json into scripts/. Send me that file.

# 3. Live end-to-end lane, single laptop.
cd .. && python scripts/live_lane.py --source mic \
    --log-decisions /tmp/decisions.jsonl
# Speak into the mic. stdout is JSONL DecisionEvent frames (D's shape).

# 4. Latency aggregate.
cd .. && python scripts/latency_report.py /tmp/decisions.jsonl
# p50/p95 for final_ms / cue_decide_ms / total_ms.

# 5. Also send me:
#    apps/api/tests/test_*.py output of `python -m pytest -q`  (should be 444 passed)
#    ruff check output                                          (should be clean)
```

## Open requests

**A — control transport wire-in.**
- I emit `DecisionEvent` (camelCase, `contractVersion` = A's
  `CONTRACT_VERSION`). Confirm whether you'd like me to wrap this in
  A's `render.command` envelope on my side, or whether A's transport
  adapter will do it. My `DecisionSender.send(event, decision_seq)` is
  the exact hand-off.
- If A wants LiveLane to speak `RenderCommand` directly, tell me — I'll
  add a `to_render_command()` in `cue_api.policy.wire` next to `to_wire`.
- Please give me a concrete `PcmSource` shape (async or sync). The
  Protocol accepts either `stream()` or `iter_chunks()`.

**B — camera state provider.**
- I consume `CameraStateProvider.cameras(now)` returning the dict
  shape my director already accepts. Confirm you'll (a) transform
  `ObservationSnapshot` + `CameraHealthReport` into that dict on your
  side, or (b) want me to add a `cue_api.guests.observation_store`
  adapter here.
- Roster IDs must be exactly the strings I use (`sarah`, `daniel`,
  `priya`, `maya`, `alex`, `jordan`, `kai`). If any observation carries
  a different `subject.guest_id`, please map it before it reaches me.

**D — compositor.**
- Every `DecisionEvent` carries `decisionSeq`; ack every applied cut
  through your `AckReceiver` (my `wait_ack()` polls it, threads it into
  `CLane.on_ack`).
- `latencies_ms["_identity"] == 1.0` means role_based (no face
  recognition). Please don't render "identified as" text in that mode.
- If you want captions on the WS as their own event kind, tell me and
  I'll add a `caption` DecisionEvent variant that piggybacks the same
  transport.
