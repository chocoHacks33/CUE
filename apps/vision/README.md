# cue-vision

Person B's guest-identity package: face detection, quality gating, calibrated
matching, local tracking and identity expiry.

It observes. It never directs — nothing here selects a camera or requests a cut.

## Design

The core has **no dependencies**. Embeddings are tuples of floats and cosine
similarity is a dot product, so the policy layer imports and tests on any of the
four machines. Only `cue_vision.adapters.opencv_models` touches pixels, and it
imports `cv2` lazily so a missing native wheel fails at the point of use with a
clear message instead of at import time.

```text
A's worker --DecodedFrame--> VisionPipeline --Observation--> backend/policy/UI
                                  |
                 detector -> quality gate -> embedder -> gallery match
                                  |
                       tracker + identity ledger (confirm, expire, invalidate)
```

## Install

```bash
python -m pip install -e "apps/vision[dev]"           # core + tests
python -m pip install -e "apps/vision[opencv,dev]"    # plus live inference
```

## Use

```bash
python -m pytest -q
python -m ruff check .

cue-vision models --model-dir models
cue-vision enrol --api https://… --secret … --event hackmit-demo \
  --name Sarah --consent-confirmed photo.jpg
cue-vision gallery --api https://… --secret … --event hackmit-demo
cue-vision forget --api https://… --secret … --event hackmit-demo --guest-id guest-sarah
```

## Status

Every test in `tests/` drives scripted detectors and embedders. They prove the
policy around the models — abstention, confirmation, expiry, epoch and consent
invalidation — and prove nothing about recognition accuracy. No model file has
been downloaded and the OpenCV adapters have never executed. See
`docs/stage-1-b-handoff.md` and `docs/vision-models.md`.
