# B — Stage 3

Plan §7, Stage 3 (B): *"calibrate guest matching, test held-out/unenrolled people
on Mac, remove identity on reframe or lost track."*

Branch: `codex/b-stage-3`, on top of Stage 3 prep.

**Read this first.** Two of the three items are measurements on hardware nobody
has run yet, and no amount of code closes them. What this branch does is remove
every remaining *coding* obstacle, so that the moment a Mac and real faces exist,
Stage 3 is a sequence of commands rather than a build. The measurement itself is
still **NOT RUN**, and the section at the end says exactly what that leaves
unproven.

## Status of the three items

| Item | State |
|---|---|
| Remove identity on reframe or lost track | **Done** — already shipped in Stage 2 and its prep |
| Calibrate guest matching | **Code complete, unmeasured** — fit, persist, load and use a `MEASURED` calibration |
| Test held-out/unenrolled people on Mac | **Tooling complete, NOT RUN** — needs D's Mac and real people |

### Already done, not rebuilt

`ObservationWorker.reframed()` voids identity even when the stream epoch has not
moved, and `observation_pipeline` calls `ledger.forget_track()` for every key the
tracker reports expired. Both were tested in Stage 2.

## What this branch adds

| File | What it does |
|---|---|
| `guests/calibration_store.py` | Save, load and **validate** a fitted calibration |
| `guests/trial_runner.py` | Score labelled captures into the identity report's inputs |
| `cue-guests calibrate` | Fit a `MEASURED` calibration from labelled pairs, write it to disk |
| `cue-guests trials` | Run labelled capture files through the real models |

## Carrying a calibration, without letting it lie

`Calibration.fit()` existed from Stage 3 prep, but nothing could carry a fitted
calibration from the machine that fitted it to the machine running the show. That
gap meant `MEASURED` could never actually reach an observation.

Closing it creates the cheapest possible way to fake a result: a hand-edited JSON
saying `MEASURED` would make every observation downstream report a confidence
nobody measured. So loading **validates the claim rather than trusting it**:

| Rejected | Why |
|---|---|
| `MEASURED` with 0 samples | `fit()` cannot produce that |
| `MEASURED` with fewer than 10 samples | `fit()` needs 5 positives and 5 negatives |
| `MEASURED` with zero slope | reports one confidence for everybody, which is not a measurement |
| `UNCALIBRATED` claiming a sample count | it reports no confidence at all |
| Missing or empty `datasetNote` | an unattributed calibration cannot be reviewed |
| Non-finite or non-numeric parameters | not a mapping |
| Unknown status, wrong file version, bad JSON | not a calibration |

Saving is validated too, so a bad claim never reaches disk in the first place.

**A missing file falls back to `PROVISIONAL_DEFAULT`** — that is a disclosure, not
a default. **A file that is present but invalid raises**, and is deliberately not
downgraded: somebody put it there on purpose and will assume it is in use.

Verified end to end:

```
no calibration file   -> PROVISIONAL_DEFAULT (sface-cosine-provisional-v1)
fitted file on disk   -> MEASURED (held-out-2026-09-19), reaches
                         to_contract()["match"]["calibrationStatus"]
tampered file         -> refused: "A MEASURED calibration claims 0 samples;
                         fitting needs at least 10, so this was not produced by a fit"
```

## Running the trials

`trial_runner` turns labelled captures into exactly what Stage 3 prep's harness
consumes, so the loop closes without anyone writing code on the night.

It scores each capture as a **single-frame** trial on purpose: this measures the
*matcher*, not the confirmation ledger. Whether repeated agreement confirms is
already covered by the pipeline tests, and mixing the two here would hide which
one a failure came from.

Two refusals:

- **A capture with no detectable face is not a trial result.** It is recorded as
  skipped, with a reason. Counting it as a refusal would flatter the refusal rate
  with photographs that never reached the matcher.
- **It never invents a label.** A positive names the guest it is supposed to be; a
  negative carries only a subject label, never a guest ID, because those people
  are not enrolled.

A positive pair is scored against **the guest the capture is supposed to be**, not
against whoever scored highest. When somebody else scores higher that is a
wrong-person result, and the honest similarity for the pair is still how well the
system matched the right person.

## The command sequence, once hardware exists

```bash
# 1. enrol consenting guests (photos never leave the laptop)
cue-guests enrol --api … --secret … --event … --name Sarah sarah-1.jpg sarah-2.jpg

# 2. score the held-out captures against the gallery
cue-guests trials --api … --secret … --event … \
  --positive guest-sarah=heldout/sarah-a.jpg \
  --negative heldout/stranger-1.jpg \
  --out trials.json

# 3. tally them; exits 1 if the run cannot support a claim
cue-guests evaluate --trials trials.json

# 4. only if the pairs are two-sided, fit and persist a calibration
cue-guests calibrate --pairs trials.json --out calibration.json \
  --calibration-id held-out-2026-09-19 \
  --dataset-note "30 positive / 30 negative, held-out set A"
```

The worker then adopts it in one line:

```python
calibration = load_or_provisional(Path("calibration.json")).calibration
```

`calibrate` refuses a one-sided sample, exit 1:

```
error: Calibration needs at least 5 positive and 5 negative labelled pairs;
       received 30 positive and 0 negative
```

## Tests

| File | Tests |
|---|---|
| `tests/test_guest_calibration_store.py` | 23 |
| `tests/test_guest_trial_runner.py` | 11 |

Most of the calibration-store tests are refusals, because that file is where a
false claim would be cheapest.

## Verified

Windows 11, Python 3.14.7:

```
cd apps/api && python -m pytest -q     ->  485 passed
cd apps/api && python -m ruff check .  ->  All checks passed
ruff --target-version py311            ->  All checks passed
cue-guests calibrate (one-sided)       ->  refused, exit 1
cue-guests calibrate (two-sided)       ->  MEASURED, 60 samples, file written
```

**That 485 is the whole backend suite, not B's.** Other lanes landed work while
this branch was open. B owns 272 of them; 34 are new here.

## What this does NOT establish

**No accuracy. No real face. Nothing measured.**

The `MEASURED` calibration demonstrated above was fitted on **synthetic similarity
values generated for the demonstration**. It proves the file format, the
validation and the wiring carry a calibration correctly. It is not a calibration
of anything, and it was written to a scratch directory, not committed.

Still **NOT RUN**, and only hardware closes these:

1. **Mac runtime gate with D.** The adapters have run on Windows only; whether an
   OpenCV wheel exists for D's macOS, Python and architecture is untested.
2. **Real faces.** Enrolment and matching of actual people from actual cameras.
   From Stage 2: drawn faces cannot substitute, because SFace collapses them into
   a narrow region of its embedding space.
3. **`docs/results/b-identity-report.template.md`** — at least 30 clear positives
   and 30 unknown/ambiguous trials on a held-out set. Every number that page asks
   for is now computed by `cue-guests evaluate`; somebody still has to run the
   trials.
4. **`docs/results/b-media-check.template.md`** — B's own capture checks.

Until (3) exists, the accept threshold stays the PRD's 0.363, no calibration file
ships, and every observation discloses `PROVISIONAL_DEFAULT`. B claims no accuracy
number on stage.

Earlier stages: [b-stage-0.md](b-stage-0.md),
[b-stage-prep-1.md](b-stage-prep-1.md), [b-stage-1.md](b-stage-1.md),
[b-stage-2-prep.md](b-stage-2-prep.md), [b-stage-2.md](b-stage-2.md),
[b-stage-3-prep.md](b-stage-3-prep.md).
