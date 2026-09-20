import { describe, expect, it } from "vitest";

import {
  extensionForMimeType,
  formatBytes,
  formatDuration,
  pickRecordingMimeType,
  RECORDING_MIME_CANDIDATES,
  recordingFileName,
  stillFileName,
  totalBytes,
} from "./recorderSupport";

describe("recording MIME selection", () => {
  it("prefers WebM VP8/Opus when the browser supports it", () => {
    expect(pickRecordingMimeType(() => true)).toBe("video/webm;codecs=vp8,opus");
  });

  it("falls through the candidate list in order", () => {
    const onlyMp4 = (type: string) => type === "video/mp4";
    expect(pickRecordingMimeType(onlyMp4)).toBe("video/mp4");
  });

  it("returns null when nothing is supported instead of guessing", () => {
    expect(pickRecordingMimeType(() => false)).toBeNull();
  });

  it("keeps the documented candidate order", () => {
    expect(RECORDING_MIME_CANDIDATES[0]).toBe("video/webm;codecs=vp8,opus");
    expect(RECORDING_MIME_CANDIDATES[RECORDING_MIME_CANDIDATES.length - 1]).toBe("video/mp4");
  });
});

describe("file naming", () => {
  it("uses the real container extension", () => {
    expect(extensionForMimeType("video/webm;codecs=vp8,opus")).toBe("webm");
    expect(extensionForMimeType("video/mp4")).toBe("mp4");
    expect(extensionForMimeType("application/octet-stream")).toBe("bin");
  });

  it("builds a safe, timestamped file name", () => {
    const when = new Date(2026, 8, 19, 14, 5, 9);
    expect(recordingFileName("CAM-HOST + master audio", "video/webm", when)).toBe(
      "cue-cam-host-master-audio-20260919-140509.webm",
    );
  });

  it("names a programme still by event, on-air source and time", () => {
    const when = new Date(2026, 8, 20, 9, 30, 1);
    expect(stillFileName("hackmit-demo", "CAM-GUEST", when)).toBe("cue-still-hackmit-demo-cam-guest-20260920-093001.png");
    expect(stillFileName("", "SLATE", when)).toBe("cue-still-x-slate-20260920-093001.png");
  });
});

describe("sizes and durations", () => {
  it("sums chunk sizes", () => {
    expect(totalBytes([{ size: 10 }, { size: 32 }])).toBe(42);
    expect(totalBytes([])).toBe(0);
  });

  it("formats bytes and durations for the operator", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(formatBytes(3 * 1024 * 1024)).toBe("3.00 MB");
    expect(formatDuration(0)).toBe("00:00");
    expect(formatDuration(65_000)).toBe("01:05");
  });
});
