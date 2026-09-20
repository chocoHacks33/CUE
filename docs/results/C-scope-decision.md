# C-lane · Scope decision

_Branch `person-c-stage-4`, based on `origin/codex/stage-3-integration`._

The v3 plan says: ship AUTO cuts only when the release evaluation is
clean. Otherwise ship ASSIST (CUE suggests, producer confirms). If face
identity is unreliable, ship role-based mapping and disclose it.

This file is a criteria matrix. Every cell is either a measured value
(from Stage-4 scripts) or the words **NOT RUN**. No guesses.

## Criteria matrix

| Criterion | Threshold for AUTO | Measured value | Verdict |
|---|---|---|---|
| Held-out wrong SHOW cuts | `= 0` | **NOT RUN** — requires `OPENAI_API_KEY` + `CUE_MODEL`; see `scripts/release_eval.py` | inconclusive |
| Held-out pass rate | `≥ 90%` | **NOT RUN** — same script | inconclusive |
| Dev pass rate | `≥ 90%` (gate before touching held-out) | **NOT RUN** — same script | inconclusive |
| Live total p95 latency | `≤ 2500 ms` | **NOT RUN** — `scripts/latency_run.py` needs mic + both keys | inconclusive |
| Live total p50 latency | `≤ 1500 ms` | **NOT RUN** — same script | inconclusive |
| Duplicate `decision_seq` in soak | `0` | **0** over 2 min replay, 79 decisions | PASS |
| Max SemanticQueue depth in soak | `≤ 2` | **1** | PASS |
| Log growth in soak | `≤ 12 MB / 20 min` | **57 KB / 2 min** (extrapolated ≤ 600 KB / 20 min) | PASS |
| Memory growth in soak | `≤ 50 MB / 20 min` | **not measured on Windows** (`resource` module missing); PASS-by-guard, re-measure on Mac | to re-measure |
| Split-utterance correction yields one TAKE | offline invariant | **PASS** (`test_no_double_cuts.test_split_correction_yields_one_take`) | PASS |
| Late cue after HOLD rejected by mode_revision | offline invariant | **PASS** (`test_no_double_cuts.test_late_cue_after_manual_hold_is_rejected_by_mode_revision`) | PASS |
| Failure paths end in safe state | offline invariant | **PASS** — all 14 failure-injection scenarios in `test_failure_injection.py` | PASS |
| Prompt-injection transcript never cuts | offline invariant | **PASS** (validate() forces UNCERTAIN → HOLD) | PASS |
| Parser hard-timeout collapses to HOLD | offline invariant | **PASS** (`test_parser_hardening.test_parse_hard_timeout_paths_to_safe_hold`) | PASS |
| Duplicate final `Results` frame → one decision | offline invariant | **PASS** (`test_failure_injection.test_duplicate_final_transcript_yields_one_decision`, backed by assembler post-flush guard) | PASS |
| Camera-state expiry blocks named TAKE | offline invariant | **PASS** | PASS |
| Unhealthy live → WIDE → SLATE | offline invariant | **PASS** | PASS |

## Recommendation

**Ship ASSIST, not AUTO, until the release evaluation runs on the Mac.**

Every offline safety property required by the plan is green:
correction-yields-one-cut, mode-revision reject, parser-error safe HOLD,
prompt-injection guard, camera expiry, unhealthy fall-back, ACK
handling, burst coalescing, and a 2-minute soak with 0 duplicate
decisions and queue depth 1. But the three cells that gate AUTO —
held-out wrong SHOW cuts, held-out pass rate, and live total p95 — all
need a network run I cannot execute offline. Until those are measured,
default to **ASSIST**: CUE proposes the next shot, the producer
confirms with the CTA. That surface is already wired.

## Identity mode

B's unknown-person rejection has not been validated against my roster
IDs in a joint run. Until it is, ship **role-based** mapping. Every
`DecisionRecord` from `LiveLane` carries
`latencies_ms["_identity"] = 1.0`. This is a sentinel: the UI treats
`1.0` as "ROLE_BASED" and does not render "identified as" text; the
demo script should disclose the mode aloud. When B's provider is
validated, flip `LiveLane(role_based=False)` and the sentinel becomes
`0.0`.

## What the Mac run needs to change

1. `python scripts/release_eval.py` — fills the top three inconclusive
   cells. Held-out is refused if the prompt hash changed without
   `--acknowledge-retune`.
2. `python scripts/latency_run.py` (12 sentences) — fills the two
   latency cells. Compare medians and p95 against the printed targets.
3. `python scripts/soak_c_lane.py --minutes 20` — re-runs the soak with
   real `resource` numbers and confirms the four operational invariants
   hold for the full 20-minute window.

Only after all three are clean should the demo run in `role_based=True`
AUTO. If any cell fails, stay in ASSIST — that is the plan's default,
not a downgrade.
