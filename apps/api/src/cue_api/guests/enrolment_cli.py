"""`cue-guests` — model checks, enrolment and deletion from the terminal.

Enrolment runs on the machine that holds the reference photo. The photo stays
there: only the embedding is sent, and only after a person has recorded consent.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from cue_api.guests.backend_client import BackendError, GuestBackendClient
from cue_api.guests.capture_quality import QualityPolicy, assess
from cue_api.guests.face_models import DEFAULT_MODEL_DIR, MODEL_FILES, status_report
from cue_api.guests.types import DecodedFrame

CONSENT_PROMPT = (
    "Consent recorded for: live identification during this event, local recording and "
    "cloud media relay. References are held in memory on the director Mac only and are "
    "deleted at event end or on request."
)


def _models_command(args: argparse.Namespace) -> int:
    report = status_report(Path(args.model_dir))
    print(json.dumps(report, indent=2))
    missing = [entry for entry in report if not entry["present"]]
    unpinned = [entry for entry in report if entry["present"] and not entry["pinned"]]
    mismatched = [entry for entry in report if entry.get("matchesPin") is False]

    for model in MODEL_FILES:
        if not model.licence_verified:
            print(
                f"note: {model.key} licence is recorded as "
                f"'{model.declared_licence}' but not yet verified against the download",
                file=sys.stderr,
            )
    if unpinned:
        print(
            "note: paste these sha256 values into cue_api/guests/face_models.py and "
            "docs/b-stage-0.md to pin them",
            file=sys.stderr,
        )
    if missing:
        print(f"error: {len(missing)} model file(s) missing", file=sys.stderr)
        return 1
    return 2 if mismatched else 0


def _load_reference(image_path: Path, model_dir: Path) -> tuple[list[float], float]:
    """Detect, quality-check and embed one reference photo."""
    import cv2  # noqa: PLC0415 - enrolment is the one CLI path that needs OpenCV

    from cue_api.guests.adapters.opencv_models import SFaceEmbedder, YuNetDetector

    image = cv2.imread(str(image_path))
    if image is None:
        raise ValueError(f"{image_path} could not be read as an image")

    height, width = image.shape[:2]
    frame = DecodedFrame(
        camera_id="ENROLMENT",
        stream_epoch=1,
        sequence=0,
        width=width,
        height=height,
        received_at_ms=int(time.time() * 1000),
        image=image,
    )

    detector = YuNetDetector(model_dir)
    detections = detector.detect(frame)
    if not detections:
        raise ValueError(f"{image_path}: no face detected")
    if len(detections) > 1:
        raise ValueError(
            f"{image_path}: {len(detections)} faces detected; a reference must be unambiguous"
        )

    verdict = assess(frame, detections[0], QualityPolicy())
    if not verdict.passed:
        raise ValueError(f"{image_path}: quality gate failed ({', '.join(verdict.failed_checks)})")

    embedder = SFaceEmbedder(model_dir)
    embedding = embedder.embed(frame, detections[0])
    return [float(value) for value in embedding], verdict.score


def _enrol_command(args: argparse.Namespace) -> int:
    print(CONSENT_PROMPT)
    if not args.consent_confirmed:
        print(
            "error: rerun with --consent-confirmed only after the guest has agreed out loud",
            file=sys.stderr,
        )
        return 1

    model_dir = Path(args.model_dir)
    references: list[tuple[list[float], float]] = []
    for image_path in args.images:
        try:
            references.append(_load_reference(Path(image_path), model_dir))
        except ValueError as error:
            print(f"error: {error}", file=sys.stderr)
            return 1

    client = GuestBackendClient(args.api, args.secret)
    try:
        guest = client.enrol_guest(
            event_id=args.event,
            display_name=args.name,
            consent_purposes=["LIVE_IDENTIFICATION", "RECORDING", "CLOUD_RELAY"],
            recorded_by=args.recorded_by,
            aliases=args.alias,
            guest_id=args.guest_id,
        )
        guest_id = str(guest["guestId"])
        record = guest
        for embedding, quality in references:
            record = client.add_reference(
                event_id=args.event,
                guest_id=guest_id,
                embedding=embedding,
                quality=quality,
                embedder="opencv-sface",
                embedder_version="2021dec",
                captured_at_ms=int(time.time() * 1000),
            )
    except BackendError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(json.dumps(record, indent=2))
    return 0


def _gallery_command(args: argparse.Namespace) -> int:
    client = GuestBackendClient(args.api, args.secret)
    try:
        print(json.dumps(client.list_guests(args.event), indent=2))
    except BackendError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


def _forget_command(args: argparse.Namespace) -> int:
    client = GuestBackendClient(args.api, args.secret)
    try:
        if args.guest_id:
            receipt = client.withdraw(event_id=args.event, guest_id=args.guest_id)
        else:
            receipt = client.purge_event(args.event)
    except BackendError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, indent=2))
    return 0


def _evaluate_command(args: argparse.Namespace) -> int:
    """Tally trials a human actually ran into the identity report's numbers.

    Exits non-zero when the run does not support a claim, so a green terminal
    can never be mistaken for measured accuracy.
    """
    from cue_api.guests.identity_eval import (
        InsufficientEvidence,
        LabelledPair,
        NegativeTrial,
        PositiveTrial,
        recommend_accept_similarity,
        summarise,
        summary_lines,
    )

    document = json.loads(Path(args.trials).read_text("utf-8"))
    positives = [
        PositiveTrial(
            guest_id=row["guestId"],
            named_guest_id=row.get("namedGuestId"),
            status=row.get("status", ""),
            ms_to_confirmed=row.get("msToConfirmed"),
        )
        for row in document.get("positives", [])
    ]
    negatives = [
        NegativeTrial(
            subject=row["subject"],
            named_guest_id=row.get("namedGuestId"),
            status=row.get("status", ""),
        )
        for row in document.get("negatives", [])
    ]

    report = summarise(positives, negatives)
    for line in summary_lines(report):
        print(line)

    pairs = [
        LabelledPair(similarity=float(row["similarity"]), same_person=bool(row["samePerson"]))
        for row in document.get("pairs", [])
    ]
    if pairs:
        print()
        try:
            recommendation = recommend_accept_similarity(pairs)
        except InsufficientEvidence as error:
            print(f"threshold:    not recommended - {error}")
        else:
            print(
                f"threshold:    {recommendation.accept_similarity:.4f} "
                f"(worst stranger {recommendation.highest_negative_similarity:.4f}, "
                f"measured on {recommendation.positives_measured} positive / "
                f"{recommendation.negatives_measured} negative pairs)"
            )
            print(f"              {recommendation.note}")

    if not report.claimable:
        print()
        print("This run does not support an accuracy claim.", file=sys.stderr)
        return 1
    return 0


def _calibrate_command(args: argparse.Namespace) -> int:
    """Fit a MEASURED calibration from labelled pairs and write it to disk.

    Refuses a one-sided sample, the same way the fitter does, so nothing on disk
    can claim a measurement that the pairs do not support.
    """
    from cue_api.guests.calibration_store import CalibrationFileError, save
    from cue_api.guests.confidence_calibration import Calibration

    document = json.loads(Path(args.pairs).read_text("utf-8"))
    labelled = [
        (float(row["similarity"]), bool(row["samePerson"])) for row in document.get("pairs", [])
    ]
    if not labelled:
        print("error: no labelled pairs in the file", file=sys.stderr)
        return 1

    try:
        calibration = Calibration.fit(labelled, calibration_id=args.calibration_id)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    try:
        stored = save(calibration, Path(args.out), dataset_note=args.dataset_note)
    except CalibrationFileError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    positives = sum(1 for _, same in labelled if same)
    print(f"fitted:       {stored.calibration.calibration_id}")
    print(f"status:       {stored.calibration.status.value}")
    print(f"samples:      {stored.calibration.sample_count} "
          f"({positives} positive / {len(labelled) - positives} negative)")
    print(f"written to:   {args.out}")
    print(f"dataset:      {stored.dataset_note}")
    return 0


def _trials_command(args: argparse.Namespace) -> int:
    """Score labelled capture files into the document `evaluate` reads.

    Filenames carry the labels: a positive is passed as guestId=path, a negative
    as a bare path. Nothing here infers who is in a photograph.
    """
    import cv2  # noqa: PLC0415 - scoring real captures needs OpenCV

    from cue_api.guests.adapters.opencv_models import SFaceEmbedder, YuNetDetector
    from cue_api.guests.backend_client import GuestBackendClient
    from cue_api.guests.trial_runner import Capture, run_captures
    from cue_api.guests.types import DecodedFrame

    model_dir = Path(args.model_dir)
    detector = YuNetDetector(model_dir=model_dir)
    embedder = SFaceEmbedder(model_dir=model_dir)
    gallery = GuestBackendClient(args.api, args.secret).fetch_gallery(args.event)

    captures: list[Capture] = []
    for entry in args.positive:
        guest_id, _, image_path = entry.partition("=")
        if not guest_id or not image_path:
            print(f"error: --positive expects guestId=path, received {entry!r}", file=sys.stderr)
            return 1
        captures.append(_load_capture(cv2, DecodedFrame, Capture, image_path, guest_id))
    for image_path in args.negative:
        captures.append(_load_capture(cv2, DecodedFrame, Capture, image_path, None))

    if not captures:
        print("error: no captures given", file=sys.stderr)
        return 1

    results = run_captures(captures, gallery, detector, embedder)
    document = json.dumps(results.to_document(), indent=2) + chr(10)
    Path(args.out).write_text(document, "utf-8")

    print(f"positives:    {len(results.positives)}")
    print(f"negatives:    {len(results.negatives)}")
    print(f"pairs:        {len(results.pairs)}")
    print(f"skipped:      {len(results.skipped)}")
    for skip in results.skipped:
        print(f"              {skip.label}: {skip.reason}")
    print(f"written to:   {args.out}")
    print()
    print(f"next: cue-guests evaluate --trials {args.out}")
    return 0


def _load_capture(cv2, decoded_frame, capture_type, image_path: str, guest_id: str | None):
    image = cv2.imread(image_path)
    if image is None:
        raise SystemExit(f"error: cannot read {image_path}")
    height, width = image.shape[:2]
    frame = decoded_frame(
        camera_id="CAM-GUEST",
        stream_epoch=1,
        sequence=0,
        width=width,
        height=height,
        received_at_ms=int(time.time() * 1000),
        image=image,
    )
    return capture_type(label=Path(image_path).name, frame=frame, guest_id=guest_id)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cue-guests", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    models = subparsers.add_parser("models", help="check model files, licences and checksums")
    models.add_argument("--model-dir", default=str(DEFAULT_MODEL_DIR))
    models.set_defaults(handler=_models_command)

    def add_backend_arguments(target: argparse.ArgumentParser) -> None:
        target.add_argument("--api", required=True, help="director API base URL")
        target.add_argument("--secret", required=True, help="operator credential")
        target.add_argument("--event", required=True, help="event ID")

    enrol = subparsers.add_parser("enrol", help="enrol one consenting guest from reference photos")
    add_backend_arguments(enrol)
    enrol.add_argument("--name", required=True)
    enrol.add_argument("--alias", action="append", default=[])
    enrol.add_argument("--guest-id")
    enrol.add_argument("--recorded-by", default="B")
    enrol.add_argument("--model-dir", default=str(DEFAULT_MODEL_DIR))
    enrol.add_argument("--consent-confirmed", action="store_true")
    enrol.add_argument("images", nargs="+", help="reference photos; they are never uploaded")
    enrol.set_defaults(handler=_enrol_command)

    gallery = subparsers.add_parser("gallery", help="list enrolled guests (no embeddings)")
    add_backend_arguments(gallery)
    gallery.set_defaults(handler=_gallery_command)

    forget = subparsers.add_parser("forget", help="withdraw one guest, or purge the whole event")
    add_backend_arguments(forget)
    forget.add_argument("--guest-id", help="omit to purge every guest for the event")
    forget.set_defaults(handler=_forget_command)

    evaluate = subparsers.add_parser(
        "evaluate", help="tally identity trials into the report's numbers"
    )
    evaluate.add_argument(
        "--trials",
        required=True,
        help="JSON with positives/negatives, and optional labelled similarity pairs",
    )
    evaluate.set_defaults(handler=_evaluate_command)

    calibrate = subparsers.add_parser(
        "calibrate", help="fit a MEASURED calibration from labelled pairs"
    )
    calibrate.add_argument("--pairs", required=True, help="JSON with labelled similarity pairs")
    calibrate.add_argument("--out", default="calibration.json")
    calibrate.add_argument("--calibration-id", required=True)
    calibrate.add_argument(
        "--dataset-note", required=True, help="where the held-out pairs came from"
    )
    calibrate.set_defaults(handler=_calibrate_command)

    trials = subparsers.add_parser(
        "trials", help="score labelled capture files into a trials document"
    )
    add_backend_arguments(trials)
    trials.add_argument("--model-dir", default=str(DEFAULT_MODEL_DIR))
    trials.add_argument(
        "--positive", action="append", default=[], metavar="GUEST_ID=PATH",
        help="a capture of an enrolled guest; repeatable",
    )
    trials.add_argument(
        "--negative", action="append", default=[], metavar="PATH",
        help="a capture of someone who never enrolled; repeatable",
    )
    trials.add_argument("--out", default="trials.json")
    trials.set_defaults(handler=_trials_command)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler = args.handler
    return int(handler(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
