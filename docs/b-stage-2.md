# B — Stage 2

Plan §7, Stage 2 (B): *"live observations with UNKNOWN/AMBIGUOUS, expiry, consent
deletion and track/epoch association."*

Branch: `codex/b-stage-2`, on top of Stage 2 prep.

Stage 2 prep built the decision logic as a pure function. **Nothing drove it.**
This stage is the wiring: A's decoded frames in, observations posted, epochs and
withdrawals handled live.

## The two new pieces

| File | What it does |
|---|---|
| `guests/frame_intake.py` | A's `DecodedVideoFrame` → B's `DecodedFrame`, with the clock mapping |
| `guests/observation_worker.py` | The loop: take the freshest frame, analyse, post, invalidate, refresh |

`GuestBackendClient` regains `post_observation` and `invalidate`, which were
removed while B was Stage 0/1 only.

## Integrating against A's real contract

A already publishes the seam, so B builds against it rather than inventing one:

- **`DecodedVideoFrame`** — A's decoded frame: event, camera, epoch, track SID,
  sequence, dimensions, stride, pixel format, orientation, mirrored flag,
  monotonic arrival time, optional capture time, and the bytes.
- **`LatestFrameSlot`** — capacity-one handoff. Producers overwrite; the consumer
  analyses the freshest frame rather than draining a queue whose latency only
  grows. The worker honours that: three frames pushed, one analysed.

### Two real problems this seam had to solve

**1. The clocks do not match.** A timestamps frames on a *monotonic* clock. The
backend judges freshness on *wall* time. Comparing them directly would silently
mis-age every observation. `WorkerClock` makes the mapping explicit — an anchor
pair sampled once, plus an honest uncertainty — and every observation declares
`clockDomain: WORKER_MONOTONIC_MAPPED` with that uncertainty attached, so nobody
downstream mistakes a mapped time for a measured one.

**2. Geometry must have one owner.** A frame that arrives rotated, mirrored, or
in the wrong pixel format is **refused**, not corrected:

| Delivered | Result |
|---|---|
| `orientation_degrees != 0` | refused — ingest must rotate it upright |
| `mirrored` | refused — ingest must un-mirror it |
| not `BGR24` | refused — B does not convert |

This is the one place it would be tempting to be helpful. It would be a mistake.
A detector fed a mirrored or rotated frame **does not fail loudly** — it returns
plausible boxes with landmark geometry that is quietly wrong, which produces a
confident wrong name. Every refusal names the camera and the owner who can fix it,
so a dropped frame is actionable rather than a silent blind spot.

## What the worker guarantees

**It never blocks the camera.** Capacity-one in, freshest frame analysed.

**It never crashes the loop.** A backend that is down, slow, or returning 409 is
an expected condition during a live show. Failures are counted in
`WorkerCounters` and the worker keeps looking at frames. A failed `invalidate`
still voids the local evidence first — losing a name is acceptable, keeping a
wrong one is not.

**A republish voids what the old epoch supported**, exactly once, locally and on
the backend. Frames on an unchanged epoch never invalidate. The first epoch seen
is not treated as a republish.

**A reframe voids identity even when the epoch has not moved** — `reframed()`
exists because a camera pointed somewhere new invalidates identity without the
stream changing at all.

**Withdrawal wins immediately.** A refreshed gallery is the authority on who may
be named; anyone missing from it loses their identity in that same call.
`forget_guest()` covers the case where the worker learns first.

## Tests

| File | Tests |
|---|---|
| `tests/test_guest_observation_worker.py` | 17 |
| `tests/test_guest_frame_intake.py` | 16 |
| `tests/test_guest_opencv_adapters.py` | 13 — the only tests that run real models |

The worker tests assert the **positive** path first — three frames of agreement
reach `CONFIRMED` with `usableForNamedTake: true` — because without that, every
"does not name anyone" assertion below it would pass on broken code. That nearly
happened: the first version of these tests used an 8×4 fixture frame with a
200×240 detection box, so every observation was refused by the quality gate as
out-of-frame and the confirmation path was never reached. The tests passed and
proved nothing. The fixture frame now matches the detection geometry.

