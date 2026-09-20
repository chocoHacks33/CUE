# D Stage 6: overnight offline check on the Mac

Run by D on the Mac, 2026-09-19 late evening (Boston), on the frozen trunk commit `296e112` (merge of B's Stage 6 prep, after the Stage 5 integration). No code was changed for this stage, on purpose: the plan permits only documentation and offline regression checks overnight.

## 1. A's release preflight, offline, on the exact commit

```bash
cd apps/api
.venv/bin/python -m cue_api.release_preflight_cli --repo-root <repo> --env-file <repo>/.env --run-suite --startup-smoke
```

Result: **FAIL, releaseReady false**, which is the correct answer tonight. Manifest kept privately (not in Git).

| Check | Status | Detail |
|---|---|---|
| git-branch, git-clean, git-pushed | PASS | clean, pushed HEAD |
| tracked-private-files | PASS | no private runtime artifacts tracked |
| python-version, node-version | PASS | 3.14.7, v25.9.0 |
| release-files | PASS | required source and lock files exist |
| **environment** | **FAIL** | **missing OPENAI_API_KEY, DEEPGRAM_API_KEY, CUE_MODEL**: those three lines in the root `.env` on this Mac are empty. LiveKit and both admission secrets are populated. Values were not logged. |
| release-approval | INCOMPLETE | no private approval file yet; expected before any trial has run |
| api-tests, api-lint | PASS | exit 0 |
| web-tests, typecheck, production-build | PASS | exit 0 |
| api-clean-start | PASS | a fresh integrated process reached ready with three cameras |
| web-artifact | PASS | built index references present assets |
| provider-smoke | INCOMPLETE | not run offline, by design |

The first run pointed at `apps/api/.env`, which does not exist here; the tool's default differs from the API's own lookup, which also reads the repo root. Pass `--env-file <repo>/.env` on this Mac.

## 2. B's offline regression, on the Mac, with the models exercised

B's Stage 6 note says CI being green does not prove the models ran, because the weights are absent on CI and the model-backed tests skip. On this Mac the same 13 tests had been skipping for a different reason: the Stage 0 weights live in `apps/vision/models`, while B's code looks in `models` relative to `apps/api`. Both files were verified against B's pins first:

| Model | SHA-256 matches B's pin | Licence verified |
|---|---|---|
| YuNet `face_detection_yunet_2023mar.onnx` | yes | MIT |
| SFace `face_recognition_sface_2021dec.onnx` | yes | Apache-2.0 |

They were then copied into `apps/api/models` (gitignored, local only; nothing in the tree changed). With that:

```
scripts/b_offline_regression.py
  PASS  B's tests      391 passed, 312 deselected
  PASS  ruff           All checks passed!
  PASS  naming policy  ROLE_BASED True False
  PASS  doc links      16 documents, every link resolves
```

So YuNet and SFace have now run on this Mac, in the API venv (opencv-python 4.14), through B's own tests. That is model loading and inference on synthetic images. It is not recognition of a real face; see B's identity report, still zero trials.

## 3. Whole suite on the Mac

| Check | Result |
|---|---|
| `apps/api` pytest, with weights | 703 passed, 0 skipped |
| `apps/api` ruff | clean |
| web tests, typecheck, build | PASS (via the preflight) |

## 3a. GitHub Actions stopped starting jobs at about 01:50 Boston

Every workflow run on every branch pushed after that time, including A's and B's Stage 6 branches and this one, fails in a few seconds with zero steps. The job annotation is:

> The job was not started because recent account payments have failed or your spending limit needs to be increased. Please check the 'Billing & plans' section in your settings.

The repository is private and owned by a user account; private-repo minutes count against the account's allowance, with macOS runners billed at ten times the rate and Windows at twice. The workflow runs two macOS and two Windows jobs on every push and pull request, and there were dozens of pushes today. The frozen trunk commit `296e112` was checked before the cut-off and is green. Only the account owner can clear this: raise the spending limit or fix the payment method under Billing, make the repository public (public repositories do not consume the allowance; the plan already expects a public code link at submission, with no secrets or recordings in it), or drop the macOS jobs from the matrix. Until then a red check on a new branch means "not run", not "failed". Tonight's offline preflight on this Mac ran the same suites, lint, type-check and build on the frozen commit.

## 4. State of D's lane going into the night

Nothing changed. Every physical row in `d-stage4-check.md` and `d-stage5-freeze.md` is NOT RUN; no live feed has reached this Mac at any stage. The tooling for every row exists and its offline tests pass.

## 5. Morning-first, in order (D's part of Stage 7, plus what D needs from others)

1. **Provider keys** (user, before anything else): fill `OPENAI_API_KEY`, `DEEPGRAM_API_KEY`, `CUE_MODEL` in the root `.env`. Without them C's live lane cannot run and the parser returns safe HOLD. Rerun A's preflight with `--provider-smoke` once they are in.
2. Network and tunnel: `ngrok http 5173` per the runbook, share the address privately.
3. Start the API from the API venv and the worker from the repo-root venv (the one with `livekit`).
4. Three Windows publishers join, D verifies the marker mapping physically; readiness shows three renderable slots.
5. A's audio attached; one master track in the log; headphones on.
6. Clap and flash per angle, `scripts/av_skew.py` on a short recording.
7. 30 cuts and 10 failovers with the Stage 4 block open, export, fill `d-stage4-check.md`.
8. 20-minute soak if time allows, else 5 minutes and say so.
9. Official recording: `scripts/verify_recording.py --min-seconds 120 --backup <private dir> --markdown`, play in VLC or Chrome, fill `d-stage5-freeze.md`, then D's fields in A's approval file.
