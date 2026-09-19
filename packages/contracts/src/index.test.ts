import { describe, expect, it } from "vitest";

import {
  CAMERA_CONTRACTS,
  CAMERA_IDS,
  mayPublishMicrophone,
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
