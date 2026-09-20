# Stage 7 integration check (A + B + C + D)

Integrated by D on the Mac, 2026-09-19 late evening (Boston), for Sunday morning. Branch `codex/stage-7-integration` from trunk 04e33ea (which already held B's Stage 7 prep via #30 and Stage 7 via #31).

## Merged

| Lane | Branch | Content | Result |
|---|---|---|---|
| A | `codex/person-a-stage-7` (6f5fdbd) | `cue-stage7-preflight`: fail-closed morning gate bound to the exact pushed commit; venue, power and cable evidence; live liveness, readiness and topology probes; admission rejection without a secret and subscribe-only session issue; second admission must get a fresh identity; a real CAM-HOST reconnect that returns to ASSIST; report keeps system, hardware and release flags false | merged clean |
| C | `person-c-stage-7` (f9f3fa3) | `scripts/morning_check.py` (six sub-steps: preflight, room noise, speaker positions, five live sentences, full live lane, fixture plus soak), `scripts/fallback_drill.py`, demo config freeze (`config/demo.example.env`, `config/demo_roster.json`, `cue_api.config.demo_profile`), pitch numbers page, sync report | merged clean |
| D | `codex/person-d-stage-7` (c1d4e5e, PR #33) | `scripts/d_morning_preflight.py` against the running backend, operator card `docs/DEMO-D.md`, results template | merged clean |
| B | already on trunk (#30, #31) | morning-validation channel on the readiness route; restart drill demonstrated, two checks NOT RUN | no action |

No file was touched by more than one branch. A's branch also carries A's Stage 6 commits, already on trunk through #32; git resolved that with no conflict.

## Verification on the merged tree (macOS 26.3 arm64, Node v25.9.0, Python 3.14.7)

| Check | Result |
|---|---|
| `apps/api`: `pytest` | 772 passed, 0 skipped (weights in the ignored `apps/api/models`) |
| `apps/api`: `ruff check .` | clean |
| `npm run typecheck`, `npm test`, `npm run build` | clean, 207 passed (53 contracts, 154 web), build OK |
| `--help` on A's three CLIs and on `morning_check`, `fallback_drill`, `demo_preflight`, `d_morning_preflight`, `verify_recording`, `av_skew` | all exit 0 |
| imports `cue_api.config.demo_profile`, `cue_api.morning_preflight` | OK |

## Each lane's morning tool, run on this tree tonight (no publishers, no keys, no venue)

| Tool | Result | Why |
|---|---|---|
| A: `cue-stage7-preflight` (no `--run-live`) | INCOMPLETE | HEAD not yet pushed at run time; private evidence file absent; live preflight is for A's laptop |
| C: `demo_preflight.py --offline` | NO-GO | `OPENAI_API_KEY`, `DEEPGRAM_API_KEY`, `CUE_MODEL` empty; `sounddevice` not installed in the API venv; roster loads (7 guests); fixture timeline clean |
| D: `d_morning_preflight.py --offline` | NO-GO on one line | the same three empty provider variables; commit, worker venv, ffmpeg, disk all GO |

Every NO-GO above is a true statement about this Mac tonight, not a defect in a tool.

## Stage 7 exit gate: claims match today's conditions

Nothing physical has run. Each lane's Stage 7 record lists its rows as NOT RUN: A's judging location, power, network path and CAM-HOST reconnect; B's re-enrolment, reframe and unknown rejection (restart drill demonstrated); C's room noise, speaker positions, live sentences and live lane; D's mappings, audio, clap and flash, soak, recording and rehearsal. The show mode stays role-based ASSIST with B's disclosure until those rows say otherwise.

## Morning order, across lanes

1. Key holder fills the three provider variables in the root `.env` on the Mac. Everything below that needs speech or meaning stops without them.
2. Merge this branch; A tags nothing until A's preflight says PASS on the exact candidate.
3. D starts the API and worker per the runbook; D's preflight to GO; A's live preflight from A's laptop; B's morning validation posted; C's morning check with keys and mic.
4. Physical rows in each lane's Stage 7 results file, then the pitch rehearsal from `docs/DEMO-D.md` and C's demo script.

## Known issues carried

- GitHub Actions still refuses to start jobs on this private repository (account billing limit). This PR is red with zero steps for that reason; the checks above ran on the Mac.
- Three recording-verifier tests fail on A's Windows host with FFmpeg 8.0.1 and pass here with 7.1; unresolved until reproduced on a real recording.
- Port 8765 on this Mac is held by another Python process, not the team API; the team API stays on 8000.
