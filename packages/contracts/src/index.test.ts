import { describe, expect, it } from "vitest";

import {
  CAMERA_CONTRACTS,
  CAMERA_IDS,
  isDecodedAudioDescriptor,
  isDecodedFrameDescriptor,
  mayPublishMicrophone,
  parsePublisherMetadata,
} from "./index";

describe("camera topology", () => {
  it("defines exactly three stable camera IDs", () => {
    expect(CAMERA_IDS).toEqual(["CAM-HOST", "CAM-GUEST", "CAM-WIDE"]);
  });

  it("allows a microphone only on CAM-HOST", () => {
    expect(mayPublishMicrophone("CAM-HOST")).toBe(true);
    expect(mayPublishMicrophone("CAM-GUEST")).toBe(false);
    expect(mayPublishMicrophone("CAM-WIDE")).toBe(false);
  });

  it("does not overload role with source identity", () => {
    expect(CAMERA_CONTRACTS["CAM-HOST"].cameraId).toBe("CAM-HOST");
    expect(CAMERA_CONTRACTS["CAM-HOST"].role).toBe("HOST");
  });
});

describe("publisher metadata parsing", () => {
  const valid = {
    contractVersion: "0.1.0",
    eventId: "hackmit-demo",
    cameraId: "CAM-HOST",
    role: "HOST",
    audioPolicy: "MASTER",
    streamEpoch: 1,
  };

  it("accepts metadata that matches the server-owned contract", () => {
    expect(parsePublisherMetadata(JSON.stringify(valid))).toEqual(valid);
  });

  it("preserves a valid Stage 1 device session binding", () => {
    const withSession = { ...valid, deviceSessionId: "abc123" };
    expect(parsePublisherMetadata(JSON.stringify(withSession))).toEqual(withSession);
    expect(
      parsePublisherMetadata(JSON.stringify({ ...valid, deviceSessionId: 123 })),
    ).toBeNull();
  });

  it("returns null for missing or malformed metadata", () => {
    expect(parsePublisherMetadata(undefined)).toBeNull();
    expect(parsePublisherMetadata("")).toBeNull();
    expect(parsePublisherMetadata("not json")).toBeNull();
    expect(parsePublisherMetadata("[]")).toBeNull();
  });

  it("rejects unknown camera IDs", () => {
    expect(parsePublisherMetadata(JSON.stringify({ ...valid, cameraId: "CAM-4" }))).toBeNull();
  });

  it("rejects metadata that contradicts the camera contract", () => {
    expect(parsePublisherMetadata(JSON.stringify({ ...valid, audioPolicy: "DISABLED" }))).toBeNull();
    expect(parsePublisherMetadata(JSON.stringify({ ...valid, role: "GUEST" }))).toBeNull();
    expect(
      parsePublisherMetadata(
        JSON.stringify({ ...valid, cameraId: "CAM-GUEST", role: "GUEST", audioPolicy: "MASTER" }),
      ),
    ).toBeNull();
  });

  it("rejects a missing or non-positive stream epoch", () => {
    expect(parsePublisherMetadata(JSON.stringify({ ...valid, streamEpoch: 0 }))).toBeNull();
    expect(parsePublisherMetadata(JSON.stringify({ ...valid, streamEpoch: "1" }))).toBeNull();
    const { streamEpoch: _dropped, ...withoutEpoch } = valid;
    expect(parsePublisherMetadata(JSON.stringify(withoutEpoch))).toBeNull();
  });
});

describe("decoded media descriptors", () => {
  it("accepts an epoch-scoped decoded frame descriptor", () => {
    expect(
      isDecodedFrameDescriptor({
        eventId: "demo-event",
        cameraId: "CAM-GUEST",
        streamEpoch: 2,
        trackSid: "TR_video",
        sequence: 42,
        width: 1280,
        height: 720,
        strideBytes: 3840,
        pixelFormat: "RGB24",
        orientationDegrees: 0,
        mirrored: false,
        receivedAtMonotonicS: 12.5,
        captureTimeS: null,
      }),
    ).toBe(true);
  });

  it("rejects a frame with an invalid camera, epoch or orientation", () => {
    const base = {
      eventId: "demo-event",
      cameraId: "CAM-HOST",
      streamEpoch: 1,
      trackSid: "TR_video",
      sequence: 0,
      width: 1280,
      height: 720,
      strideBytes: 3840,
      pixelFormat: "RGB24",
      orientationDegrees: 0,
      mirrored: false,
      receivedAtMonotonicS: 1,
      captureTimeS: null,
    };
    expect(isDecodedFrameDescriptor({ ...base, cameraId: "CAM-4" })).toBe(false);
    expect(isDecodedFrameDescriptor({ ...base, streamEpoch: 0 })).toBe(false);
    expect(isDecodedFrameDescriptor({ ...base, orientationDegrees: 45 })).toBe(false);
  });

  it("accepts only real CAM-HOST PCM metadata", () => {
    const pcm = {
      eventId: "demo-event",
      cameraId: "CAM-HOST",
      masterTrackSid: "TR_audio",
      audioEpoch: 1,
      sequence: 0,
      sampleRateHz: 48000,
      channels: 1,
      sampleFormat: "S16LE",
      sampleOffset: 0,
      sampleFrameCount: 480,
      receivedAtMonotonicS: 2,
    };
    expect(isDecodedAudioDescriptor(pcm)).toBe(true);
    expect(isDecodedAudioDescriptor({ ...pcm, cameraId: "CAM-GUEST" })).toBe(false);
    expect(isDecodedAudioDescriptor({ ...pcm, sampleFormat: "mp3" })).toBe(false);
    expect(isDecodedAudioDescriptor({ ...pcm, sampleFrameCount: 0 })).toBe(false);
  });
});
