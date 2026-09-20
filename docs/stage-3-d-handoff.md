# Person D Stage 3 handoff: control link, evidence, failed-ACK and DEGRADED UI

Branch `codex/person-d-stage-3`, on top of the Stage 2 integration (trunk d396085). Date: 2026-09-19 (Boston).

Stage 3 for D in the v3 plan: evidence ages and reasons, failed-ACK and recording warnings, explicit ASSIST/AUTO/DEGRADED UI. A's Stage 2 handoff added the compositor side of the control socket to D's list. All of it is here. Nothing has run against a live feed.

## 1. Control link to A's backend (`apps/web/src/compositor/ProgramPanel.tsx`, `controlAdapter.ts`)

Enter the producer secret once on the producer page. While the LiveKit link is up, the compositor requests a `DIRECTOR` control session, opens A's socket with A's own `ControlSocketClient`, and from then on:

| Direction | Message | Source |
|---|---|---|
| up, on connect | `render.reconcile` with what is actually on the canvas (camera+epoch or SLATE) | `reconciliationFor()` |
| up, every 250 ms | `receiver.readiness` (the same payload the readiness panel shows) | `buildReadiness()` |
| up, per decision | `render.ack` with `APPLIED` (first drawn frame), `REJECTED` (gate failed, reason in `detail`) or `FAILED` (no frame within 1 s) | `ackToAcknowledgement()` |
| up, after any local cut | `render.reconcile` (manual slate, failover, revert) | `reconciliationFor()` |
| down | `control.state`: the switcher adopts the backend's generation, mode and revision | `syncControlState()` |
| down | `render.command`: converted to a `ShotDecision` and run through every switcher gate; duplicates by `decisionId` ignored | `commandToDecision()` |

Clocks: A stamps commands in wall milliseconds. The compositor maps with `performance.now() - Date.now()` at each use and acknowledges in wall milliseconds. Backend and browser share the Mac's clock.

Operator actions while linked go through A: TAKE calls `/take` with the slot's current epoch and the current revision; HOLD, ASSIST and AUTO call `/mode`. The compositor applies only the resulting `render.command`. If the backend refuses (stale revision, ended event), the refusal shows as a banner and nothing changes on air. **SLATE stays local** so it works with the backend gone, and is reconciled afterwards.

Without a producer secret, or when the socket is down, every control is local exactly as in Stage 2, and the mode strip says DEGRADED with "control link down: local manual mode".

## 2. Explicit ASSIST / AUTO / DEGRADED UI

A mode strip at the top of the compositor shows the effective mode in large type with a one-line meaning, and the backend's own mode, revision and live camera next to it. DEGRADED is computed, not chosen, from: media link down, control link wanted but not connected, no master audio, no renderable camera, draw loop throttled, recording error, chunks not persisted. The underlying control mode is still shown so the operator knows what AUTO would do once the degradation clears.

## 3. Failed-ACK and recording warnings

- A switch that draws no frame within 1 s is acknowledged `FAILED` (`ACK_TIMEOUT`), the tally never goes red for it, and the compositor reverts to the previous source if renderable, else a safe source, else the slate, with reason `ACK_TIMEOUT_REVERT`. A red banner explains it for 10 s. (`expirePendingAck()`, tested.)
- Backend refusals and socket errors show as an amber banner for 8 s and in the log.
- Recording errors, unpersisted chunks and a recording without audio each get their own banner, separate from the tally.

## 4. Evidence ages and reasons (`apps/web/src/producer/evidenceView.ts`)

While connected, the page polls B's `GET /api/v1/guests/observations` every 500 ms with the operator credential and shows one line per tile:

| B's status | Tile shows |
|---|---|
| CONFIRMED with a consenting guest | `Sarah Tan: face match` · age · named take allowed/not allowed · calibration note |
| PROVISIONAL | `Sarah Tan? provisional` |
| AMBIGUOUS | `ambiguous: more than one possible match, no name` |
| UNKNOWN | `unknown face, not an enrolled guest` |
| LOW_QUALITY | `face too small or unclear to identify` |
| NO_FACE | `no face in frame` |
| stale or wrong epoch | struck through, with the epoch mismatch spelled out |

Never a percentage. "Named take allowed" is B's `supportsNamedTake` plus backend freshness plus the tile's current stream epoch. The decision timeline shows A's `reasonCode` for backend commands and the switcher's evidence text for local ones.

## 5. Contract changes (`packages/contracts/src/switching.ts`)

- `controlGeneration` is a string (A's opaque generation; `"local"` for renderer-issued decisions).
- `reason` is an open string; the renderer's own codes stay listed as `KnownDecisionReason`.
- `issuerDecisionId` links a decision and its ack to A's `decisionId`.
- Ack outcome adds `FAILED`; reject reasons add `ACK_TIMEOUT`.

## 6. Verification

Automated on the Mac: `npm run typecheck`, `npm test` (157 tests: 27 switcher, 6 adapter, 6 evidence among them), `npm run build`. In-process protocol check against A's real control socket with D's payload shapes: session, authenticate, readiness with `currentSource: "SLATE"`, reconcile, manual TAKE, `APPLIED` ack in wall time, HOLD invalidating a pending command's late ack, metrics. Results in the commit message.

Not run: anything with a real feed. The Stage 3 exit gate in the v3 plan is one genuine end-to-end live sequence: future mention holds, unscripted introduction takes the verified guest, covered camera fails over, manual HOLD wins. That needs A, B and C publishing and C's policy driving A's backend.

## 7. For A and C

- A: `readiness.py` accepts `"SLATE"` as `current_source`. On the integrated A Stage 3 branch, a trusted `render.reconcile` invalidates an outstanding command, records it as rejected and advances the revision, so a local slate/failover or reconnect cannot remain stuck behind an unreachable ACK.
- C: policy cuts arrive at the compositor only as A's `render.command`; C's `plainReason` and transcript span are not on that message. If A adds them to `RenderCommand` the timeline will show them as evidence text.
