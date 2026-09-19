# C-lane · Stage 1 status

_Branch `person-c-stage-1`, branched from `origin/codex/person-a-stage-1` (A's Stage-1 merged with everyone's integrated Stage-0)._

## Base I'm building on: A's Stage-1

A's Stage-1 commit (`1309f27 Build Person A Stage 1 admission and media contracts`) ships two contracts C consumes:

### PCM interface (what C reads)

`cue_api.media_contracts.DecodedAudioChunk` — one immutable frozen dataclass per PCM chunk on the master audio track. Field-for-field:

| Field | Type | What C uses it for |
|---|---|---|
| `event_id` | `str` | pass-through in logs; not gated on |
| `camera_id` | `CameraId` | must be `CameraId.HOST`; A rejects anything else in `__post_init__` |
| `master_track_sid` | `str` | continuity: track-change without a new epoch is rejected |
| `audio_epoch` | `int ≥ 1` | assembler / DirectorSession epoch propagation |
| `sequence` | `int ≥ 0` | continuity; strict monotonic |
| `sample_rate_hz` | `int` (8k–192k) | resampler input rate |
| `channels` | `1` or `2` | downmix to mono if `2` |
| `sample_format` | `SampleFormat` (`S16LE` / `F32LE`) | format at ingress |
| `sample_offset` | `int ≥ 0` | absolute offset within the audio_epoch's timeline |
| `received_at_monotonic_s` | `float ≥ 0` | producer clock |
| `data` | `bytes` | raw PCM |

A also ships `PcmContinuityGuard.accept(chunk) -> AudioContinuity(accepted, gap_sample_frames, reason)`. C runs it on every ingress chunk and reports `reason` verbatim on rejection. It rejects: stale epoch, duplicate/out-of-order sequence, track change without epoch bump, PCM format change within an epoch, overlapping/replayed sample offsets. It reports positive `gap_sample_frames` when there's a hole.

### Camera state contract

A's `contracts.py` fixes `CameraId` (`CAM-HOST` / `CAM-GUEST` / `CAM-WIDE`), `CameraRole` (uppercase `HOST` / `GUEST` / `WIDE`), and `AudioPolicy` (`MASTER` / `DISABLED`). The `CameraBindingResponse` on `GET /api/v1/events/{event}/bindings` gives the authoritative camera → device → track-SID → stream-epoch mapping. My director's `cameras` dict field names (`role`, `healthy`, `epoch`, `confirmed_guest_ids`, `evidence_age_s`, `guest_ready`) are still the shape I take in `decide()` — none of A's Stage-1 additions collide with mine.

`DecodedVideoFrame` + `LatestFrameSlot` are for B's face-id path, not mine. C does not read them.

### Overlap with my Cue / Decision / State / DecisionRecord

**No overlap.** Class-name sweep of `apps/api/src/cue_api/contracts.py` and `apps/api/src/cue_api/media_contracts.py` on A's branch:

```
CameraId, CameraRole, AudioPolicy, CameraContract, PublisherTokenRequest/Response,
PairingGrantRequest/Response, PairingClaimRequest/Response, PairingDecisionRequest,
PairingStatusRequest/Response, ProducerPairingClaimResponse, PairingExchangeResponse,
CameraBindingResponse, TopologyResponse, HealthResponse,
ReceiverRole, ReceiverTokenRequest/Response,
PixelFormat, SampleFormat, DecodedVideoFrame, DecodedAudioChunk,
LatestFrameSlot, AudioContinuity, PcmContinuityGuard
```

Nothing named `Cue`, `Decision`, `State`, `DecisionRecord`, or `SessionDecision`. A's contracts describe media admission and PCM ingress; mine describe semantic interpretation and directing. I adopt A's `CameraId` / `SampleFormat` verbatim and add my own semantic types alongside.

## What I built on top: `cue_api.speech.deepgram_stream`

`apps/api/src/cue_api/speech/deepgram_stream.py` bridges A's PCM contract into Deepgram's WebSocket and out through my assembler.

Public surface:

```python
class DeepgramStream:
    def __init__(self, connection, assembler, *,
                 target_sample_rate=16_000,
                 speech_down_timeout_s=5.0): ...

    def feed(self, chunk: DecodedAudioChunk, *, now: float) -> list[SpeechEvent]
    def on_deepgram_message(self, msg: dict, *, now: float) -> list[SpeechEvent]
    def tick(self, now: float) -> list[SpeechEvent]
    def reset(self, new_epoch: int) -> None
```

Rules encoded:

