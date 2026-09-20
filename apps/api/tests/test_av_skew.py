"""scripts/av_skew.py against synthetic clap-and-flash clips rendered by ffmpeg.

The clips are generated here with known offsets, so the test checks that the
tool recovers a known skew, not that any real recording is in sync.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPTS = REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

np = pytest.importorskip("numpy")
pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not on PATH")

import av_skew  # noqa: E402

# One 30 fps source frame is 33 ms; the analysis samples video at 100 Hz.
TOLERANCE_MS = 35.0


def make_clip(
    path: Path, flashes_s: list[float], claps_s: list[float], duration_s: float = 6.0
) -> Path:
    """Black 320x180 video, 100 ms white flashes, a 1 kHz burst per clap over a faint hum."""
    boxes = ",".join(
        f"drawbox=enable='between(t\\,{start}\\,{start + 0.1})'"
        ":x=0:y=0:w=iw:h=ih:color=white:t=fill"
        for start in flashes_s
    )
    vf = f"{boxes},format=yuv420p" if boxes else "format=yuv420p"
    bursts = "+".join(f"between(t\\,{start}\\,{start + 0.08})" for start in claps_s) or "0"
    expr = f"0.02*sin(2*PI*200*t)+0.8*sin(2*PI*1000*t)*({bursts})"
    command = [
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", f"color=c=black:s=320x180:r=30:d={duration_s}",
        "-f", "lavfi", "-i", f"aevalsrc={expr}:s=16000:d={duration_s}",
        "-vf", vf,
        "-c:v", "mpeg4", "-q:v", "2", "-c:a", "pcm_s16le", "-shortest",
        str(path),
    ]
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return path


def test_recovers_a_known_positive_skew(tmp_path: Path):
    clip = make_clip(tmp_path / "late-audio.mkv", flashes_s=[2.0], claps_s=[2.12])
    report = av_skew.analyse(str(clip), events=1, limit_ms=150.0)
    assert len(report["pairs"]) == 1
    assert abs(report["pairs"][0]["skew_ms"] - 120.0) <= TOLERANCE_MS
    assert report["verdict"] == "pass"


def test_three_events_pair_in_order_and_p95_is_the_worst_pair(tmp_path: Path):
    clip = make_clip(
        tmp_path / "three.mkv",
        flashes_s=[1.0, 2.5, 4.0],
        claps_s=[1.12, 2.42, 4.04],
        duration_s=6.0,
    )
    report = av_skew.analyse(str(clip), events=3, limit_ms=150.0)
    skews = [pair["skew_ms"] for pair in report["pairs"]]
    assert len(skews) == 3
    for measured, expected in zip(skews, [120.0, -80.0, 40.0], strict=True):
        assert abs(measured - expected) <= TOLERANCE_MS
    assert report["abs_skew_ms"]["p95"] == max(abs(value) for value in skews)
    assert report["verdict"] == "pass"
    assert report["warnings"] == []


def test_fails_when_the_skew_exceeds_the_limit(tmp_path: Path):
    clip = make_clip(tmp_path / "bad.mkv", flashes_s=[2.0], claps_s=[2.4])
    report = av_skew.analyse(str(clip), events=1, limit_ms=150.0)
    assert abs(report["pairs"][0]["skew_ms"] - 400.0) <= TOLERANCE_MS
    assert report["verdict"] == "fail"


def test_reports_mismatched_counts_instead_of_inventing_pairs(tmp_path: Path):
    clip = make_clip(tmp_path / "mismatch.mkv", flashes_s=[1.0, 3.0], claps_s=[1.1])
    report = av_skew.analyse(str(clip), events=None, limit_ms=150.0)
    assert len(report["pairs"]) == 1
    assert any("2 flash(es) but 1 clap(s)" in warning for warning in report["warnings"])


def test_no_flash_is_an_error_not_a_measurement(tmp_path: Path):
    clip = make_clip(tmp_path / "noflash.mkv", flashes_s=[], claps_s=[2.0])
    with pytest.raises(av_skew.SkewError, match="no flash found"):
        av_skew.analyse(str(clip), events=1, limit_ms=150.0)


def test_cli_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    clip = make_clip(tmp_path / "cli.mkv", flashes_s=[2.0], claps_s=[2.05])
    assert av_skew.main([str(clip), "--events", "1", "--json"]) == 0
    assert '"verdict": "pass"' in capsys.readouterr().out
    assert av_skew.main([str(tmp_path / "missing.mkv")]) == 2
