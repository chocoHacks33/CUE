# Person D Stage 7 handoff: morning preflight and operator card

Branch `codex/person-d-stage-7`, on top of the Stage 6 integration (trunk 04e33ea). Date: 2026-09-19 late (Boston), for Sunday 08:00.

Stage 7 for D in the v3 plan: recheck all mappings, A's audio, clap and flash timing, 20-minute final soak and recording playback, rehearse the pitch. Exit gate: claims match today's conditions. Those rows are physical. What shipped is the part a command can do, the results template for the rest, and the card D operates from during the live segment.

## 1. Morning preflight (`scripts/d_morning_preflight.py`)

One command against the running backend, GO or NO-GO per line, exit 0 only when every automated check is GO. Physical rows are printed as MANUAL and never counted.

| Check | What it proves |
|---|---|
| frozen commit | HEAD is the expected candidate or the release tag, tree clean |
| env populated | the eight names the Mac needs are non-empty (names only; values never printed) |
| worker venv has livekit | the rtc SDK imports from the repo-root venv (the Stage 5 finding) |
| ffmpeg and ffprobe | the verifier and skew tools can run |
| free disk for recordings | at least 5 GB where the recording goes |
| API ready | `/health/ready` says ready with LiveKit configured |
| three cameras bound | all three camera IDs bound to distinct publisher identities with a current video track (A's bindings route) |
| compositor readiness live | two reads one second apart: the report advances, three slots renderable with frames progressing, master audio attached, something on air (A's readiness route) |
| control state | not AUTO before validation, not ENDED, nothing pending acknowledgement |
| naming policy and disclosure | disclosure non-empty; a named policy is GO only if B's morning validation is filed and passed today (B's readiness route) |
| A's Stage 4 evidence route | reachable; trial count and assessment summary |

Secrets are read from the root `.env` into memory for the request headers only. Tests: `apps/api/tests/test_d_morning_preflight.py` (11) over a fake backend, including one that asserts no secret value appears in any output.

## 2. Operator card (`docs/DEMO-D.md`)

The four beats of the live segment (future mention holds, immediate introduction is suggested and taken, covered camera fails over, HOLD beats late AI), each with the key to press, what the compositor should show, what to say, and the fallback when it does not happen. Plus the three things never to do on stage.

## 3. Results template (`docs/results/d-stage7-morning.md`)

Preflight paste, twelve physical rows, and the exit-gate table mapping each claim the pitch makes to where it was measured today. All NOT RUN.

## 4. Verification actually run (this Mac)

- `apps/api` pytest: 742 passed, 2 warnings in 76.89s (0:01:16); ruff clean including the new script and test.
- Preflight against a fresh local API process on this Mac with no publishers connected: NO-GO for the dirty tree (new files not yet committed), the empty provider keys, no bindings and no readiness report; GO for API ready, control state (ASSIST, revision 0), naming policy (ROLE_BASED with disclosure) and A's Stage 4 route (0 trials, INCOMPLETE). Exit 1, as it should be.
- No web change in this branch.

## 5. For A, B and C

- **A:** the preflight reads `/bindings`, `/readiness`, `/control-state` and `/stage4/report` with the producer secret and `/health/ready` without. It does not write anything. A's own `cue-stage7-preflight` covers admission and reconnect; D's covers what the compositor shows.
- **B:** a named policy on the strip is GO only when `morningValidation` on `/guests/readiness` is filed today with `allPassed` true. ROLE_BASED is GO regardless, with a note whether the validation was filed.
- **C:** beat 2 depends on C's live lane producing a cue; the card's fallback is a manual TAKE said out loud.
