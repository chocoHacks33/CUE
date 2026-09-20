import { describe, expect, it } from "vitest";

import { readHeapUsedBytes, SOAK_GATE, type SoakSample, soakVerdict, summarizeSoak } from "./soak";

function sample(index: number, overrides: Partial<SoakSample> = {}): SoakSample {
  return {
    atMs: index * 1000,
    wallMs: 1_700_000_000_000 + index * 1000,
    slots: ["CAM-HOST", "CAM-GUEST", "CAM-WIDE"].map((cameraId) => ({
      cameraId: cameraId as SoakSample["slots"][number]["cameraId"],
      frameCount: index * 30,
      lastFrameAgeMs: 33,
      renderable: true,
      streamEpoch: 1,
      videoTrackSid: `TR_${cameraId}`,
    })),
    masterAudioTrackId: "audio-a",
    masterAudioAttached: true,
    programSource: "CAM-HOST",
    live: true,
    mode: "ASSIST",
    drawIntervalMs: 33,
    throttled: false,
    recorderPhase: "recording",
    recorderChunks: index,
    recorderBytes: index * 100_000,
    recorderPersistFailures: 0,
    heapUsedBytes: 50_000_000 + index * 100,
    linkStatus: "connected",
    ackCount: 3,
    ...overrides,
  };
}

/** A clean run of the given length in seconds. */
function cleanRun(seconds: number): SoakSample[] {
  return Array.from({ length: seconds + 1 }, (_, i) => sample(i));
}

describe("summarizeSoak", () => {
  it("handles an empty run", () => {
    const summary = summarizeSoak([]);
    expect(summary.sampleCount).toBe(0);
    expect(summary.durationMs).toBe(0);
    expect(summary.heap).toBeNull();
    expect(summary.slots).toEqual([]);
  });

  it("counts frames, stalls, epoch and track changes per slot, tolerating a counter reset", () => {
    const samples = cleanRun(4);
    // GUEST stalls at t=2, republishes at t=3 with a new epoch, track and reset counter.
    samples[2].slots[1] = { ...samples[2].slots[1], renderable: false, lastFrameAgeMs: 1200 };
    samples[3].slots[1] = { cameraId: "CAM-GUEST", frameCount: 5, lastFrameAgeMs: 40, renderable: true, streamEpoch: 2, videoTrackSid: "TR_new" };
    samples[4].slots[1] = { ...samples[3].slots[1], frameCount: 35 };
    const guest = summarizeSoak(samples).slots.find((slot) => slot.cameraId === "CAM-GUEST");
    expect(guest).toMatchObject({ stalls: 1, epochChanges: 1, trackChanges: 1, maxFrameAgeMs: 1200 });
    // 30 + 30 (t1, t2) + 5 (reset at t3) + 30 (t4)
    expect(guest?.framesDecoded).toBe(95);
    expect(guest?.renderableRatio).toBeCloseTo(4 / 5);
  });

  it("counts audio-source changes only after the track first appeared", () => {
    const samples = [
      sample(0, { masterAudioTrackId: null, masterAudioAttached: false }),
      sample(1, { masterAudioTrackId: "audio-a" }),
      sample(2, { masterAudioTrackId: "audio-a" }),
      sample(3, { masterAudioTrackId: "audio-b" }),
    ];
    const summary = summarizeSoak(samples);
    expect(summary.audioSourceChanges).toBe(1);
    expect(summary.audioDetachedSamples).toBe(1);
  });

  it("measures heap growth as a slope and remembers the peak", () => {
    const samples = Array.from({ length: 121 }, (_, i) => sample(i, { heapUsedBytes: 100_000_000 + i * 1000 }));
    const heap = summarizeSoak(samples).heap;
    expect(heap?.growthBytes).toBe(120_000);
    // 1000 bytes per second is 60 000 bytes per minute.
    expect(heap?.slopeBytesPerMinute).toBeCloseTo(60_000, 0);
    expect(heap?.maxBytes).toBe(100_120_000);
  });

  it("tracks throttling, persist failures, link outages and programme changes", () => {
    const samples = [
      sample(0),
      sample(1, { throttled: true, drawIntervalMs: 900 }),
      sample(2, { recorderPersistFailures: 2, linkStatus: "reconnecting" }),
      sample(3, { programSource: "CAM-WIDE" }),
    ];
    const summary = summarizeSoak(samples);
    expect(summary.throttledSamples).toBe(1);
    expect(summary.maxDrawIntervalMs).toBe(900);
    expect(summary.recorder.maxPersistFailures).toBe(2);
    expect(summary.linkDownSamples).toBe(1);
    expect(summary.programChanges).toBe(1);
  });
});

describe("soakVerdict", () => {
  it("is insufficient before 20 minutes even when everything else is clean", () => {
    const verdict = soakVerdict(summarizeSoak(cleanRun(600)));
    expect(verdict.status).toBe("insufficient");
    expect(verdict.checks.find((check) => check.name === "duration")?.status).toBe("insufficient");
    expect(verdict.checks.find((check) => check.name === "audio source")?.status).toBe("pass");
  });

  it("passes a clean 20-minute run", () => {
    const verdict = soakVerdict(summarizeSoak(cleanRun(SOAK_GATE.minDurationMs / 1000)));
    expect(verdict.status).toBe("pass");
    expect(verdict.checks.every((check) => check.status === "pass")).toBe(true);
  });

  it("fails on an audio-source change regardless of duration", () => {
    const samples = cleanRun(SOAK_GATE.minDurationMs / 1000);
    samples[500] = sample(500, { masterAudioTrackId: "audio-b" });
    for (let i = 501; i < samples.length; i += 1) samples[i] = sample(i, { masterAudioTrackId: "audio-b" });
    const verdict = soakVerdict(summarizeSoak(samples));
    expect(verdict.status).toBe("fail");
    expect(verdict.checks.find((check) => check.name === "audio source")?.detail).toBe("1 audio-source change(s)");
  });

  it("flags sustained heap growth for review rather than passing it", () => {
    const seconds = SOAK_GATE.minDurationMs / 1000;
    const samples = Array.from({ length: seconds + 1 }, (_, i) => sample(i, { heapUsedBytes: 100_000_000 + i * 50_000 }));
    const verdict = soakVerdict(summarizeSoak(samples));
    expect(verdict.status).toBe("review");
    expect(verdict.checks.find((check) => check.name === "memory")?.status).toBe("review");
  });

  it("reports memory as unmeasured when the browser exposes no heap size", () => {
    const samples = cleanRun(30).map((item) => ({ ...item, heapUsedBytes: null }));
    const memory = soakVerdict(summarizeSoak(samples)).checks.find((check) => check.name === "memory");
    expect(memory?.status).toBe("unmeasured");
  });

  it("fails a slot that was not renderable for more than 1% of samples", () => {
    const samples = cleanRun(SOAK_GATE.minDurationMs / 1000);
    for (let i = 100; i < 120; i += 1) samples[i].slots[2] = { ...samples[i].slots[2], renderable: false };
    const wide = soakVerdict(summarizeSoak(samples)).checks.find((check) => check.name === "CAM-WIDE");
    expect(wide?.status).toBe("fail");
  });
});

describe("readHeapUsedBytes", () => {
  it("returns null where performance.memory is absent", () => {
    expect(readHeapUsedBytes()).toBeNull();
  });
});
