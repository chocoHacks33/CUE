"""Exit codes for the identity commands.

These matter more than the printed text: the whole point of `evaluate` refusing a
run is that a script, or a tired person at 3am, cannot mistake it for a pass.
Anything that shells out to these commands relies on the exit code alone.
"""

from __future__ import annotations

import json
from pathlib import Path

from cue_api.guests.enrolment_cli import main


def write(path: Path, document: dict) -> str:
    path.write_text(json.dumps(document), encoding="utf-8")
    return str(path)


def clean_run(positives: int = 30, negatives: int = 30) -> dict:
    return {
        "positives": [
            {
                "guestId": "guest-sarah",
                "namedGuestId": "guest-sarah",
                "status": "CONFIRMED",
                "msToConfirmed": 600,
            }
            for _ in range(positives)
        ],
        "negatives": [
            {"subject": f"unenrolled-{index}", "namedGuestId": None, "status": "UNKNOWN"}
            for index in range(negatives)
        ],
    }


def test_a_claimable_run_exits_zero(tmp_path: Path) -> None:
    trials = write(tmp_path / "trials.json", clean_run())

    assert main(["evaluate", "--trials", trials]) == 0


def test_a_short_run_exits_non_zero(tmp_path: Path) -> None:
    trials = write(tmp_path / "trials.json", clean_run(positives=3, negatives=3))

    assert main(["evaluate", "--trials", trials]) == 1


def test_a_run_with_a_wrong_name_exits_non_zero(tmp_path: Path) -> None:
    """The safety case: everything else looks perfect."""
    document = clean_run()
    document["negatives"][0]["namedGuestId"] = "guest-sarah"
    document["negatives"][0]["status"] = "CONFIRMED"
    trials = write(tmp_path / "trials.json", document)

    assert main(["evaluate", "--trials", trials]) == 1


def test_a_run_without_strangers_exits_non_zero(tmp_path: Path) -> None:
    trials = write(tmp_path / "trials.json", clean_run(negatives=0))

    assert main(["evaluate", "--trials", trials]) == 1


def test_calibrating_a_one_sided_sample_exits_non_zero(tmp_path: Path) -> None:
    pairs = write(
        tmp_path / "pairs.json",
        {"pairs": [{"similarity": 0.9, "samePerson": True} for _ in range(40)]},
    )
    out = tmp_path / "calibration.json"

    assert (
        main(
            [
                "calibrate",
                "--pairs",
                pairs,
                "--out",
                str(out),
                "--calibration-id",
                "one-sided",
                "--dataset-note",
                "positives only",
            ]
        )
        == 1
    )
    assert not out.exists()


def test_calibrating_a_two_sided_sample_writes_a_measured_file(tmp_path: Path) -> None:
    rows = [{"similarity": 0.70 + index * 0.01, "samePerson": True} for index in range(20)]
    rows += [{"similarity": 0.05 + index * 0.01, "samePerson": False} for index in range(20)]
    pairs = write(tmp_path / "pairs.json", {"pairs": rows})
    out = tmp_path / "calibration.json"

    assert (
        main(
            [
                "calibrate",
                "--pairs",
                pairs,
                "--out",
                str(out),
                "--calibration-id",
                "held-out-test",
                "--dataset-note",
                "20 positive / 20 negative",
            ]
        )
        == 0
    )

    from cue_api.guests.calibration_store import load

    stored = load(out)
    assert stored.calibration.status.value == "MEASURED"
    assert stored.calibration.sample_count == 40


def test_calibrating_an_empty_file_exits_non_zero(tmp_path: Path) -> None:
    pairs = write(tmp_path / "pairs.json", {"pairs": []})

    assert (
        main(
            [
                "calibrate",
                "--pairs",
                pairs,
                "--out",
                str(tmp_path / "c.json"),
                "--calibration-id",
                "empty",
                "--dataset-note",
                "nothing",
            ]
        )
        == 1
    )
