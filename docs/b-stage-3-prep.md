# B — Stage 3 prep

Plan §7, Stage 3 (B): *"calibrate guest matching, test held-out/unenrolled people
on Mac, remove identity on reframe or lost track."*

Branch: `codex/b-stage-3-prep`, on top of Stage 2.

Stage 3 needs real faces on real cameras, which is a hardware gate nobody has
passed yet. What can be built before the data arrives is **the measuring
instrument** — and building it first is the point. Deciding how a number will be
judged before anyone has seen the number is the only way the judgement stays
honest.

## What it adds

| File | What it does |
|---|---|
| `guests/confidence_calibration.py` | `Calibration.fit()` restored: Platt-style logistic fit on held-out labelled pairs |
| `guests/identity_eval.py` | Threshold selection and trial tallies for the identity report |
| `cue-guests evaluate --trials` | Runs the tally over trials a human recorded |

## Already satisfied, not rebuilt

"Remove identity on reframe or lost track" is the third Stage 3 item, and it is
already done and tested:

- **Reframe** — `ObservationWorker.reframed()` voids identity even when the
  stream epoch has not moved (Stage 2).
- **Lost track** — `observation_pipeline` calls `ledger.forget_track()` for every
  key the tracker reports expired, covered by
  `test_a_track_expires_once_the_face_is_gone` and
  `test_identity_expires_with_its_last_supporting_frame`.

## Calibration fitting

`Calibration.fit()` learns the similarity → confidence mapping from held-out
labelled pairs and stamps the result `MEASURED` with its sample count. Until it
is run on real data, `PROVISIONAL_CALIBRATION` remains the only calibration in
the system and every observation still discloses `PROVISIONAL_DEFAULT`.

It **refuses a one-sided sample** — fewer than 5 positives or 5 negatives raises.
A mapping learnt from positives alone would report high confidence for everybody,
which is the single most dangerous thing this module could produce.

## The measuring instrument

Three refusals are wired into `identity_eval.py`, because each is a way a demo
could claim more than it measured.

**1. A rate is never invented from an empty arm.** No negative trials means the
false-accept rate is `None`, not `0.0`. Zero out of zero is not zero, and a
false-accept rate measured on nobody is the most misleading number the module
could return.

**2. One wrong name makes a run unclaimable**, however good the rest looks. This
is not a weighted score. A wrong confident cut is the worst outcome this project
can produce, so no completion rate absorbs one:

```
positives:    30/30 correct (100.0%)
negatives:    29/30 correctly refused (96.7%)
wrong names:  1  (target: 0)
verdict:      NOT claimable —
              - 1 wrong name(s) were produced; the target is zero, and no
                completion rate excuses one
```

That run exits **1**, so a green terminal can never be mistaken for measured
accuracy.

**3. A threshold is never recommended from a one-sided sample**, for the same
reason `fit()` refuses one.

### Choosing a threshold from data, not from the PRD

`recommend_accept_similarity()` returns the **lowest threshold that named nobody
it should not have** — it maximises accepted true matches *subject to zero false
accepts*, rather than balancing the two errors. Losing a name costs a wide shot;
naming the wrong person costs the demo.

It reports what that choice costs, so the trade is visible rather than implied:

```
threshold:    0.2891 (worst stranger 0.2881, measured on 12 positive / 12 negative pairs)
              Zero false accepts at 0.2891. 0 of 12 true matches fall below it and
              would be refused, which is the trade this project prefers.
```

`sweep()` scores any list of candidate thresholds, and acceptance uses
`similarity >= accept_similarity` — the same comparison `face_matching.match`
makes, so the counts describe production behaviour rather than an approximation
of it. `test_the_prd_threshold_is_not_assumed_to_be_right` demonstrates the case
where the PRD's 0.363 would have named every stranger in the sample.

### A miss is not a safety failure

Failing to name an enrolled guest counts against the completion rate and does
**not** block a claim. Naming the wrong person does. The report separates the two
deliberately, because treating them as the same error is what leads to loosening
a threshold to rescue a miss.

## Using it

```bash
cue-guests evaluate --trials trials.json
```

```json
{
  "positives": [
    {"guestId": "guest-sarah", "namedGuestId": "guest-sarah",
     "status": "CONFIRMED", "msToConfirmed": 640}
  ],
  "negatives": [
    {"subject": "unenrolled-1", "namedGuestId": null, "status": "UNKNOWN"}
  ],
  "pairs": [{"similarity": 0.81, "samePerson": true}]
}
```

`positives` and `negatives` fill `docs/results/b-identity-report.template.md`.
`pairs` is optional and only drives the threshold recommendation.

## Tests

| File | Tests |
|---|---|
| `tests/test_guest_identity_eval.py` | 20 |
| `tests/test_guest_confidence_calibration.py` | 7 (2 restored with `fit()`) |

Most of them assert what the harness **refuses** to say.

## Verified

Windows 11, Python 3.14.7:

```
cd apps/api && python -m pytest -q     ->  308 passed  (was 286)
cd apps/api && python -m ruff check .  ->  All checks passed
ruff --target-version py311            ->  All checks passed
cue-guests evaluate (flawed run)       ->  NOT claimable, exit 1
cue-guests evaluate (clean run)        ->  claimable, exit 0
```

Without the OpenCV extra or the weights: **295 passed, 13 skipped** — what CI runs.

## What this does NOT establish

**Nothing about accuracy.** Not one number in this branch came from a real face.
The harness has only ever been fed synthetic trials, and the calibration fitter
has only ever been fitted on synthetic similarity values.

`MEASURED` calibration remains unreachable in practice until someone fits one on
a held-out set of real captures, so the demo still discloses
`PROVISIONAL_DEFAULT`, and the accept threshold is still the PRD's 0.363.

Still **NOT RUN**, unchanged:

1. **Mac runtime gate with D** — the adapters ran on Windows only.
2. **Real faces**, enrolled and matched from real cameras. Note from Stage 2:
   drawn faces cannot substitute, because SFace collapses them together.
3. **The identity report** — `docs/results/b-identity-report.template.md`. The
   harness computes every number that page asks for, and
   [b-stage-3.md](b-stage-3.md) adds `cue-guests trials` to produce its input;
   somebody still has to run the trials.
4. **B's media checks** — `docs/results/b-media-check.template.md`.

Earlier stages: [b-stage-0.md](b-stage-0.md),
[b-stage-prep-1.md](b-stage-prep-1.md), [b-stage-1.md](b-stage-1.md),
[b-stage-2-prep.md](b-stage-2-prep.md), [b-stage-2.md](b-stage-2.md).
