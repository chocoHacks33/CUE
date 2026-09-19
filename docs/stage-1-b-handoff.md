# Person B handoff — Stage 0, Stage 1 prep and Stage 1

Branch: `codex/b-vision-clean`. Built on A's Stage 0 foundation (`d064a4d`).

Scope is deliberately **Stage 0 + Stage 1 only**. Stage 2 and Stage 3 vision work
(live matching, tracking, the observation ledger, the calibration fitter) is
parked on `codex/b-vision-stage2` and is *not* in this change. See
"Deferred to Stage 2/3" below.

B's code lives inside A's backend package, the same way C's `semantics/` and
`policy/` lanes do. There is no separate `apps/vision` app any more and CI no
longer has a third Python job.

## What is in this change

### Stage 0 — model provenance and the consent roster

| Area | Path | Notes |
|---|---|---|
| Model registry + licence/checksum gate | `apps/api/src/cue_api/vision/models.py` | Nothing is pinned until someone downloads the weights; tests assert that |
| Model/licence procedure | `docs/vision-models.md` | Sources, licences, pinning steps |
| Consent + reference registry | `apps/api/src/cue_api/guests/registry.py` | In-memory, event-scoped, deletion receipts |
| Privacy behaviour of record | `docs/guest-privacy.md` | What the code does today, not an intention |
| Mac face-inference spike | `docs/results/b-identity-report.template.md` | **NOT RUN** — needs D's Mac |

### Stage 1 prep — the offline half, driven by fixtures

| Area | Path | Notes |
|---|---|---|
| Shared vision contracts (TS) | `packages/contracts/src/vision.ts` | Observation, guest, consent and snapshot types with runtime parsers |
| Shared vision contracts (Python) | `apps/api/src/cue_api/guests/contracts.py` | Pydantic mirror, same rules |
| Cross-language fixtures | `packages/contracts/fixtures/` | The same bytes validated by TypeScript and by the API |
| Observation store | `apps/api/src/cue_api/guests/observations.py` | Latest per camera, epoch-aware, freshness at read time |
| Producer evidence semantics | `apps/web/src/guests/evidence.ts` | What an observation means, for D's UI to render |

### Stage 1 — capture, enrolment and the feed

| Area | Path | Notes |
|---|---|---|
| Capture-quality gate | `apps/api/src/cue_api/vision/quality.py` | Refuses a face rather than matching it weakly |
| Enrolled reference gallery | `apps/api/src/cue_api/vision/gallery.py` | Embeddings as plain float tuples, no numpy in the core |
| Enrolment CLI | `apps/api/src/cue_api/vision/cli.py` | `cue-vision models / enrol / gallery / forget` |
| Backend client for the CLI | `apps/api/src/cue_api/vision/client.py` | stdlib `urllib`, no new dependency |
| OpenCV adapters | `apps/api/src/cue_api/vision/adapters/opencv_models.py` | YuNet + SFace, imported lazily; **never executed** |
| Guest/vision routes | `apps/api/src/cue_api/guests/router.py` | Enrolment, references, gallery, observations, invalidation, tallies |
| Video-only capture for `CAM-GUEST` | `packages/contracts/src/index.ts` (`audioPolicy: "DISABLED"`) | Enforced by the contract, not by UI discipline |
| B's own media checks | `docs/results/b-media-check.template.md` | **NOT RUN** — local capture, feed on D's Mac, remote observer clip |

## Cross-owner edits — please review, A and D

These touch files outside B's lane. They are deliberately minimal:

1. `apps/api/src/cue_api/main.py` — `create_app` now also builds a
   `GuestRegistry` and `ObservationStore` (both injectable for tests) and
   includes B's router. No existing route or behaviour changed.
2. `packages/contracts/src/index.ts` — one line: `export * from "./vision";`.
3. `.github/workflows/ci.yml` — the `apps/vision` install/test/lint steps are
   **removed**. B's code is covered by the existing `apps/api` job.
4. `apps/api/pyproject.toml` — adds an optional `[vision]` extra (numpy, OpenCV)
   and the `cue-vision` console script. The default install is unchanged, so
   `pip install -e ".[dev]"` still needs no native wheel.
5. `apps/web/src/guests/` — new directory. The web boundary in the plan does not
   assign one for guests; move it if you would rather it lived elsewhere.

The plan's repository map says `services/api/guests/` and
`services/worker/vision/`. This repo uses `apps/`, and A has not created a worker
app, so B's vision core lives at `apps/api/src/cue_api/vision/` alongside C's
lanes. It still has no native dependency, so A can lift it into a worker later
without touching the code.

