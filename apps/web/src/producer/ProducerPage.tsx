import {
  CAMERA_CONTRACTS,
  CAMERA_IDS,
  type CameraBinding,
  type CameraId,
  type IdentityReadiness,
  type ObservationSnapshot,
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
import { describeEvidence, type EvidenceLine } from "./evidenceView";
import { fetchIdentityReadiness, fetchObservations } from "./guestApi";
import { listCameraBindings } from "./pairingApi";
import { PairingPanel } from "./PairingPanel";
import { buildReadiness } from "./readiness";
import { requestReceiverToken } from "./receiverApi";
import {
  applyAuthoritativeBinding,
  applyStallCheck,
  clearAudioTrack,
  clearVideoTrack,
  emptySlots,
  frameAgeMs,
  MASTER_AUDIO_CAMERA,
  markFrame,
  reconcileAuthoritativeBindings,
  setAudioPlayback,
  setAudioTrack,
  setVideoTrack,
  shouldSubscribe,
  type SlotState,
  type Slots,
} from "./slotState";
import { attachVideoTrack, detachVideoTrack, endEvent } from "./transportApi";
import { CameraTransportSequencer } from "./transportSequencer";

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
  const [producerSecret, setProducerSecret] = useState("");
  const [evidence, setEvidence] = useState<ObservationSnapshot | null>(null);
  const [evidenceError, setEvidenceError] = useState<string | null>(null);
  const [identityReadiness, setIdentityReadiness] = useState<IdentityReadiness | null>(null);
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
  const [eventEnding, setEventEnding] = useState(false);

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
  const transportSequencer = useRef(new CameraTransportSequencer());
  const bindingMutationVersion = useRef(0);
  const bindingSnapshotRequest = useRef(0);

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

  // Evidence: poll B's observation snapshot while connected. Read-only, operator-side only.
  useEffect(() => {
    if (status !== "connected" || !bootstrapSecret.trim()) {
      setEvidence(null);
      return;
    }
    let cancelled = false;
    let failures = 0;
    const poll = async () => {
      try {
        const snapshot = await fetchObservations(apiBaseUrl, bootstrapSecret.trim(), connectedEventRef.current);
        if (!cancelled) {
          setEvidence(snapshot);
          setEvidenceError(null);
          failures = 0;
        }
      } catch (error) {
        failures += 1;
        if (!cancelled && failures === 1) {
          setEvidenceError(error instanceof Error ? error.message : String(error));
        }
      }
    };
    void poll();
    const id = window.setInterval(() => void poll(), 500);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [apiBaseUrl, bootstrapSecret, status]);

  // Naming policy and disclosure: B computes the verdict per request (Stage 4 exit gate). Slow poll, never cached here.
  useEffect(() => {
    if (status !== "connected" || !bootstrapSecret.trim()) {
      setIdentityReadiness(null);
      return;
    }
    let cancelled = false;
    const poll = async () => {
      try {
        const verdict = await fetchIdentityReadiness(apiBaseUrl, bootstrapSecret.trim(), connectedEventRef.current);
        if (!cancelled) setIdentityReadiness(verdict);
      } catch {
        if (!cancelled) setIdentityReadiness(null);
      }
    };
    void poll();
    const id = window.setInterval(() => void poll(), 5000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [apiBaseUrl, bootstrapSecret, status]);

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

  const detachVideoMedia = useCallback(
    (cameraId: CameraId) => {
      stopFrameWatcher(cameraId);
      const track = videoTracks.current.get(cameraId);
      if (track) {
        track.detach();
        videoTracks.current.delete(cameraId);
      }
      const element = videoElements.current.get(cameraId);
      if (element) element.srcObject = null;
    },
    [stopFrameWatcher],
  );

  const detachVideo = useCallback(
    (cameraId: CameraId) => {
      detachVideoMedia(cameraId);
      commitSlots((s) => clearVideoTrack(s, cameraId));
    },
    [commitSlots, detachVideoMedia],
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
    bindingMutationVersion.current += 1;
    setSlots(slotsRef.current);
    setUnassigned({});
    ignoredPublications.current.clear();
  }, [detachAudio, detachVideo]);

  const synchronizeBindings = useCallback(async (): Promise<boolean> => {
    const secret = producerSecret.trim();
    if (!secret) throw new Error("Producer secret is required for authoritative camera bindings");
    const requestId = ++bindingSnapshotRequest.current;
    const mutationVersion = bindingMutationVersion.current;
    const bindings = await listCameraBindings(
      apiBaseUrl,
      secret,
      connectedEventRef.current,
    );
    if (
      requestId !== bindingSnapshotRequest.current ||
      mutationVersion !== bindingMutationVersion.current
    ) {
      appendLog("Ignored a binding snapshot superseded by newer transport state");
      return false;
    }
    const previous = slotsRef.current;
    const snapshot = reconcileAuthoritativeBindings(
      previous,
      bindings,
      connectedEventRef.current,
    );
    for (const cameraId of CAMERA_IDS) {
      const before = previous[cameraId];
      const after = snapshot.slots[cameraId];
      if (
        before.videoTrackSid !== null &&
        (before.videoTrackSid !== after.videoTrackSid ||
          before.publisherIdentity !== after.publisherIdentity)
      ) {
        detachVideoMedia(cameraId);
      }
    }
    slotsRef.current = snapshot.slots;
    bindingMutationVersion.current += 1;
    setSlots(snapshot.slots);
    appendLog(
      `Authoritative binding snapshot: ${bindings.length} slot${bindings.length === 1 ? "" : "s"}`,
    );
    return true;
  }, [apiBaseUrl, appendLog, detachVideoMedia, producerSecret]);

  async function refreshBindings(): Promise<void> {
    if (!(await synchronizeBindings())) await synchronizeBindings();
  }

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

  async function handleParticipant(
    participant: RemoteParticipant,
    refreshSnapshot = true,
  ): Promise<void> {
    if (refreshSnapshot) {
      try {
        await refreshBindings();
      } catch (error) {
        const reason = `binding check failed: ${error instanceof Error ? error.message : String(error)}`;
        setUnassigned((previous) => ({ ...previous, [participant.identity]: reason }));
        appendLog(`Unassigned ${participant.identity}: ${reason}`);
        participant.trackPublications.forEach((publication) =>
          (publication as RemoteTrackPublication).setSubscribed(false),
        );
        return;
      }
    }

    const metadata = parsePublisherMetadata(participant.metadata);
    let reason: string | null = null;
    if (!metadata) {
      reason = "missing or invalid server metadata";
    } else if (metadata.eventId !== connectedEventRef.current) {
      reason = `metadata event "${metadata.eventId}" does not match "${connectedEventRef.current}"`;
    } else {
      const holder = slotsRef.current[metadata.cameraId].publisherIdentity;
      if (holder !== participant.identity) {
        reason = holder
          ? `${metadata.cameraId} belongs to ${holder}, not this participant`
          : `${metadata.cameraId} has no approved binding`;
      }
    }

    if (reason) {
      setUnassigned((previous) => ({ ...previous, [participant.identity]: reason }));
      appendLog(`Unassigned ${participant.identity}: ${reason}`);
    } else {
      setUnassigned((previous) => {
        const { [participant.identity]: _dropped, ...rest } = previous;
        return rest;
      });
      appendLog(
        `${metadata?.cameraId}: verified ${participant.identity} against the authoritative binding`,
      );
    }
    participant.trackPublications.forEach((publication) =>
      evaluatePublication(publication as RemoteTrackPublication, participant),
    );
  }

  function applyTransportBinding(binding: CameraBinding): boolean {
    const reconciled = applyAuthoritativeBinding(
      slotsRef.current,
      binding,
      connectedEventRef.current,
    );
    if (reconciled.result.kind === "stale") {
      appendLog(`${binding.cameraId}: ignored stale transport response at epoch ${binding.streamEpoch}`);
      return false;
    }
    if (reconciled.result.kind === "conflict") {
      appendLog(
        `CONFLICT: backend returned ${binding.participantIdentity} for ${binding.cameraId}; ` +
          `local authoritative holder is ${reconciled.result.holder}`,
      );
      return false;
    }
    slotsRef.current = reconciled.slots;
    bindingMutationVersion.current += 1;
    setSlots(reconciled.slots);
    return true;
  }

  async function reportVideoDetach(
    cameraId: CameraId,
    participantIdentity: string,
    trackSid: string,
  ): Promise<void> {
    const mutation = await detachVideoTrack(
      apiBaseUrl,
      producerSecret.trim(),
      connectedEventRef.current,
      cameraId,
      participantIdentity,
      trackSid,
    );
    applyTransportBinding(mutation.binding);
    appendLog(`${cameraId}: ${mutation.outcome} for video track ${trackSid}`);
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
      void transportSequencer.current
        .enqueue(cameraId, async () => {
          const mutation = await attachVideoTrack(
            apiBaseUrl,
            producerSecret.trim(),
            connectedEventRef.current,
            cameraId,
            participant.identity,
            publication.trackSid,
          );
          if (
            mutation.binding.currentVideoTrackSid !== publication.trackSid ||
            !applyTransportBinding(mutation.binding)
          ) {
            publication.setSubscribed(false);
            return;
          }
          const previous = videoTracks.current.get(cameraId);
          if (previous && previous !== videoTrack) previous.detach();
          videoTracks.current.set(cameraId, videoTrack);
          const element = videoElements.current.get(cameraId);
          if (element) {
            videoTrack.attach(element);
            watchFrames(element, cameraId);
          }
          commitSlots((s) => setVideoTrack(s, cameraId, publication.trackSid));
          appendLog(
            `${cameraId}: ${mutation.outcome} ${publication.trackSid} at epoch ${mutation.binding.streamEpoch}`,
          );
        })
        .catch((error) => {
          publication.setSubscribed(false);
          appendLog(
            `${cameraId}: refused video ${publication.trackSid}; ` +
              `${error instanceof Error ? error.message : String(error)}`,
          );
        });
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
    const metadata = parsePublisherMetadata(participant.metadata);
    for (const [cameraId, known] of videoTracks.current) {
      if (known === track) {
        detachVideo(cameraId);
        appendLog(`${cameraId}: video track ${publication.trackSid} unsubscribed (${participant.identity})`);
      }
    }
    if (metadata?.eventId === connectedEventRef.current) {
      void transportSequencer.current
        .enqueue(metadata.cameraId, () =>
          reportVideoDetach(metadata.cameraId, participant.identity, publication.trackSid),
        )
        .catch((error) =>
          appendLog(
            `${metadata.cameraId}: detach report failed for ${publication.trackSid}; ` +
              `${error instanceof Error ? error.message : String(error)}`,
          ),
        );
    }
  }

  function onParticipantDisconnected(participant: RemoteParticipant) {
    for (const cameraId of CAMERA_IDS) {
      const slot = slotsRef.current[cameraId];
      if (slot.publisherIdentity === participant.identity) {
        if (slot.videoTrackSid) {
          void transportSequencer.current
            .enqueue(cameraId, () =>
              reportVideoDetach(cameraId, participant.identity, slot.videoTrackSid as string),
            )
            .catch((error) =>
              appendLog(
                `${cameraId}: disconnect report failed; ` +
                  `${error instanceof Error ? error.message : String(error)}`,
              ),
            );
        }
        detachVideo(cameraId);
        if (cameraId === MASTER_AUDIO_CAMERA) detachAudio();
        appendLog(`${cameraId}: publisher ${participant.identity} left; slot keeps its ID and waits`);
      }
    }
    setUnassigned((previous) => {
      const { [participant.identity]: _dropped, ...rest } = previous;
      return rest;
    });
  }

  const reportCurrentDetaches = useCallback(async () => {
    const secret = producerSecret.trim();
    if (!secret) return;
    const event = connectedEventRef.current;
    const active = CAMERA_IDS.flatMap((cameraId) => {
      const slot = slotsRef.current[cameraId];
      return slot.publisherIdentity && slot.videoTrackSid
        ? [{ cameraId, participantIdentity: slot.publisherIdentity, trackSid: slot.videoTrackSid }]
        : [];
    });
    const results = await Promise.allSettled(
      active.map(({ cameraId, participantIdentity, trackSid }) =>
        transportSequencer.current.enqueue(cameraId, () =>
          detachVideoTrack(
            apiBaseUrl,
            secret,
            event,
            cameraId,
            participantIdentity,
            trackSid,
          ),
        ),
      ),
    );
    results.forEach((result, index) => {
      if (result.status === "rejected") {
        appendLog(
          `${active[index].cameraId}: final detach report failed; ` +
            `${result.reason instanceof Error ? result.reason.message : String(result.reason)}`,
        );
      }
    });
    await transportSequencer.current.drain();
  }, [apiBaseUrl, appendLog, producerSecret]);

  const disconnect = useCallback(
    async (announce = true) => {
      const room = roomRef.current;
      roomRef.current = null;
      if (room) {
        await reportCurrentDetaches();
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
    [appendLog, reportCurrentDetaches, resetSlots],
  );

  useEffect(() => {
    return () => {
      void roomRef.current?.disconnect();
    };
  }, []);

  async function connect() {
    const secret = bootstrapSecret.trim();
    const transportSecret = producerSecret.trim();
    const name = displayName.trim();
    if (!secret || !transportSecret || !eventId || !name) {
      setStatus("error");
      setDetail(
        "API URL, event ID, display name, Stage 0 secret and producer secret are required.",
      );
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
      await refreshBindings();

      room = new Room({ adaptiveStream: false, dynacast: false });
      roomRef.current = room;
      room
        .on(RoomEvent.ParticipantConnected, (participant) => {
          appendLog(`Participant joined: ${participant.identity}`);
          void handleParticipant(participant);
        })
        .on(RoomEvent.ParticipantDisconnected, onParticipantDisconnected)
        .on(RoomEvent.ParticipantMetadataChanged, (_metadata, participant) => {
          if (participant instanceof RemoteParticipant) void handleParticipant(participant);
        })
        .on(RoomEvent.TrackPublished, (_publication, participant) => {
          void handleParticipant(participant);
        })
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
          setDetail("Reconnected. Reconciling authoritative bindings and publishers.");
          void (async () => {
            try {
              await refreshBindings();
              roomRef.current?.remoteParticipants.forEach((participant) => {
                void handleParticipant(participant, false);
              });
            } catch (error) {
              setDetail(
                `Media reconnected but binding reconciliation failed: ` +
                  `${error instanceof Error ? error.message : String(error)}`,
              );
            }
          })();
        })
        .on(RoomEvent.ConnectionStateChanged, (state) => appendLog(`Connection state: ${state}`))
        .on(RoomEvent.Disconnected, (reason) => {
          void reportCurrentDetaches();
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

      await refreshBindings();
      room.remoteParticipants.forEach((participant) => {
        void handleParticipant(participant, false);
      });

      try {
        await room.startAudio();
      } catch {
        // Autoplay policy: the Enable audio button retries inside a user gesture.
      }
      noteAudioPlayback(room.canPlaybackAudio);

      setStatus("connected");
      setDetail("Connected subscribe-only. Tiles follow backend-approved bindings and track epochs.");
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

  async function finishEvent() {
    const secret = producerSecret.trim();
    if (!secret || eventEnding) return;
    if (
      !window.confirm(
        `End ${eventId}? This disconnects the receiver and deletes pairing, identity and live event state.`,
      )
    ) {
      return;
    }
    setEventEnding(true);
    setDetail("Stopping media before the event cleanup…");
    try {
      await disconnect(false);
      const receipt = await endEvent(apiBaseUrl, secret, eventId);
      setEvidence(null);
      setStatus("idle");
      setDetail(
        `Event ended. Deleted ${receipt.bindingsDeleted} binding(s), ` +
          `${receipt.referencesDeleted} identity reference(s), and revoked ` +
          `${receipt.controlSessionsRevoked} control session(s).`,
      );
      appendLog(`Event ${eventId} ended and its in-memory state was cleaned up`);
    } catch (error) {
      setStatus("error");
      setDetail(`Event cleanup failed: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setEventEnding(false);
    }
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
    eventEnding ||
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
        <p className="eyebrow">CUE · STAGE 3 · PERSON A + D</p>
        <h1>Authoritative Mac director</h1>
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

            <label>
              Producer secret (this Mac only; enables pairing and the control link)
              <input
                type="password"
                value={producerSecret}
                disabled={controlsLocked || eventEnding}
                autoComplete="off"
                onChange={(event) => setProducerSecret(event.target.value)}
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
              <button
                type="button"
                className="danger"
                onClick={() => void finishEvent()}
                disabled={!producerSecret.trim() || eventEnding}
              >
                {eventEnding ? "Ending event…" : "End event + delete live state"}
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

          <PairingPanel apiBaseUrl={apiBaseUrl} eventId={eventId} producerSecret={producerSecret} onLog={appendLog} />

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
            apiBaseUrl={apiBaseUrl}
            producerSecret={producerSecret}
            identityReadiness={identityReadiness}
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
            <p className="detail">
              Evidence:{" "}
              {evidence
                ? `snapshot ${Math.round((Date.now() - evidence.nowMs) / 100) / 10} s old · gallery v${evidence.galleryVersion}`
                : evidenceError
                  ? `unavailable (${evidenceError})`
                  : "not polling"}
            </p>
            <div className="slots">
              {CAMERA_IDS.map((cameraId) => (
                <SlotTile
                  key={cameraId}
                  slot={slots[cameraId]}
                  now={now}
                  registerVideo={registerVideo}
                  evidence={
                    evidence
                      ? describeEvidence(
                          evidence.cameras.find((view) => view.cameraId === cameraId) ?? null,
                          evidence.nowMs,
                          slots[cameraId].streamEpoch,
                        )
                      : null
                  }
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
  evidence: EvidenceLine | null;
}

function SlotTile({ slot, now, registerVideo, evidence }: SlotTileProps) {
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
        <dt>Binding revision</dt>
        <dd>{slot.bindingRevision ?? "none"}</dd>
        <dt>Video SID</dt>
        <dd>{slot.videoTrackSid ?? "none"}</dd>
        {slot.previousVideoTrackSids.length > 0 && (
          <>
            <dt>Earlier SIDs</dt>
            <dd>{slot.previousVideoTrackSids.join(", ")}</dd>
          </>
        )}
        <dt>Who</dt>
        <dd className={evidence ? `evidence evidence-${evidence.tone}` : undefined}>
          {evidence ? (
            <>
              <strong>{evidence.headline}</strong>
              <br />
              <span>{evidence.detail}</span>
            </>
          ) : (
            "evidence off"
          )}
        </dd>
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
