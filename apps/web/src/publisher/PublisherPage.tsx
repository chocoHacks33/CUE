import {
  CAMERA_CONTRACTS,
  CAMERA_IDS,
  type CameraId,
  mayPublishMicrophone,
} from "@cue/contracts";
import { Room, RoomEvent, Track } from "livekit-client";
import { useCallback, useEffect, useRef, useState } from "react";

import { requestPublisherToken } from "./api";
import { captureConstraints, validateCapturedTracks } from "./mediaPolicy";

type PublisherStatus =
  | "idle"
  | "requesting-media"
  | "preview-ready"
  | "connecting"
  | "published"
  | "reconnecting"
  | "error";

const DEFAULT_API_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

function messageForMediaError(error: unknown): string {
  if (error instanceof DOMException) {
    if (error.name === "NotAllowedError") return "Camera or microphone permission was denied.";
    if (error.name === "NotFoundError") return "The required camera or microphone was not found.";
    if (error.name === "NotReadableError") return "The camera is already in use or unavailable.";
  }
  return error instanceof Error ? error.message : "Unable to start the webcam.";
}

export function PublisherPage() {
  const [apiBaseUrl, setApiBaseUrl] = useState(DEFAULT_API_URL);
  const [bootstrapSecret, setBootstrapSecret] = useState("");
  const [eventId, setEventId] = useState("hackmit-demo");
  const [displayName, setDisplayName] = useState("Person A");
  const [cameraId, setCameraId] = useState<CameraId>("CAM-HOST");
  const [status, setStatus] = useState<PublisherStatus>("idle");
  const [detail, setDetail] = useState("Choose a source and test the local preview.");
  const [remoteIdentity, setRemoteIdentity] = useState<string | null>(null);

  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const roomRef = useRef<Room | null>(null);

  const stop = useCallback(async () => {
    const room = roomRef.current;
    roomRef.current = null;
    if (room) await room.disconnect();

    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;

    setRemoteIdentity(null);
    setStatus("idle");
    setDetail("Camera and room connection stopped.");
  }, []);

  useEffect(() => {
    return () => {
      void roomRef.current?.disconnect();
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

    await stop();
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
      setStatus("preview-ready");
      setDetail(
        mayPublishMicrophone(cameraId)
          ? "Local preview ready with the designated master microphone."
          : "Local video preview ready. Microphone is disabled by contract.",
      );
    } catch (error) {
      setStatus("error");
      setDetail(messageForMediaError(error));
    }
  }

  async function publish() {
    const stream = streamRef.current;
    if (!stream) {
      setStatus("error");
      setDetail("Start and verify the local preview before publishing.");
      return;
    }
    if (!bootstrapSecret || !eventId || !displayName.trim()) {
      setStatus("error");
      setDetail("API URL, event ID, display name and Stage 0 secret are required.");
      return;
    }

    setStatus("connecting");
    setDetail("Requesting a scoped credential and connecting to LiveKit…");
    let room: Room | null = null;
    try {
      const credential = await requestPublisherToken(apiBaseUrl, bootstrapSecret, {
        eventId,
        cameraId,
        displayName: displayName.trim(),
      });

      if (credential.camera.cameraId !== cameraId) {
        throw new Error("Server returned a different camera contract");
      }

      room = new Room({ adaptiveStream: false, dynacast: false });
      roomRef.current = room;
      room.on(RoomEvent.Reconnecting, () => {
        setStatus("reconnecting");
        setDetail("Media connection interrupted; reconnecting without changing source identity…");
      });
      room.on(RoomEvent.Reconnected, () => {
        setStatus("published");
        setDetail("Reconnected and publishing. Confirm the physical marker on D's Mac.");
      });
      room.on(RoomEvent.Disconnected, () => {
        setStatus("preview-ready");
        setDetail("Disconnected from LiveKit. Local preview remains available.");
        setRemoteIdentity(null);
      });

      await room.connect(credential.serverUrl, credential.participantToken, {
        autoSubscribe: false,
      });

      const videoTrack = stream.getVideoTracks()[0];
      if (!videoTrack) throw new Error("Webcam track ended before publication");
      await room.localParticipant.publishTrack(videoTrack, {
        name: `${cameraId}-camera`,
        source: Track.Source.Camera,
        simulcast: false,
      });

      if (mayPublishMicrophone(cameraId)) {
        const audioTrack = stream.getAudioTracks()[0];
        if (!audioTrack) throw new Error("Master microphone track ended before publication");
        await room.localParticipant.publishTrack(audioTrack, {
          name: `${cameraId}-master-audio`,
          source: Track.Source.Microphone,
        });
      }

      setRemoteIdentity(credential.participantIdentity);
      setStatus("published");
      setDetail("Publishing. D must verify the real image, label and audio on the MacBook.");
    } catch (error) {
      if (room) await room.disconnect();
      roomRef.current = null;
      stream.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
      if (videoRef.current) videoRef.current.srcObject = null;
      setStatus("error");
      const reason = error instanceof Error ? error.message : "Unable to publish the webcam.";
      setDetail(`${reason} Start a new local preview before retrying.`);
    }
  }

  const controlsLocked = status === "connecting" || status === "published" || status === "reconnecting";
  const contract = CAMERA_CONTRACTS[cameraId];

  return (
    <main className="shell">
      <header className="hero">
        <p className="eyebrow">CUE · STAGE 0</p>
        <h1>Windows camera publisher</h1>
        <p>Preview locally, then publish one server-labelled source to D’s MacBook.</p>
      </header>

      <section className="grid">
        <div className="panel form-panel">
          <h2>Source contract</h2>

          <label>
            Camera source
            <select
              value={cameraId}
              disabled={controlsLocked || status === "preview-ready"}
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

          <label>
            Event ID
            <input
              value={eventId}
              disabled={controlsLocked}
              pattern="[a-z0-9][a-z0-9-]*"
              onChange={(event) => setEventId(event.target.value.toLowerCase())}
            />
          </label>

          <label>
            Display name
            <input
              value={displayName}
              disabled={controlsLocked}
              onChange={(event) => setDisplayName(event.target.value)}
            />
          </label>

          <label>
            Mac API URL
            <input
              type="url"
              value={apiBaseUrl}
              disabled={controlsLocked}
              onChange={(event) => setApiBaseUrl(event.target.value)}
            />
          </label>

          <label>
            Stage 0 admission secret
            <input
              type="password"
              value={bootstrapSecret}
              disabled={controlsLocked}
              autoComplete="off"
              onChange={(event) => setBootstrapSecret(event.target.value)}
            />
          </label>

          <div className="actions">
            <button type="button" onClick={() => void startPreview()} disabled={controlsLocked}>
              Test local preview
            </button>
            <button
              type="button"
              className="primary"
              onClick={() => void publish()}
              disabled={status !== "preview-ready" && status !== "error"}
            >
              Publish to D’s Mac
            </button>
            <button type="button" className="danger" onClick={() => void stop()}>
              Stop sharing
            </button>
          </div>
        </div>

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
            {!streamRef.current && <p>Camera preview appears here</p>}
          </div>

          <p className="detail" role="status" aria-live="polite">
            {detail}
          </p>
          {remoteIdentity && (
            <dl className="connection-details">
              <dt>Server identity</dt>
              <dd>{remoteIdentity}</dd>
              <dt>Audio rule</dt>
              <dd>{contract.audioPolicy}</dd>
            </dl>
          )}
        </div>
      </section>

      <footer>
        Stage 0 uses a temporary shared admission secret. Stage 1 replaces it with single-use pairing and producer approval.
      </footer>
    </main>
  );
}
