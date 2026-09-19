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

The worker tests assert the **positive** path first — three frames of agreement
reach `CONFIRMED` with `usableForNamedTake: true` — because without that, every
"does not name anyone" assertion below it would pass on broken code. That nearly
happened: the first version of these tests used an 8×4 fixture frame with a
200×240 detection box, so every observation was refused by the quality gate as
out-of-frame and the confirmation path was never reached. The tests passed and
proved nothing. The fixture frame now matches the detection geometry.

`FramePayload.packed_bytes()` strips row padding in pure Python, so the stride
arithmetic — the part most likely to be wrong — is verified on every machine.
Only the numpy reshape in `_payload_to_array` stays on the untested live path.

## Verified

Windows 11, Python 3.14.7:

```
cd apps/api && python -m pytest -q     ->  272 passed  (was 239)
cd apps/api && python -m ruff check .  ->  All checks passed
ruff --target-version py311            ->  All checks passed
```

## What this does NOT establish

**No pixels have moved through this.** numpy and OpenCV are not installed on this
machine, so `YuNetDetector`, `SFaceEmbedder` and `_payload_to_array` have still
never executed. The detector and embedder in every test are scripted stand-ins.

So this stage establishes that **the plumbing is right and the policy abstains
when it should**. It does not establish that identity works. The exit gate for
that is unchanged and still **NOT RUN**:

1. **Mac runtime gate with D** — `apps/api[opencv]`, confirm a wheel exists for
   D's Python and architecture.
2. **Download and pin the weights** — procedure in [b-stage-0.md](b-stage-0.md).
3. **First real inference** — one photo through `cue-guests enrol`, one live frame
   through `YuNetDetector`. The first thing to check is
   `_payload_to_array`: if A's stride handling and this reshape disagree, the
   image arrives skewed, and a skewed face still detects.
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
