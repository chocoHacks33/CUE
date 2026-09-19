# Person B — Stage 1

Plan §7, Stage 1 (B): *"own video-only capture; enrolment/reference module;
confirm B feed reaches the Mac."*

Branch: `codex/b-vision-clean` (PR #7).

## Deliverable 1 — video-only capture on CAM-GUEST

`CAM-GUEST` carries video and no audio, and that is enforced by the contract
rather than by remembering to tick a box:

| File | What it does |
|---|---|
| `packages/contracts/src/index.ts` | `CAM-GUEST` is declared `audioPolicy: "DISABLED"`; only `CAM-HOST` is `MASTER` |
| `apps/web/src/publisher/mediaPolicy.ts` | Capture constraints follow the camera contract, so the guest camera cannot request a mic |

One master mic, on the host camera. B's camera can never restart master audio.

## Deliverable 2 — enrolment and reference module

| File | What it does |
|---|---|
| `apps/api/src/cue_api/vision/quality.py` | Capture-quality gate: refuses a face instead of matching it weakly |
| `apps/api/src/cue_api/vision/gallery.py` | Enrolled reference gallery; embeddings are plain float tuples, no numpy in the core |
| `apps/api/src/cue_api/vision/cli.py` | `cue-vision models / enrol / gallery / forget` |
| `apps/api/src/cue_api/vision/client.py` | stdlib `urllib` client, so the worker gains no dependency |
| `apps/api/src/cue_api/vision/types.py` | `DecodedFrame`, `FaceDetection`, `PixelBox`, `Embedding` |
| `apps/api/src/cue_api/guests/router.py` | The routes below |

### Routes

```
POST   /api/v1/guests                        enrol a consenting guest
GET    /api/v1/guests                        list guests (never embeddings)
POST   /api/v1/guests/{guest_id}/references  add an enrolment reference
DELETE /api/v1/guests/{guest_id}             withdraw consent, delete references
DELETE /api/v1/guests                        purge the event
GET    /api/v1/vision/gallery                worker-only; carries embeddings
```

Verified against the running app's OpenAPI schema. There are no
`/vision/observations`, `/vision/invalidate` or `/vision/tallies` routes — those
are Stage 2.

### Enrolment keeps the photo where it is

`cue-vision enrol` prints the spoken consent script, computes the embedding
locally, and sends only the embedding. The reference image never travels.

### The quality gate's thresholds

In `quality.py`, all unmeasured on our actual cameras: face width ratio 0.08,
detector score 0.70, sharpness 0.25, brightness 0.20–0.92, max out-of-frame
0.02. The sharpness scale (Laplacian variance / 500) was chosen without looking
at a real webcam frame and should be expected to need retuning.

## Deliverable 3 — confirm B's feed reaches the Mac

**NOT RUN.** Needs hardware. Template:
`docs/results/b-media-check.template.md`.

Three checks, all outstanding:

1. Local video-only capture on B's Windows laptop.
2. `CAM-GUEST` arriving on D's Mac.
3. A remote observer recording of another laptop.

## Tests

| File | Tests |
|---|---|
| `apps/api/tests/test_guest_routes.py` | 16 |
| `apps/api/tests/test_vision_gallery.py` | 12 |
| `apps/api/tests/test_vision_quality.py` | 8 |
| `apps/web/src/publisher/mediaPolicy.test.ts` | capture constraints per camera |

## Verified

Windows 11, Python 3.14.7:

```
cd apps/api && python -m pytest -q     ->  182 passed (whole backend suite)
cd apps/api && python -m ruff check .  ->  All checks passed
cue-vision --help                      ->  entry point resolves
OpenAPI route dump                     ->  6 guest/vision routes, no observation endpoints
```

**Not run locally:** the npm gates — Node is not installed on this machine.
CI passes on macOS and Windows for PR #7.

**Not run anywhere:** anything involving real pixels. No weights downloaded, no
OpenCV wheel installed, no face detected, no camera published. Every test here
uses scripted fixtures.

## Not in Stage 1 — deferred to Stage 2/3

Removed from this branch so nothing implies a capability that has not been built.
Parked on `codex/b-vision-stage2`.

| What | Stage |
|---|---|
| `guests/observations.py` — live observation store | 2 |
| `POST`/`GET /vision/observations` | 2 |
| `POST /vision/invalidate` | 2 |
| `GET /vision/tallies` | 2 |
| `apps/web/src/guests/evidence.ts` — producer-UI evidence semantics | 3 |
| `matching.py`, `tracking.py`, `pipeline.py`, `ledger.py` | 2 |
| `calibration.py` | 3 |

`PurgeReceipt.observations_dropped` stays in the contract but always reports `0`,
because there is no store to drop from yet.

## What has to happen next, in order

1. **Mac runtime gate with D** — install `apps/api[vision]`, confirm an OpenCV
   wheel exists for D's Python and architecture. Nothing else matters until this
   passes.
2. **Download and pin the weights** — procedure in `docs/vision-models.md`,
   including verifying the licences rather than trusting the table.
3. **First real inference on the Mac** — one photo through `cue-vision enrol`,
   one live frame through `YuNetDetector`.
4. **B's media checks** — `docs/results/b-media-check.template.md`.
5. **Only then** unpark Stage 2.

See also [person-b-stage-0.md](person-b-stage-0.md) and
[person-b-stage-1-prep.md](person-b-stage-1-prep.md).
