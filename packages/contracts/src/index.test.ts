import { describe, expect, it } from "vitest";

import {
  CAMERA_CONTRACTS,
  CAMERA_IDS,
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
