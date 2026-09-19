import { useCallback, useEffect, useRef, useState } from "react";

import {
  formatBytes,
  formatDuration,
  pickRecordingMimeType,
  RECORDING_MIME_CANDIDATES,
  recordingFileName,
  totalBytes,
} from "./recorderSupport";

type Phase = "unsupported" | "idle" | "recording" | "stopped" | "error";

export interface RecordingTestProps {
  /** Short label used in the file name, e.g. "CAM-HOST". */
  label: string;
  /**
   * Returns the tracks to record, or null when nothing is live. The component
   * never opens a camera or microphone itself; it only records tracks that
   * already exist (a remote LiveKit track, a local preview, or later a canvas).
   */
  getStream: () => MediaStream | null;
  disabled?: boolean;
}

interface Result {
  url: string;
  mimeType: string;
  bytes: number;
  chunkCount: number;
  durationMs: number;
}

const TIMESLICE_MS = 1000;

/**
 * Shared smoke-test recorder (v3 plan section 6). Every machine uses the same
 * component so "it recorded locally" means the same thing on all four laptops.
 */
export function RecordingTest({ label, getStream, disabled = false }: RecordingTestProps) {
  const recorderAvailable = typeof MediaRecorder !== "undefined";
  const [phase, setPhase] = useState<Phase>(recorderAvailable ? "idle" : "unsupported");
  const [support, setSupport] = useState<Record<string, boolean>>({});
  const [chosenMimeType, setChosenMimeType] = useState<string | null>(null);
  const [message, setMessage] = useState(
    recorderAvailable ? "Probe complete. Start when a live source is attached." : "MediaRecorder is not available in this browser.",
  );
  const [elapsedMs, setElapsedMs] = useState(0);
  const [liveBytes, setLiveBytes] = useState(0);
  const [liveChunks, setLiveChunks] = useState(0);
  const [result, setResult] = useState<Result | null>(null);
  const [sourceSummary, setSourceSummary] = useState<string>("");

  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const startedAtRef = useRef<number>(0);
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    if (!recorderAvailable) return;
    const probe: Record<string, boolean> = {};
    for (const candidate of RECORDING_MIME_CANDIDATES) {
      probe[candidate] = MediaRecorder.isTypeSupported(candidate);
    }
    setSupport(probe);
    setChosenMimeType(pickRecordingMimeType((type) => probe[type] ?? false));
  }, [recorderAvailable]);

  const clearTimer = () => {
    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
  };

  const revokeResult = useCallback(() => {
    setResult((previous) => {
      if (previous) URL.revokeObjectURL(previous.url);
      return null;
    });
  }, []);

  useEffect(() => {
    return () => {
      clearTimer();
      const recorder = recorderRef.current;
      if (recorder && recorder.state !== "inactive") recorder.stop();
      setResult((previous) => {
        if (previous) URL.revokeObjectURL(previous.url);
        return null;
      });
    };
  }, []);

  function describe(stream: MediaStream): string {
    const parts = stream.getTracks().map((track) => {
      const settings = track.getSettings();
      const size =
        track.kind === "video" && settings.width && settings.height
          ? ` ${settings.width}x${settings.height}`
          : "";
      return `${track.kind}${size} (${track.readyState})`;
    });
    return parts.join(", ") || "no tracks";
  }

  function start() {
    if (!recorderAvailable || !chosenMimeType) {
      setPhase("error");
      setMessage("No supported recording format was found.");
      return;
    }
    const stream = getStream();
    if (!stream || stream.getTracks().length === 0) {
      setPhase("error");
      setMessage("No live tracks to record. Attach a source first.");
      return;
    }

    revokeResult();
    chunksRef.current = [];
    setLiveBytes(0);
    setLiveChunks(0);
    setElapsedMs(0);
    setSourceSummary(describe(stream));

    let recorder: MediaRecorder;
    try {
      recorder = new MediaRecorder(stream, { mimeType: chosenMimeType });
    } catch (error) {
      setPhase("error");
      setMessage(error instanceof Error ? error.message : "MediaRecorder refused the stream.");
      return;
    }

    recorder.ondataavailable = (event: BlobEvent) => {
      if (event.data.size > 0) {
        chunksRef.current.push(event.data);
        setLiveChunks(chunksRef.current.length);
        setLiveBytes(totalBytes(chunksRef.current));
      }
    };
    recorder.onerror = () => {
      clearTimer();
      setPhase("error");
      setMessage("The recorder reported an error. The source track may have ended.");
    };
    recorder.onstop = () => {
      clearTimer();
      const actualMimeType = recorder.mimeType || chosenMimeType;
      const chunks = chunksRef.current;
      const blob = new Blob(chunks, { type: actualMimeType });
      const durationMs = performance.now() - startedAtRef.current;
      setResult({
        url: URL.createObjectURL(blob),
        mimeType: actualMimeType,
        bytes: blob.size,
        chunkCount: chunks.length,
        durationMs,
      });
      setPhase("stopped");
      setMessage(
        blob.size > 0
          ? "Stopped. Play it back here, then download and play it outside the app before calling it a pass."
          : "Stopped, but no data was captured. Check that the source had live frames.",
      );
    };

    recorderRef.current = recorder;
    startedAtRef.current = performance.now();
    recorder.start(TIMESLICE_MS);
    timerRef.current = window.setInterval(() => {
      setElapsedMs(performance.now() - startedAtRef.current);
    }, 250);
    setPhase("recording");
    setMessage(`Recording as ${chosenMimeType}. Chunks arrive every ${TIMESLICE_MS} ms.`);
  }

  function stop() {
    const recorder = recorderRef.current;
    if (!recorder || recorder.state === "inactive") return;
    recorder.stop();
  }

  function download() {
    if (!result) return;
    const anchor = document.createElement("a");
    anchor.href = result.url;
    anchor.download = recordingFileName(label, result.mimeType, new Date());
    anchor.click();
  }

  function clear() {
    revokeResult();
    setPhase(recorderAvailable ? "idle" : "unsupported");
    setMessage("Cleared. Nothing was saved to disk unless you downloaded it.");
  }

  const recording = phase === "recording";

  return (
    <section className="panel form-panel" aria-label="Recording test">
      <div className="preview-heading">
        <div>
          <p className="eyebrow">RECORDING TEST</p>
          <h2>{label}</h2>
        </div>
        <span className={`status status-${phase}`}>{phase}</span>
      </div>

      <dl className="connection-details">
        {RECORDING_MIME_CANDIDATES.map((candidate) => (
          <FragmentRow
            key={candidate}
            term={candidate}
            value={
              support[candidate] === undefined ? "probing" : support[candidate] ? "supported" : "no"
            }
          />
        ))}
        <FragmentRow term="Chosen" value={chosenMimeType ?? "none"} />
        {sourceSummary && <FragmentRow term="Source" value={sourceSummary} />}
        {(recording || result) && (
          <>
            <FragmentRow term="Elapsed" value={formatDuration(result?.durationMs ?? elapsedMs)} />
            <FragmentRow
              term="Captured"
              value={`${result?.chunkCount ?? liveChunks} chunks, ${formatBytes(result?.bytes ?? liveBytes)}`}
            />
          </>
        )}
        {result && <FragmentRow term="Actual container" value={result.mimeType} />}
      </dl>

      <div className="inline-actions">
        <button
          type="button"
          className="primary"
          onClick={start}
          disabled={disabled || recording || !chosenMimeType}
        >
          Start recording
        </button>
        <button type="button" className="danger" onClick={stop} disabled={!recording}>
          Stop
        </button>
        <button type="button" onClick={download} disabled={!result || result.bytes === 0}>
          Download
        </button>
        <button type="button" onClick={clear} disabled={recording || !result}>
          Clear
        </button>
      </div>

      <p className="detail" role="status" aria-live="polite">
        {message}
      </p>

      {result && result.bytes > 0 && (
        <div className="playback">
          <video controls playsInline src={result.url} />
        </div>
      )}
    </section>
  );
}

function FragmentRow({ term, value }: { term: string; value: string }) {
  return (
    <>
      <dt>{term}</dt>
      <dd>{value}</dd>
    </>
  );
}
