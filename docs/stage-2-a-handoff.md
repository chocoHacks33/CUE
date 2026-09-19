# Person A Stage 2 handoff

Branch: `codex/person-a-stage-2`

Person A's Stage 2 code is complete on this branch. The automated fixture joins
C's deterministic policy to A's control state and a simulated compositor ACK.
It is deliberately labelled fixture-only: D must still run the real three-feed
Mac compositor and recording gates before the team's Stage 2 exit gate passes.

## What A completed

- Authoritative per-event control state with process generations, monotonic
  decision sequences, mode revisions and idempotent mutations.
- Manual mode/TAKE endpoints and AUTO-only policy TAKE/slate methods. A manual
  action invalidates any pending automated command before it can become LIVE.
- Short-lived, hashed, role-scoped control credentials. The token is sent as
  the first WebSocket message, never in the URL. Observers cannot ACK,
  reconcile, report renderer readiness or otherwise mutate the programme.
- Renderer commands bound to one generation, revision, sequence, target,
  camera and stream epoch. LIVE changes only after D ACKs the exact rendered
  target; expired, stale, mismatched and duplicate-conflicting ACKs are rejected.
- Camera and safety-slate reconciliation after a compositor reconnect or API
  restart. An old-generation ACK cannot alter the restarted backend.
- Renderer-readiness ingestion with single-renderer ownership, generation
  checks, exact three-slot validation and server-clock frame-progression health.
- Per-camera health keyed by stable camera ID and current stream epoch, with a
  one-second stall threshold and a two-second stable recovery gate.
- Capacity-one, latest-frame-only video ingestion for B, including validated
  RGB/BGR/RGBA, stride, rotation and mirror conversion to upright BGR frames.
- Bounded, ordered PCM ingestion for C. Overflow and sample gaps are visible;
  audio is never silently replaced like video.
- A typed browser control client with authenticated connection, safe parsing,
  ACK/reconcile/readiness messages and bounded reconnect backoff.
- Per-event TAKE-to-ACK p50/p95/max metrics and rejected/outstanding counts.
- A fixture-only cue → policy → command → compositor → ACK loop covering a
  named take, future mention (no cut), and no-healthy-camera safety slate.

## Safety invariants D must preserve

1. Keep one `DIRECTOR` compositor. Diagnostics use `OBSERVER` sessions.
2. Keep all three feeds decoded. A connection icon alone is not readiness.
3. On `render.command`, verify generation, revision, expiry, target and current
   stream epoch before drawing anything.
4. Send `APPLIED` only after the requested source is actually on the programme
   canvas. Use `REJECTED` or `FAILED` otherwise.
5. `CAM-HOST` remains the sole programme audio source through every video cut.
6. On reconnect, send `render.reconcile` with the camera/epoch actually drawn,
   or `actualTarget: "SLATE"` with null camera/epoch.
7. Send `receiver.readiness` continuously from the real decoded slots. Do not
   infer visual usability from a LiveKit connection alone.

## Automated verification on A

From `apps/api`:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m cue_api.stage2_fixture_cli
```

From the repository root:

```powershell
npm.cmd test
npm.cmd run typecheck
npm.cmd run build
```

The CLI output must say `"fixtureOnly": true`, end with `CAM-GUEST` LIVE and
show an `APPLIED` acknowledgement. It proves contract wiring, not a real cut.

## D's real-Mac acceptance gate

After A's commit is merged into D's Stage 2 branch:

1. Start the existing API and web app on the Mac using the Stage 0/1 runbook.
2. Connect the compositor as `DIRECTOR`; open any diagnostics as `OBSERVER`.
3. Confirm readiness reports show the exact `CAM-HOST`, `CAM-GUEST`,
   `CAM-WIDE` order, current epochs and advancing frame counts.
4. Run at least one fixture cue through the real policy. D must draw the target
   on its real canvas and only then ACK it; verify backend LIVE matches canvas.
5. Run manual TAKE across all three real feeds, then HOLD while an AUTO command
   is pending. The stale automated command must not change LIVE.
6. Cover the live source or stop its publisher. Confirm stall is detected and a
   safe wide/slate action can be rendered without switching programme audio.
7. Restart the backend while the compositor stays open. The old command must be
   rejected and the compositor must reconcile its actual camera or slate.
8. Record and play a real three-camera programme with continuous A audio. Run
   the clap/flash timing check and close extra observers for the load trial.
9. Record 30 manual cuts and inspect `/control-metrics`; the plan target is p95
   TAKE-to-ACK below 300 ms. Save results in
   `docs/results/a-stage2-integration-check.md`.

Person A integrates fixes; D owns and signs off the physical Mac results. Until
those rows are PASS, report “A Stage 2 code complete; system gate not yet run.”
