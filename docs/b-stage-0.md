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

| Key | File | Purpose | Source | Declared licence | Licence verified | SHA-256 pinned |
|---|---|---|---|---|---|---|
| `yunet` | `face_detection_yunet_2023mar.onnx` | face detection | [opencv_zoo/face_detection_yunet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) | MIT (as published upstream) | NO | NO |
| `sface` | `face_recognition_sface_2021dec.onnx` | face embedding | [opencv_zoo/face_recognition_sface](https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface) | Apache-2.0 (as published upstream) | NO | NO |

Weights are **not** committed. `models/` is gitignored.

## Why the checksum column is empty

A checksum written from memory would pass review and prove nothing. The values
stay empty until someone downloads the files and records the digest of what they
actually got. `apps/api/tests/test_guest_face_models.py` asserts that nothing is
pinned until that happens, so this page and the code cannot drift apart.

## Pinning procedure

```bash
cd apps/api
mkdir -p models
# download both .onnx files from the source links above into models/
python -m pip install -e ".[dev]"
python -m cue_api.guests.enrolment_cli models --model-dir models
```

The command prints each file's `sha256`. For each one:

1. Paste the digest into `expected_sha256` in `src/cue_api/guests/face_models.py`.
2. Paste the same digest into the table above and set "SHA-256 pinned" to YES.
3. Open the upstream `LICENSE` file next to the model, confirm the licence text
   matches the declared licence, then set `licence_verified=True` and update the
   table. If it does not match, record what it actually says.
4. Re-run `python -m pytest` — the "nothing is claimed before download" test will
   now fail by design; update it to assert the pins instead.

After pinning, every machine that runs the adapters verifies the digest at model
load time and refuses a file that does not match.

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
| `apps/api/tests/test_guest_face_models.py` | 6 |

## Verified

Windows 11, Python 3.14.7:

```
cd apps/api && python -m pytest -q     ->  182 passed (whole backend suite)
cd apps/api && python -m ruff check .  ->  All checks passed
```

Never run: any real pixels. No weights downloaded, no OpenCV wheel installed, no
face detected. The adapters are written against OpenCV's documented API and have
never executed.

Next: [b-stage-prep-1.md](b-stage-prep-1.md), then [b-stage-1.md](b-stage-1.md).
