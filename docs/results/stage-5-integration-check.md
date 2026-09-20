# Stage 5 integration check (A + B + C + D)

Integrated by D on the Mac, 2026-09-19 (Boston). Branch `codex/stage-5-integration` from trunk cca3e04 (which already held B's Stage 5 via PR #23, including B's Stage 5 prep).

## Merged

| Lane | Branch | Content | Result |
|---|---|---|---|
| A | `codex/person-a-stage-5` (9e7d555) | release preflight (`cue-release-preflight`) that binds a release to an exact clean pushed commit and runs suites, lint, build, startup and provider checks; `cue-release-finalize` that revalidates and only tags with explicit flags; approval template and private runbook template; release status (BLOCKED) | merged clean |
| C | `person-c-stage-5` (f27da7c) | demo preflight script with GO/NO-GO lines, 90-second demo script for C's part, evidence record with NOT RUN rows, AI-tooling contribution record | merged clean |
| D | `codex/person-d-stage-5` (c9f3c08, PR #25) | recording verifier with verified backup and manifest, Mac configuration snapshot (names only), programme stills, freeze template | merged clean |
| B | already on trunk (#23) | enforceable freeze tests over the limitations document, run sheet, consented-data cleanup | no action |

No file was touched by more than one of the three branches. Nothing to resolve.

## Verification on the merged tree (macOS 26.3 arm64, Node v25.9.0, Python 3.14.7)

| Check | Result |
|---|---|
| `npm run typecheck` | clean |
| `npm test` | 207 passed (53 contracts, 154 web) |
| `npm run build` | OK |
| `apps/api`: `pytest` | 690 passed, 13 skipped (the skips are B's OpenCV adapters, weights not downloaded here) |
| `apps/api`: `ruff check .` | clean |
| `--help` on `cue_api.release_preflight_cli`, `release_finalize_cli`, `stage4_gate_cli` and on `scripts/demo_preflight.py`, `verify_recording.py`, `mac_config_snapshot.py`, `release_eval.py`, `latency_run.py`, `soak_c_lane.py`, `av_skew.py` | all exit 0 |

A's new console scripts (`cue-release-preflight`, `cue-release-finalize`) need `pip install -e ".[dev]"` once in the API venv to appear on PATH; the modules run with `python -m` without it. No dependency changed.

## Release state after this integration

A's `docs/results/stage-5-a-release-status.md` says it: **BLOCKED, no passing release tag may be created yet.** Every lane's physical gate is INCOMPLETE, no live feed has reached this Mac at any stage, and the saved Plume project has not been reopened and verified. The software candidate is ROLE_BASED_ASSIST with B's disclosure. The path to a tag is the same for everyone: run the real Stage 4 rows on the exact candidate, fill the ignored approval file from evidence, then `cue-release-preflight` must print `releaseReady: true` before `cue-release-finalize --create-tag --push`.

## Notes for the lanes

- **A:** `docs/results/stage5-release-approval.json` is now gitignored (A's change) so private evidence references never land in the repo. D's rows that back `stage4Gates.D`, `macValidation.*` and `ownerSignoffs.D` are listed in `docs/results/d-stage5-freeze.md`.
- **C:** `scripts/demo_preflight.py --offline` covers env names, roster, mic and fixture without network; run it on the Mac before the pitch. C's held-out and live latency rows still need the OpenAI and Deepgram keys.
- **D:** after the official session, `scripts/verify_recording.py <file> --min-seconds 120 --backup <private dir> --markdown`, then play the file in VLC or Chrome (WebM does not open in QuickTime).

## Not run

Every physical row in every lane's Stage 4 and Stage 5 records. This integration proves the four lanes' Stage 5 tooling builds and tests together on the Mac; it does not claim any trial, recording, or submission check has happened.
