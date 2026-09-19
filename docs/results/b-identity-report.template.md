# B identity report — measured behaviour

Copy to `b-identity-report.md`. Every number here must come from a trial that was
actually run on D's Mac with the real cameras. A fixture result is not a result.

- Date/time:
- Commit SHA:
- Mac: macOS version / architecture / Python:
- Model files and pinned SHA-256:
- Calibration status used in the run: PROVISIONAL_DEFAULT / MEASURED (id, sample count)
- Thresholds used: accept similarity / margin / confirmations / window / identity TTL

## Enrolment

| Guest | References | Mean reference quality | Lighting / position notes |
|---|---|---|---|
| | | | |

Consent recorded by: ______ at ______. Reference photos deleted after enrolment: NOT RUN

## Clear positives (target: at least 30 trials)

| # | Guest | Camera | Result | Time to CONFIRMED | Notes |
|---|---|---|---|---|---|

- Trials run: NOT RUN
- Correct completions: NOT RUN
- Wrong-person confirmations (target: zero): NOT RUN

## Unknown and ambiguous (target: at least 30 trials)

Include people who never enrolled, and at least one deliberate near-pair.

| # | Subject | Camera | Result | Notes |
|---|---|---|---|---|

- Trials run: NOT RUN
- Correctly refused (UNKNOWN or AMBIGUOUS): NOT RUN
- Wrongly named: NOT RUN

## Invalidation behaviour

- Guest changes seat: old seat keeps no name: NOT RUN
- Guest moves to another camera: identity does not follow: NOT RUN
- Camera reframed / republished: identity dropped and re-earned: NOT RUN
- Identity expires 1.5 s after last supporting frame: NOT RUN
- Consent withdrawn mid-run: name disappears from live evidence: NOT RUN

## Calibration

- Held-out set size (must be separate from anything used for tuning): NOT RUN
- Positives / negatives:
- Fitted calibration ID and sample count:
- Confidence reported for a true match / a stranger:

## Honest summary

- What we will claim on stage:
- What we will explicitly not claim:
- Conditions this was measured under (lighting, distance, who was present):
- Known failure modes seen during testing:
