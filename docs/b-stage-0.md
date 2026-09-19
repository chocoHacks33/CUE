# B — Stage 0

Plan §7, Stage 0 (B): *"model-weight/licence check, consent roster and Mac
face-inference spike with D. Keep calibration and release captures separate."*

Everything B owns lives in one package, `apps/api/src/cue_api/guests/`.

---

# Part 1 — Model weight and licence check

| File | What it does |
|---|---|
| `guests/face_models.py` | Model registry: filenames, sources, licences, SHA-256 slots, `verify()` at load time |
| `guests/adapters/opencv_models.py` | YuNet detector + SFace embedder, OpenCV imported lazily. **Never executed** |

## The model files

| Key | File | Purpose | Declared licence | Licence verified | SHA-256 pinned |
|---|---|---|---|---|---|
| `yunet` | `face_detection_yunet_2023mar.onnx` | face detection | MIT, Copyright (c) 2020 Shiqi Yu | **YES** | **YES** |
| `sface` | `face_recognition_sface_2021dec.onnx` | face embedding | Apache-2.0 | **YES** | **YES** |

Sources: [opencv_zoo/face_detection_yunet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet)
and [opencv_zoo/face_recognition_sface](https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface).

Pinned digests, recorded in `guests/face_models.py`:

```
yunet  8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4   232,589 bytes
sface  0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79  38,696,353 bytes
```

Weights are **not** committed. `models/` is gitignored.

## How these digests were obtained

Not copied from a README. The files were downloaded from upstream opencv_zoo and
hashed locally:

```bash
cd apps/api && mkdir -p models
base=https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models
curl -sSL -o models/face_detection_yunet_2023mar.onnx   "$base/face_detection_yunet/face_detection_yunet_2023mar.onnx"
curl -sSL -o models/face_recognition_sface_2021dec.onnx   "$base/face_recognition_sface/face_recognition_sface_2021dec.onnx"
python -m cue_api.guests.enrolment_cli models --model-dir models
```

Note the `media.githubusercontent.com/media/` host. The ordinary `raw.` URL
returns a **131-byte git-lfs pointer**, not the model, and an ONNX loader fails
on it with an unhelpful parse error.

**Independent check:** that pointer file declares `oid sha256:8f2383e4…2552fa4`
for YuNet, which matches the digest of the file actually downloaded. So the
YuNet pin is corroborated by upstream metadata, not only by our own hashing.

**Licences read, not assumed.** Both upstream `LICENSE` files were fetched and
read. YuNet is the MIT licence, Copyright (c) 2020 Shiqi Yu. SFace is Apache-2.0.
Both match what was declared, so `licence_verified=True` is recorded.

From here on every machine verifies a model against its pin at load time and
refuses a file that does not match — `test_a_wrong_digest_stops_the_model_loading_at_all`
covers that.

`models/` is gitignored, so the weights are never committed.

## Runtime requirement

The package installs with no native dependency. Live inference needs the extra:

```bash
python -m pip install -e "apps/api[opencv]"
```

`opencv-python` ships platform wheels. Whether a wheel exists for D's exact
macOS/Python/architecture combination is **unverified** and is part of the Mac
runtime gate below, not an assumption.

---

# Part 2 — Consent roster

| File | What it does |
|---|---|
| `guests/registry.py` | Event-scoped, in-memory consent + reference registry with deletion receipts |
| `guests/contracts.py` | Consent purposes, guest status, enrolment rules |

## What we ask for, and when

Nobody is identified without opt-in, event-scoped consent recorded before
enrolment. `POST /api/v1/guests` refuses an enrolment where `consentGranted` is
false, and refuses one that omits the `LIVE_IDENTIFICATION` purpose, so a guest
who agreed only to be recorded cannot be matched by face.

The spoken consent script, printed by `cue-guests enrol` before it will do
anything:

> Consent recorded for: live identification during this event, local recording
> and cloud media relay. References are held in memory on the director Mac only
> and are deleted at event end or on request.

