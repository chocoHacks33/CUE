import {
  CAMERA_CONTRACTS,
  CAMERA_IDS,
  type CameraId,
  parsePublisherMetadata,
  type ProgramSource,
  type ReceiverReadiness,
  type RenderAck,
} from "@cue/contracts";
import { RemoteParticipant, Room, RoomEvent, Track } from "livekit-client";
import type {
  RemoteAudioTrack,
  RemoteTrack,
  RemoteTrackPublication,
  RemoteVideoTrack,
} from "livekit-client";
import { useCallback, useEffect, useRef, useState } from "react";

import { ProgramPanel } from "../compositor/ProgramPanel";
import { RecordingTest } from "../recording/RecordingTest";
import { PairingPanel } from "./PairingPanel";
import { buildReadiness } from "./readiness";
import { requestReceiverToken } from "./receiverApi";
import {
  applyStallCheck,
  claimSlot,
  clearAudioTrack,
  clearVideoTrack,
  emptySlots,
  frameAgeMs,
  MASTER_AUDIO_CAMERA,
  markFrame,
  releaseParticipant,
  setAudioPlayback,
  setAudioTrack,
  setVideoTrack,
  shouldSubscribe,
  type SlotState,
  type Slots,
} from "./slotState";

type ReceiverStatus =
  | "idle"
  | "requesting-token"
  | "connecting"
  | "connected"
  | "reconnecting"
  | "disconnected"
  | "error";

const DEFAULT_API_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const MAX_LOG_LINES = 80;
const TICK_MS = 250;

interface FrameMetadata {
  width: number;
  height: number;
}

interface VideoWithFrameCallback {
  requestVideoFrameCallback?: (
    callback: (now: number, metadata: FrameMetadata) => void,
  ) => number;
}

interface FrameWatcher {
  active: boolean;
  cleanup?: () => void;
}

const VIDEO_STATE_LABEL: Record<SlotState["videoState"], string> = {
  waiting: "waiting for publisher",
  "publisher-connected": "publisher connected",
  subscribing: "subscribing",
  "video-ready": "video ready",
  stalled: "stalled",
};

const AUDIO_STATE_LABEL: Record<SlotState["audioState"], string> = {
  "not-applicable": "video only",
  waiting: "audio waiting",
  "audio-ready": "audio ready",
  "playback-blocked": "audio blocked",
};

function timestamp(): string {
  return new Date().toLocaleTimeString([], { hour12: false });
}

function formatAge(ms: number | null): string {
  if (ms === null) return "no frames yet";
  if (ms < 1000) return `${Math.round(ms)} ms ago`;
  return `${(ms / 1000).toFixed(1)} s ago`;
}

/**
 * Person D's Stage 0 receiver. Subscribe-only: the token cannot publish, the
 * page never calls getUserMedia, and every incoming track is attached by the
 * camera ID in its server-set participant metadata, never by tile order.
 */
