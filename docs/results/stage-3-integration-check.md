# Stage 3 integration check (A + B + C + D)

Integrated by D on the Mac, 2026-09-19 (Boston). Branch `codex/stage-3-integration` from trunk 4866d53 (which already held B's Stage 3 via PRs #15 and #17 and D's Stage 3 via #16).

## Merged

| Lane | Branch | Result |
|---|---|---|
| A | `codex/person-a-stage-3` (eca5604): trusted video attach/detach, server-owned stream epochs, duplicate-slot rejection, observation invalidation on track change, event-end and fencing, browser transport client and sequencer, D's Stage 3 renderer merged in | merged clean |
| C | `person-c-stage-3` (f7fa8bd): live async lane (PCM to Deepgram to parser to director), parser hardening (duplicate names, role holders, bounded context, hard timeout, safe HOLD, pinned model required), no-double-cut proofs, latency trace and report, 16 new dev cases (46 to 62) | merged clean |
| B | already on trunk (#15, #17) | no action |
| D | already on trunk (#16) | no action |

No conflicts in either merge. A's copy of D's compositor files is byte-identical to trunk apart from one line in `docs/stage-3-d-handoff.md`.

## Verification on the merged tree (macOS 26.3 arm64, Node v25.9.0, Python 3.14.7)

| Check | Result |
|---|---|
| `npm run typecheck` | clean |
| `npm test` | 166 passed (43 contracts, 123 web) |
| `npm run build` | production build OK |
| `apps/api`: `pytest` | 522 passed, 13 skipped |
| `apps/api`: `ruff check .` | clean |
| `python -c "import cue_api.main, cue_api.c_lane_live, cue_api.transport, cue_api.lifecycle"` | imports OK |
| `scripts/live_lane.py`, `scripts/latency_report.py`, `scripts/run_semantic.py`, `scripts/fixture_cues.py` with `--help` | all import and exit 0 |

All 13 skips are `tests/test_guest_opencv_adapters.py`: YuNet/SFace model weights are not downloaded on this Mac. Same count as trunk before this integration.

## Integration notes

- C's live lane (`cue_api.c_lane_live`) is not yet called from A's runtime. It is a standalone runner (`scripts/live_lane.py`) whose `DecisionSender` protocol is where A's `ControlStore.policy_take` plugs in. Nothing in `main.py`, `worker_ingest.py`, `control.py` or `transport.py` references it. A and C own that seam.
- C based on `codex/stage-2-integration` out of concern that A's and B's prep branches deleted C's Stage 2 files. Trunk kept them; the merge needed no rebase.
- A's handoff: install the `opencv` extra on this Mac before the physical gate.

## Not run

- Every row of `docs/results/a-stage3-integration-check.md` (13 rows, all NOT RUN).
- C's live measurements: dev-set pass rate on the 62 cases against the pinned OpenAI model, the real mic-to-Deepgram lane, real latency numbers.
- B's held-out identity trials (30 positives, 30 unknown/ambiguous) on real people; B's readiness gate currently returns ROLE_BASED.
- The Stage 3 exit gate: one genuine live sequence (future mention holds, unscripted introduction takes, covered camera fails over, manual HOLD wins) with real webcams and the master microphone. No live feed has reached this Mac at any stage.
