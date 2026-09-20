#!/usr/bin/env python3
"""Verify an official programme recording independently of the browser; back it up.

v3 plan Stage 5 (D): independently play the official recording and make a
permitted backup copy. The browser that wrote the file is not an independent
check of it, so this decodes the file end to end with ffmpeg, reports what is
really inside (codecs, decoded lengths of picture and sound, decode errors),
checksums it, and can copy it to a backup location with a manifest. WebM from
MediaRecorder often has no duration in its header, so the decoded lengths are
what count here, not the header.

    python scripts/verify_recording.py programme.webm --min-seconds 120
        [--backup /Volumes/backup/cue] [--mp4 derived.mp4] [--json | --markdown]

Exit 0 when every check passes, 1 when a check fails, 2 when the file cannot be read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

PROGRAM_WIDTH, PROGRAM_HEIGHT = 1280, 720
LENGTH_AGREEMENT_S = 0.5
MAX_ERROR_LINES = 20


class RecordingError(RuntimeError):
    pass


def _require(tool: str) -> None:
    if shutil.which(tool) is None:
        raise RecordingError(f"{tool} is not on PATH")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def probe(path: Path) -> dict:
    _require("ffprobe")
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RecordingError(result.stderr.strip() or "ffprobe could not read the file")
    return json.loads(result.stdout)


def decode_through(path: Path, kind: str) -> dict:
    """Decode one stream ("v" or "a") to nothing; report decoded length, frames and errors."""
    _require("ffmpeg")
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostats",
            "-progress",
            "pipe:1",
            "-i",
            str(path),
            "-map",
            f"0:{kind}:0",
            "-fps_mode",
            "passthrough",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    seconds: float | None = None
    frames: int | None = None
    for line in result.stdout.splitlines():
        key, _, value = line.partition("=")
        if key == "out_time_us" and value.strip().lstrip("-").isdigit():
            seconds = int(value) / 1_000_000
        elif key == "frame" and value.strip().isdigit():
            frames = int(value)
    errors = [line for line in result.stderr.splitlines() if line.strip()]
    if result.returncode != 0 and not errors:
        errors.append(f"ffmpeg exited {result.returncode}")
    return {
        "seconds": seconds,
        "frames": frames if kind == "v" else None,
        "errors": errors[:MAX_ERROR_LINES],
        "errorCount": len(errors),
    }


def _stream(info: dict, codec_type: str) -> dict | None:
    for stream in info.get("streams", []):
        if stream.get("codec_type") == codec_type:
            return stream
    return None


def _float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def verify(path: Path, min_seconds: float | None = None) -> dict:
    if not path.is_file():
        raise RecordingError(f"not a file: {path}")
    info = probe(path)
    video = _stream(info, "video")
    audio = _stream(info, "audio")
    fmt = info.get("format", {})
    decoded_video = decode_through(path, "v") if video else None
    decoded_audio = decode_through(path, "a") if audio else None

    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "status": "pass" if ok else "fail", "detail": detail})

    check("video stream", video is not None, video["codec_name"] if video else "none")
    check(
        "audio stream",
        audio is not None,
        audio["codec_name"] if audio else "none (master audio missing)",
    )
    if video:
        width, height = video.get("width"), video.get("height")
        check(
            "programme resolution",
            (width, height) == (PROGRAM_WIDTH, PROGRAM_HEIGHT),
            f"{width}x{height} (expected {PROGRAM_WIDTH}x{PROGRAM_HEIGHT})",
        )
    for label, decoded in (
        ("video decodes cleanly", decoded_video),
        ("audio decodes cleanly", decoded_audio),
    ):
        if decoded is not None:
            check(
                label,
                decoded["errorCount"] == 0,
                "no decode errors"
                if decoded["errorCount"] == 0
                else f"{decoded['errorCount']} error line(s): {decoded['errors'][0]}",
            )
    video_s = decoded_video["seconds"] if decoded_video else None
    audio_s = decoded_audio["seconds"] if decoded_audio else None
    if video_s is not None and audio_s is not None:
        delta = abs(video_s - audio_s)
        check(
            "picture and sound lengths agree",
            delta <= LENGTH_AGREEMENT_S,
            f"video {video_s:.2f} s, audio {audio_s:.2f} s, difference {delta:.2f} s "
            f"(limit {LENGTH_AGREEMENT_S} s)",
        )
    length_s = max((value for value in (video_s, audio_s) if value is not None), default=None)
    if min_seconds is not None:
        check(
            "minimum length",
            length_s is not None and length_s >= min_seconds,
            f"{length_s:.2f} s decoded (required {min_seconds:.0f} s)"
            if length_s is not None
            else "nothing decoded",
        )

    verdict = "pass" if all(item["status"] == "pass" for item in checks) else "fail"
    return {
        "file": str(path),
        "bytes": path.stat().st_size,
        "sha256": sha256_of(path),
        "container": fmt.get("format_name"),
        "headerDurationS": _float(fmt.get("duration")),
        "video": {
            "codec": video.get("codec_name"),
            "width": video.get("width"),
            "height": video.get("height"),
            "frameRate": video.get("r_frame_rate"),
        }
        if video
        else None,
        "audio": {
            "codec": audio.get("codec_name"),
            "sampleRate": audio.get("sample_rate"),
            "channels": audio.get("channels"),
        }
        if audio
        else None,
        "decoded": {"video": decoded_video, "audio": decoded_audio, "lengthS": length_s},
        "checks": checks,
        "verdict": verdict,
        "note": "WebM does not open in QuickTime; play it in VLC or Chrome for the human check.",
    }


def git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False, timeout=5
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() or None if result.returncode == 0 else None


def backup(path: Path, directory: Path, report: dict) -> dict:
    """Copy the recording byte for byte, prove the copy matches, and write a manifest beside it."""
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / path.name
    if target.exists() and target.resolve() == path.resolve():
        raise RecordingError("backup directory contains the source itself")
    shutil.copy2(path, target)
    copy_sha = sha256_of(target)
    if copy_sha != report["sha256"]:
        raise RecordingError(f"backup checksum mismatch: {copy_sha} != {report['sha256']}")
    manifest = {
        "source": str(path.resolve()),
        "backup": str(target.resolve()),
        "bytes": report["bytes"],
        "sha256": report["sha256"],
        "copiedAt": datetime.now(UTC).isoformat(),
        "container": report["container"],
        "video": report["video"],
        "audio": report["audio"],
        "decodedLengthS": report["decoded"]["lengthS"],
        "verdict": report["verdict"],
        "gitCommit": git_commit(),
    }
    manifest_path = directory / f"{path.name}.manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return {"backup": str(target), "manifest": str(manifest_path), "sha256Matches": True}


def derive_mp4(path: Path, out: Path) -> dict:
    """A derived H.264/AAC copy for players that do not open WebM. Not the official recording."""
    _require("ffmpeg")
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(path),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-movflags",
            "+faststart",
            str(out),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RecordingError(result.stderr.strip() or "mp4 derivation failed")
    info = probe(out)
    video = _stream(info, "video")
    audio = _stream(info, "audio")
    return {
        "mp4": str(out),
        "bytes": out.stat().st_size,
        "sha256": sha256_of(out),
        "video": video.get("codec_name") if video else None,
        "audio": audio.get("codec_name") if audio else None,
        "derived": True,
    }


def render_markdown(report: dict, extra: dict | None = None) -> str:
    lines = [
        f"| File | `{Path(report['file']).name}` |",
        "|---|---|",
        f"| Size | {report['bytes'] / 1_048_576:.2f} MB |",
        f"| SHA-256 | `{report['sha256']}` |",
        f"| Container | {report['container']} |",
    ]
    if report["video"]:
        video = report["video"]
        lines.append(
            f"| Video | {video['codec']} {video['width']}x{video['height']}"
            f" @ {video['frameRate']} |"
        )
    if report["audio"]:
        audio = report["audio"]
        lines.append(
            f"| Audio | {audio['codec']} {audio['sampleRate']} Hz, {audio['channels']} ch |"
        )
    decoded = report["decoded"]
    if decoded["video"]:
        seconds = decoded["video"]["seconds"]
        lines.append(
            f"| Decoded video | {seconds:.2f} s, {decoded['video']['frames']} frames |"
            if seconds is not None
            else "| Decoded video | not decoded |"
        )
    if decoded["audio"]:
        seconds = decoded["audio"]["seconds"]
        lines.append(
            f"| Decoded audio | {seconds:.2f} s |"
            if seconds is not None
            else "| Decoded audio | not decoded |"
        )
    for item in report["checks"]:
        lines.append(f"| {item['name']} | {item['status'].upper()}: {item['detail']} |")
    lines.append(f"| Verdict | **{report['verdict'].upper()}** |")
    for key, value in (extra or {}).items():
        lines.append(f"| {key} | {value} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("recording")
    parser.add_argument("--min-seconds", type=float, default=None, help="fail if shorter")
    parser.add_argument("--backup", type=Path, default=None, help="directory for the verified copy")
    parser.add_argument(
        "--mp4", type=Path, default=None, help="write a derived H.264/AAC copy here"
    )
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true")
    output.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = verify(Path(args.recording), args.min_seconds)
        extra: dict = {}
        if args.backup is not None:
            extra["Backup"] = backup(Path(args.recording), args.backup, report)
        if args.mp4 is not None:
            extra["Derived MP4"] = derive_mp4(Path(args.recording), args.mp4)
    except RecordingError as error:
        print(f"verify_recording: {error}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({**report, **extra}, indent=2))
    elif args.markdown:
        flat = {key: f"`{value.get('backup') or value.get('mp4')}`" for key, value in extra.items()}
        print(render_markdown(report, flat))
    else:
        for item in report["checks"]:
            print(f"  {item['status'].upper():4} {item['name']}: {item['detail']}")
        print(f"  sha256 {report['sha256']}")
        for key, value in extra.items():
            print(f"  {key}: {json.dumps(value)}")
        print(f"  verdict: {report['verdict']}  ({report['note']})")
    return 0 if report["verdict"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
