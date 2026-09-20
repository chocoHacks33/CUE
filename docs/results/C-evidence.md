# C-lane · Evidence, one page

_Branch `person-c-stage-5`, based on `person-c-stage-4`._

Every number below comes from a real command run on this branch. If a
number is missing, the row says **NOT RUN** and points to the script
that will produce it on the Mac.

## Test count

```
python -m pytest -q
539 passed, 2 skipped, 2 warnings                      # Stage 4
542 passed, 2 skipped, 2 warnings                      # Stage 4 bugfix
```

Stage-4 baseline was 525 tests inherited from `codex/stage-3-integration`.
Stage 4 added 14 failure-injection tests + 3 identity-field tests.

## The 14 failure-injection scenarios (offline)

`apps/api/tests/test_failure_injection.py` — all PASS.

| # | Scenario | Outcome |
|---|---|---|
| 1 | Parser TimeoutError | HOLD cue, STAY |
| 2 | Parser HTTP 429 | HOLD cue, STAY |
| 3 | Parser malformed JSON | HOLD cue, STAY |
| 4 | Parser refusal | HOLD cue, STAY |
| 5 | Deepgram disconnect | SPEECH_DOWN, auto TAKE blocked, manual TAKE still works |
| 6 | Reconnect with new audio_epoch | Stale-epoch messages dropped by the assembler |
| 7 | Duplicate final `Results` frame | Exactly one decision (post-flush guard in the assembler) |
| 8 | Camera state older than `camera_state_max_age_s` | No named TAKE; STAY with a reason |
| 9 | Live camera unhealthy, healthy wide | WIDE fallback |
| 10 | Live camera unhealthy, no healthy wide | SLATE |
| 11 | Burst of 10 utterances in one drain window | 1 in-flight + latest pending; remainder logged as `dropped` |
| 12 | Stale-`mode_revision` cue after HOLD | Rejected at the session boundary |
| 13 | Missing / `applied=False` ACK | `current_camera` unchanged |
| 14 | Prompt-injection sentences (3 variants) | HOLD, HOLD, HOLD |

## Soak (offline, 2 minutes)

`python scripts/soak_c_lane.py --minutes 2`

- Loops: 12
- Decisions emitted: 79
- Duplicate `decision_seq`: **0**
- Max SemanticQueue depth: **1**
- Log size: 57 252 bytes (well under the 12 MB / 20 min cap)
- Memory delta: NOT measured (Windows lacks `resource`; re-run on Mac)
- Verdict: **all four invariants PASS**

## Contracts

- `docs/contracts-proposal/decision_record.schema.json` includes the new
  `identity` enum (`ROLE_BASED` | `VERIFIED`).
- `cue_api.policy.wire.DecisionEvent` carries `identity` on the wire,
  additively — a client that ignores it still works. A is asked to
  confirm the schema extension (see `C-stage4.md`).

## Ruff

`python -m ruff check .` → **All checks passed** on Stage 4 and Stage 5.

## NOT RUN and why

| Cell | Blocked by | Script that fills it |
|---|---|---|
| Held-out wrong SHOW cuts | `OPENAI_API_KEY` + `CUE_MODEL` | `scripts/release_eval.py` |
| Held-out pass rate | same | same |
| Dev pass rate | same | same |
| Live total p50 / p95 latency | `OPENAI_API_KEY` + `DEEPGRAM_API_KEY` + mic | `scripts/latency_run.py` |
| 20-min soak with real RSS | Windows lacks `resource` | `scripts/soak_c_lane.py --minutes 20` on the Mac |
| Live semantic dev-set run | `OPENAI_API_KEY` + `CUE_MODEL` | `scripts/run_semantic.py --models "$CUE_MODEL" --set dev` |

The full commands and files-to-send-back are in `docs/results/C-stage4.md`.

## Result files (this branch)

- `docs/results/C-stage3.md`
- `docs/results/C-stage4.md`
- `docs/results/C-soak.md`
- `docs/results/C-scope-decision.md`
- `docs/results/C-feature-freeze.md`
- `docs/results/heldout_runs.jsonl` — populated by `release_eval.py`
  on the Mac.
- `docs/DEMO-C.md`, `docs/C-INTEGRATION.md` — operator-facing.

## One-line summary

Every offline safety property gated by the plan is green. Three release
gates (held-out cuts / held-out pass / live p95) are still measurement,
not code. Ship ASSIST + role_based until those come back clean.
