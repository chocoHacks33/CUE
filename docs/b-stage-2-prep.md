# B — Stage 2 prep

Plan §7, Stage 2 (B): *"live observations with UNKNOWN/AMBIGUOUS, expiry, consent
deletion and track/epoch association."*

Branch: `codex/b-stage-2-prep`, on top of Stage 0/1.

**Prep means the offline half.** Every rule below is driven by scripted fixtures,
the same way C's Stage 1 prep drove the utterance assembler off Deepgram
fixtures. No pixels, no models, no camera. What this branch cannot tell you is
whether YuNet and SFace behave as the thresholds assume — that needs the Mac
runtime gate, which is still **NOT RUN**.

## What it adds

| File | What it does |
|---|---|
| `guests/observation_pipeline.py` | Frame in, observations out: detect → quality → match → track → confirm |
| `guests/face_matching.py` | Gallery matching with a real abstention: candidate, ambiguous, or unknown |
| `guests/face_tracking.py` | IoU track association inside one camera epoch |
| `guests/identity_ledger.py` | Confirmation over repeated observations, expiry, epoch and consent invalidation |
| `guests/observation_store.py` | Latest observation per camera, epoch-aware, freshness computed at read time |
| `guests/confidence_calibration.py` | Similarity → confidence, provisional anchor only |

## Routes it adds

```
POST   /api/v1/guests/observations   record an observation (202)
GET    /api/v1/guests/observations   snapshot, one view per camera
POST   /api/v1/guests/invalidate     epoch or reframe signal from A
GET    /api/v1/guests/tallies        status counts for B's identity report
```

`PurgeReceipt.observations_dropped` is meaningful again: withdrawal and event
purge now drop live evidence and count it.

## The rules it actually enforces

**Abstention is the point.** An observation that cannot name someone says so:

- A face that matches nobody above threshold is `UNKNOWN`.
- A face that matches two enrolled guests too closely is `AMBIGUOUS` and carries
  no name. The margin rule decides, not the raw threshold.
- A frame that fails the capture gate is `LOW_QUALITY`. No face at all is
  `NO_FACE`.
- An empty gallery never invents a name.

**One frame is not an identity.** A name needs repeated agreement inside a short
window. A flicker between two guests confirms neither, and a gap restarts the
count.

**Identity is perishable and local.** It is bound to one camera, one stream
epoch, and one local track, and expires with its last supporting frame. It is
dropped when the camera republishes, when a reframe is signalled even on an
unchanged epoch, when a frame becomes unreadable, or when the guest withdraws.
Identity never follows a guest to another camera, and an old seat does not keep
its name when someone else sits down.

**A late observation does not become fresh by arriving late.** Evidence from a
superseded epoch is refused with 409 rather than stored.

**No confidence is claimed that was not measured.** Every match reports
`PROVISIONAL_DEFAULT`, anchored on OpenCV's published SFace reference point
(0.363). That is an anchor, not our result.

## Tuning values, all unmeasured

From the PRD, none measured on our cameras: identity expiry 1.5 s, 3 consistent
observations inside a 1.2 s window, 0.363 accept similarity, 0.06 margin. Expect
the Mac runtime gate to move them.

## Tests

| File | Tests |
|---|---|
| `tests/test_guest_observation_pipeline.py` | 14 |
| `tests/test_guest_identity_ledger.py` | 9 |
| `tests/test_guest_face_matching.py` | 7 |
| `tests/test_guest_face_tracking.py` | 6 |
| `tests/test_guest_confidence_calibration.py` | 5 |
| `tests/test_guest_observation_contract.py` | 4 |
| `tests/test_guest_routes.py` | 27 (11 of them observation routes) |

Shared scaffolding lives in `tests/conftest.py`: `ScriptedDetector` and
`KeyedEmbedder` are deterministic stand-ins that let a test move a face and keep
its embedding, or keep the position and change who is in the chair. They are
fixtures, not recognition, and they say so in their docstring.

## Verified

Windows 11, Python 3.14.7:

```
cd apps/api && python -m pytest -q     ->  239 passed  (was 182)
cd apps/api && python -m ruff check .  ->  All checks passed
OpenAPI route dump                     ->  10 guest routes, no path contains "vision"
```

**Not run locally:** the npm gates. Node is not installed on this machine.

**Not run anywhere:** anything involving real pixels. No weights downloaded, no
OpenCV wheel installed, no face detected, no camera published. Every test on this
branch uses scripted fixtures. **This branch does not establish that identity
works** — it establishes that the policy around it abstains when it should.

## Not in scope here

- **Fitting a measured calibration.** `Calibration.confidence()` and the
  provisional anchor are here; `Calibration.fit()` is Stage 3 and is not. Until
  someone fits one on a held-out set, `MEASURED` is unreachable by construction.
- **Producer-UI evidence semantics** (`evidence.ts`) — Stage 3.
- **Group framing.** B reports each face separately; deciding that "Sarah and
  Daniel" needs a wide shot is C's policy, using B's per-face observations.

## What has to happen next, in order

1. **Mac runtime gate with D** — still the blocker. Install `apps/api[opencv]`,
   confirm an OpenCV wheel exists for D's Python and architecture.
2. **Download and pin the weights** — procedure in [b-stage-0.md](b-stage-0.md).
3. **First real inference on the Mac** — one photo through `cue-guests enrol`,
   one live frame through `YuNetDetector`. Until then every adapter on this
   branch is untested code.
4. **Retune against real frames.** The tracker is IoU-only: a guest who crosses
   in front of another on the same camera can swap tracks. The confirmation reset
   limits that to a lost identity rather than a wrong one, but it is not solved.

The live wiring that drives all of this is [b-stage-2.md](b-stage-2.md).

Earlier stages: [b-stage-0.md](b-stage-0.md),
[b-stage-prep-1.md](b-stage-prep-1.md), [b-stage-1.md](b-stage-1.md).
