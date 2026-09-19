import {
  CAMERA_IDS,
  type CameraId,
  type ControlServerMessage,
  type ControlSnapshot,
  type OperatorMode,
  type ProgramSource,
  type ReceiverReadiness,
  type RenderAck,
  type RenderCommand,
  SLATE,
} from "@cue/contracts";
import { useCallback, useEffect, useRef, useState } from "react";

import { pickRecordingMimeType, RECORDING_MIME_CANDIDATES, recordingFileName, formatBytes, formatDuration } from "../recording/recorderSupport";
import { initialRecorderStatus, ProgramRecorder, type RecorderStatus } from "../recording/programRecorder";
import {
  assembleRecording,
  findInterrupted,
  MemoryRecordingStore,
  openIndexedDbRecordingStore,
  type RecordingMeta,
  type RecordingStore,
} from "../recording/recordingStore";
import {
  ControlSocketClient,
  requestControlSession,
  setControlMode,
  takeCamera,
} from "../producer/controlClient";
import { drawSlate, drawVideoFrame, isThrottled, PROGRAM_HEIGHT, PROGRAM_WIDTH } from "./canvasRenderer";
import {
  ackToAcknowledgement,
  backendClockOffsetMs,
  commandToDecision,
  idempotencyKey,
  reconciliationFor,
} from "./controlAdapter";
import {
  acceptSuggestion,
  confirmDraw,
  createSwitcher,
  evaluateDecision,
  expirePendingAck,
  isLive,
  operatorHold,
  operatorResume,
  operatorSlate,
  operatorTake,
  resetForGeneration,
  runHealthCheck,
  type Step,
  type SwitcherState,
  syncControlState,
} from "./switcher";

export interface ProgramPanelProps {
  eventId: string;
  rendererId: string;
  rendererGeneration: number;
  /** LiveKit media link is up. */
  connected: boolean;
  apiBaseUrl: string;
  /** Empty string keeps the control link off; the compositor then runs in local manual mode. */
  producerSecret: string;
  readiness: ReceiverReadiness | null;
  getSourceElement: (cameraId: CameraId) => HTMLVideoElement | null;
  getMasterAudioTrack: () => MediaStreamTrack | null;
  onProgramChange: (source: ProgramSource) => void;
  onAck: (ack: RenderAck) => void;
  onLog: (line: string) => void;
}

const DRAW_INTERVAL_MS = 33;
const HEALTH_INTERVAL_MS = 250;
const KEY_FOR_CAMERA: Record<CameraId, string> = { "CAM-HOST": "1", "CAM-GUEST": "2", "CAM-WIDE": "3" };
const MODE_HINT: Record<OperatorMode, string> = {
  SETUP: "no automatic cuts",
  READY: "preflight passed",
  ASSIST: "policy suggests, you press TAKE",
  AUTO: "policy executes validated decisions; HOLD to stop it",
  MANUAL_HOLD: "you own the shot; policy is ignored; health failover stays on",
  DEGRADED: "some capability is unavailable",
  ENDED: "event ended",
};

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable;
}

/**
 * The programme output and the operator's manual controls (v3 plan, Stage 2 D).
 * Draws one selected source to a 1280x720 canvas with hard cuts, keeps every
 * source decoding, keeps A's audio fixed on the output, acknowledges a cut only
 * after the first drawn frame, and records the output to persisted chunks.
 */
type LinkStatus = "off" | "connecting" | "connected" | "reconnecting" | "error";

interface LinkState {
  status: LinkStatus;
  snapshot: ControlSnapshot | null;
  lastError: string | null;
  lastErrorAtMs: number | null;
}

const LINK_ERROR_TTL_MS = 8000;

