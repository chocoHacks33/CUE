# C-lane · Stage 4 status

_Branch `person-c-stage-4`, based on `origin/codex/stage-3-integration`_
_(the newest team integration branch that already contains my Stage 3)._

Stage 4 is **failure tests, release evaluation, scope decision**. No
new product features.

## What went in

| Purpose | Files |
|---|---|
| Release evaluation (dev + held-out, prompt-hash ledger) | `scripts/release_eval.py` |
| Live latency probe (12 sentences) | `scripts/latency_run.py` |
| Real-time soak (offline replay through CLane) | `scripts/soak_c_lane.py` |
| Failure-injection tests (14 scenarios) | `apps/api/tests/test_failure_injection.py` |
| Post-flush duplicate guard in the assembler | `apps/api/src/cue_api/speech/assembler.py` |
| Scope decision matrix + freeze doc | `docs/results/C-scope-decision.md`, `C-feature-freeze.md` |
| Held-out run ledger (append-only) | `docs/results/heldout_runs.jsonl` (auto-created) |

## Tests

- Full run: **`539 passed, 2 skipped, 2 warnings`** (Stage-3 baseline
  was 444 + 29 new = 473 without integrated teammate tests; the
  `codex/stage-3-integration` base contributes the rest).
- `ruff check .`: **All checks passed**.

## Scripts verified offline

- `scripts/soak_c_lane.py --minutes 2`
  - Elapsed: 2.0 min, 12 timeline loops, 79 decisions
  - Duplicate `decision_seq`: **0**
  - Max SemanticQueue depth: **1**
  - Log size: **57 252 bytes** (well under the 12 MB cap for 20 min)
  - Memory invariant skipped on Windows (`resource` module missing);
    re-run on the Mac to confirm.
- `scripts/release_eval.py` (no keys): exits **2** with
  `OPENAI_API_KEY not set` as required. Never runs a silent default.
- `scripts/latency_run.py` (no keys): exits **2** with the missing-key
  message. Requires a mic for the actual run.

## Failure injection — every scenario green offline

1. Parser timeout / HTTP 429 / malformed JSON / refusal → HOLD, STAY.
2. Deepgram disconnect → SPEECH_DOWN blocks AI TAKEs, manual TAKE
   still works, RESUME_AUTO required to un-pause.
3. Reconnect with a new `audio_epoch` → stale-epoch messages dropped.
4. Duplicate final `Results` frame → exactly one decision (assembler
   post-flush duplicate guard).
5. Camera state older than expiry → no named TAKE; STAY with a reason.
6. Live camera unhealthy → WIDE fallback; no healthy wide → SLATE.
7. Burst of 10 utterances in one drain window → 1 in-flight, latest
   pending, remaining 8+ dropped.
8. Stale-`mode_revision` cue after HOLD → rejected.
9. Missing / `applied=False` ACK → `current_camera` unchanged.
10. Prompt-injection transcripts (three variants) → HOLD.

## NOT RUN offline

The full list is in `docs/results/C-scope-decision.md`. The three cells
that gate AUTO all need a Mac run:

- Held-out wrong SHOW cuts (target 0)
- Held-out pass rate (target ≥ 90%)
- Live total p50 / p95 (targets 1.5 s / 2.5 s)

## Handoff — exact commands, in order, on the Mac

```bash
# 0. From the repo root; assumes the apps/api venv is active.
cd apps/api && python -m pip install -e ".[dev,desk]"
cd ../..

# 1. Smoke the credentials + roster.
python scripts/smoke_api.py

# 2. Release evaluation (dev + held-out).
#    Requires OPENAI_API_KEY and CUE_MODEL in the env.
#    Refuses if the SYSTEM prompt hash changed without acknowledgement.
python scripts/release_eval.py
# Writes:
#   docs/results/C-release-eval.md    (human summary)
#   docs/results/C-release-eval.json  (machine summary)
#   docs/results/heldout_runs.jsonl   (append-only ledger)

# 3. Live latency probe (12 sentences).
#    Requires OPENAI_API_KEY, DEEPGRAM_API_KEY, CUE_MODEL and a mic.
python scripts/latency_run.py
# Writes:
#   docs/results/C-latency.md
#   docs/results/C-latency.json

# 4. Soak (20 min).
python scripts/soak_c_lane.py --minutes 20
# Writes:
#   docs/results/C-soak.md

# 5. Send me back:
#    docs/results/C-release-eval.md    docs/results/C-release-eval.json
#    docs/results/C-latency.md         docs/results/C-latency.json
#    docs/results/C-soak.md
#    docs/results/heldout_runs.jsonl
```

## Pitch-number checklist — where each number comes from

| Number in the pitch | Source (script → cell) |
|---|---|
| Dev pass rate | `release_eval.py` → `dev.pass_rate` |
| Held-out pass rate | `release_eval.py` → `heldout.pass_rate` |
| Wrong SHOW cuts (held-out) | `release_eval.py` → `heldout.wrong_cuts` |
| Semantic p50 / p95 latency | `release_eval.py` → `dev.p50_ms` / `dev.p95_ms` |
| Live end-to-end p50 / p95 | `latency_run.py` → `hops.total_ms` |
| Deepgram commit latency | `latency_run.py` → `hops.final_ms` |
| Parser + policy latency | `latency_run.py` → `hops.cue_decide_ms` |
| Duplicate decisions (soak) | `soak_c_lane.py` → `duplicate_seqs` |
| Queue depth (soak) | `soak_c_lane.py` → `max_queue_depth` |
| Memory growth (soak) | `soak_c_lane.py` → `rss_delta_mb` (Mac/Linux only) |
| Log growth (soak) | `soak_c_lane.py` → `log_bytes` |
| Identity mode disclosure | `LiveLane` → `latencies_ms._identity == 1.0` = ROLE_BASED |

## Recommendation (today, offline evidence only)

Every offline safety property gated by the plan is green:
correction-yields-one-cut, mode-revision reject, parser-error safe HOLD,
prompt-injection guard, camera-expiry gate, unhealthy fall-back, ACK
handling, burst coalescing, and a 2-minute soak with zero duplicate
decisions and queue depth 1. **The three cells that gate AUTO —
held-out wrong cuts, held-out pass rate, and live total p95 — are still
NOT RUN.** Ship the demo in **ASSIST + role_based** by default: CUE
proposes, the producer confirms, every DecisionRecord is stamped
`_identity=1.0`. Flip to AUTO only after the Mac run comes back with
`heldout.wrong_cuts=0`, `heldout.pass_rate ≥ 90%`, and
`hops.total_ms.p95 ≤ 2500`. Anything less is not a downgrade — it is
the plan's default.