## Interfaces A and C depend on

**A → B, decoded frame** (`cue_api.vision.types.DecodedFrame`): camera ID, stream
epoch, sequence, width, height, `received_at_ms`, optional `captured_at_ms`,
`pixel_format` (`BGR24` expected), `orientation_degrees` (frames must arrive
upright — rotate in ingest so one owner handles orientation), and `image`. The
pure-Python core never indexes `image`; only the OpenCV adapter does.

**B → backend/policy/UI, visual observation**: `POST /api/v1/vision/observations`
with the payload the `VisualObservation` contract defines. `GET` returns a
snapshot with one view per camera plus freshness computed against the backend
clock.

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
  **No calibration exists in this change** — the fitter is Stage 3 work. The
  contract carries the field and `evidence.ts` discloses it so the demo can never
  quietly present an unmeasured number as a measured one.
- `margin` is best minus runner-up. When it is below threshold the observation is
  `AMBIGUOUS` and carries no name. The thresholds that produce it live with the
  matcher, which is Stage 2.
- The only tuning values in this change are the capture-quality gate's, in
  `quality.py` (face width ratio 0.08, detector score 0.70, sharpness 0.25,
  brightness 0.20–0.92). All are unmeasured on our actual cameras.
- Identity expiry is `IDENTITY_TTL_MS = 1500` in `guests/contracts.py`, the PRD's
  starting point, also unmeasured.

## Verification actually run

On this Windows laptop (Python 3.14.7, Windows 11), commit-local:

```
cd apps/api && python -m pytest -q    ->  86 passed
cd apps/api && python -m ruff check . ->  All checks passed
```

That 86 is the whole backend suite. B's share is 53: `test_guests.py` (23),
`test_guest_contracts.py` (16), `test_vision_quality.py` (8),
`test_vision_models.py` (6).

**Not run here:** `npm ci`, `npm run typecheck`, `npm test`, `npm run build`.
Node is not installed on this machine, so the TypeScript contracts, the
`apps/web/src/guests/` tests and the web build are **unverified locally** and
rest on CI. A or D should run them before merge.

**Not run anywhere:** everything involving real pixels. No model weights have
been downloaded, no OpenCV wheel has been installed, no face has been detected,
no camera has published. The detector and embedder adapters are written against
OpenCV's documented API and have never executed. Every vision test uses scripted
fixtures, which is why the fixtures say so in their docstring.

## Deferred to Stage 2/3 — parked on `codex/b-vision-stage2`

Removed from this branch on purpose, so nothing here implies a capability that
has not been built:

| Module | Stage | Why it is not here |
|---|---|---|
| `matching.py` | 2 | Live identification needs the Mac runtime gate first |
| `tracking.py` | 2 | IoU track association across a camera epoch |
| `pipeline.py` | 2 | Wires detect → quality → match → track per frame |
| `ledger.py` | 2 | Observation history, expiry and consent-deletion sweeps |
| `calibration.py` | 3 | `Calibration.fit()` needs held-out labelled pairs we do not have |

That branch still refers to the old `cue_vision` package layout, so it needs the
same `cue_api.vision` rename before it can be merged forward.

## What has to happen next, in order

1. **Mac runtime gate with D.** Install `apps/api[vision]` on the MacBook and
   confirm an OpenCV wheel exists for D's Python and architecture. If it does
   not, nothing else on this list matters yet.
2. **Download and pin the weights** — `docs/vision-models.md` has the procedure,
   including verifying the licences rather than trusting this repo's table.
3. **First real inference on the Mac**: one photo through `cue-vision enrol`, one
   live frame through `YuNetDetector`. Until then the adapters are untested code.
4. **B's own media checks** — `docs/results/b-media-check.template.md`: local
   video-only capture on B's Windows laptop, `CAM-GUEST` arriving on D's Mac,
   and a remote observer recording of another laptop. All currently NOT RUN.
5. **Only then** unpark Stage 2 from `codex/b-vision-stage2`.

## Known gaps B still owns

- The quality gate's sharpness scale (Laplacian variance / 500) is a scaling
  choice made without looking at a real webcam frame. Expect to retune it.
- No group-framing logic. B reports each face separately; deciding that "Sarah
  and Daniel" needs a wide shot is C's policy, using B's per-face observations.
- The operator credential is A's Stage 0 bootstrap secret. B's routes inherit
  whatever A replaces it with in Stage 1.
- `docs/results/stage-0-integration-check.md` records a run against the old
  `apps/vision` layout. It is left as written — it is dated evidence of what was
  actually run, not a description of the current tree.
