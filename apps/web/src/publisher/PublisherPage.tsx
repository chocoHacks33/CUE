import {
  CAMERA_CONTRACTS,
  type CameraId,
  mayPublishMicrophone,
} from "@cue/contracts";
import { Room, RoomEvent, Track } from "livekit-client";
import { useCallback, useEffect, useRef, useState } from "react";

import { defaultApiBaseUrl } from "../apiBase";
import { claimPairing, exchangePairing, readPairingStatus } from "./api";
import { captureConstraints, listVideoInputs, validateCapturedTracks, type VideoInput } from "./mediaPolicy";

type PublisherStatus =
  | "idle"
  | "claiming"
  | "awaiting-approval"
  | "paired"
  | "requesting-media"
  | "preview-ready"
  | "connecting"
  | "published"
  | "reconnecting"
  | "error";

const DEFAULT_API_URL = defaultApiBaseUrl(import.meta.env.VITE_API_BASE_URL, window.location);

interface PairingSession {
  claimId: string;
  claimSecret: string;
  verificationCode: string;
  status: string;
}

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
  const [pairingToken, setPairingToken] = useState("");
  const [displayName, setDisplayName] = useState("Person A");
  const [deviceLabel, setDeviceLabel] = useState("A Windows laptop");
  const [cameraId, setCameraId] = useState<CameraId>("CAM-HOST");
  const [pairing, setPairing] = useState<PairingSession | null>(null);
  const [status, setStatus] = useState<PublisherStatus>("idle");
  const [detail, setDetail] = useState("Enter the single-use token supplied by the producer.");
  const [remoteIdentity, setRemoteIdentity] = useState<string | null>(null);
  /** Cameras the browser exposes after the first permission; a phone lists each lens separately. */
  const [videoInputs, setVideoInputs] = useState<VideoInput[]>([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState<string | null>(null);

  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const roomRef = useRef<Room | null>(null);

  const stopMedia = useCallback(async () => {
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

  const stop = useCallback(async () => {
    await stopMedia();
    setPairing(null);
    setPairingToken("");
    setDetail("Sharing stopped. Request a new single-use pairing token to reconnect.");
  }, [stopMedia]);

  useEffect(() => {
    return () => {
      void roomRef.current?.disconnect();
      streamRef.current?.getTracks().forEach((track) => track.stop());
    };
  }, []);

  async function startPreview(deviceId: string | null = selectedDeviceId) {
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

    if (!pairing) {
      setStatus("error");
      setDetail("Claim a producer-issued pairing token before opening the camera.");
      return;
    }
    await stopMedia();
    setStatus("requesting-media");
    setDetail("Waiting for camera permission…");
    try {
      const stream = await navigator.mediaDevices.getUserMedia(captureConstraints(cameraId, { deviceId }));
      validateCapturedTracks(cameraId, stream);
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }
      // Labels exist only after a permission; list the lenses now and remember which one opened.
      try {
        const devices = await navigator.mediaDevices.enumerateDevices();
        setVideoInputs(listVideoInputs(devices));
      } catch {
        // A browser that cannot enumerate still previews and publishes.
      }
      const opened = stream.getVideoTracks()[0]?.getSettings().deviceId;
      if (opened) setSelectedDeviceId(opened);
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

  async function pairDevice() {
    if (!pairingToken.trim() || !displayName.trim() || !deviceLabel.trim()) {
      setStatus("error");
      setDetail("Pairing token, display name and device label are required.");
      return;
    }
    await stopMedia();
    setStatus("claiming");
    setDetail("Consuming the single-use pairing token…");
    try {
      const claim = await claimPairing(apiBaseUrl, {
        pairingToken: pairingToken.trim(),
        displayName: displayName.trim(),
        deviceLabel: deviceLabel.trim(),
      });
      setCameraId(claim.camera.cameraId);
      setPairing({
        claimId: claim.claimId,
        claimSecret: claim.claimSecret,
        verificationCode: claim.verificationCode,
        status: claim.status,
      });
      setPairingToken("");
      setStatus("awaiting-approval");
      setDetail(
        `Show ${claim.verificationCode} to the producer. You may test the local preview while approval is pending.`,
      );
    } catch (error) {
      setStatus("error");
      setDetail(error instanceof Error ? error.message : "Unable to claim pairing token.");
    }
  }

  async function checkApproval() {
    if (!pairing) return;
    try {
      const result = await readPairingStatus(apiBaseUrl, pairing);
      setPairing((current) => (current ? { ...current, status: result.status } : current));
      if (result.status === "APPROVED") {
        setStatus(streamRef.current ? "preview-ready" : "paired");
        setDetail("Producer approved this device. Start the preview, then publish.");
      } else if (result.status === "REJECTED") {
        setStatus("error");
        setDetail("Producer rejected this device. Request a new pairing token if needed.");
      } else {
        setStatus("awaiting-approval");
        setDetail(`Approval is ${result.status.toLowerCase()}. Verify ${result.verificationCode}.`);
      }
    } catch (error) {
      setStatus("error");
      setDetail(error instanceof Error ? error.message : "Unable to check pairing approval.");
    }
  }

  async function publish() {
    const stream = streamRef.current;
    if (!stream) {
      setStatus("error");
      setDetail("Start and verify the local preview before publishing.");
      return;
    }
    if (!pairing) {
      setStatus("error");
      setDetail("A producer-approved pairing session is required.");
      return;
    }

    setStatus("connecting");
    setDetail("Requesting a scoped credential and connecting to LiveKit…");
    let room: Room | null = null;
    let credentialExchanged = false;
    try {
      const credential = await exchangePairing(apiBaseUrl, pairing);
      credentialExchanged = true;

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
        setStatus("error");
        setDetail("Disconnected from LiveKit. Request a new pairing token before publishing again.");
        setPairing(null);
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
      if (credentialExchanged) {
        setPairing(null);
        setDetail(`${reason} The claim was consumed; request a new pairing token.`);
      } else {
        setDetail(`${reason} Start a new local preview before retrying.`);
      }
    }
  }

  const controlsLocked =
    status === "claiming" ||
    status === "requesting-media" ||
    status === "connecting" ||
    status === "published" ||
    status === "reconnecting";
  const contract = CAMERA_CONTRACTS[cameraId];

  return (
    <main className="shell">
      <header className="hero">
        <p className="eyebrow">CUE · STAGE 1</p>
        <h1>Windows camera publisher</h1>
        <p>Preview locally, then publish one server-labelled source to D’s MacBook.</p>
      </header>

      <section className="grid">
        <div className="panel form-panel">
          <h2>Source contract</h2>

          <label>
            Camera source
            <input value={pairing ? cameraId : "Assigned after pairing"} readOnly />
          </label>

          <div className="contract-card">
            {pairing ? (
              <>
                <span>Owner {contract.owner}</span>
                <strong>{contract.role}</strong>
                <span>
                  {contract.audioPolicy === "MASTER" ? "Master mic enabled" : "Video only"}
                </span>
              </>
            ) : (
              <strong>Waiting for server assignment</strong>
            )}
          </div>

          <label>
            Display name
            <input
              value={displayName}
              disabled={controlsLocked || Boolean(pairing)}
              onChange={(event) => setDisplayName(event.target.value)}
            />
          </label>

          <label>
            Device label
            <input
              value={deviceLabel}
              disabled={controlsLocked || Boolean(pairing)}
              onChange={(event) => setDeviceLabel(event.target.value)}
            />
          </label>

          <label>
            Camera lens
            <select
              value={selectedDeviceId ?? ""}
              disabled={videoInputs.length === 0 || status === "connecting" || status === "published" || status === "reconnecting"}
              onChange={(event) => {
                const deviceId = event.target.value || null;
                setSelectedDeviceId(deviceId);
                void startPreview(deviceId);
              }}
            >
              {videoInputs.length === 0 && <option value="">Test the preview first to list cameras</option>}
              {videoInputs.map((input) => (
                <option key={input.deviceId} value={input.deviceId}>
                  {input.label}
                </option>
              ))}
            </select>
          </label>

          <label>
            Mac API URL
            <input
              type="url"
              value={apiBaseUrl}
              disabled={controlsLocked || Boolean(pairing)}
              onChange={(event) => setApiBaseUrl(event.target.value)}
            />
          </label>

          <label>
            Single-use pairing token
            <input
              type="password"
              value={pairingToken}
              disabled={controlsLocked || Boolean(pairing)}
              autoComplete="off"
              onChange={(event) => setPairingToken(event.target.value)}
            />
          </label>

          <div className="actions">
            <button type="button" onClick={() => void pairDevice()} disabled={controlsLocked || Boolean(pairing)}>
              Claim pairing
            </button>
            <button type="button" onClick={() => void startPreview()} disabled={controlsLocked}>
              Test local preview
            </button>
            <button type="button" onClick={() => void checkApproval()} disabled={!pairing || controlsLocked}>
              Check approval
            </button>
            <button
              type="button"
              className="primary"
              onClick={() => void publish()}
              disabled={status !== "preview-ready" || pairing?.status !== "APPROVED"}
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
          {pairing && !remoteIdentity && (
            <dl className="connection-details">
              <dt>Verification</dt>
              <dd>{pairing.verificationCode}</dd>
              <dt>Approval</dt>
              <dd>{pairing.status}</dd>
            </dl>
          )}
        </div>
      </section>

      <footer>
        The producer credential stays on D’s Mac. This page receives only a short-lived, single-use pairing capability.
      </footer>
    </main>
  );
}