The three purposes are recorded separately, because the guest is agreeing to
three different things: being matched by face, being recorded, and having their
video relayed through LiveKit Cloud.

## What is stored, and where

| Data | Where | Lifetime |
|---|---|---|
| Reference photo | The enrolling laptop, never uploaded | Deleted by B after enrolment |
| Reference embedding (128 floats) | Memory of the API process on D's Mac | Until withdrawal, event purge, or restart |
| Display name and aliases | Same process memory | Same |

There is no database and no disk persistence. A backend restart clears every
embedding and requires re-enrolment. That is the privacy default, not an
unfinished feature.

Reference embeddings leave the process through exactly one route: the
worker-facing `GET /api/v1/guests/gallery`, which requires the operator
credential. The guest-facing shapes (`GuestRecord`, `GuestListResponse`) carry no
embeddings at all, and both the TypeScript and Python parsers reject a guest
record that tries to carry one.

## What never happens

- A name is never inferred from a seat, a camera role, a join order or a track.
  A display name without a guest ID is rejected as a seat label.
- Face references and embeddings never enter a language-model request or an
  operational log.
- An unknown face stays unknown. Two faces that score too closely produce an
  abstention, not the better guess.
- A raw similarity is never reported as a confidence.

## Deletion

| Action | Endpoint | Effect |
|---|---|---|
| One guest withdraws | `DELETE /api/v1/guests/{guestId}?eventId=` | Embeddings zeroed and unlinked, reference version reset, consent marked withdrawn, removed from the worker gallery |
| Event ends | `DELETE /api/v1/guests?eventId=` | Every guest record and embedding for the event removed |

Both return a receipt counting what was deleted, so deletion is observable rather
than promised. After withdrawal, adding a new reference to that guest is refused;
re-enrolment means a fresh consent conversation. A withdrawn guest may not hold
references, and the contract rejects a record that claims otherwise.

**Stated limitation:** Python cannot guarantee that a float list's bytes leave
process memory. `purge_references()` overwrites each vector with zeros and
unlinks it, which is best effort. The real guarantee is that nothing is written
to disk and the process is stopped at the end of the event.

---

# Part 3 — Mac face-inference spike with D

**NOT RUN.** Needs D's MacBook. Template:
`docs/results/b-identity-report.template.md`.

This is B's exit gate for Stage 0: install `apps/api[opencv]` on the Mac and
confirm an OpenCV wheel exists for D's Python and architecture. If no wheel
exists, that is a runtime-gate failure to solve with D, not something to discover
during the demo.

Calibration and release captures are kept separate, as the plan requires: no
calibration exists anywhere in B's code, and any observation carrying a
confidence must declare `PROVISIONAL_DEFAULT` rather than implying a measured
number.

---

## Tests

| File | Tests |
|---|---|
| `apps/api/tests/test_guest_registry.py` | 44 |
| `apps/api/tests/test_guest_face_models.py` | 7 |
| `apps/api/tests/test_guest_opencv_adapters.py` | 13 (skipped without the weights) |

## Verified

Windows 11, Python 3.14.7:

```
cd apps/api && python -m pip install -e ".[opencv,dev]"
cd apps/api && python -m pytest -q     ->  286 passed
cd apps/api && python -m ruff check .  ->  All checks passed
cue-guests models --model-dir models   ->  both digests match their pins
```

Without the OpenCV extra or the weights, the 13 adapter tests skip and the suite
reports **273 passed, 13 skipped** — which is what CI does.

**The weights have now been downloaded and both models load and run** on this
Windows laptop. See [b-stage-2.md](b-stage-2.md) for what that established and
what it did not.

**Still NOT RUN:** the Mac runtime gate with D. This was Windows; whether an
OpenCV wheel exists for D's macOS, Python and architecture is a separate
question and still unanswered.

Next: [b-stage-prep-1.md](b-stage-prep-1.md), then [b-stage-1.md](b-stage-1.md).
