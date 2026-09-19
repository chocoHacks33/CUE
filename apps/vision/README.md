# cue-vision

Person B's guest-identity package. Stage 0/1 scope: model provenance, face
detection, the capture-quality gate and the enrolled reference gallery.

It observes. It never directs — nothing here selects a camera or requests a cut.

Matching, calibration, local tracking, identity expiry and the observation
pipeline are Stage 2/3 work and live on `codex/b-vision-stage2`, unmerged until
the Mac runtime gate passes.

## Design

The core has **no dependencies**. Embeddings are tuples of floats and cosine
similarity is a dot product, so the policy layer imports and tests on any of the
four machines. Only `cue_vision.adapters.opencv_models` touches pixels, and it
imports `cv2` lazily so a missing native wheel fails at the point of use with a
clear message instead of at import time.

```text
enrolment photo --> detector --> quality gate --> embedder --> backend gallery

A's worker --DecodedFrame--> detector --> quality gate --> [Stage 2: match]
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

Every test in `tests/` drives fixtures rather than pixels. They prove the
quality gate's thresholds, the model registry's refusals and the gallery
loader's rules, and prove nothing about recognition accuracy. No model file has
been downloaded and the OpenCV adapters have never executed. See
`docs/stage-1-b-handoff.md` and `docs/vision-models.md`.
