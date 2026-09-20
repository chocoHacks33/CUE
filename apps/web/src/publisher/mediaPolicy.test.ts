import { describe, expect, it } from "vitest";

import { captureConstraints, listVideoInputs } from "./mediaPolicy";

describe("capture policy", () => {
  it("requests audio for CAM-HOST", () => {
    expect(captureConstraints("CAM-HOST").audio).not.toBe(false);
  });

  it.each(["CAM-GUEST", "CAM-WIDE"] as const)("keeps %s video-only", (cameraId) => {
    expect(captureConstraints(cameraId).audio).toBe(false);
  });

  it("prefers the rear camera when no device is chosen, so a phone does not open its selfie camera", () => {
    const video = captureConstraints("CAM-GUEST").video as MediaTrackConstraints;
    expect(video.facingMode).toEqual({ ideal: "environment" });
    expect(video.width).toEqual({ ideal: 1280 });
    expect(video.deviceId).toBeUndefined();
  });

  it("uses the chosen device exactly and drops the facing preference", () => {
    const video = captureConstraints("CAM-WIDE", { deviceId: "ultra-wide-1" }).video as MediaTrackConstraints;
    expect(video.deviceId).toEqual({ exact: "ultra-wide-1" });
    expect(video.facingMode).toBeUndefined();
    expect(video.frameRate).toEqual({ ideal: 24, max: 30 });
  });
});

describe("listVideoInputs", () => {
  const device = (kind: MediaDeviceKind, deviceId: string, label: string) =>
    ({ kind, deviceId, label, groupId: "g", toJSON: () => ({}) }) as MediaDeviceInfo;

  it("keeps only video inputs with an id and labels unnamed ones by their position among cameras", () => {
    const inputs = listVideoInputs([
      device("audioinput", "mic", "Microphone"),
      device("videoinput", "back-wide", "Back Camera"),
      device("videoinput", "", "hidden until permission"),
      device("videoinput", "back-ultra", "   "),
    ]);
    expect(inputs).toEqual([
      { deviceId: "back-wide", label: "Back Camera" },
      { deviceId: "back-ultra", label: "Camera 2" },
    ]);
  });
});
