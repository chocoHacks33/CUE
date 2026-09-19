# Person B handoff — guest identity, consent and visual observations

Branch: `codex/b-vision`. Built on A's Stage 0 foundation (`d064a4d`).

## What is in this change

| Area | Path | Notes |
|---|---|---|
| Shared vision contracts (TS) | `packages/contracts/src/vision.ts` | Observation, guest, consent and snapshot types with runtime parsers |
| Shared vision contracts (Python) | `apps/api/src/cue_api/guests/contracts.py` | Pydantic mirror, same rules |
| Cross-language fixtures | `packages/contracts/fixtures/` | Validated by TypeScript, the API and the pipeline |
| Consent + reference registry | `apps/api/src/cue_api/guests/registry.py` | In-memory, event-scoped, deletion receipts |
| Observation store | `apps/api/src/cue_api/guests/observations.py` | Latest per camera, epoch-aware, freshness at read time |
| Guest/vision routes | `apps/api/src/cue_api/guests/router.py` | Enrolment, references, gallery, observations, invalidation, tallies |
| Vision pipeline | `apps/vision/src/cue_vision/` | Detection adapter, quality gate, calibrated matching, tracking, expiry |
| Enrolment CLI | `apps/vision/src/cue_vision/cli.py` | `cue-vision models / enrol / gallery / forget` |
| Producer evidence semantics | `apps/web/src/guests/evidence.ts` | What an observation means, for D's UI to render |

## Cross-owner edits — please review, A and D

These touch files outside B's lane. They are deliberately minimal:

1. `apps/api/src/cue_api/main.py` — `create_app` now also builds a
   `GuestRegistry` and `ObservationStore` (both injectable for tests) and
   includes B's router. No existing route or behaviour changed.
2. `packages/contracts/src/index.ts` — one line: `export * from "./vision";`.
3. `.github/workflows/ci.yml` — installs and tests `apps/vision`.
4. `apps/web/src/guests/` — new directory. The web boundary in the plan does not
   assign one for guests; move it if you would rather it lived elsewhere.

The plan's repository map says `services/api/guests/` and
`services/worker/vision/`. This repo uses `apps/`, and A has not created a worker
app, so B's vision code is a standalone package (`apps/vision`) that A's worker
imports rather than a folder inside a worker A has not written yet. Say the word
and it moves.

## Interfaces A and C depend on

**A → B, decoded frame** (`cue_vision.types.DecodedFrame`): camera ID, stream
epoch, sequence, width, height, `received_at_ms`, optional `captured_at_ms`,
`pixel_format` (`BGR24` expected), `orientation_degrees` (frames must arrive
upright — rotate in ingest so one owner handles orientation), and `image`. The
pure-Python core never indexes `image`; only the OpenCV adapter does. A
capacity-one latest-frame queue on A's side is the right shape: the pipeline is
stateless per frame apart from the tracker and ledger.

**B → backend/policy/UI, visual observation**: `POST /api/v1/vision/observations`
with the payload `Observation.to_contract()` produces. `GET` returns a snapshot
with one view per camera plus freshness computed against the backend clock.

**A → B, epoch and reframe signals**: `POST /api/v1/vision/invalidate` with the
camera's current stream epoch and a reason. Any explicit invalidation clears the
stored evidence, including on an unchanged epoch, because a reframe invalidates
identity even when the stream does not change.

**For C's policy**: the one question to ask is `supportsNamedTake(observation,
nowMs, currentStreamEpoch)` (TypeScript) or `usable_for_named_take` plus
`is_fresh()` (Python). It is true only for a CONFIRMED observation of a
consenting guest, on the current epoch, that passed the quality gate and has not
expired. C's own gates still apply on top; B's flag never authorises a cut.

## What the numbers mean

- `similarity` is a raw cosine score. It is a diagnostic. Do not gate on it.
- `calibratedConfidence` is null unless a calibration exists, and every
  observation states which: `MEASURED`, `PROVISIONAL_DEFAULT` or `UNCALIBRATED`.
  Today it is `PROVISIONAL_DEFAULT` — a logistic anchored on OpenCV's published
  SFace reference point, **not** a measured result. `Calibration.fit()` produces
  a `MEASURED` one from held-out labelled pairs and refuses a one-sided sample.
- `margin` is best minus runner-up. When it is below threshold the observation is
  `AMBIGUOUS` and carries no name.
- Tuning values in the code are the PRD's starting points: 1.5 s identity expiry,
  3 consistent observations inside a 1.2 s window, 0.363 accept similarity, 0.06
  margin. All are unmeasured on our actual cameras.

## Verification actually run

On this Windows laptop, commit-local:

```
cd apps/api    && python -m pytest -q   ->  45 passed
cd apps/api    && python -m ruff check . ->  All checks passed
cd apps/vision && python -m pytest -q   ->  61 passed
cd apps/vision && python -m ruff check . ->  All checks passed
```

Python 3.14.7 on Windows 11.

**Not run here:** `npm run typecheck`, `npm test`, `npm run build`. Node is not
installed on this machine, so the TypeScript contracts, the new
`apps/web/src/guests/` tests and the web build are **unverified locally** and
rest on CI. A or D should run them before merge.

**Not run anywhere:** everything involving real pixels. No model weights have
been downloaded, no OpenCV wheel has been installed, no face has been detected,
no camera has published. The detector and embedder adapters are written against
OpenCV's documented API and have never executed. Every vision test uses scripted
fixtures, which is why the fixtures say so in their docstring.

## What has to happen next, in order

1. **Mac runtime gate with D.** Install `apps/vision[opencv]` on the MacBook and
   confirm an OpenCV wheel exists for D's Python and architecture. If it does
   not, nothing else on this list matters yet.
2. **Download and pin the weights** — `docs/vision-models.md` has the procedure,
   including verifying the licences rather than trusting this repo's table.
3. **First real inference on the Mac**: one photo through `cue-vision enrol`, one
   live frame through `YuNetDetector`. Until then the adapters are untested code.
4. **B's own media checks** — `docs/results/b-media-check.template.md`: local
   video-only capture on B's Windows laptop, `CAM-GUEST` arriving on D's Mac,
   and a remote observer recording of another laptop. All currently NOT RUN.
5. **Calibrate and measure** — `docs/results/b-identity-report.template.md`:
   at least 30 clear positives and 30 unknown/ambiguous trials, on a held-out set
   separate from anything used for tuning. Until that exists, the demo discloses
   `PROVISIONAL_DEFAULT` and B does not claim an accuracy number.

## Known gaps B still owns

- The quality gate's sharpness scale (Laplacian variance / 500) is a scaling
  choice made without looking at a real webcam frame. Expect to retune it.
- The tracker is IoU-only. A guest who crosses in front of another on the same
  camera can swap tracks; the confirmation reset limits the damage to a lost
  identity rather than a wrong one, but it is not solved.
- No group-framing logic. B reports each face separately; deciding that "Sarah
  and Daniel" needs a wide shot is C's policy, using B's per-face observations.
- The operator credential is A's Stage 0 bootstrap secret. B's routes inherit
  whatever A replaces it with in Stage 1.
