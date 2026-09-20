import type { CameraId, ProgramSource } from "@cue/contracts";

/**
 * Stage 4 soak monitor (v3 plan section 9, stability): sample the receiver once a
 * second for the 20-minute run and summarise what the gate asks about, which is
 * no audio-source change and no unbounded memory growth, plus what an operator
 * needs to see: frame gaps per slot, throttling, recorder persistence.
 * Pure apart from readHeapUsedBytes, which is guarded.
 */

/** Plan section 9: a 20-minute Mac run with all publishers, worker, inference and recorder. */
export const SOAK_GATE = {
  minDurationMs: 20 * 60_000,
  /** Sustained growth above this over the run is flagged for review, not passed silently. */
  heapSlopeReviewBytesPerMinute: 1_000_000,
  /** A slot must be renderable in this share of samples to count as stable. */
  minRenderableRatio: 0.99,
} as const;

export interface SoakSlotSample {
  cameraId: CameraId;
  frameCount: number;
  lastFrameAgeMs: number | null;
  renderable: boolean;
  streamEpoch: number | null;
  videoTrackSid: string | null;
}

export interface SoakSample {
  /** Renderer clock. */
  atMs: number;
  wallMs: number;
  slots: SoakSlotSample[];
  /** MediaStreamTrack id feeding the programme audio. Must never change during a run. */
  masterAudioTrackId: string | null;
  masterAudioAttached: boolean;
  programSource: ProgramSource;
  live: boolean;
  mode: string;
  drawIntervalMs: number;
  throttled: boolean;
  recorderPhase: string;
  recorderChunks: number;
  recorderBytes: number;
  recorderPersistFailures: number;
  heapUsedBytes: number | null;
  linkStatus: string;
  ackCount: number;
}

export interface SoakSlotSummary {
  cameraId: CameraId;
  framesDecoded: number;
  renderableRatio: number;
  maxFrameAgeMs: number | null;
  /** Transitions from renderable to not renderable. */
  stalls: number;
  epochChanges: number;
  trackChanges: number;
}

export interface HeapSummary {
  firstBytes: number;
  lastBytes: number;
  maxBytes: number;
  growthBytes: number;
  /** Least-squares slope over the run. */
  slopeBytesPerMinute: number;
}

export interface SoakSummary {
  sampleCount: number;
  durationMs: number;
  startedWallMs: number | null;
  endedWallMs: number | null;
  slots: SoakSlotSummary[];
  /** Changes of the audio track feeding the programme, after it first appeared. */
  audioSourceChanges: number;
  audioDetachedSamples: number;
  throttledSamples: number;
  maxDrawIntervalMs: number;
  heap: HeapSummary | null;
  recorder: { maxPersistFailures: number; finalBytes: number; phases: string[] };
  linkDownSamples: number;
  programChanges: number;
}

export type CheckStatus = "pass" | "fail" | "insufficient" | "review" | "unmeasured";

export interface SoakCheck {
  name: string;
  status: CheckStatus;
  detail: string;
}

export interface SoakVerdict {
  status: CheckStatus;
  checks: SoakCheck[];
}

