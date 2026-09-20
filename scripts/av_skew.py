#!/usr/bin/env python3
"""Measure audio/video skew in a programme recording from clap-and-flash markers.

v3 plan section 9 (D): recorded output p95 absolute skew below 150 ms, clap
tests per angle initially and after 15 minutes. During the recording someone
claps in front of a visible light or phone flash. This script finds each flash
(a step in frame luminance) and each clap (an audio onset), pairs them in order
and reports the skew per pair plus the p95 of the absolute skew. Positive skew
means the audio arrives later than the picture.

Needs ffmpeg on PATH and numpy. It reads what the recorder wrote (WebM from
MediaRecorder, or anything ffmpeg decodes); it does not touch the live path.

    python scripts/av_skew.py programme.webm [--events 3] [--limit-ms 150] [--json]
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass

try:
    import numpy as np
except ImportError:  # pragma: no cover - exercised only on a machine without numpy
    np = None

VIDEO_FPS = 100
AUDIO_RATE = 16000
THUMB_W, THUMB_H = 16, 9
REFRACTORY_S = 0.5
MIN_FLASH_STEP = 20.0  # 8-bit luminance units above the baseline


class SkewError(RuntimeError):
    pass


@dataclass(frozen=True)
class Onset:
    time_s: float
    strength: float


@dataclass(frozen=True)
class Pair:
    flash_s: float
    clap_s: float
    skew_ms: float


def _run_ffmpeg(args: list[str]) -> bytes:
    if shutil.which("ffmpeg") is None:
        raise SkewError("ffmpeg is not on PATH")
    result = subprocess.run(
        ["ffmpeg", "-v", "error", *args, "-"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise SkewError(result.stderr.decode(errors="replace").strip() or "ffmpeg failed")
    return result.stdout


def video_luminance(path: str, fps: int = VIDEO_FPS) -> tuple[np.ndarray, np.ndarray]:
    """Mean 8-bit luminance per output frame at a constant `fps`, plus frame times."""
    raw = _run_ffmpeg(
        [
            "-i", path,
            "-vf", f"fps={fps},scale={THUMB_W}:{THUMB_H}:flags=area,format=gray",
            "-f", "rawvideo", "-pix_fmt", "gray",
        ]
    )
    pixels = THUMB_W * THUMB_H
    frames = len(raw) // pixels
    if frames == 0:
        raise SkewError("no video frames decoded")
    lum = np.frombuffer(raw[: frames * pixels], dtype=np.uint8).reshape(frames, pixels)
    return lum.mean(axis=1).astype(np.float64), np.arange(frames) / fps


def audio_envelope(path: str, rate: int = AUDIO_RATE) -> tuple[np.ndarray, np.ndarray]:
    """Absolute mono sample values in [0, 1] at `rate`, plus sample times."""
    raw = _run_ffmpeg(["-i", path, "-vn", "-ac", "1", "-ar", str(rate), "-f", "s16le"])
    if len(raw) < 2:
        raise SkewError("no audio decoded")
    samples = np.frombuffer(raw[: len(raw) - len(raw) % 2], dtype=np.int16).astype(np.float64)
    env = np.abs(samples) / 32768.0
    return env, np.arange(len(env)) / rate


def onsets(
    signal: np.ndarray, times: np.ndarray, threshold: float, refractory_s: float
) -> list[Onset]:
    """First crossing above `threshold` per burst; bursts closer than `refractory_s` merge."""
    above = np.flatnonzero(signal > threshold)
    found: list[Onset] = []
    last_time = -1e9
    for index in above:
        t = float(times[index])
        if t - last_time < refractory_s:
            continue
        window_end = np.searchsorted(times, t + refractory_s, side="left")
        strength = float(signal[index:window_end].max())
        found.append(Onset(time_s=t, strength=strength))
        last_time = t
    return found


def flash_onsets(lum: np.ndarray, times: np.ndarray) -> list[Onset]:
    baseline = float(np.median(lum))
    peak = float(lum.max())
    if peak - baseline < MIN_FLASH_STEP:
        raise SkewError(
            f"no flash found: peak luminance {peak:.1f} is within {MIN_FLASH_STEP:.0f} "
            f"of the baseline {baseline:.1f}"
        )
    threshold = baseline + 0.5 * (peak - baseline)
    return onsets(lum, times, threshold, REFRACTORY_S)


def clap_onsets(env: np.ndarray, times: np.ndarray) -> list[Onset]:
    noise = float(np.median(env))
    peak = float(env.max())
    if peak <= 0.0 or peak < 8.0 * max(noise, 1e-4):
        raise SkewError(
            f"no clap found: audio peak {peak:.3f} is not clearly above the noise floor {noise:.4f}"
        )
    threshold = max(8.0 * noise, 0.35 * peak)
    return onsets(env, times, threshold, REFRACTORY_S)


def strongest(found: list[Onset], count: int | None) -> list[Onset]:
    if count is None or len(found) <= count:
        return sorted(found, key=lambda onset: onset.time_s)
    top = sorted(found, key=lambda onset: onset.strength, reverse=True)[:count]
    return sorted(top, key=lambda onset: onset.time_s)


def pair_events(flashes: list[Onset], claps: list[Onset]) -> list[Pair]:
    pairs: list[Pair] = []
    for flash, clap in zip(flashes, claps, strict=False):
        skew_ms = (clap.time_s - flash.time_s) * 1000.0
        pairs.append(Pair(flash_s=flash.time_s, clap_s=clap.time_s, skew_ms=skew_ms))
    return pairs


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, min(len(ordered), int(np.ceil(p / 100.0 * len(ordered)))))
    return ordered[rank - 1]


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


def analyse(path: str, events: int | None, limit_ms: float) -> dict:
    if np is None:
        raise SkewError("numpy is required: pip install numpy (or the api 'opencv' extra)")
    lum, frame_times = video_luminance(path)
    env, sample_times = audio_envelope(path)
    flashes = strongest(flash_onsets(lum, frame_times), events)
    claps = strongest(clap_onsets(env, sample_times), events)
    pairs = pair_events(flashes, claps)
    abs_skews = [abs(pair.skew_ms) for pair in pairs]
    warnings: list[str] = []
    if len(flashes) != len(claps):
        warnings.append(
            f"{len(flashes)} flash(es) but {len(claps)} clap(s); "
            f"paired the first {len(pairs)} in order"
        )
    if events is not None and len(pairs) < events:
        warnings.append(f"expected {events} events, found {len(pairs)} pair(s)")
    p95 = percentile(abs_skews, 95)
    if not pairs:
        verdict = "insufficient"
    elif p95 is not None and p95 <= limit_ms:
        verdict = "pass"
    else:
        verdict = "fail"
    return {
        "file": path,
        "video_fps_analysed": VIDEO_FPS,
        "audio_rate_analysed": AUDIO_RATE,
        "flashes_s": [round(flash.time_s, 3) for flash in flashes],
        "claps_s": [round(clap.time_s, 3) for clap in claps],
        "pairs": [asdict(pair) | {"skew_ms": round(pair.skew_ms, 1)} for pair in pairs],
        "abs_skew_ms": {
            "count": len(abs_skews),
            "p50": _round(percentile(abs_skews, 50)),
            "p95": _round(p95),
            "max": _round(max(abs_skews)) if abs_skews else None,
        },
        "mean_skew_ms": (
            round(sum(pair.skew_ms for pair in pairs) / len(pairs), 1) if pairs else None
        ),
        "limit_ms": limit_ms,
        "verdict": verdict,
        "warnings": warnings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("recording", help="programme recording (WebM or anything ffmpeg decodes)")
    parser.add_argument(
        "--events",
        type=int,
        default=None,
        help="number of clap/flash events to keep (the strongest)",
    )
    parser.add_argument(
        "--limit-ms", type=float, default=150.0, help="p95 absolute skew limit (plan: 150)"
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)
    try:
        report = analyse(args.recording, args.events, args.limit_ms)
    except SkewError as error:
        print(f"av_skew: {error}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    print(f"{report['file']}")
    for pair in report["pairs"]:
        print(
            f"  flash {pair['flash_s']:.3f} s  clap {pair['clap_s']:.3f} s"
            f"  skew {pair['skew_ms']:+.1f} ms"
        )
    stats = report["abs_skew_ms"]
    if stats["count"]:
        print(
            f"  |skew| p50 {stats['p50']:.1f} ms  p95 {stats['p95']:.1f} ms"
            f"  max {stats['max']:.1f} ms"
            f"  mean skew {report['mean_skew_ms']:+.1f} ms over {stats['count']} pair(s)"
        )
    for warning in report["warnings"]:
        print(f"  warning: {warning}")
    print(f"  verdict: {report['verdict']} (limit {report['limit_ms']:.0f} ms)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
