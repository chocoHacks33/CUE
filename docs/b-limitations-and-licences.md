# B — limitations and licences

Owner: Person B (guest visual identity). Submission-ready statement of what this
part of CUE does, what it does **not** do, and what it is built on.

Written to be read by a judge who is sceptical, which is the correct posture. Every
"not" below is a real gap rather than a modesty formula.

## In one paragraph

B identifies consenting, enrolled guests by face so the director can name them —
and **on today's evidence it is switched off**. No trial with a real person has
been run, so B's readiness gate reports `ROLE_BASED`: cameras are chosen by role
and no name on screen comes from a face. That verdict is served live at
`GET /api/v1/guests/readiness` with its reasons, so it can be checked rather than
taken on trust.

## What is built and verified

| Capability | Verified how |
|---|---|
| Consent recorded before enrolment, event-scoped, three separate purposes | automated tests through the HTTP API |
| Reference photos never leave the enrolling laptop; only embeddings travel | `cue-guests enrol` computes locally and posts the embedding |
| Embeddings leave the process by exactly one route, operator-credentialled | `GET /api/v1/guests/gallery`; guest-facing shapes reject embeddings on both sides |
| Withdrawal deletes references, drops live evidence, returns a counted receipt | end-to-end API scenario tests |
| Withdrawal cannot be undone by a late observation already in flight | refused 409 |
| Re-enrolment after withdrawal needs fresh consent | refused 403 |
| End-of-event cleanup that **re-reads and proves** nothing remains | `cue-guests end-event`, run against a live server |
| Abstention: UNKNOWN for no match, AMBIGUOUS when two guests score too closely | fixture-driven tests |
| One frame is never an identity; three consistent frames are | fixture-driven tests |
| Identity bound to one camera, epoch and track; expires with its last frame | fixture-driven tests |
| Capture-quality gate refuses rather than matching weakly | boundary sweep across lighting, blur, distance, framing |
| Model files verified against pinned digests at load time | real ONNX files loaded; wrong digest refuses to load |
| YuNet and SFace actually execute | run on Windows, detected a drawn face, produced a 128-d unit embedding |

## What is NOT done

- **No real human face has ever been through this system.** Not one. Every
  verification above used scripted fixtures or a crudely drawn face.
- **Never run on the Mac that will run the show.** OpenCV was installed and the
  models executed on B's Windows laptop. Whether a wheel exists for D's macOS,
  Python and architecture is untested.
- **No accuracy figure exists**, and none will be claimed. The identity report
  (`docs/results/b-identity-report.md`) records 0 trials in both arms.
- **No measured calibration.** Any confidence the system can show comes from a
  provisional logistic anchored on OpenCV's published SFace reference point
  (0.363). That is an anchor, not a result, and every observation discloses
  `PROVISIONAL_DEFAULT`.
- **Thresholds are unmeasured.** Accept similarity 0.363, margin 0.06, 3
  confirmations in 1.2 s, 1.5 s identity TTL — all the PRD's starting points, none
  measured on our cameras.
- **No camera has published to this system** from B's laptop, and nothing has been
  received on D's Mac. B's media checks are all NOT RUN.
- **The tracker is IoU-only.** Two guests crossing on the same camera can swap
  tracks. The confirmation reset limits the damage to a lost identity rather than a
  wrong one, but it is not solved.
- **No group framing.** B reports each face separately; deciding that "Sarah and
  Daniel" needs a wide shot is C's policy.
- **The quality gate's sharpness scale** (Laplacian variance / 500) was chosen
  without looking at a real webcam frame.
- **Drawn faces cannot stand in for real ones.** Measured here, every detectable
  drawn-face variant scored 0.78–0.93 cosine against an unrelated reference,
  because SFace is trained on photographs and collapses drawings together. A
  passing synthetic suite is therefore not evidence of recognition.
- **No validation against today's conditions.** The gate requires B's three Stage 7
  checks — reframe, re-enrolment after a restart, and unknown rejection in the
  current lighting — to be re-run and recorded **each day**, because moving a laptop
  changes framing and a room's light changes with the hour. None has been run. See
  [`docs/results/b-stage-7-morning-check.md`](results/b-stage-7-morning-check.md).