export function ProducerPage() {
  const [apiBaseUrl, setApiBaseUrl] = useState(DEFAULT_API_URL);
  const [bootstrapSecret, setBootstrapSecret] = useState("");
  const [eventId, setEventId] = useState("hackmit-demo");
  const [displayName, setDisplayName] = useState("Person D");
  const [status, setStatus] = useState<ReceiverStatus>("idle");
  const [detail, setDetail] = useState("Subscribe-only receiver. This Mac publishes nothing.");
  const [slots, setSlots] = useState<Slots>(emptySlots);
  const [now, setNow] = useState(() => performance.now());
  const [log, setLog] = useState<string[]>([]);
  const [roomName, setRoomName] = useState<string | null>(null);
  const [localIdentity, setLocalIdentity] = useState<string | null>(null);
  const [localPublications, setLocalPublications] = useState(0);
  const [audioPlaybackAllowed, setAudioPlaybackAllowed] = useState(true);
  const [monitorMuted, setMonitorMuted] = useState(false);
  const [unassigned, setUnassigned] = useState<Record<string, string>>({});
  const [recordSlot, setRecordSlot] = useState<CameraId>(MASTER_AUDIO_CAMERA);
  const [recordWithAudio, setRecordWithAudio] = useState(true);
  const [readiness, setReadiness] = useState<ReceiverReadiness | null>(null);
  const [rendererGeneration, setRendererGeneration] = useState(0);

  const roomRef = useRef<Room | null>(null);
  /** Stable for this tab. A second tab is a different renderer and can never ACK for this one. */
  const rendererIdRef = useRef(`renderer-${crypto.randomUUID().slice(0, 8)}`);
  const rendererGenerationRef = useRef(0);
  const readinessRef = useRef<ReceiverReadiness | null>(null);
  const programSourceRef = useRef<ProgramSource | null>(null);
  const lastAckRef = useRef<RenderAck | null>(null);
  const readinessContextRef = useRef({
    receiverIdentity: null as string | null,
    connected: false,
    audioPlaybackAllowed: true,
  });
  const slotsRef = useRef<Slots>(emptySlots());
  const connectedEventRef = useRef(eventId);
  const videoElements = useRef(new Map<CameraId, HTMLVideoElement>());
  const videoTracks = useRef(new Map<CameraId, RemoteVideoTrack>());
  const audioTrackRef = useRef<RemoteAudioTrack | null>(null);
  const audioElementRef = useRef<HTMLAudioElement | null>(null);
  const frameWatchers = useRef(new Map<CameraId, FrameWatcher>());
  const ignoredPublications = useRef(new Set<string>());

  const noteAudioPlayback = useCallback((allowed: boolean) => {
    readinessContextRef.current = { ...readinessContextRef.current, audioPlaybackAllowed: allowed };
    setAudioPlaybackAllowed(allowed);
  }, []);

  const appendLog = useCallback((line: string) => {
    setLog((previous) => [`${timestamp()}  ${line}`, ...previous].slice(0, MAX_LOG_LINES));
  }, []);

  /** The ref is the source of truth; state is a snapshot for rendering. */
  const commitSlots = useCallback((update: (slots: Slots) => Slots) => {
    slotsRef.current = update(slotsRef.current);
    setSlots(slotsRef.current);
  }, []);

  /** Per-frame path: update the ref only. The ticker flushes to state. */
  const touchSlots = useCallback((update: (slots: Slots) => Slots) => {
    slotsRef.current = update(slotsRef.current);
  }, []);

  useEffect(() => {
    const id = window.setInterval(() => {
      const t = performance.now();
      slotsRef.current = applyStallCheck(slotsRef.current, t);
      setSlots(slotsRef.current);
      setNow(t);
      const ctx = readinessContextRef.current;
      readinessRef.current = buildReadiness(
        slotsRef.current,
        t,
        {
          eventId: connectedEventRef.current,
          rendererId: rendererIdRef.current,
          rendererGeneration: rendererGenerationRef.current,
          receiverIdentity: ctx.receiverIdentity,
          connected: ctx.connected,
          audioPlaybackAllowed: ctx.audioPlaybackAllowed,
          audioAttached: audioTrackRef.current !== null,
          currentSource: programSourceRef.current,
        },
        readinessRef.current,
      );
      setReadiness(readinessRef.current);
    }, TICK_MS);
    return () => window.clearInterval(id);
  }, []);

  const stopFrameWatcher = useCallback((cameraId: CameraId) => {
    const watcher = frameWatchers.current.get(cameraId);
    if (watcher) {
      watcher.active = false;
      watcher.cleanup?.();
    }
    frameWatchers.current.delete(cameraId);
  }, []);

  const watchFrames = useCallback(
    (element: HTMLVideoElement, cameraId: CameraId) => {
      stopFrameWatcher(cameraId);
      const watcher: FrameWatcher = { active: true };
      frameWatchers.current.set(cameraId, watcher);

      const video = element as unknown as VideoWithFrameCallback;
      if (!video.requestVideoFrameCallback) {
        appendLog(`${cameraId}: requestVideoFrameCallback unsupported; freshness is approximate.`);
        const onTimeUpdate = () => {
          if (!watcher.active) return;
          touchSlots((s) =>
            markFrame(s, cameraId, performance.now(), element.videoWidth, element.videoHeight),
          );
        };
        element.addEventListener("timeupdate", onTimeUpdate);
        watcher.cleanup = () => element.removeEventListener("timeupdate", onTimeUpdate);
        return;
      }

      const tick = (_now: number, metadata: FrameMetadata) => {
        if (!watcher.active) return;
        touchSlots((s) => markFrame(s, cameraId, performance.now(), metadata.width, metadata.height));
        video.requestVideoFrameCallback?.(tick);
      };
      video.requestVideoFrameCallback(tick);
    },
    [appendLog, stopFrameWatcher, touchSlots],
  );

  const detachVideo = useCallback(
    (cameraId: CameraId) => {
      stopFrameWatcher(cameraId);
      const track = videoTracks.current.get(cameraId);
      if (track) {
        track.detach();
        videoTracks.current.delete(cameraId);
      }
      const element = videoElements.current.get(cameraId);
      if (element) element.srcObject = null;
      commitSlots((s) => clearVideoTrack(s, cameraId));
    },
    [commitSlots, stopFrameWatcher],
  );

  const detachAudio = useCallback(() => {
    const track = audioTrackRef.current;
    if (track) {
      track.detach();
      audioTrackRef.current = null;
    }
    if (audioElementRef.current) audioElementRef.current.srcObject = null;
    commitSlots((s) => clearAudioTrack(s, MASTER_AUDIO_CAMERA));
  }, [commitSlots]);

  const resetSlots = useCallback(() => {
    for (const cameraId of CAMERA_IDS) detachVideo(cameraId);
    detachAudio();
    slotsRef.current = emptySlots();
    setSlots(slotsRef.current);
    setUnassigned({});
    ignoredPublications.current.clear();
  }, [detachAudio, detachVideo]);

  const registerVideo = useCallback(
    (cameraId: CameraId, element: HTMLVideoElement | null) => {
      if (element) {
        videoElements.current.set(cameraId, element);
        const track = videoTracks.current.get(cameraId);
        if (track) {
          track.attach(element);
          watchFrames(element, cameraId);
        }
      } else {
        videoElements.current.delete(cameraId);
      }
    },
    [watchFrames],
  );

  // ---- LiveKit event handling. These read refs, so they stay correct across renders. ----

  function evaluatePublication(publication: RemoteTrackPublication, participant: RemoteParticipant) {
    const metadata = parsePublisherMetadata(participant.metadata);
    const currentEvent = connectedEventRef.current;
    const holder = metadata ? slotsRef.current[metadata.cameraId].publisherIdentity : null;
    const wanted =
      shouldSubscribe(metadata, publication.source, currentEvent) && holder === participant.identity;

    if (wanted) {
      if (!publication.isSubscribed) {
        publication.setSubscribed(true);
        appendLog(`${metadata?.cameraId}: subscribing to ${publication.source} ${publication.trackSid}`);
      }
      return;
    }

    if (publication.isSubscribed) publication.setSubscribed(false);
    if (ignoredPublications.current.has(publication.trackSid)) return;
    ignoredPublications.current.add(publication.trackSid);

    let reason = "unwanted source";
    if (!metadata) reason = "no valid server metadata";
    else if (holder !== participant.identity) reason = "not the bound publisher for that slot";
    else if (publication.source === Track.Source.Microphone) reason = "only CAM-HOST may supply audio";
    appendLog(
      `Ignored ${publication.source} ${publication.trackSid} from ${participant.identity}: ${reason}`,
    );
  }

  function handleParticipant(participant: RemoteParticipant) {
    const metadata = parsePublisherMetadata(participant.metadata);
    const { slots: next, result } = claimSlot(
      slotsRef.current,
      participant.identity,
      participant.name ?? null,
      metadata,
      connectedEventRef.current,
    );
    slotsRef.current = next;
    setSlots(next);

    switch (result.kind) {
      case "assigned":
        appendLog(
          `${result.cameraId} bound to ${participant.identity} (stream epoch ${metadata?.streamEpoch ?? "?"})`,
        );
        setUnassigned((previous) => {
          const { [participant.identity]: _dropped, ...rest } = previous;
          return rest;
        });
        break;
      case "conflict":
        appendLog(
          `CONFLICT: ${participant.identity} also claims ${result.cameraId}; keeping ${result.holder}`,
        );
        break;
      case "unassigned":
        setUnassigned((previous) => ({ ...previous, [participant.identity]: result.reason }));
        appendLog(`Unassigned ${participant.identity}: ${result.reason}`);
        break;
      case "already-assigned":
        break;
    }

    participant.trackPublications.forEach((publication) =>
      evaluatePublication(publication as RemoteTrackPublication, participant),
    );
  }

  function onTrackSubscribed(
    track: RemoteTrack,
    publication: RemoteTrackPublication,
    participant: RemoteParticipant,
  ) {
    const metadata = parsePublisherMetadata(participant.metadata);
    if (!metadata || slotsRef.current[metadata.cameraId].publisherIdentity !== participant.identity) {
      publication.setSubscribed(false);
      appendLog(`Dropped ${publication.trackSid} from ${participant.identity}: not a bound publisher`);
      return;
    }
    const { cameraId } = metadata;

    if (track.kind === Track.Kind.Video) {
      const videoTrack = track as RemoteVideoTrack;
      const previous = videoTracks.current.get(cameraId);
      if (previous && previous !== videoTrack) previous.detach();
      videoTracks.current.set(cameraId, videoTrack);
      const element = videoElements.current.get(cameraId);
      if (element) {
        videoTrack.attach(element);
        watchFrames(element, cameraId);
      }
      commitSlots((s) => setVideoTrack(s, cameraId, publication.trackSid));
      appendLog(`${cameraId}: video track ${publication.trackSid} attached`);
      return;
    }

    if (track.kind === Track.Kind.Audio) {
      if (cameraId !== MASTER_AUDIO_CAMERA || metadata.audioPolicy !== "MASTER") {
        publication.setSubscribed(false);
        appendLog(`Refused audio ${publication.trackSid} from ${cameraId}: not the master microphone`);
        return;
      }
      const audioTrack = track as RemoteAudioTrack;
      if (audioTrackRef.current && audioTrackRef.current !== audioTrack) audioTrackRef.current.detach();
      audioTrackRef.current = audioTrack;
      if (audioElementRef.current) audioTrack.attach(audioElementRef.current);
      const allowed = roomRef.current?.canPlaybackAudio ?? true;
      noteAudioPlayback(allowed);
      commitSlots((s) => setAudioTrack(s, cameraId, publication.trackSid, allowed));
      appendLog(`Master audio ${publication.trackSid} attached from ${participant.identity}`);
    }
  }

  function onTrackUnsubscribed(
    track: RemoteTrack,
    publication: RemoteTrackPublication,
    participant: RemoteParticipant,
  ) {
    if (track.kind === Track.Kind.Audio) {
      if (audioTrackRef.current === track) {
        detachAudio();
        appendLog(`Master audio ${publication.trackSid} unsubscribed`);
      }
      return;
    }
    for (const [cameraId, known] of videoTracks.current) {
      if (known === track) {
        detachVideo(cameraId);
        appendLog(`${cameraId}: video track ${publication.trackSid} unsubscribed (${participant.identity})`);
      }
    }
  }

  function onParticipantDisconnected(participant: RemoteParticipant) {
    for (const cameraId of CAMERA_IDS) {
      if (slotsRef.current[cameraId].publisherIdentity === participant.identity) {
        detachVideo(cameraId);
        if (cameraId === MASTER_AUDIO_CAMERA) detachAudio();
        appendLog(`${cameraId}: publisher ${participant.identity} left; slot keeps its ID and waits`);
      }
    }
    commitSlots((s) => releaseParticipant(s, participant.identity));
    setUnassigned((previous) => {
      const { [participant.identity]: _dropped, ...rest } = previous;
      return rest;
    });
  }

  const disconnect = useCallback(
    async (announce = true) => {
      const room = roomRef.current;
      roomRef.current = null;
      if (room) {
        room.removeAllListeners();
        await room.disconnect();
      }
      resetSlots();
      readinessContextRef.current = { ...readinessContextRef.current, receiverIdentity: null, connected: false };
      setRoomName(null);
      setLocalIdentity(null);
      setLocalPublications(0);
      if (announce) {
        setStatus("idle");
        setDetail("Receiver disconnected. Nothing was ever published from this Mac.");
        appendLog("Disconnected by operator");
      }
    },
    [appendLog, resetSlots],
  );

  useEffect(() => {
    return () => {
      void roomRef.current?.disconnect();
    };
  }, []);

  async function connect() {
    const secret = bootstrapSecret.trim();
    const name = displayName.trim();
    if (!secret || !eventId || !name) {
      setStatus("error");
      setDetail("API URL, event ID, display name and Stage 0 secret are required.");
      return;
    }

    await disconnect(false);
    setStatus("requesting-token");
    setDetail("Requesting a subscribe-only credential from the Mac API…");

    let room: Room | null = null;
    try {
      const credential = await requestReceiverToken(apiBaseUrl, secret, {
        eventId,
        displayName: name,
        receiverRole: "DIRECTOR",
      });
      connectedEventRef.current = eventId;

      room = new Room({ adaptiveStream: false, dynacast: false });
      roomRef.current = room;
      room
        .on(RoomEvent.ParticipantConnected, (participant) => {
          appendLog(`Participant joined: ${participant.identity}`);
          handleParticipant(participant);
        })
        .on(RoomEvent.ParticipantDisconnected, onParticipantDisconnected)
        .on(RoomEvent.ParticipantMetadataChanged, (_metadata, participant) => {
          if (participant instanceof RemoteParticipant) handleParticipant(participant);
        })
        .on(RoomEvent.TrackPublished, evaluatePublication)
        .on(RoomEvent.TrackUnpublished, (publication, participant) => {
          appendLog(`${participant.identity} unpublished ${publication.source} ${publication.trackSid}`);
        })
        .on(RoomEvent.TrackSubscribed, onTrackSubscribed)
        .on(RoomEvent.TrackUnsubscribed, onTrackUnsubscribed)
        .on(RoomEvent.TrackSubscriptionFailed, (trackSid, participant, reason) => {
          appendLog(`Subscription failed for ${trackSid} from ${participant.identity}: ${String(reason)}`);
        })
        .on(RoomEvent.TrackStreamStateChanged, (publication, streamState, participant) => {
          appendLog(`${participant.identity} ${publication.source} stream ${streamState}`);
        })
        .on(RoomEvent.AudioPlaybackStatusChanged, (playing) => {
          noteAudioPlayback(playing);
          commitSlots((s) => setAudioPlayback(s, playing));
        })
        .on(RoomEvent.LocalTrackPublished, () => {
          const count = roomRef.current?.localParticipant.trackPublications.size ?? 1;
          setLocalPublications(count);
          setStatus("error");
          setDetail("This Mac published a local track. That must never happen; disconnecting.");
          appendLog("VIOLATION: local track published from the receiver; disconnecting");
          void disconnect(false);
        })
        .on(RoomEvent.Reconnecting, () => {
          setStatus("reconnecting");
          setDetail("Media connection interrupted; reconnecting without changing slot identity…");
        })
        .on(RoomEvent.Reconnected, () => {
          setStatus("connected");
          setDetail("Reconnected. Re-checking bound publishers.");
          roomRef.current?.remoteParticipants.forEach((participant) => handleParticipant(participant));
        })
        .on(RoomEvent.ConnectionStateChanged, (state) => appendLog(`Connection state: ${state}`))
        .on(RoomEvent.Disconnected, (reason) => {
          setStatus("disconnected");
          setDetail(
            `Disconnected from LiveKit${reason !== undefined ? ` (reason ${String(reason)})` : ""}.`,
          );
          resetSlots();
        });

      setStatus("connecting");
      setDetail("Connecting to LiveKit as a subscriber…");
      await room.connect(credential.serverUrl, credential.participantToken, {
        autoSubscribe: false,
      });

      rendererGenerationRef.current += 1;
      setRendererGeneration(rendererGenerationRef.current);
      readinessContextRef.current = {
        receiverIdentity: room.localParticipant.identity,
        connected: true,
        audioPlaybackAllowed: readinessContextRef.current.audioPlaybackAllowed,
      };
      setRoomName(credential.roomName);
      setLocalIdentity(room.localParticipant.identity);
      setLocalPublications(room.localParticipant.trackPublications.size);
      appendLog(`Connected to ${credential.roomName} as ${room.localParticipant.identity} (subscribe-only)`);

      room.remoteParticipants.forEach((participant) => handleParticipant(participant));

      try {
        await room.startAudio();
      } catch {
        // Autoplay policy: the Enable audio button retries inside a user gesture.
      }
      noteAudioPlayback(room.canPlaybackAudio);

      setStatus("connected");
      setDetail("Connected subscribe-only. Tiles bind to server metadata, not join order.");
    } catch (error) {
      if (room) {
        room.removeAllListeners();
        await room.disconnect();
      }
      roomRef.current = null;
      setStatus("error");
      setDetail(error instanceof Error ? error.message : "Unable to connect the receiver.");
    }
  }

  async function enableAudio() {
    const room = roomRef.current;
    if (!room) return;
    try {
      await room.startAudio();
    } catch (error) {
      appendLog(`Audio playback still blocked: ${error instanceof Error ? error.message : String(error)}`);
    }
    noteAudioPlayback(room.canPlaybackAudio);
    commitSlots((s) => setAudioPlayback(s, room.canPlaybackAudio));
  }

  const getSourceElement = useCallback(
    (cameraId: CameraId): HTMLVideoElement | null => videoElements.current.get(cameraId) ?? null,
    [],
  );
  const getMasterAudioTrack = useCallback(
    (): MediaStreamTrack | null => audioTrackRef.current?.mediaStreamTrack ?? null,
    [],
  );
  const onProgramChange = useCallback((source: ProgramSource) => {
    programSourceRef.current = source;
  }, []);
  /** Acks are kept for the Stage 2 control socket; until then the switcher log already narrates them. */
  const onAck = useCallback((ack: RenderAck) => {
    lastAckRef.current = ack;
  }, []);

  const getRecordingStream = useCallback((): MediaStream | null => {
    const video = videoTracks.current.get(recordSlot)?.mediaStreamTrack;
    if (!video) return null;
    const tracks: MediaStreamTrack[] = [video];
    const audio = audioTrackRef.current?.mediaStreamTrack;
    if (recordWithAudio && audio) tracks.push(audio);
    return new MediaStream(tracks);
  }, [recordSlot, recordWithAudio]);

  const controlsLocked =
    status === "requesting-token" ||
    status === "connecting" ||
    status === "connected" ||
    status === "reconnecting";
  const hostSlot = slots[MASTER_AUDIO_CAMERA];
  const readyCount = CAMERA_IDS.filter((id) => slots[id].videoState === "video-ready").length;
  const unassignedEntries = Object.entries(unassigned);

  return (
    <main className="shell">
      <header className="hero">
        <p className="eyebrow">CUE · STAGE 0 · PERSON D</p>
        <h1>Mac receiver</h1>
        <p>
          Subscribe-only director desk. Three fixed slots bind to server-labelled publishers. This
          Mac publishes no camera and no microphone.
        </p>
      </header>

      <section className="producer-grid">
        <div className="stack">
          <div className="panel form-panel">
            <h2>Receiver session</h2>

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
              <button
                type="button"
                className="primary"
                onClick={() => void connect()}
                disabled={controlsLocked}
              >
                Connect subscribe-only
              </button>
              <button
                type="button"
                className="danger"
                onClick={() => void disconnect()}
                disabled={status === "idle"}
              >
                Disconnect
              </button>
            </div>

            <dl className="connection-details">
              <dt>Status</dt>
              <dd>
                <span className={`status status-${status}`}>{status.replace(/-/g, " ")}</span>
              </dd>
              <dt>Room</dt>
              <dd>{roomName ?? "not connected"}</dd>
              <dt>Local identity</dt>
              <dd>{localIdentity ?? "none"}</dd>
              <dt>Mac publishes</dt>
              <dd className={localPublications === 0 ? undefined : "error-text"}>
                {localPublications === 0
                  ? "nothing (0 local tracks; token cannot publish)"
                  : `${localPublications} local tracks: WRONG`}
              </dd>
              <dt>Subscriptions</dt>
              <dd>explicit per track · adaptive stream off · dynacast off</dd>
              <dt>Video ready</dt>
              <dd>
                {readyCount} of {CAMERA_IDS.length}
              </dd>
            </dl>

            <p className="detail" role="status" aria-live="polite">
              {detail}
            </p>
          </div>

          <PairingPanel apiBaseUrl={apiBaseUrl} eventId={eventId} onLog={appendLog} />

          <div className="panel form-panel">
            <h2>Master audio</h2>
            <audio ref={audioElementRef} autoPlay muted={monitorMuted} />
            <dl className="connection-details">
              <dt>Source</dt>
              <dd>{MASTER_AUDIO_CAMERA} only; other microphones are never subscribed</dd>
              <dt>State</dt>
              <dd>
                <span className={`badge badge-${hostSlot.audioState}`}>
                  {AUDIO_STATE_LABEL[hostSlot.audioState]}
                </span>
              </dd>
              <dt>Track SID</dt>
              <dd>{hostSlot.audioTrackSid ?? "none"}</dd>
              <dt>Browser playback</dt>
              <dd>{audioPlaybackAllowed ? "allowed" : "blocked until you click Enable audio"}</dd>
            </dl>
            <div className="inline-actions">
              <button
                type="button"
                onClick={() => void enableAudio()}
                disabled={status !== "connected" || audioPlaybackAllowed}
              >
                Enable audio playback
              </button>
              <button type="button" onClick={() => setMonitorMuted((muted) => !muted)}>
                {monitorMuted ? "Unmute monitor" : "Mute monitor"}
              </button>
            </div>
            <p className="detail">
              Monitor on headphones. Muting the monitor never mutes the received track; the recorder
              still gets A's audio.
            </p>
          </div>

          {unassignedEntries.length > 0 && (
            <div className="panel form-panel">
              <h2>Unassigned participants</h2>
              <ul className="unassigned">
                {unassignedEntries.map(([identity, reason]) => (
                  <li key={identity}>
                    {identity}: {reason}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        <div className="stack">
          <ProgramPanel
            eventId={connectedEventRef.current}
            rendererId={rendererIdRef.current}
            rendererGeneration={rendererGeneration}
            connected={status === "connected" || status === "reconnecting"}
            readiness={readiness}
            getSourceElement={getSourceElement}
            getMasterAudioTrack={getMasterAudioTrack}
            onProgramChange={onProgramChange}
            onAck={onAck}
            onLog={appendLog}
          />

          <div className="panel preview-panel">
            <div className="preview-heading">
              <div>
                <p className="eyebrow">PREVIEWS</p>
                <h2>Three fixed slots</h2>
              </div>
              <span className="status">
                {readyCount}/{CAMERA_IDS.length} live
              </span>
            </div>
            <div className="slots">
              {CAMERA_IDS.map((cameraId) => (
                <SlotTile
                  key={cameraId}
                  slot={slots[cameraId]}
                  now={now}
                  registerVideo={registerVideo}
                />
              ))}
            </div>
          </div>

          <div className="panel form-panel">
            <h2>Recording source</h2>
            <label>
              Video slot
              <select
                value={recordSlot}
                onChange={(event) => setRecordSlot(event.target.value as CameraId)}
              >
                {CAMERA_IDS.map((cameraId) => (
                  <option key={cameraId} value={cameraId}>
                    {cameraId} · {VIDEO_STATE_LABEL[slots[cameraId].videoState]}
                  </option>
                ))}
              </select>
            </label>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={recordWithAudio}
                onChange={(event) => setRecordWithAudio(event.target.checked)}
              />
              Include {MASTER_AUDIO_CAMERA} master audio
              {hostSlot.audioTrackSid ? "" : " (not attached yet)"}
            </label>
          </div>

          <RecordingTest
            label={recordWithAudio ? `${recordSlot} + master audio` : recordSlot}
            getStream={getRecordingStream}
            disabled={status !== "connected"}
          />

          <div className="panel form-panel">
            <h2>Receiver log</h2>
            <pre className="log">{log.length > 0 ? log.join("\n") : "No events yet."}</pre>
          </div>

          <div className="panel form-panel">
            <h2>Readiness contract preview</h2>
            <p className="detail">
              What this renderer would report to the backend (v3 plan section 5, Readiness row).
              Renderer {rendererIdRef.current}, generation {rendererGenerationRef.current}. Not yet
              transmitted; A's control socket is Stage 2.
            </p>
            <pre className="log">
              {readiness
                ? JSON.stringify(
                    {
                      ...readiness,
                      reportedAtMs: Math.round(readiness.reportedAtMs),
                      slots: readiness.slots.map((slot) => ({
                        ...slot,
                        lastFrameAgeMs:
                          slot.lastFrameAgeMs === null ? null : Math.round(slot.lastFrameAgeMs),
                      })),
                    },
                    null,
                    2,
                  )
                : "waiting for first tick"}
            </pre>
          </div>
        </div>
      </section>

      <footer>
        Stage 0 receiver. Contextual switching, identity and the compositor canvas arrive in later
        stages. Stage 1 replaces the shared admission secret with producer approval.
      </footer>
    </main>
  );
}

interface SlotTileProps {
  slot: SlotState;
  now: number;
  registerVideo: (cameraId: CameraId, element: HTMLVideoElement | null) => void;
}

function SlotTile({ slot, now, registerVideo }: SlotTileProps) {
  const contract = CAMERA_CONTRACTS[slot.cameraId];
  const age = frameAgeMs(slot, now);
  const videoRef = useCallback(
    (element: HTMLVideoElement | null) => registerVideo(slot.cameraId, element),
    [registerVideo, slot.cameraId],
  );

  return (
    <article className={`slot slot-${slot.videoState}`} aria-label={slot.cameraId}>
      <header className="slot-heading">
        <div>
          <p className="eyebrow">
            {contract.role} · {contract.audioPolicy === "MASTER" ? "MASTER MIC" : "VIDEO ONLY"}
          </p>
          <h3>{slot.cameraId}</h3>
        </div>
        <div className="badges">
          <span className={`badge badge-${slot.videoState}`}>
            {VIDEO_STATE_LABEL[slot.videoState]}
          </span>
          {slot.cameraId === MASTER_AUDIO_CAMERA && (
            <span className={`badge badge-${slot.audioState}`}>
              {AUDIO_STATE_LABEL[slot.audioState]}
            </span>
          )}
        </div>
      </header>

      <div className="slot-video">
        <video ref={videoRef} muted playsInline autoPlay />
        {!slot.videoTrackSid && (
          <p>
            {slot.publisherIdentity
              ? "Publisher bound; waiting for its video track"
              : `Waiting for a publisher whose server metadata says ${slot.cameraId}`}
          </p>
        )}
      </div>

      <dl className="connection-details">
        <dt>Publisher</dt>
        <dd>
          {slot.publisherIdentity ?? "none"}
          {slot.publisherName ? ` (${slot.publisherName})` : ""}
        </dd>
        <dt>Stream epoch</dt>
        <dd>{slot.streamEpoch ?? "none"}</dd>
        <dt>Video SID</dt>
        <dd>{slot.videoTrackSid ?? "none"}</dd>
        {slot.previousVideoTrackSids.length > 0 && (
          <>
            <dt>Earlier SIDs</dt>
            <dd>{slot.previousVideoTrackSids.join(", ")}</dd>
          </>
        )}
        <dt>Last frame</dt>
        <dd>{formatAge(age)}</dd>
        <dt>Frames</dt>
        <dd>
          {slot.frameCount}
          {slot.width ? ` · ${slot.width}×${slot.height}` : ""}
        </dd>
        {slot.conflictIdentities.length > 0 && (
          <>
            <dt>Conflict</dt>
            <dd className="warning">
              Also claimed by {slot.conflictIdentities.join(", ")}; not attached
            </dd>
          </>
        )}
      </dl>
    </article>
  );
}
