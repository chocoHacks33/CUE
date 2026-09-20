# Stage 6 integration check (A + B + C + D)

Integrated by D on the Mac, 2026-09-19 late evening (Boston). Branch `codex/stage-6-integration` from trunk f54eac8 (which already held B's Stage 6 via #28 and B's Stage 7 prep via #30).

Stage 6 permits documentation and offline regression only. Every branch below is docs, or offline tooling with tests; nothing changed in the media path, the models or the compositor.

## Merged

| Lane | Branch | Content | Result |
|---|---|---|---|
| A | `codex/person-a-stage-6` (52eda0c) | `cue-offline-handoff`: bounded offline regression bound to an exact commit and a private A-to-D handoff file that must name blockers, completed work and morning actions; the report can never claim hardware validation or release certification; status and handoff pages | merged clean |
| C | `person-c-stage-6` (4255f1e) | overnight regression snapshot and a Sunday morning runbook for C's lane | merged clean |
| D | `codex/person-d-stage-6` (7a409cc, PR #29) | overnight offline check on the Mac (A's preflight, B's regression with the models exercised, whole suite with no skips) and handoff; the CI billing finding | merged clean |
| B | already on trunk (#28, #30) | overnight check filed, Stage 7 prep | no action |

No file was touched by more than one branch.

## Verification on the merged tree (macOS 26.3 arm64, Node v25.9.0, Python 3.14.7)

| Check | Result |
|---|---|
| `apps/api`: `pytest` | 731 passed, 0 skipped (B's pinned weights are in the ignored `apps/api/models` on this Mac, so the model-backed tests ran) |
| `apps/api`: `ruff check .` | clean |
| `npm run typecheck`, `npm test`, `npm run build` | clean, 207 passed (53 contracts, 154 web), build OK |
| A's `cue-offline-handoff --run-suite` on this exact commit | git branch, clean, pushed: PASS; api-tests, api-lint, web-tests, typecheck, production-build: PASS; **handoff: INCOMPLETE, only because `acknowledgements.handoffAgreed` is not true**; hardwareValidated false, releaseCertified false, as designed |

The private handoff file used for that run was drafted by D from A's template with the exact commit, six concrete blockers and four completed items; it lives outside the repository and is not agreed yet. Agreeing it is a decision for D as a person, not for this integration.

## Notes for the lanes

- **A:** the validator's placeholder test rejects any text containing "pending" as a substring, so a blocker that says "spending limit" is refused as not concrete. Reworded here as "billing limit"; a word-boundary match or a check for the literal `REPLACE_WITH` prefix would avoid it. Also, A's report of three failing recording-verifier tests on FFmpeg 8.0.1 stands as a morning item: they pass on this Mac with FFmpeg 7.1, the machine the verifier runs on, and no decoder message will be silenced without a reproduction on a real recording.
- **Everyone:** GitHub Actions has not started a job on this repository since about 01:50 Boston (account billing limit; annotation quoted in `d-stage-6-check.md`). This branch and every Stage 6 branch are red with zero steps for that reason. The checks above were run on the Mac instead, and the frozen trunk commit was green before the cut-off.

## Blockers carried into Sunday, unchanged by this integration

1. `OPENAI_API_KEY`, `DEEPGRAM_API_KEY` and `CUE_MODEL` are empty in the root `.env` on the Mac. First action after 08:00.
2. No three-camera live feed has reached the Mac at any stage; every physical Stage 4 and Stage 5 row for all four lanes is NOT RUN.
3. The saved Plume project has not been reopened and verified.
4. Named AUTO stays unsupported; the show mode is role-based ASSIST with B's disclosure.
5. CI needs the account owner to raise the limit, fix payment, make the repository public, or drop the macOS jobs.
