"""The OpenCV adapters, executed for real.

Every other vision test in this suite uses scripted stand-ins. These are the only
tests that load the actual ONNX weights and run YuNet and SFace, which is why
they exist: the adapters were written against OpenCV's documented API and, until
these ran, had never executed.

Both gates are deliberate. CI installs `apps/api[dev]` without the OpenCV extra,
and model weights are never committed, so these skip rather than fail there. A
skip here means "not verified on this machine", not "passed".
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from cue_api.contracts import CameraId
from cue_api.guests.face_models import MODEL_FILES, SFACE, YUNET, verify
from cue_api.guests.frame_intake import WorkerClock, adapt
from cue_api.guests.types import FaceDetection, PixelBox
from cue_api.media_contracts import DecodedVideoFrame, PixelFormat

numpy = pytest.importorskip("numpy", reason="needs apps/api[opencv]")
pytest.importorskip("cv2", reason="needs apps/api[opencv]")

MODEL_DIR = Path(__file__).resolve().parents[1] / "models"

pytestmark = pytest.mark.skipif(
    not all(model.path(MODEL_DIR).exists() for model in MODEL_FILES),
    reason="model weights are not downloaded on this machine",
)

CLOCK = WorkerClock(wall_reference_ms=0, monotonic_reference_s=0.0)


def known_image(width: int, height: int):
    """A BGR image whose every pixel value is a function of its position."""
    image = numpy.zeros((height, width, 3), dtype=numpy.uint8)
    for y in range(height):
        for x in range(width):
            image[y, x] = ((10 * y + x) % 256, (100 + 10 * y + x) % 256, (200 + x) % 256)
    return image


def frame_from(image, *, stride_bytes: int | None = None) -> DecodedVideoFrame:
    height, width, _ = image.shape
    packed = width * 3
    stride = packed if stride_bytes is None else stride_bytes
    rows = [image[y].tobytes() + b"\xee" * (stride - packed) for y in range(height)]
    return DecodedVideoFrame(
        event_id="hackmit-demo",
        camera_id=CameraId.GUEST,
        stream_epoch=1,
        track_sid="TR_guest_1",
        sequence=0,
        width=width,
        height=height,
        stride_bytes=stride,
        pixel_format=PixelFormat.BGR24,
        orientation_degrees=0,
        mirrored=False,
        received_at_monotonic_s=1.0,
        capture_time_s=None,
        data=b"".join(rows),
    )


# -- the weights themselves -------------------------------------------------


def test_the_downloaded_weights_match_their_pins() -> None:
    """The pins describe the files on disk, not a value copied from a README."""
    for model in MODEL_FILES:
        assert verify(model, MODEL_DIR) == model.expected_sha256


# -- the payload conversion, with real numpy -------------------------------


def test_an_unpadded_payload_reconstructs_the_exact_pixels() -> None:
    from cue_api.guests.adapters.opencv_models import _payload_to_array

    image = known_image(8, 5)
    adapted = adapt(frame_from(image), CLOCK)

    assert numpy.array_equal(_payload_to_array(adapted.image), image)


def test_a_padded_payload_reconstructs_the_exact_pixels() -> None:
    """If stride handling were wrong the image would skew, and a skewed face
    still detects, so this is the failure that would be hardest to notice."""
    from cue_api.guests.adapters.opencv_models import _payload_to_array

    image = known_image(8, 5)
    adapted = adapt(frame_from(image, stride_bytes=8 * 3 + 7), CLOCK)

    assert numpy.array_equal(_payload_to_array(adapted.image), image)


def test_the_array_handed_to_opencv_is_writable_and_contiguous() -> None:
    """OpenCV writes into the buffers it is given during alignment."""
    from cue_api.guests.adapters.opencv_models import _payload_to_array

    array = _payload_to_array(adapt(frame_from(known_image(8, 5)), CLOCK).image)

    assert array.flags.writeable
    assert array.flags.c_contiguous
    assert array.dtype == numpy.uint8
    assert array.shape == (5, 8, 3)


# -- YuNet ------------------------------------------------------------------


def test_the_detector_loads_the_real_model() -> None:
    from cue_api.guests.adapters.opencv_models import YuNetDetector

    detector = YuNetDetector(model_dir=MODEL_DIR)

    assert detector.name == "opencv-yunet"
    assert detector.version == "2023mar"


def test_the_detector_finds_no_face_in_a_frame_without_one() -> None:
    from cue_api.guests.adapters.opencv_models import YuNetDetector

    detector = YuNetDetector(model_dir=MODEL_DIR)
    flat = numpy.full((480, 640, 3), 96, dtype=numpy.uint8)

    assert detector.detect(adapt(frame_from(flat), CLOCK)) == []


def test_the_detector_accepts_a_change_of_frame_size() -> None:
    """`setInputSize` is stateful on the OpenCV object; two sizes in a row must work."""
    from cue_api.guests.adapters.opencv_models import YuNetDetector

    detector = YuNetDetector(model_dir=MODEL_DIR)

    detector.detect(adapt(frame_from(numpy.full((480, 640, 3), 96, numpy.uint8)), CLOCK))
    detector.detect(adapt(frame_from(numpy.full((720, 1280, 3), 96, numpy.uint8)), CLOCK))


# -- SFace ------------------------------------------------------------------


def test_the_embedder_returns_a_unit_vector() -> None:
    """The footgun this guards: `cosine_similarity` is a plain dot product, so an
    unnormalised embedding would inflate every similarity and name everybody.
    Measured raw norm from this build is about 3.9."""
    from cue_api.guests.adapters.opencv_models import SFaceEmbedder

    embedder = SFaceEmbedder(model_dir=MODEL_DIR)
    image = numpy.full((480, 640, 3), 110, dtype=numpy.uint8)
    detection = FaceDetection(
        box=PixelBox(x=220, y=140, width=200, height=200),
        score=0.9,
        sharpness=0.8,
        brightness=0.5,
        landmarks=((280, 200), (360, 200), (320, 250), (285, 290), (355, 290)),
    )

    embedding = embedder.embed(adapt(frame_from(image), CLOCK), detection)

    assert len(embedding) == 128
    assert numpy.isclose(float(numpy.linalg.norm(numpy.array(embedding))), 1.0, atol=1e-6)


def test_the_embedder_refuses_a_detection_without_five_landmarks() -> None:
    from cue_api.guests.adapters.opencv_models import SFaceEmbedder

    embedder = SFaceEmbedder(model_dir=MODEL_DIR)
    detection = FaceDetection(
        box=PixelBox(x=10, y=10, width=40, height=40),
        score=0.9,
        sharpness=0.8,
        brightness=0.5,
        landmarks=((20, 20), (30, 20)),
    )

    with pytest.raises(ValueError, match="five"):
        embedder.embed(adapt(frame_from(known_image(64, 64)), CLOCK), detection)


def test_a_wrong_digest_stops_the_model_loading_at_all() -> None:
    """The pin is enforced at load time, not merely reported."""
    from cue_api.guests.face_models import ModelVerificationError

    with pytest.raises(ModelVerificationError, match="expected"):
        verify(replace(SFACE, expected_sha256="0" * 64), MODEL_DIR)
    with pytest.raises(ModelVerificationError, match="expected"):
        verify(replace(YUNET, expected_sha256="1" * 64), MODEL_DIR)


# -- the whole path, with real models ---------------------------------------


def drawn_face(*, eye_separation: int = 30):
    """A crude drawn face that YuNet does detect.

    Good enough to prove the path runs end to end. Useless for measuring
    accuracy — see `test_drawn_faces_cannot_serve_as_negatives`.
    """
    import cv2

    image = numpy.full((480, 640, 3), 200, numpy.uint8)
    cv2.ellipse(image, (320, 240), (90, 120), 0, 0, 360, (170, 150, 140), -1)
    for offset in (-eye_separation, eye_separation):
        cv2.ellipse(image, (320 + offset, 210), (14, 9), 0, 0, 360, (255, 255, 255), -1)
        cv2.circle(image, (320 + offset, 210), 6, (40, 30, 25), -1)
    cv2.line(image, (320, 220), (320, 258), (140, 120, 110), 3)
    cv2.ellipse(image, (320, 290), (28, 12), 0, 0, 180, (90, 60, 60), -1)
    return image


def test_yunet_detects_a_drawn_face_with_five_landmarks() -> None:
    from cue_api.guests.adapters.opencv_models import YuNetDetector

    detected = YuNetDetector(model_dir=MODEL_DIR).detect(adapt(frame_from(drawn_face()), CLOCK))

    assert len(detected) == 1
    assert detected[0].score > 0.5
    assert len(detected[0].landmarks) == 5


def test_the_whole_path_confirms_a_named_take_with_real_models() -> None:
    """detect -> quality -> embed -> match -> confirm, no stand-ins anywhere."""
    from cue_api.guests.adapters.opencv_models import SFaceEmbedder, YuNetDetector
    from cue_api.guests.observation_pipeline import VisionPipeline
    from cue_api.guests.reference_gallery import GuestReferences, ReferenceGallery
    from cue_api.guests.types import ObservationStatus

    detector = YuNetDetector(model_dir=MODEL_DIR)
    embedder = SFaceEmbedder(model_dir=MODEL_DIR)
    image = drawn_face()

    enrolment = adapt(frame_from(image), CLOCK)
    reference = embedder.embed(enrolment, detector.detect(enrolment)[0])
    assert numpy.isclose(float(numpy.linalg.norm(numpy.array(reference))), 1.0, atol=1e-6)

    pipeline = VisionPipeline(
        event_id="hackmit-demo",
        detector=detector,
        embedder=embedder,
        gallery=ReferenceGallery(
            version=1,
            guests=(
                GuestReferences(
                    guest_id="guest-sarah",
                    display_name="Sarah",
                    reference_version=1,
                    embeddings=(reference,),
                ),
            ),
        ),
    )

    statuses = []
    for index in range(4):
        adapted = adapt(frame_from(image), CLOCK)
        # Advance the frame in time so the confirmation window is real.
        adapted = replace(
            adapted,
            sequence=index,
            received_at_ms=adapted.received_at_ms + index * 200,
        )
        observations = pipeline.observe(adapted)
        assert len(observations) == 1
        statuses.append(observations[0])

    # One frame is not an identity; three consistent ones are.
    assert statuses[0].status is ObservationStatus.PROVISIONAL
    assert statuses[0].usable_for_named_take is False
    assert statuses[2].status is ObservationStatus.CONFIRMED
    assert statuses[2].guest_id == "guest-sarah"
    assert statuses[2].display_name == "Sarah"
    assert statuses[2].usable_for_named_take is True
    assert statuses[2].calibration_status.value == "PROVISIONAL_DEFAULT"


def test_drawn_faces_cannot_serve_as_negatives() -> None:
    """Records why the thresholds are still unmeasured.

    SFace is trained on photographs. Crude drawings land close together in its
    embedding space, so a drawn face is not a usable stand-in for a different
    person. Every detectable variant tried scored well above the 0.363 accept
    threshold against an unrelated reference. The accept and margin thresholds
    therefore cannot be validated this way and still need real faces on the Mac.
    """
    from cue_api.guests.adapters.opencv_models import SFaceEmbedder, YuNetDetector
    from cue_api.guests.face_matching import MatchThresholds
    from cue_api.guests.reference_gallery import cosine_similarity

    detector = YuNetDetector(model_dir=MODEL_DIR)
    embedder = SFaceEmbedder(model_dir=MODEL_DIR)

    def embed(image):
        adapted = adapt(frame_from(image), CLOCK)
        return embedder.embed(adapted, detector.detect(adapted)[0])

    reference = embed(drawn_face(eye_separation=30))
    different = embed(drawn_face(eye_separation=44))
    similarity = cosine_similarity(reference, different)

    # Two visibly different drawings, and the score is nowhere near separable.
    assert similarity > MatchThresholds().accept_similarity
