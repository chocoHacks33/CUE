import { type CameraId, isCameraId, parsePublisherMetadata } from "@cue/contracts";
import {
  type RemoteAudioTrack,
  type RemoteParticipant,
  type RemoteTrack,
  type RemoteTrackPublication,
  type RemoteVideoTrack,
  Room,
  RoomEvent,
  Track,
} from "livekit-client";

/**
 * The desk page's camera tiles on the team stack: subscribe-only LiveKit tracks
 * attached by the camera id in each publisher's server-set metadata, never by
 * tile order. The programme view mirrors the live camera's track. Audio is
 * analysed for the level bars only and never played here; the producer page
 * owns playback.
 */

export interface LivekitInfo {
  serverUrl: string;
  participantToken: string;
}

export function cameraOf(metadata: string | null | undefined): CameraId | null {
  const parsed = parsePublisherMetadata(metadata);
  return parsed && isCameraId(parsed.cameraId) ? parsed.cameraId : null;
}

/** Same scale as the upstream page's local meter: RMS of an 8-bit time-domain buffer, 0 to 1. */
export function levelFrom(buffer: Uint8Array): number {
  if (buffer.length === 0) return 0;
  let sum = 0;
  for (const x of buffer) sum += (x - 128) ** 2;
  return Math.min(1, Math.sqrt(sum / buffer.length) / 26);
}

interface DeskGlobals {
  CUE?: { setMicLevel(level: number): void; setCameraState(camera: string, info: { ready?: boolean; note?: string }): void };
  CUE_LIVEKIT?: { connect(info: LivekitInfo): void; mirror(camera: string): void };
  __cueDesk?: { livekit?: LivekitInfo | null };
}

function tileVideo(camera: CameraId): HTMLVideoElement | null {
  return document.querySelector<HTMLVideoElement>(`.cam[data-cam="${camera}"] video`);
}

class DeskTiles {
  private room: Room | null = null;
  private readonly video = new Map<CameraId, RemoteVideoTrack>();
  private live: CameraId | null = null;
  private mirrored: RemoteVideoTrack | null = null;
  private audioContext: AudioContext | null = null;

  connect(info: LivekitInfo): void {
    if (this.room) return;
    const room = new Room({ adaptiveStream: false, dynacast: false });
    this.room = room;
    room.on(RoomEvent.TrackSubscribed, (track, publication, participant) => this.onTrack(track, publication, participant));
    room.on(RoomEvent.TrackUnsubscribed, (track, _publication, participant) => this.onLost(track, participant));
    room.on(RoomEvent.Disconnected, () => {
      this.room = null;
      this.video.clear();
    });
    void room.connect(info.serverUrl, info.participantToken, { autoSubscribe: true }).catch((error: unknown) => {
      this.room = null;
      console.warn("desk tiles: LiveKit connect failed", error);
    });
  }

  mirror(camera: string): void {
    if (!isCameraId(camera)) return;
    this.live = camera;
    const pgm = document.getElementById("pgm") as HTMLVideoElement | null;
    if (!pgm) return;
    if (this.mirrored) this.mirrored.detach(pgm);
    const track = this.video.get(camera) ?? null;
    this.mirrored = track;
    if (track) track.attach(pgm);
  }

  private onTrack(track: RemoteTrack, _publication: RemoteTrackPublication, participant: RemoteParticipant): void {
    const camera = cameraOf(participant.metadata);
    if (!camera) return;
    if (track.kind === Track.Kind.Video) {
      const video = track as RemoteVideoTrack;
      this.video.set(camera, video);
      const tile = tileVideo(camera);
      if (tile) video.attach(tile);
      if (camera === this.live) this.mirror(camera);
      return;
    }
    if (track.kind === Track.Kind.Audio && camera === "CAM-HOST") this.meter(track as RemoteAudioTrack);
  }

  private onLost(track: RemoteTrack, participant: RemoteParticipant): void {
    const camera = cameraOf(participant.metadata);
    if (!camera || track.kind !== Track.Kind.Video) return;
    const video = track as RemoteVideoTrack;
    video.detach();
    if (this.video.get(camera) === video) this.video.delete(camera);
    if (this.mirrored === video) this.mirrored = null;
  }

  /** Level bars from the master track; an analyser with no destination, so nothing is played here. */
  private meter(track: RemoteAudioTrack): void {
    const mediaTrack = track.mediaStreamTrack;
    if (!mediaTrack) return;
    const context = this.audioContext ?? new AudioContext();
    this.audioContext = context;
    const analyser = context.createAnalyser();
    analyser.fftSize = 512;
    context.createMediaStreamSource(new MediaStream([mediaTrack])).connect(analyser);
    const buffer = new Uint8Array(analyser.fftSize);
    const resume = () => void context.resume();
    document.addEventListener("click", resume, { once: true });
    let last = 0;
    const tick = (now: number) => {
      if (now - last > 60) {
        last = now;
        analyser.getByteTimeDomainData(buffer);
        (window as DeskGlobals).CUE?.setMicLevel(levelFrom(buffer));
      }
      if (mediaTrack.readyState === "live") requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }
}

if (typeof window !== "undefined") {
  const tiles = new DeskTiles();
  const globals = window as DeskGlobals;
  globals.CUE_LIVEKIT = { connect: (info) => tiles.connect(info), mirror: (camera) => tiles.mirror(camera) };
  // The socket may have handed over the credential before this module loaded.
  const pending = globals.__cueDesk?.livekit;
  if (pending && pending.participantToken) tiles.connect(pending);
}
