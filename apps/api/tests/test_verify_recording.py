"""scripts/verify_recording.py against synthetic WebM clips rendered by ffmpeg.

The clips are generated here, so the test proves the verifier reads codecs and
decoded lengths correctly and notices a truncated file. It says nothing about
any real programme recording.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPTS = REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import verify_recording  # noqa: E402


def _encoders() -> str:
    if shutil.which("ffmpeg") is None:
        return ""
    return subprocess.run(
        ["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True, check=False
    ).stdout


ENCODERS = _encoders()
pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or " libvpx " not in ENCODERS or " libopus " not in ENCODERS,
    reason="ffmpeg with libvpx and libopus is needed to render a WebM like the recorder's",
)


def make_webm(path: Path, seconds: float = 3.0, size: str = "1280x720") -> Path:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=s={size}:r=30:d={seconds}",
            "-f",
            "lavfi",
            "-i",
            f"sine=f=440:d={seconds}",
            "-c:v",
            "libvpx",
            "-b:v",
            "400k",
            "-c:a",
            "libopus",
            "-b:a",
            "64k",
            str(path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    return path


def test_good_clip_reports_codecs_lengths_and_passes(tmp_path: Path):
    clip = make_webm(tmp_path / "programme.webm")
    report = verify_recording.verify(clip, min_seconds=2.0)
    assert report["video"]["codec"] == "vp8"
    assert (report["video"]["width"], report["video"]["height"]) == (1280, 720)
    assert report["audio"]["codec"] == "opus"
    assert abs(report["decoded"]["video"]["seconds"] - 3.0) < 0.2
    assert abs(report["decoded"]["audio"]["seconds"] - 3.0) < 0.2
    assert report["decoded"]["video"]["frames"] == 90
    assert report["decoded"]["video"]["errorCount"] == 0
    assert report["verdict"] == "pass"
    assert len(report["sha256"]) == 64


def test_too_short_fails_the_minimum_length(tmp_path: Path):
    clip = make_webm(tmp_path / "short.webm")
    report = verify_recording.verify(clip, min_seconds=10.0)
    assert report["verdict"] == "fail"
    failed = [item for item in report["checks"] if item["status"] == "fail"]
    assert [item["name"] for item in failed] == ["minimum length"]


def test_wrong_resolution_is_a_failed_check(tmp_path: Path):
    clip = make_webm(tmp_path / "small.webm", size="640x360")
    report = verify_recording.verify(clip)
    resolution = next(item for item in report["checks"] if item["name"] == "programme resolution")
    assert resolution["status"] == "fail"
    assert report["verdict"] == "fail"


def test_truncated_file_does_not_pass(tmp_path: Path):
    clip = make_webm(tmp_path / "cut.webm")
    data = clip.read_bytes()
    clip.write_bytes(data[: int(len(data) * 0.6)])
    report = verify_recording.verify(clip, min_seconds=2.9)
    assert report["verdict"] == "fail"
    assert report["decoded"]["lengthS"] is None or report["decoded"]["lengthS"] < 2.9


def test_backup_copy_matches_and_writes_a_manifest(tmp_path: Path):
    clip = make_webm(tmp_path / "official.webm")
    report = verify_recording.verify(clip)
    result = verify_recording.backup(clip, tmp_path / "backup", report)
    copied = Path(result["backup"])
    assert copied.read_bytes() == clip.read_bytes()
    manifest = json.loads(Path(result["manifest"]).read_text())
    assert manifest["sha256"] == report["sha256"]
    assert manifest["bytes"] == clip.stat().st_size
    assert manifest["video"]["codec"] == "vp8"


@pytest.mark.skipif(" libx264 " not in ENCODERS, reason="libx264 not available")
def test_derived_mp4_is_h264_aac_and_labelled_derived(tmp_path: Path):
    clip = make_webm(tmp_path / "official.webm")
    result = verify_recording.derive_mp4(clip, tmp_path / "derived.mp4")
    assert result["video"] == "h264"
    assert result["audio"] == "aac"
    assert result["derived"] is True


def test_markdown_and_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    clip = make_webm(tmp_path / "programme.webm")
    report = verify_recording.verify(clip)
    text = verify_recording.render_markdown(report, {"Backup": "`/private/backup`"})
    assert report["sha256"] in text and "**PASS**" in text and "/private/backup" in text
    assert verify_recording.main([str(clip), "--min-seconds", "2", "--json"]) == 0
    assert '"verdict": "pass"' in capsys.readouterr().out
    assert verify_recording.main([str(clip), "--min-seconds", "10"]) == 1
    assert verify_recording.main([str(tmp_path / "missing.webm")]) == 2
