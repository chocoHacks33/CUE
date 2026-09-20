# Stage 4 integration check (A + B + C + D)

Integrated by D on the Mac, 2026-09-19 (Boston). Branch `codex/stage-4-integration` from trunk d95fe48 (which already held D's Stage 4 via PR #22).

## Merged

| Lane | Branch | Result |
|---|---|---|
| A | `codex/person-a-stage-4` (d0b840a): Stage 4 failure gate and evidence API (`/stage4/trials`, `/stage4/report`), gate CLI, control and socket hardening, Deepgram provider-failure handling | merged clean |
| C | `person-c-stage-4` (68cd286): failure-injection tests, release evaluation and live latency probe scripts, C-lane soak script, scope decision and feature-freeze records | merged clean |
| B | `codex/b-stage-4` (eff2ca2): identity readiness verdict and disclosure endpoint, consent/deletion and capture-condition tests, identity report and media check filled in as NOT RUN | merged; two conflicts resolved (below) |
| D | already on trunk (#22) | disclosure wiring and a query-name fix added on this branch |

B's Stage 5 prep (#21) was left out: it is beyond Stage 4, and it will need one more trunk merge after this lands (see notes).

## Conflicts and fixes

| File | Cause | Resolution |
|---|---|---|
| `apps/api/src/cue_api/guests/router.py` | trunk (A's Stage 3) added `ensure_event_active` to `build_guest_router`; B added `evidence` | both parameters kept, in the order B chose in its own trunk merge |
| `apps/api/src/cue_api/main.py` | imports: A's `lifecycle` next to B's `identity_evidence`; A's transport, end-event and Stage 4 endpoints against nothing on B's side; router kwargs `ensure_event_active` (A) against `evidence` (B) | both imports in isort order; A's endpoints kept; both kwargs passed |

## Integration fixes in D's lane (commit on this branch)

- **Query name.** The Stage 3 evidence poll on the producer page sent `event_id`; B's guest routes take `eventId` (a FastAPI alias present since B's Stage 2). Every observations read would have been a 422 live, and the tile evidence would have shown "unavailable". Probe on the merged app: `?event_id=` 422, `?eventId=` 200. Fixed through `apps/web/src/producer/guestApi.ts`, with a test that pins the query name.
- **Disclosure.** `GET /api/v1/guests/readiness` is polled every 5 s with the operator credential and shown in the compositor's mode strip: naming policy, cameras-by-role flag, whether unattended naming is permitted, and the disclosure sentence. It is also in the Stage 4 export. On this tree the verdict is ROLE_BASED: "Cameras are chosen by role, not by face recognition. Nothing on screen is identified by face."

## Verification on the merged tree (macOS 26.3 arm64, Node v25.9.0, Python 3.14.7)

| Check | Result |
|---|---|
| `npm run typecheck` | clean |
| `npm test` | 206 passed (53 contracts, 153 web) |
| `npm run build` | OK |
| `apps/api`: `pytest` | 629 passed, 13 skipped (the skips are B's OpenCV adapters, weights not downloaded here) |
| `apps/api`: `ruff check .` | clean |
| imports: `cue_api.main`, `stage4_gate`, `guests.identity_readiness`, `guests.identity_evidence`, `c_lane_live` | OK |
| `--help` on `scripts/release_eval.py`, `latency_run.py`, `soak_c_lane.py`, `av_skew.py`, `live_lane.py`, `latency_report.py` and `python -m cue_api.stage4_gate_cli` | all exit 0 |
| live readiness route on the merged app | 200, ROLE_BASED, guest contract 0.1.0 |

## Notes for the lanes

- **C:** A's Stage 4 edited `apps/api/src/cue_api/speech/deepgram_stream.py` (a failed `send_media` now yields one speech-down transition and a provider failure count). It did not conflict with C's Stage 4, which touched the assembler and the live lane, but it is C's file: review it.
- **B:** #21 re-merged trunk before this integration and resolved the same hunks. Against this branch it conflicts once more in `main.py`, where A's Stage 4 endpoints (`/stage4/trials`, `/stage4/report`) and B's Stage 5 verify-cleanup endpoint were both added at the same spot. After this lands, merge trunk into `codex/b-stage-5-prep` once more and keep both.
- **A:** `codex/person-a-stage-5-prep` merges cleanly onto this branch.

## Stage 4 exit-gate decision (plan section 7)

On the evidence in this tree the show runs **role-based ASSIST with the disclosure shown above**. Named AUTO is not supported: B's identity report has zero trials, the calibration is PROVISIONAL_DEFAULT, and the Mac runtime gate and B's media checks have not run. The verdict is computed per request, so a fitted calibration and a filled identity report change the strip without a code change.

## Not run

Every physical Stage 4 row in every lane: A's failure check (`docs/results/a-stage4-failure-check.md`), B's identity trials (`docs/results/b-identity-report.md`), C's held-out release evaluation and live latency probe (need the OpenAI and Deepgram keys), and D's cuts, failovers, clap tests and 20-minute soak (`docs/results/d-stage4-check.md`). No live feed has reached this Mac at any stage.
