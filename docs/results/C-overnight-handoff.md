# C-lane · Overnight handoff (Stage 6)

_Branch `person-c-stage-6`, based on `person-c-stage-5` (no
`person-c-assist` branch exists yet)._

Offline only. This is a status snapshot before Sunday morning. Nothing
below is a design change; everything is verification of what we already
have plus a runbook for tomorrow.

## Branch tips

| Branch | Local (short) | Origin (short) | Notes |
|---|---|---|---|
| `person-c-stage-1` | `591961d` | `591961d` | Stage-1 Deepgram bridge |
| `person-c-stage-2` | `ae9d360` | `ae9d360` | Stage-2 CLane façade |
| `person-c-stage-3` | `f7fa8bd` | `f7fa8bd` | Stage-3 live lane |
| `person-c-stage-4` | `68cd286` | `68cd286` | Stage-4 failure tests |
| `person-c-stage-5` | `f27da7c` | `f27da7c` | Stage-5 freeze + evidence |
| `person-c-stage-6` | `f27da7c` (new) | pending push | this branch |
| `person-c-desk-prototype` | `e5a4be7` | `bfce836` | held; do not push per instruction |

Tag `c-stage-5-freeze` is on origin at `f27da7c`.

## Offline regression — verified on this branch

Commands run from repo root with `PYTHONPATH=apps/api/src`.

```
python -m pytest apps/api/tests/ -q
542 passed, 2 skipped, 2 warnings
```

```
python -m ruff check .
All checks passed!
```

```
python scripts/fixture_cues.py
7 DecisionEvent lines, 8-step timeline runs clean:
  seq=1 STAY  CAM-HOST   Sarah joining later
  seq=2 TAKE  CAM-GUEST  cut to Sarah
  seq=3 TAKE  CAM-WIDE   guest unhealthy -> wide
  seq=4 STAY  CAM-WIDE   manual HOLD
  seq=5 STAY  CAM-WIDE   stale mode_revision cue rejected
  seq=6 STAY  CAM-WIDE   RESUME_AUTO
  seq=7 TAKE  CAM-GUEST  correction to Daniel
Every emitted line carries `identity: "ROLE_BASED"` and
`source: "FIXTURE"`. `contractVersion: 0.1.0`.
```

```
python scripts/soak_c_lane.py --minutes 2
loops               = 12
decisions           = 79
duplicate_seqs      = 0
max_queue_depth     = 1
log_bytes           = 59 307
rss_delta_mb        = 0.0  (Windows: memory invariant SKIP-by-guard)
all_invariants_passed = true
```

```
python scripts/demo_preflight.py --offline
[NO-GO] OPENAI_API_KEY present    <-- expected on dev host
[NO-GO] DEEPGRAM_API_KEY present  <-- expected on dev host
[NO-GO] CUE_MODEL pinned          <-- expected on dev host
[GO  ] Roster loads (7 guests)
[SKIP] OpenAI reachable (offline)
[SKIP] Deepgram reachable (offline)
[GO  ] Default microphone found  ([1] Microphone Array (Realtek(R) Au)
[GO  ] Microphone level > 0      (rms=38, ~1%)
[GO  ] Fixture timeline runs clean
Exit 1: env vars are the fail-safe. On the demo Mac with keys exported,
every line should read GO.
```

## What is still NOT RUN and who can run it

Everything below needs at least one live API key or the Mac. All commands
are in `docs/results/C-stage4.md` and `docs/DEMO-C.md`.

| Not run | Blocked by | Who / where |
|---|---|---|
| Dev-set pass rate against pinned model | `OPENAI_API_KEY` + `CUE_MODEL` | Whoever runs `scripts/run_semantic.py --models "$CUE_MODEL" --set dev` on the Mac |
| Held-out wrong SHOW cuts | same | `scripts/release_eval.py` on the Mac (writes `heldout_runs.jsonl` ledger, refuses on prompt hash drift without `--acknowledge-retune`) |
| Held-out pass rate | same | same |
| Live total p50 / p95 latency | Both keys + mic | `scripts/latency_run.py` on the Mac; 12 scripted sentences, prints per-hop p50/p95 |
| 20-min soak with real RSS | Windows lacks `resource` | `scripts/soak_c_lane.py --minutes 20` on the Mac |
| End-to-end LiveLane with real Deepgram v1 | Both keys | `scripts/live_lane.py --source mic` on the Mac |
| Compositor ACK round-trip | D's control WS wire-in | A + D pairing before the demo |
| Face-identity path (B's visual observation) | B's provider not yet joined | Confirmed at rehearsal; else stay ROLE_BASED |

## UNVERIFIED (hardware-dependent) fixes

None of the code changes on `person-c-stage-6` are hardware-dependent
(this branch is documentation + regression only). Everything on my
prior branches is either offline-covered by the failure-injection
suite or listed as NOT RUN above.

The one remaining hardware-touching fix in my desk prototype — the
Flux `audio_window_end` → `words[-1].end` correction that produces
`final_ms` — is unverified against a live Mac + Flux endpoint. It is
covered by the sanity floor (values under the configured silence are
suppressed and a WARN is logged) so a bug there is loud, not silent.

## Contracts touched (recap for A / B / D)

- `DecisionRecord.identity: "ROLE_BASED" | "VERIFIED"` (Stage-4 bugfix).
  Additive on the wire via `DecisionEvent.identity` — old clients
  ignore it. A: please confirm the wire schema extension when you're
  next reviewing (see `C-stage4.md` open requests).
- Schema in `docs/contracts-proposal/decision_record.schema.json`
  updated with the enum. Never marks a required field.
