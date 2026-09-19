import type { CameraId } from "@cue/contracts";
import { mayPublishMicrophone } from "@cue/contracts";

export function captureConstraints(cameraId: CameraId): MediaStreamConstraints {
  return {
    video: {
      width: { ideal: 1280 },
      height: { ideal: 720 },
      frameRate: { ideal: 24, max: 30 },
    },
    audio: mayPublishMicrophone(cameraId)
      ? {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        }
      : false,
  };
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
