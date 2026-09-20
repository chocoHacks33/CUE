# B identity report — measured behaviour

**Status: NOT RUN.** No trial in this report has been performed. It exists so the
gap is on the record at scope freeze rather than discovered during the demo.

- Date/time: not run
- Commit SHA: not run
- Mac: **not run** — every execution of B's code so far has been on B's Windows
  laptop. Whether an OpenCV wheel exists for D's macOS, Python and architecture is
  still unanswered.
- Model files and pinned SHA-256:
  - `face_detection_yunet_2023mar.onnx` — `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`
  - `face_recognition_sface_2021dec.onnx` — `0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79`
  - Both downloaded and hashed locally; YuNet's digest independently matches
    upstream's git-lfs `oid`. Licences read: MIT (© 2020 Shiqi Yu) and Apache-2.0.
- Calibration status used: **PROVISIONAL_DEFAULT** (`sface-cosine-provisional-v1`,
  sample count 0). No measured calibration exists. The fitter
  (`Calibration.fit`) has only ever been run on synthetic similarity values.
- Thresholds used: accept similarity 0.363 / margin 0.06 / 3 confirmations /
  1.2 s window / 1.5 s identity TTL. **All are the PRD's starting points and none
  has been measured on our cameras.**

## Enrolment

| Guest | References | Mean reference quality | Lighting / position notes |
|---|---|---|---|
| — | — | — | NOT RUN |

Consent recorded by: — at —. Reference photos deleted after enrolment: NOT RUN

## Clear positives (target: at least 30 trials)

| # | Guest | Camera | Result | Time to CONFIRMED | Notes |
|---|---|---|---|---|---|
| — | — | — | — | — | NOT RUN |

- Trials run: **0**
- Correct completions: NOT RUN
- Wrong-person confirmations (target: zero): NOT RUN

## Unknown and ambiguous (target: at least 30 trials)

| # | Subject | Camera | Result | Notes |
|---|---|---|---|---|
| — | — | — | — | NOT RUN |

- Trials run: **0**
- Correctly refused (UNKNOWN or AMBIGUOUS): NOT RUN
- Wrongly named: NOT RUN

**Note on synthetic substitutes.** Drawn faces cannot stand in for these trials.
Measured on this machine, every detectable drawn-face variant scored 0.78–0.93
cosine against an unrelated reference, far above the 0.363 accept threshold: SFace
is trained on photographs and collapses crude drawings into a narrow region of its
embedding space. A passing synthetic suite is therefore not evidence, and
`test_drawn_faces_cannot_serve_as_negatives` records that so nobody mistakes it
for one.

## Invalidation behaviour

These are the only rows with anything behind them, and what is behind them is
**fixture-driven automated tests, not camera trials**. They are listed separately
because the distinction matters:

| Behaviour | Camera trial | Automated test |
|---|---|---|
| Guest changes seat: old seat keeps no name | NOT RUN | covered — `test_an_old_seat_does_not_keep_a_name_when_someone_else_sits_down` |
| Guest moves to another camera: identity does not follow | NOT RUN | covered — `test_identity_does_not_follow_a_guest_to_another_camera` |
| Camera reframed / republished: identity dropped and re-earned | NOT RUN | covered — `test_a_republished_camera_must_earn_its_confirmation_again` |
| Identity expires 1.5 s after last supporting frame | NOT RUN | covered — `test_identity_expires_with_its_last_supporting_frame` |
| Consent withdrawn mid-run: name disappears from live evidence | NOT RUN | covered — `test_a_withdrawal_leaves_nothing_the_system_can_reach` (through the HTTP API) |

## Calibration

- Held-out set size: **0**
- Positives / negatives: 0 / 0
- Fitted calibration ID and sample count: none. `MEASURED` is unreachable in
  practice until `cue-guests calibrate` runs on two-sided held-out pairs.
- Confidence reported for a true match / a stranger: NOT MEASURED. Any confidence
  the system currently shows comes from the provisional logistic anchored on
  OpenCV's published SFace reference point (0.363), which is an anchor, not a
  result.

## Honest summary

- **What we will claim on stage:** nothing about face recognition accuracy. The
  readiness gate returns `ROLE_BASED` on this evidence, which means cameras are
  chosen by role and no name on screen comes from a face. Verifiable live at
  `GET /api/v1/guests/readiness`.
- **What we will explicitly not claim:** that anyone was recognised; any accuracy,
  precision or confidence figure; that the thresholds are tuned; that the system
  has been run on a Mac.
- **Conditions this was measured under:** none. No camera has published to this
  system and no human face has been through it.
- **Known failure modes seen during testing:** none observed live, because no live
  testing happened. Known from the code and from reasoning, unresolved:
  - The tracker is IoU-only. Two guests crossing on the same camera can swap
    tracks. The confirmation reset limits the damage to a lost identity rather
    than a wrong one, but it is not solved.
  - No group-framing logic. B reports each face separately.
  - The quality gate's sharpness scale (Laplacian variance / 500) was chosen
    without looking at a real webcam frame and should be expected to need
    retuning.

## What would change this document

In order, each blocked on the one before:

1. Mac runtime gate with D — `pip install -e "apps/api[opencv]"` on the MacBook.
2. Enrol consenting guests — `cue-guests enrol`.
3. Run the trials — `cue-guests trials`, varying seats, angles and lighting.
4. Tally them — `cue-guests evaluate --trials trials.json`. It exits non-zero
   while the run cannot support a claim, so this page cannot quietly acquire
   numbers that do not hold up.
5. Only if the pairs are two-sided — `cue-guests calibrate`.

See [docs/b-stage-4-prep.md](../b-stage-4-prep.md) for how the result will be
judged, and [docs/b-stage-4.md](../b-stage-4.md) for how the verdict reaches the
product.
