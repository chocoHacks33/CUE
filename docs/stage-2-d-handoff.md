# Person D Stage 2 handoff: compositor, manual control, render ACK, programme recording

Branch `codex/person-d-stage-2`, one commit on top of the integrated Stage 1 trunk `codex/person-a-stage-0` (f8b765f). Date: 2026-09-19 (Boston).

Stage 2 for D in the v3 plan: three continuously decoded previews, actual render ACK, manual TAKE/HOLD/slate, fixed audio, local recording persistence. All five are in this branch. None of it has run against a real camera feed yet; see section 6.

## 1. What is on the producer page now

The right column starts with the **Compositor** panel:

- A 1280x720 programme canvas. It draws exactly one source with a hard cut: a camera tile's decoded video, letterboxed or pillarboxed, never stretched, never mirrored; or a static slate.
- **TAKE** buttons for CAM-HOST, CAM-GUEST, CAM-WIDE (keys 1, 2, 3), disabled unless the slot is renderable right now. **SLATE** (key 0) is always available. **HOLD** (key H) freezes the programme against policy decisions and is released to ASSIST. **Enable AUTO** is an explicit button; nothing ever resumes AUTO by itself. Keys are ignored while an input has focus.
- A **tally**: red `LIVE CAM-X` only after the canvas has drawn the first frame of that source; amber `SWITCHING` in between; grey `SLATE`.
- **Programme recording**: canvas capture plus the master audio, one-second chunks persisted to IndexedDB as they arrive, inline playback and download with the real container extension, plus recovery of recordings interrupted by a crash. Recording state and errors are shown separately from the tally.
- A **decision timeline** (every acknowledgement, applied or rejected, with reason) and a JSON export.

The three preview tiles, master audio panel, pairing panel and receiver log are unchanged. The readiness contract preview now reports `currentSource` as the camera on air or `SLATE`.

## 2. Contracts added (`packages/contracts/src/switching.ts`)

| Type | Purpose |
|---|---|
| `ShotDecision` | A request to put a source on the programme: sequence, control generation, mode revision, origin (`OPERATOR`, `POLICY`, `SAFETY`), target (camera or `SLATE`), target stream epoch, reason code, evidence text, clock domain, created/expires |
| `RenderAck` | The compositor's answer: `APPLIED` with the time of the first drawn frame, or `REJECTED` with one of 15 reason codes, plus what is actually rendered, renderer id and generation, and the renderer's mode revision at that moment |
| `isShotDecision`, `isRenderAck` | Structural validators for the wire |

Reason codes for rejection: `WRONG_EVENT`, `EVENT_ENDED`, `STALE_CONTROL_GENERATION`, `DUPLICATE_OR_OUT_OF_ORDER`, `TIMING_UNCERTAIN`, `EXPIRED`, `STALE_MODE_REVISION`, `OPERATOR_HOLD`, `ASSIST_SUGGEST_ONLY`, `UNKNOWN_TARGET`, `NOT_RENDERABLE`, `EPOCH_MISMATCH`, `ALREADY_ON_AIR`, `MIN_SHOT_DURATION`, `SUPERSEDED`.

## 3. The switcher (`apps/web/src/compositor/switcher.ts`)

A pure reducer with 22 tests. Every change to the programme, from the operator, a future policy, or the health failover, is a `ShotDecision` that passes the same gates in this order, mirroring PRD section 10:

1. event id, `ENDED` mode, control generation (0 is local), sequence monotonic per generation
2. clock domain: backend-clock decisions are rejected `TIMING_UNCERTAIN` until the backend supplies an offset (`backendClockOffsetMs`), then expiry is checked in renderer time
3. mode revision must equal the renderer's current one; every manual action bumps it, applied or not, so a late decision computed before the operator acted is rejected
4. origin rules: `POLICY` is refused in `MANUAL_HOLD`, parked as a suggestion in `ASSIST` (operator presses TAKE to accept), executed only in `AUTO`; `SAFETY` runs in every mode including hold
5. target: slot must be renderable now and on the expected stream epoch; taking what is already on air is rejected; policy cuts respect the 2.5 s minimum shot, manual and safety cuts do not
6. apply: the programme intent changes and an `APPLIED` ack is parked. `confirmDraw` finalises it when the canvas actually draws the new source. An unconfirmed switch overtaken by another is acked `SUPERSEDED`.

Health failover (`runHealthCheck`, every 250 ms): if the on-air camera has been unrenderable for 1.5 s, cut to the first camera in the safe order (`CAM-WIDE`, `CAM-HOST`, `CAM-GUEST`) that has been healthy for at least 2 s; otherwise the slate. From a failover slate, return to the first safe camera once it has been healthy for 2 s. A slate the operator chose is never left automatically. A republish of the on-air camera updates epoch and track SID without a cut. Tuning values are the PRD's starting points and are unmeasured.

Local decisions use control generation 0 and never reuse a sequence the renderer has already consumed.

## 4. Fixed audio and recording

- The recorder's audio is one stable track from a Web Audio destination node. Whatever master track exists (A's microphone, including after a republish) is routed into it. Video cuts never touch audio; an audio republish changes the feed, not the output track. If the master track disappears the output goes silent rather than switching to another microphone.
- Chunks persist to IndexedDB (`cue-programme` database) as they arrive, including the first chunk with the container header. On stop the file is assembled from the persisted chunks when they are all there, otherwise from memory, and the panel says which. On the next page load, recordings left in `recording` state are listed as interrupted with assemble-and-download and delete. An interrupted file may need repair; the panel says so.
- If IndexedDB is unavailable the recorder falls back to memory and says so.

## 5. What A and C need from this, and what D needs from them

- **A, control socket**: transport `RenderAck` and `ReceiverReadiness` up, `ShotDecision` down. The renderer currently keeps the last ack in `lastAckRef` and narrates it in the log; there is no socket client yet. To evaluate backend decisions the renderer needs `controlGeneration` and a clock mapping (`backendClockOffsetMs`); until both are set, every backend decision is rejected `TIMING_UNCERTAIN` or `STALE_CONTROL_GENERATION` and the ack says so. A handshake message carrying the backend's generation and its clock at send time is enough.
- **A, operator actions through the backend**: when the socket exists, TAKE and HOLD should go to the backend (`/take`, `/mode` with expected revision and idempotency key) so the backend's state machine stays authoritative. The local path stays as the degraded mode when the backend is gone.
- **C, policy**: emit `ShotDecision` with origin `POLICY`, the roster target's camera, the target's current stream epoch, a reason code from the list, and the transcript span as `evidence`. The renderer decides whether it can render; C's own gates still apply before sending.

## 6. Verification actually run

Automated on this Mac, 2026-09-19:

| Check | Result |
|---|---|
| `npm run typecheck` | pass |
| `npm test` | pass: 132 tests on the branch rebuilt on the Stage 1 trunk (f8b765f), of which 22 switcher, 5 canvas geometry, 6 recording store, 3 switching contract, 3 readiness builder |
| `npm run build` | pass |

Not run anywhere: a real cut between two live webcams, the failover on a covered lens, the audio staying continuous through a cut on the recorded file, the clap test, the 20-minute soak. Those are the Stage 2 exit gate in the v3 plan and need A, B and C publishing.

## 7. Known limits

- The canvas draws from the preview tiles' video elements. If the page is hidden, browsers throttle timers; the panel reports the draw interval and flags throttling, but a hidden tab still means a degraded programme. Keep the producer page visible.
- No transitions, no graphics overlays, no audio ducking. Hard cuts only, by design.
- Failover selection uses slot readiness (frames arriving); it cannot see a lens covered with the frames still flowing. That is B's quality gate in a later stage.