- **Runs `PcmContinuityGuard` first.** Every chunk goes through A's guard; rejects surface as `rejected_reasons[-1]` verbatim, and no bytes are sent to Deepgram.
- **Resamples once at the boundary.** If `sample_rate_hz == 16_000`, `channels == 1`, and `sample_format == S16LE`, the bytes pass through unchanged. Otherwise, mixdown-to-mono + int16 conversion + linear-interpolation resample runs exactly once per chunk. `resamples` counter is exposed for tests / observability.
- **Epoch propagation.** When `chunk.audio_epoch` advances, the assembler is reset to the new epoch and the epoch's `sample_offset` base is captured for offset-mapping. `reset(new_epoch)` does the same manually before a reconnect.
- **Word-time → epoch + sample-offset mapping.** When the assembler emits a `FinalUtterance` with `started_at` / `ended_at` (Deepgram audio time in seconds), the bridge multiplies by the epoch's input `sample_rate_hz` and adds the epoch's start-offset, giving downstream consumers `(audio_epoch, sample_offset_start, sample_offset_end)` in A's coordinate system.
- **`SPEECH_DOWN` / `SPEECH_UP`.** If `tick(now)` fires past `speech_down_timeout_s` seconds after the last Deepgram message (or the first chunk, if no message has ever arrived), a `speech_down` event is emitted once. The next Deepgram message emits `speech_up` and clears the flag.
- **Fake connection for tests.** `DeepgramConnection` is a `Protocol` requiring only `send_media(bytes)`. The tests hand in a `FakeConn` that appends to a `sent` list — no network, no SDK dependence in the test path.

## Tests

`apps/api/tests/test_deepgram_stream.py` (16 cases):

- pass-through on matching rate/format
- 48 kHz stereo → 16 kHz mono resample byte-length check
- 44.1 kHz → 16 kHz resample within one sample
- F32LE → int16 conversion
- `PcmContinuityGuard` rejects duplicate seq / stale epoch / track change
- epoch advance resets assembler + records new offset base
- explicit `reset(new_epoch)` resets both
- Deepgram fixture replay emits `provisional` + exactly one `final_utterance` (using the recorded `simple_intro.json` from stage-1-prep)
- `final_utterance` carries `audio_epoch` + `sample_offset_start` + `sample_offset_end` mapped through the chunk's rate
- `tick` emits `speech_down` after the configured timeout
- Deepgram message after `speech_down` emits `speech_up` and clears the flag
- default 5.0 s timeout window (regression against `DEFAULT_SPEECH_DOWN_TIMEOUT_S`)
- resampler helper direct byte-length check
- unknown assembler event type raises `TypeError`

## Run commands (A's CI convention)

```bash
cd apps/api && python -m ruff check .
cd apps/api && python -m pytest -q
```

Numbers on this branch:

```
125 passed, 2 warnings in 3.89s
ruff: All checks passed!
```

`125 = 109 baseline` (A + B + D's Stage-1 test suite carried in the merge from `origin/person-c-stage-1-prep`) `+ 16 new` (`test_deepgram_stream.py`). The 2 warnings are `starlette.testclient` + `HTTP_422_UNPROCESSABLE_ENTITY` deprecations from A's suite — not from my new code.

I also added `Assembler.tick(now)` (the tiny public method that runs only the timeout-flush path). Existing assembler tests still pass; it's the same code path `feed()` runs at the top of every call.

## What I need from A

1. **A DeepgramConnection wrapper.** My bridge takes anything with `send_media(bytes)`. Give me the equivalent of the booth-demo pattern — `dg_client.listen.v1.connect(**opts)` with the `start_listening()` run in a thread — and I can drop it into `DeepgramStream(connection=…)` on the release path. If A prefers to own the SDK glue, I'll adapt to whatever object A hands me.
2. **PCM chunk ingest rate.** The tests use 10 ms chunks (160 samples at 16 kHz). What's the actual chunk cadence coming off A's worker? If chunks are 100 ms+ the SPEECH_DOWN timeout may need tuning — `speech_down_timeout_s` is a constructor arg for exactly that reason.
3. **`SPEECH_DOWN` propagation into `DirectorSession`.** I plan to wire `CLane.on_speech_down()` from `DeepgramStream`'s `speech_down` event (and matching `on_speech_up()`), so an ASR outage automatically pauses AUTO. That happens on the Stage-2 branch, not here; confirm the plan.
4. **Roster upstream.** Roster still lives in `apps/api/src/cue_api/semantics/roster.json` (C-owned). If A wants event-scoped rosters served from `/api/v1/events/{event}/roster`, I can adapt.

## Known gaps

- Linear-interpolation resampler; no low-pass filter → aliasing on high-frequency content. For prototype + booth this is fine; production should use a proper resampler (e.g. `resampy`, `soxr`) at C's boundary.
- `SPEECH_DOWN` reports only "no DG message since threshold"; it does not distinguish "socket dropped" from "silence in the room". `on_deepgram_message` receipt is the recovery signal either way, but a caller can consult the DG SDK's own close events for the distinction.
- The bridge assumes `sample_format` is stable across an epoch (A's `PcmContinuityGuard` enforces this). If A ever needs to allow in-epoch format changes, the resampler code path will need to re-latch.
