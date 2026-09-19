# Vision model files, licences and checksums

Owner: Person B. Status of every claim on this page is stated explicitly. Nothing
here has been verified on D's MacBook yet.

## Files

| Key | File | Purpose | Source | Declared licence | Licence verified | SHA-256 pinned |
|---|---|---|---|---|---|---|
| `yunet` | `face_detection_yunet_2023mar.onnx` | face detection | [opencv_zoo/face_detection_yunet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) | MIT (as published upstream) | NO | NO |
| `sface` | `face_recognition_sface_2021dec.onnx` | face embedding | [opencv_zoo/face_recognition_sface](https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface) | Apache-2.0 (as published upstream) | NO | NO |

Weights are **not** committed. `models/` is ignored by Git.

## Why the checksum column is empty

A checksum written from memory would pass review and prove nothing. The values
stay empty until someone downloads the files and records the digest of what they
actually got. `apps/api/tests/test_guest_face_models.py` asserts that nothing is pinned
until that happens, so this page and the code cannot drift apart.

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

The core package installs with no dependencies. Live inference needs the extra:

```bash
python -m pip install -e "apps/api[vision]"
```

`opencv-python` ships platform wheels. Whether a wheel exists for D's exact
macOS/Python/architecture combination is **unverified** and is part of the Stage 0
Mac runtime gate, not an assumption. If no wheel exists, that is a runtime-gate
failure to solve with D before any more vision work, not something to discover
during the demo.
