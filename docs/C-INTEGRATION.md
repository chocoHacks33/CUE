# C-lane integration for A's backend

One import, one class, eight method calls, one callback.

```python
from cue_api.c_lane import CLane
```

Everything C exposes goes through `CLane`. No global state, no threads,
no network started by the class itself. `parse_fn`, `emit`, and
(optionally) `logger` and `clock` are injected — A owns their lifecycle.

## The eight method calls

Each method takes an explicit `now` (seconds, monotonic-ish). Producer
clock. Use the same clock for every call in a session.

| Method | When to call | Payload |
|---|---|---|
| `on_transcript_message(msg, now)` | For every WebSocket message A receives from Deepgram Listen v1 (`Results` and `UtteranceEnd`). Pass the message as a plain dict (call `.model_dump()` on the SDK object). Include `"audio_epoch"` in the dict so old-epoch messages are dropped after a reconnect. | one Deepgram message |
| `on_camera_state(cameras, now)` | Every time A gets a fresh camera-state snapshot (from A's own workers + B). The lane holds the latest snapshot for the next decision. Refresh at least once per `camera_state_max_age_s` (default 1.0s); older snapshots block named TAKEs. | `{camera_id -> {role, healthy, epoch, confirmed_guest_ids, evidence_age_s, guest_ready}}` |
| `on_manual(command, now)` | Producer input, one string per action: `"TAKE CAM-GUEST"`, `"HOLD"`, `"RESUME_AUTO"`, `"SLATE"`. Every manual call bumps `mode_revision`, which invalidates any in-flight AI cues submitted before it. | `"TAKE <camera_id>"` / `"HOLD"` / `"RESUME_AUTO"` / `"SLATE"` |
| `on_ack(decision_seq, applied, now)` | When D's compositor acknowledges a decision. `applied=True` commits `current_camera`; `applied=False` (or a `decision_seq` that no longer matches the pending slot) leaves state alone. | `decision_seq: int`, `applied: bool` |
| `on_speech_down()` | ASR / transcript transport is down. Blocks automatic TAKEs; manual TAKE still works. **No RESUME_AUTO happens implicitly** when speech comes back. | — |
| `on_speech_up()` | Transport recovered. Cues can flow again into the queue but will still produce STAY until an explicit `RESUME_AUTO`. | — |
| `on_reconnect(new_epoch)` | Backend/control transport restart. Resets the assembler to `new_epoch`, clears the semantic queue, bumps `mode_revision`, and pauses AUTO. Follow with `on_manual("RESUME_AUTO", now)` when the producer is ready. | `new_epoch: int` |
| `tick(now)` | Periodically (every 100-200 ms is plenty). Runs the assembler's missing-endpoint timeout flush and drains any pending queue work. Safe to call more often. | — |

## The emit payload

Every decision (AI-driven or manual) is delivered as a
`cue_api.policy.log.DecisionRecord`. Schema and fixtures live in
`docs/contracts-proposal/decision_record.schema.json`. Shape:

```python
DecisionRecord(
    at: float,                     # producer clock seconds
    decision_seq: int,             # monotonic session-wide
    mode_revision: int,            # session's mode revision at issue
    action: "TAKE" | "STAY" | "SLATE",
    camera_id: str | None,
    reason: str,                   # short human string; not model CoT
    transcript_span: dict | None,  # {utterance_id, text, started_at, ended_at}
    cue_summary:     dict | None,  # {target_guest_ids, scope, temporal_intent, action_pre_validate}
    cameras_considered: list[dict], # one per camera, with picked + optional rejection_reason
    latencies_ms: dict[str, float], # asr / cue / decide / total (best-effort, may be empty)
    source: "LIVE",                 # fixture replays emit "FIXTURE"
)
```

If A wants JSON, call `record.to_json()` or serialise via
`dataclasses.asdict`. The class is a plain `@dataclass`.

## Required env vars

CLane itself reads no env vars. `parse_fn` is where the LLM lives, so
that reads them. For the production release path:

| Var | Owner | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | C's `parse` | OpenAI SDK auth |
| `CUE_MODEL` | C's `parse` | pinned OpenAI model id |
| `CUE_PROVIDER` | (C policy) | must be `openai` in production; other values live only on dev branches |
| `DEEPGRAM_API_KEY` | A's Deepgram client | ASR auth |

Everything else CLane needs comes through the constructor.

## What C needs from A

1. **Deepgram WebSocket → `on_transcript_message` firehose.** A owns the
   ASR connection; C only consumes messages. Each message MUST carry an
   `"audio_epoch": int` field set by A. Bump this on every reconnect and
   also call `on_reconnect(new_epoch)`.
2. **Camera state snapshot → `on_camera_state`.** Same dict shape the
   director already consumes. `evidence_age_s` and `confirmed_guest_ids`
   come from B; `role`, `healthy`, `epoch`, `guest_ready` from A. If
   `guest_ready` is missing, C defaults to `True`.
3. **Producer input transport.** A owns the WS/UI that receives producer
   TAKE/HOLD/RESUME_AUTO/SLATE and forwards to `on_manual`.
4. **Compositor ACK transport.** A owns the ACK channel from D and
   forwards to `on_ack`.
5. **Time source.** A's producer clock. Passed as `now` to every method.
   The class does not call `time.time()` on its own.

## 12-line usage example

```python
from pathlib import Path
from cue_api.c_lane import CLane
from cue_api.policy.log import DecisionLogger
from cue_api.semantics.parser import parse  # OpenAI-backed

lane = CLane(
    parse_fn=parse,
    emit=lambda rec: control_ws.send_json(rec.to_json()),
    logger=DecisionLogger(Path("run.log.jsonl")),
    role_based=False,
    initial_camera="CAM-HOST",
)
lane.on_camera_state(state_from_a_and_b, now=t())
lane.on_transcript_message(dg_msg.model_dump() | {"audio_epoch": epoch}, now=t())
lane.tick(now=t())
```

---

## Stage 3 — live lane (`cue_api.c_lane_live.LiveLane`)

`LiveLane` is the async runner that wires A's PCM source, my Deepgram
bridge, B's visual observations, D's control transport and the
Stage-2 CLane together. Nothing in `cue_api.c_lane_live` imports A/B/D
internals — everything is a small local `Protocol` you satisfy with
a duck-typed object.

Chain:

```
A.PcmSource            (async iterable of DecodedAudioChunk)
    -> PcmContinuityGuard + resample-to-16k-mono
    -> connection.send_media(bytes)                 (Deepgram)
    -> connection.on(Message) -> LiveLane.on_deepgram_message
    -> CLane.on_transcript_message()
    -> semantics.parser.parse (OpenAI, pinned model)
    -> policy.session.DirectorSession
    -> policy.log.DecisionRecord (+ latency trace)
    -> policy.wire.to_wire(record) -> DecisionEvent
    -> sender.send(event, decision_seq)             (D's transport)
D.AckReceiver.wait_ack() -> LiveLane -> CLane.on_ack()
```

### Protocols A/B/D satisfy

| Protocol            | Signature                                                        | Owned by |
|---------------------|------------------------------------------------------------------|----------|
| `PcmSource`         | `async def stream() -> AsyncIterator[DecodedAudioChunk]`         | A        |
| `CameraStateProvider` | `def cameras(now: float) -> Mapping[str, Mapping[str, Any]]`   | A + B    |
| `DecisionSender`    | `def send(event: DecisionEvent, *, decision_seq: int) -> None`   | D        |
| `AckReceiver`       | `def wait_ack() -> tuple[int, bool, float] \| None`              | D        |
| `DeepgramSession`   | context manager yielding `send_media(bytes)`; forward messages via `LiveLane.on_deepgram_message(msg, now)` | C helper |

### Latency trace stamped onto every DecisionRecord

`record.latencies_ms` now carries a per-decision timeline:

| Key             | Definition                                                          |
|-----------------|---------------------------------------------------------------------|
| `final_ms`      | `audio_seconds_sent - transcript_span.ended_at` (audio time)        |
| `cue_decide_ms` | wall-clock: last Deepgram final → decision emitted                  |
| `ack_ms`        | *filled by `scripts/latency_report.py`* — decision emitted → D's ACK |
| `_identity`     | `1.0` when the lane is `role_based`, `0.0` when face identity is on |

Aggregate with `python scripts/latency_report.py <decisions.jsonl> [--acks acks.jsonl]`. p50 / p95 per hop.

### Identity mode

If no B-side visual-observation provider is wired (or you pass
`camera_state=None`), LiveLane runs with `role_based=True`. Every
DecisionRecord is stamped `latencies_ms["_identity"] = 1.0` so nobody can
mistake a role-based cut for face recognition. When B's provider is
plugged in, pass `role_based=False`.

### Standalone runner

`scripts/live_lane.py --source mic` boots the pipeline on one laptop
with a synthetic `DecodedAudioChunk` stream from the local mic and a
fake healthy camera state. Requires `OPENAI_API_KEY` and
`DEEPGRAM_API_KEY`; exits **2** with a clear message if either is
missing. `CUE_MODEL` must also be set — otherwise every parse
returns a safe HOLD (never an unpinned-model call).
