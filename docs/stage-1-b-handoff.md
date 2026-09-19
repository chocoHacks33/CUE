# Person B handoff — Stage 0 and Stage 1 prep

Branch: `codex/b-vision`. Built on A's Stage 0 foundation (`d064a4d`).

Scope is deliberately Stage 0 plus the Stage 1 groundwork that needs no other
machine. Stage 2/3 work — matching, calibration, tracking, identity expiry, the
observation pipeline and its routes — sits on `codex/b-vision-stage2`, pushed
but **not for merge** until the Mac runtime gate passes. See "Deferred" below.

## What is in this change

| Area | Path | Notes |
|---|---|---|
| Shared vision contracts (TS) | `packages/contracts/src/vision.ts` | Observation, guest, consent and snapshot vocabulary with runtime parsers |
| Shared vision contracts (Python) | `apps/api/src/cue_api/guests/contracts.py` | Pydantic mirror, same rules |
| Cross-language fixtures | `packages/contracts/fixtures/` | Observation and full consent lifecycle, validated in both runtimes |
| Consent + reference registry | `apps/api/src/cue_api/guests/registry.py` | In-memory, event-scoped, deletion receipts |
| Guest + enrolment routes | `apps/api/src/cue_api/guests/router.py` | Enrolment, references, worker gallery, withdrawal, event purge |
| Model provenance | `apps/vision/src/cue_vision/models.py` | File registry, checksum verification, licence status |
| Capture-quality gate | `apps/vision/src/cue_vision/quality.py` | Size, sharpness, exposure, framing — thresholds as policy |
| Reference gallery | `apps/vision/src/cue_vision/gallery.py` | Loading and normalising enrolled references |
| OpenCV adapters | `apps/vision/src/cue_vision/adapters/` | YuNet + SFace, lazily imported, for the Mac inference spike |
| Enrolment CLI | `apps/vision/src/cue_vision/cli.py` | `cue-vision models / enrol / gallery / forget` |
| Privacy and model docs | `docs/guest-privacy.md`, `docs/vision-models.md` | What is stored, for how long, and what is unverified |

Contracts are in scope at Stage 0 on purpose: the plan's §5 says to freeze a
minimal shared schema in the first hour, and the observation vocabulary is one
of the interfaces listed there. Freezing the words is Stage 0; implementing the
behaviour behind them is Stage 2.

## Cross-owner edits — please review, A and D

These touch files outside B's lane. They are deliberately minimal:

1. `apps/api/src/cue_api/main.py` — `create_app` also builds a `GuestRegistry`
   (injectable for tests) and includes B's router. No existing route changed.
2. `packages/contracts/src/index.ts` — one line: `export * from "./vision";`.
3. `.github/workflows/ci.yml` — installs and tests `apps/vision`.
4. `apps/web/src/guests/` — new directory, contract tests only. The web boundary
   in the plan does not assign one for guests; move it if you prefer.

The plan's repository map says `services/api/guests/` and
`services/worker/vision/`. This repo uses `apps/`, and A has not created a worker
app, so B's vision code is a standalone package (`apps/vision`) that A's worker
imports rather than a folder inside a worker A has not written yet. Say the word
and it moves.

## Interfaces A and C can build against now

**A → B, decoded frame** (`cue_vision.types.DecodedFrame`): camera ID, stream
epoch, sequence, width, height, `received_at_ms`, optional `captured_at_ms`,
`pixel_format` (`BGR24` expected), `orientation_degrees` (frames must arrive
upright — rotate in ingest so one owner handles orientation), and `image`. The
pure-Python core never indexes `image`; only the OpenCV adapter does.

**B → backend, enrolment**: `POST /api/v1/guests` records consent and creates the
guest; `POST /api/v1/guests/{id}/references` adds one embedding;
`GET /api/v1/vision/gallery` is the worker-only view that carries embeddings;
`DELETE` on either path returns a purge receipt.

