import {
  assembleRecording,
  newRecordingId,
  type RecordingMeta,
  type RecordingStore,
} from "./recordingStore";

/**
 * Records the programme canvas plus the fixed master audio track, persisting
 * every chunk as it arrives (PRD section 11). Browser only; the store is
 * injected so the persistence logic is testable elsewhere.
 */

export type RecorderPhase = "idle" | "recording" | "stopping" | "stopped" | "error";

export interface RecorderResult {
  recordingId: string;
  url: string;
  mimeType: string;
  bytes: number;
  chunkCount: number;
  durationMs: number;
  /** True when the file was assembled from persisted chunks rather than memory. */
  fromStore: boolean;
}

export interface RecorderStatus {
  phase: RecorderPhase;
  recordingId: string | null;
  mimeType: string | null;
  actualMimeType: string | null;
  startedAtMs: number | null;
  elapsedMs: number;
  chunkCount: number;
  bytes: number;
  persistedChunks: number;
  persistFailures: number;
  hasAudio: boolean;
  lastError: string | null;
  result: RecorderResult | null;
}

const TIMESLICE_MS = 1000;

export function initialRecorderStatus(): RecorderStatus {
  return {
    phase: "idle",
    recordingId: null,
    mimeType: null,
    actualMimeType: null,
    startedAtMs: null,
    elapsedMs: 0,
    chunkCount: 0,
    bytes: 0,
    persistedChunks: 0,
    persistFailures: 0,
    hasAudio: false,
    lastError: null,
    result: null,
  };
}

export class ProgramRecorder {
  private status: RecorderStatus = initialRecorderStatus();
  private recorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];
  private meta: RecordingMeta | null = null;
  private timer: number | null = null;
  private stopping: Promise<void> | null = null;

  constructor(
    private readonly store: RecordingStore,
    private readonly onStatus: (status: RecorderStatus) => void,
  ) {}

  get current(): RecorderStatus {
    return this.status;
  }

  private update(patch: Partial<RecorderStatus>): void {
    this.status = { ...this.status, ...patch };
    this.onStatus(this.status);
  }

  async start(stream: MediaStream, eventId: string, mimeType: string): Promise<void> {
    if (this.recorder && this.recorder.state !== "inactive") {
      throw new Error("A recording is already running");
    }
    this.clearResult();

    const recordingId = newRecordingId(new Date());
    const recorder = new MediaRecorder(stream, { mimeType });
    const meta: RecordingMeta = {
      recordingId,
      eventId,
      mimeType,
      startedAt: Date.now(),
      endedAt: null,
      chunkCount: 0,
      bytes: 0,
      status: "recording",
    };
    try {
      await this.store.createRecording(meta);
    } catch (error) {
      this.update({ lastError: `Persistence unavailable: ${describe(error)}. Recording in memory only.` });
    }

    this.recorder = recorder;
    this.chunks = [];
    this.meta = meta;
    const startedAtMs = performance.now();
    this.update({
      phase: "recording",
      recordingId,
      mimeType,
      actualMimeType: recorder.mimeType || mimeType,
      startedAtMs,
      elapsedMs: 0,
      chunkCount: 0,
      bytes: 0,
      persistedChunks: 0,
      persistFailures: 0,
      hasAudio: stream.getAudioTracks().length > 0,
      result: null,
    });

    recorder.ondataavailable = (event: BlobEvent) => {
      if (event.data.size === 0) return;
      const index = this.chunks.length;
      this.chunks.push(event.data);
      const bytes = this.status.bytes + event.data.size;
      this.update({ chunkCount: this.chunks.length, bytes });
      if (this.meta) {
        this.meta = { ...this.meta, chunkCount: this.chunks.length, bytes };
      }
      void this.persist(recordingId, index, event.data);
    };
    recorder.onerror = () => {
      this.update({ phase: "error", lastError: "MediaRecorder reported an error; the source may have ended." });
      this.stopTimer();
    };

    recorder.start(TIMESLICE_MS);
    this.timer = window.setInterval(() => {
      if (this.status.startedAtMs !== null) {
        this.update({ elapsedMs: performance.now() - this.status.startedAtMs });
      }
    }, 250);
  }

  private async persist(recordingId: string, index: number, blob: Blob): Promise<void> {
    try {
      await this.store.appendChunk(recordingId, index, blob);
      this.update({ persistedChunks: this.status.persistedChunks + 1 });
      if (this.meta && this.meta.recordingId === recordingId) {
        await this.store.updateRecording(this.meta);
      }
    } catch (error) {
      this.update({
        persistFailures: this.status.persistFailures + 1,
        lastError: `Chunk ${index} not persisted: ${describe(error)}`,
      });
    }
  }

  async stop(): Promise<RecorderResult | null> {
    const recorder = this.recorder;
    if (!recorder || recorder.state === "inactive") return this.status.result;
    if (this.stopping) {
      await this.stopping;
      return this.status.result;
    }

    this.update({ phase: "stopping" });
    this.stopping = new Promise<void>((resolve) => {
      recorder.onstop = () => resolve();
      recorder.stop();
    });
    await this.stopping;
    this.stopping = null;
    this.stopTimer();

    const meta = this.meta;
    const mimeType = this.status.actualMimeType ?? this.status.mimeType ?? "application/octet-stream";
    let chunks = this.chunks;
    let fromStore = false;
    if (meta) {
      const finished: RecordingMeta = {
        ...meta,
        endedAt: Date.now(),
        chunkCount: this.chunks.length,
        bytes: this.status.bytes,
        status: "complete",
      };
      try {
        await this.store.updateRecording(finished);
        const stored = await this.store.readChunks(meta.recordingId);
        if (stored.length === this.chunks.length && stored.length > 0) {
          chunks = stored;
          fromStore = true;
        }
      } catch (error) {
        this.update({ lastError: `Could not finalise persisted recording: ${describe(error)}` });
      }
    }

    const blob = assembleRecording(chunks, mimeType);
    const result: RecorderResult = {
      recordingId: this.status.recordingId ?? "unknown",
      url: URL.createObjectURL(blob),
      mimeType,
      bytes: blob.size,
      chunkCount: chunks.length,
      durationMs: this.status.elapsedMs,
      fromStore,
    };
    this.recorder = null;
    this.meta = null;
    this.update({ phase: "stopped", result });
    return result;
  }

  clearResult(): void {
    if (this.status.result) URL.revokeObjectURL(this.status.result.url);
    this.update({ result: null, lastError: null, phase: this.status.phase === "stopped" ? "idle" : this.status.phase });
  }

  dispose(): void {
    this.stopTimer();
    const recorder = this.recorder;
    if (recorder && recorder.state !== "inactive") recorder.stop();
    if (this.status.result) URL.revokeObjectURL(this.status.result.url);
  }

  private stopTimer(): void {
    if (this.timer !== null) {
      window.clearInterval(this.timer);
      this.timer = null;
    }
  }
}

function describe(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
