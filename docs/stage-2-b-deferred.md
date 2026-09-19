# Person B — Stage 2/3 work, parked

This branch (`codex/b-vision-stage2`) holds behaviour that was written ahead of
schedule and taken back off `codex/b-vision` so A reviews only what the Stage 0
and Stage 1 checkpoint calls for.

**Do not merge this until the Stage 0 exit gate actually passes.** The plan is
explicit: prove the native packages and the capture path before building on top
of them. Nobody has yet shown that OpenCV loads on D's MacBook, that the model
weights download and verify, or that a single real face has been detected.

## What is here

| Module | Stage | What it does |
|---|---|---|
| `matching.py` | 3 | Gallery matching with a real abstention: candidate, ambiguous or unknown |
| `calibration.py` | 3 | Similarity to confidence, labelled `MEASURED`, `PROVISIONAL_DEFAULT` or `UNCALIBRATED` |
| `tracking.py` | 2 | IoU track association inside one camera epoch |
| `ledger.py` | 2 | Confirmation over repeated observations, expiry, epoch and consent invalidation |
| `pipeline.py` | 2 | Frame in, observations out |
| `guests/observations.py` | 2 | Latest observation per camera, epoch-aware, freshness at read time |
| `/vision/observations`, `/vision/invalidate`, `/vision/tallies` | 2 | Evidence intake, epoch signals, status counts |
| `apps/web/src/guests/evidence.ts` | 3 | What an observation means, for D's producer UI |

## Why it is parked rather than deleted

It is written and tested, and Stage 2 needs it. But it rests on assumptions the
runtime gate has not tested: that frames arrive as upright BGR24, that the
detector supplies usable sharpness and brightness, that SFace embeddings behave
as the thresholds assume. If the gate moves any of those, this branch absorbs
the churn instead of the Stage 0/1 review.

The branch is based on the trimmed `codex/b-vision`, so it merges forward
cleanly once the gate passes.

## Before merging it

1. The Stage 0 Mac runtime gate passes: OpenCV installs, weights verify, one
   real face is detected on D's MacBook.
2. A's decoded-frame contract is confirmed against a real feed, not assumed.
3. Re-run the numbers: every threshold in `matching.py`, `ledger.py` and
   `quality.py` is a starting point, not a measurement.
