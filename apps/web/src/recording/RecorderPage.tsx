import { CAMERA_CONTRACTS, CAMERA_IDS, type CameraId, mayPublishMicrophone } from "@cue/contracts";
import { useCallback, useEffect, useRef, useState } from "react";

import { captureConstraints, validateCapturedTracks } from "../publisher/mediaPolicy";
import { RecordingTest } from "./RecordingTest";

type CaptureStatus = "idle" | "requesting-media" | "preview-ready" | "error";

function messageForMediaError(error: unknown): string {
  if (error instanceof DOMException) {
    if (error.name === "NotAllowedError") return "Camera or microphone permission was denied.";
    if (error.name === "NotFoundError") return "The required camera or microphone was not found.";
    if (error.name === "NotReadableError") return "The camera is already in use by another page or app.";
  }
  return error instanceof Error ? error.message : "Unable to start the webcam.";
}

/**
 * Standalone local recording test (v3 plan section 6, Test 1). Any laptop opens
 * `/recorder`, captures its own webcam under the same media policy as the
 * publisher, records 30 to 60 seconds, downloads the clip and plays it outside
 * the app. Nothing here connects to LiveKit or publishes anything.
 */
export function RecorderPage() {
  const [cameraId, setCameraId] = useState<CameraId>("CAM-HOST");
  const [status, setStatus] = useState<CaptureStatus>("idle");
  const [detail, setDetail] = useState(
    "Local capture only. Close the publisher page first so the webcam is not held twice.",
  );
  const [trackSummary, setTrackSummary] = useState<string>("");

  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const stop = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    setTrackSummary("");
    setStatus("idle");
    setDetail("Capture stopped.");
  }, []);

  useEffect(() => {
    return () => {
      streamRef.current?.getTracks().forEach((track) => track.stop());
    };
  }, []);

  async function startPreview() {
    if (!window.isSecureContext) {
      setStatus("error");
      setDetail("Webcam access requires HTTPS or localhost.");
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      setStatus("error");
      setDetail("This browser does not expose webcam capture.");
      return;
    }

    stop();
    setStatus("requesting-media");
    setDetail("Waiting for camera permission…");
    try {
      const stream = await navigator.mediaDevices.getUserMedia(captureConstraints(cameraId));
      validateCapturedTracks(cameraId, stream);
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }
      setTrackSummary(
        stream
          .getTracks()
          .map((track) => `${track.kind}: ${track.label || "unnamed"}`)
          .join(" · "),
      );
      setStatus("preview-ready");
      setDetail(
        mayPublishMicrophone(cameraId)
          ? "Preview ready with the master microphone. Say a marker and wave while recording."
          : "Preview ready, video only by contract. Show a visual marker while recording.",
      );
    } catch (error) {
      setStatus("error");
      setDetail(messageForMediaError(error));
    }
  }

  const contract = CAMERA_CONTRACTS[cameraId];
  const getStream = useCallback(() => streamRef.current, []);

  return (
    <main className="shell">
      <header className="hero">
        <p className="eyebrow">CUE · STAGE 1 · TEST 1</p>
        <h1>Local recording test</h1>
        <p>
          Capture your own webcam under the same contract as the publisher, record a short clip,
          download it and play it outside the app. Nothing is published.
        </p>
      </header>

      <section className="grid">
        <div className="panel form-panel">
          <h2>Source contract</h2>
          <label>
            Camera source
            <select
              value={cameraId}
              disabled={status === "requesting-media" || status === "preview-ready"}
              onChange={(event) => setCameraId(event.target.value as CameraId)}
            >
              {CAMERA_IDS.map((id) => (
                <option key={id} value={id}>
                  {id} · {CAMERA_CONTRACTS[id].role}
                </option>
              ))}
            </select>
          </label>

          <div className="contract-card">
            <span>Owner {contract.owner}</span>
            <strong>{contract.role}</strong>
            <span>{contract.audioPolicy === "MASTER" ? "Master mic enabled" : "Video only"}</span>
          </div>

          <div className="actions">
            <button
              type="button"
              className="primary"
              onClick={() => void startPreview()}
              disabled={status === "requesting-media"}
            >
              Start local preview
            </button>
            <button type="button" className="danger" onClick={stop} disabled={status === "idle"}>
              Stop capture
            </button>
          </div>

          <p className="detail" role="status" aria-live="polite">
            {detail}
          </p>
          {trackSummary && (
            <dl className="connection-details">
              <dt>Tracks</dt>
              <dd>{trackSummary}</dd>
              <dt>Published</dt>
              <dd>nothing; this page never joins a room</dd>
            </dl>
          )}
        </div>

        <div className="stack">
          <div className="panel preview-panel">
            <div className="preview-heading">
              <div>
                <p className="eyebrow">LOCAL PREVIEW</p>
                <h2>{cameraId}</h2>
              </div>
              <span className={`status status-${status}`}>{status.replace("-", " ")}</span>
            </div>
            <div className="video-frame">
              <video ref={videoRef} muted playsInline />
              {status !== "preview-ready" && <p>Camera preview appears here</p>}
            </div>
          </div>

          <RecordingTest
            label={cameraId}
            getStream={getStream}
            disabled={status !== "preview-ready"}
          />
        </div>
      </section>

      <footer>
        Record your result in docs/results using your lane's template: browser, OS, camera, actual
        container, duration and whether the file played outside the app.
      </footer>
    </main>
  );
}
