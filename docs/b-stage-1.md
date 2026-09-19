# Person B — Stage 1

Plan §7, Stage 1 (B): *"own video-only capture; enrolment/reference module;
confirm B feed reaches the Mac."*

Branch: `codex/b-stage-1`.

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
| `apps/api/src/cue_api/guests/capture_quality.py` | Capture-quality gate: refuses a face instead of matching it weakly |
| `apps/api/src/cue_api/guests/reference_gallery.py` | Enrolled reference gallery; embeddings are plain float tuples, no numpy in the core |
| `apps/api/src/cue_api/guests/enrolment_cli.py` | `cue-guests models / enrol / gallery / forget` |
| `apps/api/src/cue_api/guests/backend_client.py` | stdlib `urllib` client, so the worker gains no dependency |
| `apps/api/src/cue_api/guests/types.py` | `DecodedFrame`, `FaceDetection`, `PixelBox`, `Embedding` |
| `apps/api/src/cue_api/guests/router.py` | The routes below |

### Routes

```
POST   /api/v1/guests                        enrol a consenting guest
GET    /api/v1/guests                        list guests (never embeddings)
POST   /api/v1/guests/{guest_id}/references  add an enrolment reference
DELETE /api/v1/guests/{guest_id}             withdraw consent, delete references
DELETE /api/v1/guests                        purge the event
GET    /api/v1/guests/gallery                worker-only; carries embeddings
```

Verified against the running app's OpenAPI schema. There are no observation
intake routes: B accepts consent, references and gallery reads, nothing else.

### Enrolment keeps the photo where it is

`cue-guests enrol` prints the spoken consent script, computes the embedding
locally, and sends only the embedding. The reference image never travels.

### The quality gate's thresholds

In `capture_quality.py`, all unmeasured on our actual cameras: face width ratio 0.08,
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
| `apps/api/tests/test_guest_reference_gallery.py` | 12 |
| `apps/api/tests/test_guest_capture_quality.py` | 8 |
| `apps/web/src/publisher/mediaPolicy.test.ts` | capture constraints per camera |

## Verified

Windows 11, Python 3.14.7:

```
cd apps/api && python -m pytest -q     ->  182 passed (whole backend suite)
cd apps/api && python -m ruff check .  ->  All checks passed
cue-guests --help                      ->  entry point resolves
OpenAPI route dump                     ->  6 guest routes, no observation endpoints
```

**Not run locally:** the npm gates — Node is not installed on this machine.
CI passes on macOS and Windows for PR #7.

**Not run anywhere:** anything involving real pixels. No weights downloaded, no
OpenCV wheel installed, no face detected, no camera published. Every test here
uses scripted fixtures.

## Not in scope here

Live observation intake, gallery matching, track association and calibration are
not part of Stage 0 or Stage 1. They are Stage 2 prep, and they arrive with
[b-stage-2-prep.md](b-stage-2-prep.md) rather than here.

## What has to happen next, in order

1. **Mac runtime gate with D** — install `apps/api[opencv]`, confirm an OpenCV
   wheel exists for D's Python and architecture. Nothing else matters until this
   passes.
2. **Download and pin the weights** — procedure in [b-stage-0.md](b-stage-0.md),
   including verifying the licences rather than trusting the table.
3. **First real inference on the Mac** — one photo through `cue-guests enrol`,
   one live frame through `YuNetDetector`.
4. **B's media checks** — `docs/results/b-media-check.template.md`.

See also [b-stage-0.md](b-stage-0.md) and
[b-stage-prep-1.md](b-stage-prep-1.md).