/** Chrome exposes a non-standard heap size; other browsers return null (unmeasured, not zero). */
export function readHeapUsedBytes(): number | null {
  const perf = globalThis.performance as Performance & { memory?: { usedJSHeapSize?: unknown } };
  const value = perf?.memory?.usedJSHeapSize;
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function slope(points: readonly { x: number; y: number }[]): number {
  if (points.length < 2) return 0;
  const n = points.length;
  const meanX = points.reduce((total, point) => total + point.x, 0) / n;
  const meanY = points.reduce((total, point) => total + point.y, 0) / n;
  let numerator = 0;
  let denominator = 0;
  for (const point of points) {
    numerator += (point.x - meanX) * (point.y - meanY);
    denominator += (point.x - meanX) ** 2;
  }
  return denominator === 0 ? 0 : numerator / denominator;
}

export function summarizeSoak(samples: readonly SoakSample[]): SoakSummary {
  const first = samples[0];
  const last = samples[samples.length - 1];
  const durationMs = first && last ? last.atMs - first.atMs : 0;

  const slotIds = new Map<CameraId, true>();
  for (const sample of samples) for (const slot of sample.slots) slotIds.set(slot.cameraId, true);
  const slots: SoakSlotSummary[] = [...slotIds.keys()].map((cameraId) => {
    let framesDecoded = 0;
    let renderableSamples = 0;
    let maxFrameAgeMs: number | null = null;
    let stalls = 0;
    let epochChanges = 0;
    let trackChanges = 0;
    let previous: SoakSlotSample | null = null;
    let seen = 0;
    for (const sample of samples) {
      const slot = sample.slots.find((candidate) => candidate.cameraId === cameraId);
      if (!slot) continue;
      seen += 1;
      if (slot.renderable) renderableSamples += 1;
      if (slot.lastFrameAgeMs !== null && (maxFrameAgeMs === null || slot.lastFrameAgeMs > maxFrameAgeMs)) {
        maxFrameAgeMs = slot.lastFrameAgeMs;
      }
      if (previous) {
        if (slot.frameCount >= previous.frameCount) framesDecoded += slot.frameCount - previous.frameCount;
        else framesDecoded += slot.frameCount; // counter reset on a republish
        if (previous.renderable && !slot.renderable) stalls += 1;
        if (previous.streamEpoch !== null && slot.streamEpoch !== previous.streamEpoch) epochChanges += 1;
        if (previous.videoTrackSid !== null && slot.videoTrackSid !== previous.videoTrackSid) trackChanges += 1;
      }
      previous = slot;
    }
    return {
      cameraId,
      framesDecoded,
      renderableRatio: seen === 0 ? 0 : renderableSamples / seen,
      maxFrameAgeMs,
      stalls,
      epochChanges,
      trackChanges,
    };
  });

  let audioSourceChanges = 0;
  let audioDetachedSamples = 0;
  let lastAudioId: string | null = null;
  let throttledSamples = 0;
  let maxDrawIntervalMs = 0;
  let maxPersistFailures = 0;
  const phases = new Set<string>();
  let linkDownSamples = 0;
  let programChanges = 0;
  let lastProgram: ProgramSource | null = null;
  const heapPoints: { x: number; y: number }[] = [];
  for (const sample of samples) {
    if (sample.masterAudioTrackId !== null) {
      if (lastAudioId !== null && sample.masterAudioTrackId !== lastAudioId) audioSourceChanges += 1;
      lastAudioId = sample.masterAudioTrackId;
    }
    if (!sample.masterAudioAttached) audioDetachedSamples += 1;
    if (sample.throttled) throttledSamples += 1;
    if (sample.drawIntervalMs > maxDrawIntervalMs) maxDrawIntervalMs = sample.drawIntervalMs;
    if (sample.recorderPersistFailures > maxPersistFailures) maxPersistFailures = sample.recorderPersistFailures;
    phases.add(sample.recorderPhase);
    if (sample.linkStatus !== "connected" && sample.linkStatus !== "off") linkDownSamples += 1;
    if (lastProgram !== null && sample.programSource !== lastProgram) programChanges += 1;
    lastProgram = sample.programSource;
    if (sample.heapUsedBytes !== null && first) {
      heapPoints.push({ x: (sample.atMs - first.atMs) / 60_000, y: sample.heapUsedBytes });
    }
  }

  const heap: HeapSummary | null =
    heapPoints.length === 0
      ? null
      : {
          firstBytes: heapPoints[0].y,
          lastBytes: heapPoints[heapPoints.length - 1].y,
          maxBytes: Math.max(...heapPoints.map((point) => point.y)),
          growthBytes: heapPoints[heapPoints.length - 1].y - heapPoints[0].y,
          slopeBytesPerMinute: slope(heapPoints),
        };

  return {
    sampleCount: samples.length,
    durationMs,
    startedWallMs: first?.wallMs ?? null,
    endedWallMs: last?.wallMs ?? null,
    slots,
    audioSourceChanges,
    audioDetachedSamples,
    throttledSamples,
    maxDrawIntervalMs,
    heap,
    recorder: { maxPersistFailures, finalBytes: last?.recorderBytes ?? 0, phases: [...phases] },
    linkDownSamples,
    programChanges,
  };
}

function formatMb(bytes: number): string {
  return `${(bytes / 1_048_576).toFixed(1)} MB`;
}

export function soakVerdict(summary: SoakSummary, gate = SOAK_GATE): SoakVerdict {
  const checks: SoakCheck[] = [];
  const minutes = summary.durationMs / 60_000;

  checks.push(
    summary.durationMs >= gate.minDurationMs
      ? { name: "duration", status: "pass", detail: `${minutes.toFixed(1)} min sampled` }
      : { name: "duration", status: "insufficient", detail: `${minutes.toFixed(1)} of ${gate.minDurationMs / 60_000} min` },
  );
  checks.push(
    summary.audioSourceChanges === 0
      ? { name: "audio source", status: "pass", detail: "programme audio track never changed" }
      : { name: "audio source", status: "fail", detail: `${summary.audioSourceChanges} audio-source change(s)` },
  );
  if (summary.heap === null) {
    checks.push({ name: "memory", status: "unmeasured", detail: "browser exposes no heap size" });
  } else if (summary.heap.slopeBytesPerMinute > gate.heapSlopeReviewBytesPerMinute) {
    checks.push({
      name: "memory",
      status: "review",
      detail: `heap ${formatMb(summary.heap.firstBytes)} to ${formatMb(summary.heap.lastBytes)}, ${formatMb(summary.heap.slopeBytesPerMinute)}/min`,
    });
  } else {
    checks.push({
      name: "memory",
      status: "pass",
      detail: `heap ${formatMb(summary.heap.firstBytes)} to ${formatMb(summary.heap.lastBytes)}, ${formatMb(summary.heap.slopeBytesPerMinute)}/min`,
    });
  }
  checks.push(
    summary.throttledSamples === 0
      ? { name: "draw loop", status: "pass", detail: `slowest interval ${Math.round(summary.maxDrawIntervalMs)} ms` }
      : { name: "draw loop", status: "fail", detail: `${summary.throttledSamples} throttled sample(s)` },
  );
  checks.push(
    summary.recorder.maxPersistFailures === 0
      ? { name: "recording", status: "pass", detail: `${formatMb(summary.recorder.finalBytes)} persisted, no failures` }
      : { name: "recording", status: "fail", detail: `${summary.recorder.maxPersistFailures} chunk persist failure(s)` },
  );
  for (const slot of summary.slots) {
    const ratio = `${(slot.renderableRatio * 100).toFixed(1)}% renderable, ${slot.stalls} stall(s), max gap ${slot.maxFrameAgeMs === null ? "n/a" : `${Math.round(slot.maxFrameAgeMs)} ms`}`;
    checks.push(
      slot.renderableRatio >= gate.minRenderableRatio
        ? { name: slot.cameraId, status: "pass", detail: ratio }
        : { name: slot.cameraId, status: "fail", detail: ratio },
    );
  }
  if (summary.linkDownSamples > 0) {
    checks.push({ name: "control link", status: "review", detail: `${summary.linkDownSamples} sample(s) with the link down` });
  }

  const status: CheckStatus = checks.some((check) => check.status === "fail")
    ? "fail"
    : checks.some((check) => check.status === "insufficient")
      ? "insufficient"
      : checks.some((check) => check.status === "review")
        ? "review"
        : "pass";
  return { status, checks };
}