## Privacy posture

- Nobody is identified without opt-in, event-scoped consent recorded before
  enrolment. `LIVE_IDENTIFICATION` must be granted specifically: consenting to be
  filmed is not consenting to be matched by face.
- Reference photos stay on the enrolling laptop and are deleted after enrolment.
  Only the 128-float embedding is transmitted.
- No database, no disk persistence. A backend restart clears every embedding and
  requires re-enrolment. That is the default, not an unfinished feature, and it is
  **demonstrated** rather than asserted: after a restart the gallery is empty, the
  guest record is gone entirely, and re-attaching a reference to the vanished guest
  is refused, so re-enrolment means a fresh consent conversation.
- Embeddings never enter a language-model request or an operational log.
- An unknown face stays unknown. Two faces that score too closely produce an
  abstention, not the better guess.
- A raw similarity is never reported as a confidence.
- **Stated limitation:** Python cannot guarantee a float list's bytes leave process
  memory. `purge_references()` overwrites each vector with zeros and unlinks it,
  which is best effort. The real guarantee is that nothing is written to disk and
  the process is stopped at the end of the event.

## Model licences

Both files were downloaded from upstream `opencv/opencv_zoo` and hashed locally;
both upstream `LICENSE` files were fetched and read rather than assumed.

| Model | File | Licence | Digest (verified locally) |
|---|---|---|---|
| YuNet | `face_detection_yunet_2023mar.onnx` | **MIT**, Copyright (c) 2020 Shiqi Yu | `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4` |
| SFace | `face_recognition_sface_2021dec.onnx` | **Apache-2.0** | `0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79` |

YuNet's digest independently matches the `oid sha256` in upstream's git-lfs
pointer, so the pin is corroborated by upstream metadata and not only by our own
hashing. Weights are **not committed**; `models/` is gitignored.

## Third-party dependencies

Versions as installed and verified on B's machine, licences read from package
metadata:

| Package | Version | Licence |
|---|---|---|
| fastapi | 0.141.1 | MIT |
| uvicorn | 0.53.0 | BSD-3-Clause |
| pydantic | 2.13.5 | MIT |
| pydantic-settings | 2.15.0 | MIT |
| livekit-api | 1.2.1 | Apache-2.0 |
| openai | 3.16.2 | Apache-2.0 |
| python-dotenv | 1.2.3 | BSD-3-Clause |
| opencv-python | 4.14.0.94 | Apache-2.0 |
| numpy | 2.5.3 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| httpx | 0.28.1 | BSD-3-Clause (dev/test only) |
| pytest | 8.4.2 | MIT (dev/test only) |
| ruff | 0.16.8 | MIT (dev/test only) |

`opencv-python` and `numpy` are **optional**, behind the `apps/api[opencv]` extra.
The default install needs no native wheel, so the whole consent and policy layer
builds and tests on every machine in the team.

## What we will say on stage, and what we will not

**Will say:**

- CUE follows what is happening, not who is talking.
- Guest identity is consent-gated, event-scoped, memory-only, and deletable with a
  receipt.
- The system is built to abstain: an unknown face stays unknown, and a close call
  produces no name.
- **Identity naming is currently switched off, because we have not measured it.**
  Cameras are chosen by role. You can check that at
  `GET /api/v1/guests/readiness`.
- That gate re-validates **daily**: even with every other piece of evidence in
  place, naming stays off until today's three checks have been run and recorded.
  A check that fails switches naming off on its own rather than relying on somebody
  remembering to.

**Will not say:**

- That anyone was recognised.
- Any accuracy, precision, recall or confidence figure.
- That the thresholds are tuned.
- That the vision path has run on the Mac.
- That a passing test suite means recognition works.

See also: [b-stage-4.md](b-stage-4.md) for the readiness gate,
[`docs/results/b-identity-report.md`](results/b-identity-report.md) and
[`docs/results/b-media-check.md`](results/b-media-check.md) for the empty trial
records, and [b-stage-0.md](b-stage-0.md) for the full privacy detail.
