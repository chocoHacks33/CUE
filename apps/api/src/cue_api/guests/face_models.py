"""Model file registry: where the weights come from, and what we verified.

Both digests are the files actually downloaded from upstream opencv_zoo and
hashed locally, not values copied from a README. YuNet's digest independently
matches the `oid sha256` in upstream's git-lfs pointer. Both upstream LICENSE
files were read and match the declared licence.

From here on every machine verifies a model file against these pins at load
time and refuses one that does not match.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

#: Default location for downloaded weights. Never committed to Git.
DEFAULT_MODEL_DIR = Path("models")


@dataclass(frozen=True)
class ModelFile:
    key: str
    filename: str
    purpose: str
    source_url: str
    #: Upstream licence as published. Confirm against the file you downloaded.
    declared_licence: str
    licence_verified: bool
    #: Fill in from `cue-guests models --record` once the file is downloaded.
    expected_sha256: str | None = None

    def path(self, model_dir: Path = DEFAULT_MODEL_DIR) -> Path:
        return model_dir / self.filename


YUNET = ModelFile(
    key="yunet",
    filename="face_detection_yunet_2023mar.onnx",
    purpose="face detection",
    source_url=(
        "https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet"
    ),
    declared_licence="MIT, Copyright (c) 2020 Shiqi Yu (upstream LICENSE read)",
    licence_verified=True,
    expected_sha256="8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
)

SFACE = ModelFile(
    key="sface",
    filename="face_recognition_sface_2021dec.onnx",
    purpose="face embedding",
    source_url=(
        "https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface"
    ),
    declared_licence="Apache-2.0 (upstream LICENSE read)",
    licence_verified=True,
    expected_sha256="0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
)

MODEL_FILES: tuple[ModelFile, ...] = (YUNET, SFACE)


class ModelVerificationError(RuntimeError):
    pass


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(model: ModelFile, model_dir: Path = DEFAULT_MODEL_DIR) -> str:
    """Return the file's digest, raising if it contradicts a recorded pin."""
    path = model.path(model_dir)
    if not path.is_file():
        raise ModelVerificationError(
            f"{model.key}: {path} is missing. Download it from {model.source_url}"
        )
    digest = sha256_of(path)
    if model.expected_sha256 and digest != model.expected_sha256:
        raise ModelVerificationError(
            f"{model.key}: {path} has digest {digest}, expected {model.expected_sha256}"
        )
    return digest


def status_report(model_dir: Path = DEFAULT_MODEL_DIR) -> list[dict[str, object]]:
    report: list[dict[str, object]] = []
    for model in MODEL_FILES:
        path = model.path(model_dir)
        entry: dict[str, object] = {
            "key": model.key,
            "path": str(path),
            "present": path.is_file(),
            "pinned": model.expected_sha256 is not None,
            "declaredLicence": model.declared_licence,
            "licenceVerified": model.licence_verified,
        }
        if path.is_file():
            entry["sha256"] = sha256_of(path)
            entry["matchesPin"] = (
                model.expected_sha256 is None or entry["sha256"] == model.expected_sha256
            )
        report.append(entry)
    return report