export function ProgramPanel({
  eventId,
  rendererId,
  rendererGeneration,
  connected,
  apiBaseUrl,
  producerSecret,
  readiness,
  getSourceElement,
  getMasterAudioTrack,
  onProgramChange,
  onAck,
  onLog,
}: ProgramPanelProps) {
  const [switcher, setSwitcher] = useState<SwitcherState>(() =>
    createSwitcher({ eventId, rendererId, rendererGeneration, now: performance.now() }),
  );
  const [drawIntervalMs, setDrawIntervalMs] = useState(0);
  const [throttled, setThrottled] = useState(false);
  const [recorderStatus, setRecorderStatus] = useState<RecorderStatus>(initialRecorderStatus);
  const [storeKind, setStoreKind] = useState<"indexeddb" | "memory" | "opening">("opening");
  const [interrupted, setInterrupted] = useState<RecordingMeta[]>([]);
  const [chosenMimeType, setChosenMimeType] = useState<string | null>(null);
  const [noFrameSince, setNoFrameSince] = useState<number | null>(null);
  const [link, setLink] = useState<LinkState>({ status: "off", snapshot: null, lastError: null, lastErrorAtMs: null });
  const [linkEpoch, setLinkEpoch] = useState(0);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const switcherRef = useRef(switcher);
  const readinessRef = useRef(readiness);
  readinessRef.current = readiness;
  const lastDrawAtRef = useRef<number | null>(null);
  const noFrameSinceRef = useRef<number | null>(null);
  const recorderRef = useRef<ProgramRecorder | null>(null);
  const storeRef = useRef<RecordingStore | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const audioDestinationRef = useRef<MediaStreamAudioDestinationNode | null>(null);
  const audioSourceRef = useRef<{ trackId: string; node: MediaStreamAudioSourceNode } | null>(null);
  const lastSourceRef = useRef<ProgramSource | null>(null);
  const lastStatsAtRef = useRef(0);
  const refreshAudioRef = useRef<() => void>(() => {});
  const clientRef = useRef<ControlSocketClient | null>(null);
  const linkConnectedRef = useRef(false);
  const seenDecisionIdsRef = useRef(new Set<string>());
  const nonceRef = useRef(0);

  const noteLinkError = useCallback((message: string) => {
    setLink((previous) => ({ ...previous, lastError: message, lastErrorAtMs: performance.now() }));
  }, []);

  const sendToBackend = useCallback(
    (action: (client: ControlSocketClient) => void, label: string) => {
      const client = clientRef.current;
      if (!client || !linkConnectedRef.current) return false;
      try {
        action(client);
        return true;
      } catch (error) {
        noteLinkError(`${label} not sent: ${error instanceof Error ? error.message : String(error)}`);
        return false;
      }
    },
    [noteLinkError],
  );

  const applyStep = useCallback(
    (step: Step) => {
      switcherRef.current = step.state;
      setSwitcher(step.state);
      for (const line of step.log) onLog(line);
      const ack = step.ack;
      if (!ack) return;
      onAck(ack);
      const offset = backendClockOffsetMs(performance.now(), Date.now());
      if (ack.issuerDecisionId !== null) {
        const acknowledgement = ackToAcknowledgement(ack, offset);
        if (acknowledgement) {
          sendToBackend((client) => client.acknowledge(acknowledgement), `ACK ${ack.issuerDecisionId}`);
        }
      } else if (ack.outcome === "APPLIED") {
        // A local cut (slate, failover, revert) is reported as the compositor's actual state.
        const program = step.state.program;
        sendToBackend(
          (client) => client.reconcile(reconciliationFor(program, step.state.controlGeneration, Date.now())),
          "reconcile",
        );
      }
    },
    [onAck, onLog, sendToBackend],
  );

  const handleCommand = useCallback(
    (command: RenderCommand) => {
      if (seenDecisionIdsRef.current.has(command.decisionId)) return;
      seenDecisionIdsRef.current.add(command.decisionId);
      const now = performance.now();
      const withClock: SwitcherState = {
        ...switcherRef.current,
        backendClockOffsetMs: backendClockOffsetMs(now, Date.now()),
      };
      const step = evaluateDecision(withClock, commandToDecision(command), readinessRef.current, now);
      applyStep(step);
    },
    [applyStep],
  );

  const handleServerMessage = useCallback(
    (message: ControlServerMessage) => {
      switch (message.type) {
        case "control.authenticated":
          onLog(`Control link authenticated as ${message.role}`);
          break;
        case "control.state": {
          setLink((previous) => ({ ...previous, snapshot: message.state }));
          const step = syncControlState(
            switcherRef.current,
            {
              controlGeneration: message.state.controlGeneration,
              mode: message.state.mode,
              modeRevision: message.state.modeRevision,
            },
            performance.now(),
          );
          if (step.state !== switcherRef.current) applyStep(step);
          break;
        }
        case "render.command":
          handleCommand(message.command);
          break;
        case "control.error":
          noteLinkError(`${message.code}${message.message ? `: ${message.message}` : ""}`);
          onLog(`Control link error ${message.code}${message.message ? `: ${message.message}` : ""}`);
          if (message.code === "INVALID_SESSION" || message.code === "SESSION_EXPIRED" || message.code === "AUTH_REQUIRED") {
            setLinkEpoch((value) => value + 1);
          }
          break;
        case "control.pong":
        case "receiver.readiness":
          break;
      }
    },
    [applyStep, handleCommand, noteLinkError, onLog],
  );

  // Event or renderer generation changed: never resume AUTO, forget pending work.
  useEffect(() => {
    const current = switcherRef.current;
    if (current.eventId !== eventId) {
      const fresh = createSwitcher({ eventId, rendererId, rendererGeneration, now: performance.now() });
      switcherRef.current = fresh;
      setSwitcher(fresh);
      return;
    }
    if (current.rendererGeneration !== rendererGeneration) {
      const reset = resetForGeneration(current, rendererGeneration);
      switcherRef.current = reset;
      setSwitcher(reset);
      onLog(`Renderer generation ${rendererGeneration}: mode back to ASSIST, revision ${reset.modeRevision}`);
    }
  }, [eventId, rendererGeneration, rendererId, onLog]);

  // Tell the readiness builder what is on the canvas.
  useEffect(() => {
    if (lastSourceRef.current !== switcher.program.source) {
      lastSourceRef.current = switcher.program.source;
      onProgramChange(switcher.program.source);
    }
  }, [switcher.program.source, onProgramChange]);

  // Control link to A's backend: session token, authenticated socket, bounded reconnect.
  useEffect(() => {
    const secret = producerSecret.trim();
    if (!secret || !connected || rendererGeneration < 1) {
      clientRef.current?.stop();
      clientRef.current = null;
      linkConnectedRef.current = false;
      setLink({ status: "off", snapshot: null, lastError: null, lastErrorAtMs: null });
      return;
    }
    let cancelled = false;
    setLink((previous) => ({ ...previous, status: "connecting" }));
    (async () => {
      try {
        const session = await requestControlSession(apiBaseUrl, secret, eventId, "DIRECTOR");
        if (cancelled) return;
        const client = new ControlSocketClient({
          apiBaseUrl,
          eventId,
          token: session.token,
          onMessage: handleServerMessage,
          onConnectionChange: (isConnected) => {
            linkConnectedRef.current = isConnected;
            setLink((previous) => ({
              ...previous,
              status: isConnected ? "connected" : previous.status === "off" ? "off" : "reconnecting",
            }));
            if (isConnected) {
              const program = switcherRef.current.program;
              sendToBackend(
                (c) => c.reconcile(reconciliationFor(program, switcherRef.current.controlGeneration, Date.now())),
                "reconcile on connect",
              );
              if (readinessRef.current) {
                const readiness = readinessRef.current;
                sendToBackend((c) => c.reportReadiness(readiness), "readiness");
              }
            }
          },
        });
        clientRef.current = client;
        client.start();
        onLog(`Control session issued (${session.role}, ${session.expiresInSeconds} s); connecting socket`);
      } catch (error) {
        if (cancelled) return;
        const message = error instanceof Error ? error.message : String(error);
        setLink({ status: "error", snapshot: null, lastError: message, lastErrorAtMs: performance.now() });
        onLog(`Control link failed: ${message}; compositor stays in local manual mode`);
      }
    })();
    return () => {
      cancelled = true;
      clientRef.current?.stop();
      clientRef.current = null;
      linkConnectedRef.current = false;
    };
  }, [apiBaseUrl, connected, eventId, handleServerMessage, linkEpoch, onLog, producerSecret, rendererGeneration, sendToBackend]);

  // Readiness goes up on every tick while the link is connected.
  useEffect(() => {
    if (!readiness || !linkConnectedRef.current) return;
    sendToBackend((client) => client.reportReadiness(readiness), "readiness");
  }, [readiness, sendToBackend]);

  // Keepalive.
  useEffect(() => {
    const id = window.setInterval(() => {
      if (linkConnectedRef.current) sendToBackend((client) => client.ping(), "ping");
    }, 15_000);
    return () => window.clearInterval(id);
  }, [sendToBackend]);

  // Persistence store and recorder.
  useEffect(() => {
    let cancelled = false;
    const probe = pickRecordingMimeType((type) =>
      typeof MediaRecorder !== "undefined" ? MediaRecorder.isTypeSupported(type) : false,
    );
    setChosenMimeType(probe);
    (async () => {
      let store: RecordingStore;
      try {
        store = await openIndexedDbRecordingStore();
        if (cancelled) return;
        setStoreKind("indexeddb");
      } catch (error) {
        store = new MemoryRecordingStore();
        if (cancelled) return;
        setStoreKind("memory");
        onLog(`IndexedDB unavailable (${error instanceof Error ? error.message : String(error)}); recording chunks stay in memory only`);
      }
      storeRef.current = store;
      recorderRef.current = new ProgramRecorder(store, setRecorderStatus);
      try {
        const list = await store.listRecordings();
        const found = findInterrupted(list, null);
        if (!cancelled) setInterrupted(found);
        if (found.length > 0) onLog(`${found.length} interrupted recording(s) found from an earlier session`);
      } catch {
        // listing is best effort
      }
    })();
    return () => {
      cancelled = true;
      recorderRef.current?.dispose();
      recorderRef.current = null;
      void audioContextRef.current?.close();
    };
  }, [onLog]);

  // Draw loop. setInterval rather than requestAnimationFrame so a hidden tab keeps drawing (throttled, and reported).
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const draw = () => {
      const now = performance.now();
      const last = lastDrawAtRef.current;
      if (last !== null) {
        const interval = now - last;
        const slow = isThrottled(interval);
        // Re-render the stats at most twice a second, or immediately when throttling starts.
        if (slow || now - lastStatsAtRef.current > 500) {
          lastStatsAtRef.current = now;
          setDrawIntervalMs(interval);
          setThrottled(slow);
        }
      }
      lastDrawAtRef.current = now;

      const state = switcherRef.current;
      const source = state.program.source;
      if (source === SLATE) {
        drawSlate(ctx, ["CUE", eventId, "programme standing by"]);
        noFrameSinceRef.current = null;
        setNoFrameSince(null);
        const step = confirmDraw(state, { source: SLATE, videoTrackSid: null }, now);
        if (step.state !== state) applyStep(step);
        return;
      }

      const element = getSourceElement(source);
      const result = element ? drawVideoFrame(ctx, element) : "no-frame";
      if (result === "drawn") {
        noFrameSinceRef.current = null;
        setNoFrameSince(null);
        const slot = readinessRef.current?.slots.find((candidate) => candidate.cameraId === source);
        const step = confirmDraw(state, { source, videoTrackSid: slot?.videoTrackSid ?? null }, now);
        if (step.state !== state) applyStep(step);
      } else {
        if (noFrameSinceRef.current === null) {
          noFrameSinceRef.current = now;
          setNoFrameSince(now);
        }
      }
    };

    const id = window.setInterval(draw, DRAW_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [applyStep, eventId, getSourceElement]);

  // Health check on the readiness cadence. Failover runs in every mode.
  useEffect(() => {
    const id = window.setInterval(() => {
      const now = performance.now();
      const expired = expirePendingAck(switcherRef.current, readinessRef.current, now);
      if (expired.state !== switcherRef.current) applyStep(expired);
      const step = runHealthCheck(switcherRef.current, readinessRef.current, now);
      if (step.state !== switcherRef.current) applyStep(step);
      refreshAudioRef.current();
    }, HEALTH_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [applyStep]);

  /** Operator TAKE: through the backend when the control link is up, locally otherwise. */
  const requestTake = useCallback(
    (cameraId: CameraId) => {
      const now = performance.now();
      const state = switcherRef.current;
      const slot = readinessRef.current?.slots.find((candidate) => candidate.cameraId === cameraId);
      if (linkConnectedRef.current && slot?.streamEpoch) {
        nonceRef.current += 1;
        void takeCamera(
          apiBaseUrl,
          producerSecret.trim(),
          eventId,
          cameraId,
          slot.streamEpoch,
          state.modeRevision,
          idempotencyKey("take", Date.now(), `${rendererId}-${nonceRef.current}`),
        )
          .then((result) => {
            if (result.renderCommand) handleCommand(result.renderCommand);
          })
          .catch((error) => {
            const message = error instanceof Error ? error.message : String(error);
            noteLinkError(`TAKE ${cameraId} refused: ${message}`);
            onLog(`Backend refused TAKE ${cameraId}: ${message}`);
          });
        return;
      }
      applyStep(operatorTake(state, cameraId, readinessRef.current, now));
    },
    [apiBaseUrl, applyStep, eventId, handleCommand, noteLinkError, onLog, producerSecret, rendererId],
  );

  /** Mode changes (HOLD, ASSIST, AUTO): through the backend when linked, locally otherwise. */
  const requestMode = useCallback(
    (mode: Extract<OperatorMode, "ASSIST" | "AUTO" | "MANUAL_HOLD">) => {
      const now = performance.now();
      const state = switcherRef.current;
      if (linkConnectedRef.current) {
        nonceRef.current += 1;
        void setControlMode(
          apiBaseUrl,
          producerSecret.trim(),
          eventId,
          mode,
          state.modeRevision,
          idempotencyKey("mode", Date.now(), `${rendererId}-${nonceRef.current}`),
        )
          .then((result) => {
            const step = syncControlState(
              switcherRef.current,
              {
                controlGeneration: result.state.controlGeneration,
                mode: result.state.mode,
                modeRevision: result.state.modeRevision,
              },
              performance.now(),
            );
            if (step.state !== switcherRef.current) applyStep(step);
            setLink((previous) => ({ ...previous, snapshot: result.state }));
          })
          .catch((error) => {
            const message = error instanceof Error ? error.message : String(error);
            noteLinkError(`Mode ${mode} refused: ${message}`);
            onLog(`Backend refused mode ${mode}: ${message}`);
          });
        return;
      }
      if (mode === "MANUAL_HOLD") applyStep(operatorHold(state, now));
      else applyStep(operatorResume(state, mode, now));
    },
    [apiBaseUrl, applyStep, eventId, noteLinkError, onLog, producerSecret, rendererId],
  );

  /** Emergency slate is always local: it must work with the backend gone. Reconciled afterwards. */
  const requestSlate = useCallback(() => {
    applyStep(operatorSlate(switcherRef.current, performance.now()));
  }, [applyStep]);

  // Keyboard: 1/2/3 take, 0 slate, H hold toggle. Ignored while typing.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (isTypingTarget(event.target) || event.metaKey || event.ctrlKey || event.altKey) return;
      const state = switcherRef.current;
      if (event.key === "1" || event.key === "2" || event.key === "3") {
        const cameraId = CAMERA_IDS.find((id) => KEY_FOR_CAMERA[id] === event.key);
        if (cameraId) requestTake(cameraId);
      } else if (event.key === "0") {
        requestSlate();
      } else if (event.key === "h" || event.key === "H") {
        requestMode(state.mode === "MANUAL_HOLD" ? "ASSIST" : "MANUAL_HOLD");
      } else {
        return;
      }
      event.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [requestMode, requestSlate, requestTake]);

  /** Keep the recorder's audio track stable: route whatever master track exists into one destination node. */
  function refreshAudioSource() {
    // (body below; the health ticker calls the latest version through refreshAudioRef)
    const context = audioContextRef.current;
    const destination = audioDestinationRef.current;
    if (!context || !destination) return;
    const track = getMasterAudioTrack();
    const currentId = audioSourceRef.current?.trackId ?? null;
    if ((track?.id ?? null) === currentId) return;
    audioSourceRef.current?.node.disconnect();
    audioSourceRef.current = null;
    if (track) {
      const node = context.createMediaStreamSource(new MediaStream([track]));
      node.connect(destination);
      audioSourceRef.current = { trackId: track.id, node };
      onLog(`Programme audio now fed by master track ${track.id.slice(0, 8)}; output track unchanged`);
    } else {
      onLog("Master audio track gone; programme audio output continues silent, no switch to another mic");
    }
  }

  refreshAudioRef.current = refreshAudioSource;

  async function ensureProgramAudioTrack(): Promise<MediaStreamTrack | null> {
    if (!audioContextRef.current) {
      const context = new AudioContext();
      audioContextRef.current = context;
      audioDestinationRef.current = context.createMediaStreamDestination();
    }
    await audioContextRef.current.resume();
    refreshAudioSource();
    return audioDestinationRef.current?.stream.getAudioTracks()[0] ?? null;
  }

  async function startRecording() {
    const canvas = canvasRef.current;
    const recorder = recorderRef.current;
    if (!canvas || !recorder || !chosenMimeType) {
      onLog("Cannot record: canvas, store or a supported MIME type is missing");
      return;
    }
    const video = canvas.captureStream(30).getVideoTracks()[0];
    const tracks: MediaStreamTrack[] = video ? [video] : [];
    const audio = await ensureProgramAudioTrack();
    if (audio) tracks.push(audio);
    else onLog("Recording without audio: no master track attached yet");
    try {
      await recorder.start(new MediaStream(tracks), eventId, chosenMimeType);
      onLog(`Programme recording started (${chosenMimeType}, ${audio ? "with" : "without"} master audio)`);
    } catch (error) {
      onLog(`Recording failed to start: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  async function stopRecording() {
    const result = await recorderRef.current?.stop();
    if (result) {
      onLog(
        `Programme recording stopped: ${result.chunkCount} chunks, ${formatBytes(result.bytes)}, ${formatDuration(result.durationMs)}, ${result.fromStore ? "assembled from persisted chunks" : "assembled from memory"}`,
      );
    }
  }

  function downloadResult() {
    const result = recorderStatus.result;
    if (!result) return;
    const anchor = document.createElement("a");
    anchor.href = result.url;
    anchor.download = recordingFileName(`programme-${eventId}`, result.mimeType, new Date());
    anchor.click();
  }

  async function recoverInterrupted(meta: RecordingMeta) {
    const store = storeRef.current;
    if (!store) return;
    try {
      const chunks = await store.readChunks(meta.recordingId);
      const blob = assembleRecording(chunks, meta.mimeType);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = recordingFileName(`recovered-${meta.eventId}`, meta.mimeType, new Date(meta.startedAt));
      anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
      await store.updateRecording({ ...meta, status: "interrupted", endedAt: meta.endedAt ?? Date.now() });
      onLog(`Recovered ${meta.recordingId}: ${chunks.length} chunks, ${formatBytes(blob.size)}. Play it before trusting it; an interrupted file may need repair`);
    } catch (error) {
      onLog(`Recovery failed for ${meta.recordingId}: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  async function deleteInterrupted(meta: RecordingMeta) {
    const store = storeRef.current;
    if (!store) return;
    await store.deleteRecording(meta.recordingId);
    setInterrupted((list) => list.filter((item) => item.recordingId !== meta.recordingId));
  }

  function downloadTimeline() {
    const blob = new Blob([JSON.stringify({ eventId, rendererId, rendererGeneration, exportedAt: new Date().toISOString(), acks: switcher.acks }, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `cue-decisions-${eventId}-${Date.now()}.json`;
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
  }

  const now = performance.now();
  const live = isLive(switcher);
  const program = switcher.program;
  const tallyClass = program.source === SLATE ? "tally-slate" : live ? "tally-live" : "tally-pending";
  const tallyText =
    program.source === SLATE
      ? live ? "SLATE" : "SLATE (drawing)"
      : live ? `LIVE ${program.source}` : `SWITCHING to ${program.source}`;
  const outageMs = noFrameSince === null ? null : now - noFrameSince;
  const recording = recorderStatus.phase === "recording" || recorderStatus.phase === "stopping";
  const slotFor = (cameraId: CameraId) => readiness?.slots.find((slot) => slot.cameraId === cameraId) ?? null;

  const linkWanted = producerSecret.trim().length > 0;
  const degradedReasons: string[] = [];
  if (!connected) degradedReasons.push("media link down");
  if (linkWanted && link.status !== "connected") degradedReasons.push(`control link ${link.status}: local manual mode`);
  if (readiness && !readiness.masterAudio.attached) degradedReasons.push("no master audio");
  if (readiness && readiness.slots.every((slot) => !slot.renderable)) degradedReasons.push("no renderable camera");
  if (throttled) degradedReasons.push("draw loop throttled");
  if (recorderStatus.phase === "error") degradedReasons.push("recording error");
  if (recorderStatus.persistFailures > 0) degradedReasons.push("recording chunks not persisted");
  const displayMode = degradedReasons.length > 0 ? "DEGRADED" : switcher.mode;
  const lastFailed = switcher.acks.find((ack) => ack.outcome === "FAILED" && now - ack.atMs < 10_000) ?? null;
  const recentLinkError = link.lastError && link.lastErrorAtMs !== null && now - link.lastErrorAtMs < LINK_ERROR_TTL_MS ? link.lastError : null;

  return (
    <section className="panel form-panel program-panel" aria-label="Programme">
      <div className="preview-heading">
        <div>
          <p className="eyebrow">STAGE 2 · PROGRAMME OUT</p>
          <h2>Compositor</h2>
        </div>
        <div className="badges">
          <span className={`tally ${tallyClass}`}>{tallyText}</span>
          <span className={`badge ${recording ? "badge-recording" : "badge-waiting"}`}>
            {recording ? `REC ${formatDuration(recorderStatus.elapsedMs)}` : "not recording"}
          </span>
        </div>
      </div>

      <div className={`mode-strip mode-${displayMode.toLowerCase().replace("_", "-")}`}>
        <div>
          <span className="mode-label">{displayMode.replace("_", " ")}</span>
          <span className="mode-sub">
            {displayMode === "DEGRADED" ? `control mode ${switcher.mode} · ${degradedReasons.join(" · ")}` : MODE_HINT[switcher.mode]}
          </span>
        </div>
        <div className="mode-sub">
          {linkWanted
            ? `control link ${link.status}${link.snapshot ? ` · backend ${link.snapshot.mode} rev ${link.snapshot.modeRevision} · live ${link.snapshot.liveCameraId ?? "slate"}` : ""}`
            : "control link off: enter the producer secret to hand authority to the backend"}
        </div>
      </div>

      {lastFailed && (
        <p className="banner banner-error">
          Switch to {lastFailed.renderedSource} failed: no frame drawn within 1 s. Reverted. The tally never went live for it.
        </p>
      )}
      {recentLinkError && <p className="banner banner-warn">Backend: {recentLinkError}</p>}
      {(recorderStatus.phase === "error" || recorderStatus.persistFailures > 0) && (
        <p className="banner banner-error">
          Recording problem: {recorderStatus.lastError ?? `${recorderStatus.persistFailures} chunks not persisted`}. Live output continues.
        </p>
      )}
      {recording && !recorderStatus.hasAudio && (
        <p className="banner banner-warn">Recording has no audio: the master microphone was not attached when it started.</p>
      )}

      <div className="program-out">
        <canvas ref={canvasRef} width={PROGRAM_WIDTH} height={PROGRAM_HEIGHT} aria-label="Programme output" />
        {outageMs !== null && outageMs > 500 && program.source !== SLATE && (
          <p className="program-warning">No new frame from {program.source} for {Math.round(outageMs)} ms; failover arms at 1.5 s</p>
        )}
      </div>

      <div className="take-row">
        {CAMERA_IDS.map((cameraId) => {
          const slot = slotFor(cameraId);
          const onAir = program.source === cameraId;
          return (
            <button
              key={cameraId}
              type="button"
              className={`take ${onAir ? "take-on-air" : ""}`}
              disabled={!slot?.renderable || !connected}
              onClick={() => requestTake(cameraId)}
              title={slot?.renderable ? "TAKE" : "Not renderable"}
            >
              <span className="key-hint">{KEY_FOR_CAMERA[cameraId]}</span>
              TAKE {cameraId}
              <span className="take-state">{slot ? slot.state : "waiting"}</span>
            </button>
          );
        })}
        <button
          type="button"
          className="take take-slate"
          disabled={program.source === SLATE}
          onClick={requestSlate}
        >
          <span className="key-hint">0</span>
          SLATE
          <span className="take-state">emergency</span>
        </button>
      </div>

      <div className="inline-actions">
        <button
          type="button"
          className={switcher.mode === "MANUAL_HOLD" ? "danger" : "primary"}
          onClick={() => requestMode(switcher.mode === "MANUAL_HOLD" ? "ASSIST" : "MANUAL_HOLD")}
        >
          <span className="key-hint">H</span>
          {switcher.mode === "MANUAL_HOLD" ? "HOLDING · release to ASSIST" : "HOLD"}
        </button>
        <button
          type="button"
          disabled={switcher.mode === "AUTO"}
          onClick={() => requestMode("AUTO")}
        >
          Enable AUTO
        </button>
        <button
          type="button"
          disabled={switcher.mode === "ASSIST"}
          onClick={() => requestMode("ASSIST")}
        >
          Back to ASSIST
        </button>
      </div>

      {switcher.suggestion && (
        <div className="suggestion">
          <div>
            Policy suggests <strong>{switcher.suggestion.target}</strong> ({switcher.suggestion.reason})
            {switcher.suggestion.evidence ? `: "${switcher.suggestion.evidence}"` : ""}
          </div>
          <button type="button" className="primary" onClick={() => applyStep(acceptSuggestion(switcherRef.current, readinessRef.current, performance.now()))}>
            TAKE suggestion
          </button>
        </div>
      )}

      <dl className="connection-details">
        <dt>Mode</dt>
        <dd>
          {switcher.mode} · revision {switcher.modeRevision} · generation {switcher.rendererGeneration}
          {switcher.mode === "MANUAL_HOLD" ? " · health failover still active" : ""}
        </dd>
        <dt>On air</dt>
        <dd>
          {program.source}
          {program.streamEpoch !== null ? ` · epoch ${program.streamEpoch}` : ""}
          {program.videoTrackSid ? ` · ${program.videoTrackSid}` : ""} · {program.reason}
          {program.confirmedAtMs !== null && program.decisionSequence !== null
            ? ` · ack ${Math.round(program.confirmedAtMs - program.sinceMs)} ms after decision`
            : ""}
        </dd>
        <dt>Draw loop</dt>
        <dd className={throttled ? "error-text" : undefined}>
          {drawIntervalMs ? `${Math.round(drawIntervalMs)} ms between draws` : "starting"}
          {throttled ? " · THROTTLED (tab hidden or Mac overloaded)" : ""}
        </dd>
        <dt>Recording</dt>
        <dd className={recorderStatus.phase === "error" || recorderStatus.persistFailures > 0 ? "error-text" : undefined}>
          {recorderStatus.phase}
          {recorderStatus.recordingId ? ` · ${recorderStatus.recordingId}` : ""}
          {recorderStatus.chunkCount ? ` · ${recorderStatus.chunkCount} chunks, ${formatBytes(recorderStatus.bytes)}, ${recorderStatus.persistedChunks} persisted` : ""}
          {recorderStatus.persistFailures ? ` · ${recorderStatus.persistFailures} persist failures` : ""}
          {recorderStatus.hasAudio ? " · with master audio" : recording ? " · NO AUDIO" : ""}
          {` · store ${storeKind}`}
          {recorderStatus.lastError ? ` · ${recorderStatus.lastError}` : ""}
        </dd>
        <dt>Format</dt>
        <dd>{recorderStatus.actualMimeType ?? chosenMimeType ?? `none of ${RECORDING_MIME_CANDIDATES.length} candidates supported`}</dd>
      </dl>

      <div className="inline-actions">
        <button type="button" className="primary" onClick={() => void startRecording()} disabled={recording || !chosenMimeType || !live}>
          Start programme recording
        </button>
        <button type="button" className="danger" onClick={() => void stopRecording()} disabled={!recording}>
          Stop recording
        </button>
        <button type="button" onClick={downloadResult} disabled={!recorderStatus.result}>
          Download recording
        </button>
        <button type="button" onClick={downloadTimeline} disabled={switcher.acks.length === 0}>
          Download decision timeline
        </button>
      </div>

      {recorderStatus.result && (
        <div className="playback">
          <video controls playsInline src={recorderStatus.result.url} />
          <p className="detail">
            {recorderStatus.result.mimeType} · {formatBytes(recorderStatus.result.bytes)} · {formatDuration(recorderStatus.result.durationMs)} ·{" "}
            {recorderStatus.result.fromStore ? "assembled from persisted chunks" : "assembled from memory"}. Play it outside the app before counting it as a pass.
          </p>
        </div>
      )}

      {interrupted.length > 0 && (
        <div className="interrupted">
          <h3>Interrupted recordings</h3>
          <ul className="claims">
            {interrupted.map((meta) => (
              <li key={meta.recordingId} className="claim claim-pending">
                <div>
                  {meta.recordingId} · {new Date(meta.startedAt).toLocaleTimeString()} · {meta.chunkCount} chunks · {formatBytes(meta.bytes)}
                </div>
                <div className="inline-actions">
                  <button type="button" onClick={() => void recoverInterrupted(meta)}>Assemble and download</button>
                  <button type="button" className="danger" onClick={() => void deleteInterrupted(meta)}>Delete</button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      <h3>Decision timeline</h3>
      <pre className="log">
        {switcher.acks.length === 0
          ? "No decisions yet."
          : switcher.acks
              .slice(0, 40)
              .map(
                (ack) =>
                  `${ack.outcome === "APPLIED" ? "APPLIED " : "REJECTED"} #${ack.controlGeneration}.${ack.decisionSequence} -> ${ack.renderedSource}${ack.rejectReason ? ` (${ack.rejectReason})` : ""} · rev ${ack.modeRevision} · t=${Math.round(ack.atMs)}`,
              )
              .join("\n")}
      </pre>
    </section>
  );
}