**For C's policy**: the observation vocabulary is frozen — `supportsNamedTake()`
in TypeScript, `usable_for_named_take` plus `is_fresh()` in Python. Write against
those names now. The pipeline that produces observations arrives in Stage 2, so
until then C should drive the policy from fixtures, which is what the plan's
H4 fixture milestone expects anyway.

## What the numbers mean

- `similarity` is a raw cosine score. It is a diagnostic. Do not gate on it.
- `calibratedConfidence` is null unless a calibration exists, and every
  observation states which: `MEASURED`, `PROVISIONAL_DEFAULT` or `UNCALIBRATED`.
- Tuning values are the PRD's starting points and are unmeasured on our cameras.

## Verification actually run

On this Windows laptop (Python 3.14.7, Windows 11):

```
cd apps/api    && python -m pytest -q    ->  92 passed
cd apps/api    && python -m ruff check . ->  All checks passed
cd apps/vision && python -m pytest -q    ->  26 passed
cd apps/vision && python -m ruff check . ->  All checks passed
```

The TypeScript runs in CI only — there is no Node on this machine. CI is green
on both `windows-latest` and `macos-latest`.

### Consent coverage

The consent path is tested at three levels, because a consent rule that only
exists in one of them is not enforced:

- the **contract** (`test_guest_contracts.py`, `consentFixtures.test.ts`) — shape,
  vocabulary and lifecycle invariants, on the shared fixture bytes;
- the **registry** (`test_guest_registry.py`) — 44 cases covering enrolment,
  ID derivation, reference versioning and normalisation, identifiability, the
  worker gallery, withdrawal and event purge;
- the **wire** (`test_guests.py`) — the same fixtures posted verbatim as request
  bodies, so a fixture that drifts from the API fails rather than rots.

Two fixtures exist to mark the boundary the schema cannot express:
`guest-enrolment-request.consent-refused.json` and `...recording-only.json` both
validate cleanly and are both refused by the registry with 403. Consenting to be
filmed is not consenting to be matched.

That split already caught a real divergence: the Python model refused a
withdrawn guest that still counted references and the TypeScript parser did not.
CI failed on both runners and the parser was fixed.

**Not run anywhere:** everything involving real pixels. No model weights have
been downloaded, no OpenCV wheel has been installed, no face has been detected,
no camera has published. The detector and embedder adapters are written against
OpenCV's documented API and have never executed.

## Deferred to `codex/b-vision-stage2`

Written, tested and parked. It is ahead of the checkpoint, so it is not part of
this review:

| Module | Stage |
|---|---|
| `matching.py`, `calibration.py` | 3 — calibrated matching with abstention |
| `tracking.py`, `ledger.py` | 2 — track association, confirmation, expiry |
| `pipeline.py` | 2 — live observations with UNKNOWN/AMBIGUOUS |
| `guests/observations.py` + `/vision/observations`, `/vision/invalidate`, `/vision/tallies` | 2 — evidence store and epoch invalidation |
| `apps/web/src/guests/evidence.ts` | 3 — evidence ages and reasons for D's UI |

Branching it out rather than merging it respects the Stage 0 exit gate: the plan
says to fix native packages and capture before building elaborate behaviour on
top, and none of that has been proved on D's Mac yet. If the gate changes the
frame or PCM interface, the deferred branch is what absorbs the churn.

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
5. **Then, and only then, merge Stage 2** from `codex/b-vision-stage2` and start
   calibration and measurement against
   `docs/results/b-identity-report.template.md`.

## Known gaps B still owns

- The quality gate's sharpness scale (Laplacian variance / 500) is a scaling
  choice made without looking at a real webcam frame. Expect to retune it.
- No group-framing logic. B reports each face separately; deciding that "Sarah
  and Daniel" needs a wide shot is C's policy, using B's per-face observations.
- The operator credential is A's Stage 0 bootstrap secret. B's routes inherit
  whatever A replaces it with in Stage 1.
- A withdrawal's purge receipt reports `observationsDropped: 0` on this branch
  because there is no observation store yet. Stage 2 wires it in.
