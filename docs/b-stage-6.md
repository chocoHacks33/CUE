# B — Stage 6

Plan §7, Stage 6: *"overnight until Sunday 08:00: permitted accommodation and
rest."*

Branch: `codex/b-stage-6`, on top of Stage 6 prep.

**Stage 6 lists no per-person deliverables at all.** Unlike every other stage, there
is no `- **B:**` line, because the stage's content is rest. What it permits is a
short handoff and offline regression checks; what it forbids is new media
architecture, model migration or any major feature.

Prep built the two permitted things. So Stage 6 proper is not a build — it is
*running* the procedure and filing the result:

**[`docs/results/b-stage-6-check.md`](results/b-stage-6-check.md)**

That is the entire deliverable, and it is one page.

## Why there is no code in this branch

B's own handoff, written yesterday, tells the team not to retune thresholds, loosen
the readiness gate, migrate models or touch hardware overnight. Adding a feature
here would contradict advice B shipped one commit earlier, and it would be the one
class of change that cannot be verified before the venue reopens.

So: nothing was added. That is the correct outcome, not a shortfall.

## What the check found

```
  PASS  B's tests      391 passed, 312 deselected
  PASS  ruff           All checks passed!
  PASS  naming policy  ROLE_BASED True False
  PASS  doc links      16 documents, every link resolves

Nothing drifted. B's lane is where it was left.        exit 0
```

Whole suite: **690 passed, 13 skipped**.

One detail worth having in the record rather than discovered at 08:00: **those 13
skips are D's**, not B's. They are `test_av_skew.py` and `test_verify_recording.py`
skipping because `ffmpeg` is not on this laptop's PATH, confirmed with `pytest -rs`.
B's model-backed tests ran, because the weights are on this machine.

Checked rather than assumed: moving the weights aside makes the suite read **677
passed, 26 skipped**. That is the shape CI runs — which is why CI being green does
not by itself mean the models were exercised.

## Readiness, unchanged overnight

`ROLE_BASED`, `PROVISIONAL_DEFAULT`, four blocking reasons — the same four as at
freeze. No name on screen comes from a face, and the disclosure is served live and
rendered in D's compositor.

## Next

Stage 7 at 08:00 is where B's four outstanding items get attempted, all of them
hardware: the Mac runtime gate with D, real trials, a measured calibration, and B's
media checks. The command sequence is ready in
[b-stage-6-prep.md](b-stage-6-prep.md).

The instruction to keep in mind from that page: **if an unenrolled person is named
even once, stop and leave the gate on `ROLE_BASED`.** Shipping `ROLE_BASED` with its
disclosure is a defensible demo. A confident wrong name is not.

Earlier stages: [b-stage-0.md](b-stage-0.md),
[b-stage-prep-1.md](b-stage-prep-1.md), [b-stage-1.md](b-stage-1.md),
[b-stage-2-prep.md](b-stage-2-prep.md), [b-stage-2.md](b-stage-2.md),
[b-stage-3-prep.md](b-stage-3-prep.md), [b-stage-3.md](b-stage-3.md),
[b-stage-4-prep.md](b-stage-4-prep.md), [b-stage-4.md](b-stage-4.md),
[b-stage-5-prep.md](b-stage-5-prep.md), [b-stage-5.md](b-stage-5.md),
[b-stage-6-prep.md](b-stage-6-prep.md).
