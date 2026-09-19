# Stage 2 integration check (A + B + C + D)

Integrated by D on the Mac, 2026-09-19 (Boston). Branch `codex/stage-2-integration` from trunk cf9dded (which already held B's Stage 2 via PRs #11 and #13 and D's Stage 2 via #12).

## Merged

| Lane | Branch | Result |
|---|---|---|
| A | `codex/person-a-stage-2` (3c54163): control state, control socket, readiness ingestion, camera health, worker ingestion, browser control client, fixture loop | merged; two conflicts resolved (below) |
| C | `person-c-stage-2` (ae9d360, includes C's Stage 1 Deepgram bridge and Stage 2 prep): director session, semantic queue, decision log, explain, wire adapter, fixture cue producer | merged clean |
| B | already on trunk | no action |
| D | already on trunk | no action |

## Conflicts and fixes

| File | Cause | Resolution |
|---|---|---|
| `packages/contracts/src/index.ts` | A's branch predates B's `vision` to `guests` rename and D's `switching` export | trunk's exports kept, A's `export * from "./control"` added |
| `apps/api/pyproject.toml` | same, around B's optional extra and console script names | trunk's names kept, A's `cue-stage2-fixture` script added |
| `apps/api/src/cue_api/worker_ingest.py` | A imports `cue_api.vision.types.DecodedFrame`, which B moved to `cue_api.guests.types` | import repointed; the kwargs A passes all exist on B's dataclass. Note for A and B: `worker_ingest.to_vision_frame` and B's `guests/frame_intake.py` both adapt A's `DecodedVideoFrame` to B's `DecodedFrame`; pick one |
| `apps/api/src/cue_api/readiness.py` | A's Python `ReceiverReadiness.current_source` accepted only a camera or null, while the TypeScript contract (and A's own browser client validator) accept `"SLATE"`, which D's compositor reports on the safe picture | widened to `CameraId \| Literal["SLATE"] \| None`; `current_source` is not read anywhere else. Test: `tests/test_readiness_slate.py` |

## Verification on the merged tree (macOS 26.3 arm64, Node 25.9, Python 3.14.5)

| Check | Result |
|---|---|
| `npm run typecheck`, `npm test`, `npm run build` | pass, 140 tests |
| `apps/api`: `pytest` | 416 passed, 13 skipped |
| `apps/api`: `ruff check .` | clean |
| `python -m cue_api.stage2_fixture_cli` | runs, `"fixtureOnly": true`, ends with an `APPLIED` acknowledgement |

## Contract notes for Stage 3 (D wires the compositor to A's socket)

- A stamps `createdAtMs`, `expiresAtMs` and validates `appliedAtMs` in wall-clock milliseconds (`time.time() * 1000`). The compositor's switcher works in `performance.now()`. The offset is `performance.now() - Date.now()`; backend and browser run on the same Mac.
- A's `RenderCommand` uses a string `controlGeneration` and a `decisionId`; D's `ShotDecision` used a numeric generation. D adapts in Stage 3.
- C's `policy/wire.py` emits a `DecisionEvent` shape that is not A's `RenderCommand`. That is A and C's reconciliation; D consumes only `render.command`.

## Not run

Every physical row in `docs/results/a-stage2-integration-check.md` and in D's Stage 2 handoff. No real feed has reached the Mac yet.