`FramePayload.packed_bytes()` strips row padding in pure Python, so the stride
arithmetic — the part most likely to be wrong — is verified on every machine.

## Real models now run

OpenCV and the weights were installed and the adapters **executed for the first
time**. `test_guest_opencv_adapters.py` holds what that established; it skips
without `apps/api[opencv]` or the weights, so CI is unaffected.

What ran, for real:

- Both ONNX models load and verify against their pinned digests.
- `_payload_to_array` reconstructs a known image **exactly**, with a packed
  stride and with a padded one. This was the failure I most expected: a stride
  mistake skews the image, and a skewed face still detects.
- YuNet returns no face on a flat frame, and **does detect a crudely drawn face**
  with five landmarks at score 0.76.
- The full path runs with no stand-ins anywhere: detect -> quality -> embed ->
  match -> confirm. One frame gives `PROVISIONAL`; three consistent frames give
  `CONFIRMED` with `usableForNamedTake: true` and `PROVISIONAL_DEFAULT`.

### One real bug, found by running it

**SFace returns an unnormalised embedding** — measured norm about 3.9, not 1.0.
`cosine_similarity` is a plain dot product of unit vectors, so an unnormalised
probe inflates every similarity several-fold and would put a name on everybody.

It was not live: `observation_pipeline` normalises the probe, and the server
normalises references on enrolment, so both sides were already unit vectors. But
it was one forgotten call away from being the exact failure this project must not
ship. `SFaceEmbedder.embed` now normalises at the source, and
`test_the_embedder_returns_a_unit_vector` holds it there.

## Verified

Windows 11, Python 3.14.7:

```
cd apps/api && python -m pip install -e ".[opencv,dev]"
cd apps/api && python -m pytest -q     ->  286 passed  (was 239)
cd apps/api && python -m ruff check .  ->  All checks passed
ruff --target-version py311            ->  All checks passed
```

Without the extra or the weights: **273 passed, 13 skipped** — what CI runs.

## What this still does NOT establish

**Accuracy. Nothing here measures it, and one result says clearly why not.**

Every *detectable* drawn-face variant scored **0.78-0.93** cosine against an
unrelated reference — far above the 0.363 accept threshold. SFace is trained on
photographs, so crude drawings collapse into a narrow region of its embedding
space and are **useless as negatives**.
`test_drawn_faces_cannot_serve_as_negatives` records this so nobody later
mistakes a passing synthetic suite for evidence.

So the accept threshold (0.363) and margin (0.06) remain **unmeasured**, and no
real human face has been through this system.

Still **NOT RUN**:

1. **Mac runtime gate with D.** This was Windows. Whether an OpenCV wheel exists
   for D's macOS, Python and architecture is a separate question, still open.
2. **A real face.** Enrolling and matching actual people, from real cameras.
3. **The identity report** — `docs/results/b-identity-report.template.md`: at
   least 30 clear positives and 30 unknown/ambiguous trials on a held-out set.
   Until that exists B claims no accuracy number and the demo discloses
   `PROVISIONAL_DEFAULT`.
4. **B's media checks** — `docs/results/b-media-check.template.md`.

## Still open in B's lane

- The tracker is IoU-only. A guest crossing in front of another on the same
  camera can swap tracks; the confirmation reset limits that to a lost identity
  rather than a wrong one, but it is not solved.
- No group framing. B reports each face separately; deciding that "Sarah and
  Daniel" needs a wide shot is C's policy.
- Nothing calls the worker yet. A owns the thread that polls the slots; this
  stage provides `poll()` for it to call.

Earlier stages: [b-stage-0.md](b-stage-0.md),
[b-stage-prep-1.md](b-stage-prep-1.md), [b-stage-1.md](b-stage-1.md),
[b-stage-2-prep.md](b-stage-2-prep.md).
