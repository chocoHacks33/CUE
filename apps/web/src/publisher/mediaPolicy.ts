import type { CameraId } from "@cue/contracts";
import { mayPublishMicrophone } from "@cue/contracts";

export interface CaptureOptions {
  /** A specific camera from `listVideoInputs`; when absent, the rear camera is preferred (phones). */
  deviceId?: string | null;
}

/**
 * Capture constraints per camera contract. Laptops ignore `facingMode`; an
 * iPhone honours it and opens the rear camera instead of the selfie camera.
 * An explicit device wins over the facing preference.
 */
export function captureConstraints(cameraId: CameraId, options: CaptureOptions = {}): MediaStreamConstraints {
  const shape = {
    width: { ideal: 1280 },
    height: { ideal: 720 },
    frameRate: { ideal: 24, max: 30 },
  };
  const video: MediaTrackConstraints = options.deviceId
    ? { deviceId: { exact: options.deviceId }, ...shape }
    : { facingMode: { ideal: "environment" }, ...shape };
  return {
    video,
    audio: mayPublishMicrophone(cameraId)
      ? {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        }
      : false,
  };
}

export interface VideoInput {
  deviceId: string;
  label: string;
}

/**
 * Cameras the browser exposes. Labels are empty until a capture permission was
 * granted, so call this after the first preview; Safari lists each iPhone lens
 * (wide, ultra wide, telephoto) as its own input.
 */
export function listVideoInputs(devices: readonly MediaDeviceInfo[]): VideoInput[] {
  return devices
    .filter((device) => device.kind === "videoinput" && device.deviceId)
    .map((device, index) => ({
      deviceId: device.deviceId,
      label: device.label.trim() || `Camera ${index + 1}`,
    }));
}

export function validateCapturedTracks(cameraId: CameraId, stream: MediaStream): void {
  if (stream.getVideoTracks().length !== 1) {
    throw new Error("Expected exactly one webcam video track");
  }

  const audioCount = stream.getAudioTracks().length;
  if (mayPublishMicrophone(cameraId) && audioCount !== 1) {
    throw new Error("CAM-HOST requires exactly one master microphone track");
  }
  if (!mayPublishMicrophone(cameraId) && audioCount !== 0) {
    throw new Error(`${cameraId} must remain video-only`);
  }
}
