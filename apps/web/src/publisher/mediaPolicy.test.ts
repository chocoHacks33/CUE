import { describe, expect, it } from "vitest";

import { captureConstraints } from "./mediaPolicy";

describe("capture policy", () => {
  it("requests audio for CAM-HOST", () => {
    expect(captureConstraints("CAM-HOST").audio).not.toBe(false);
  });

  it.each(["CAM-GUEST", "CAM-WIDE"] as const)("keeps %s video-only", (cameraId) => {
    expect(captureConstraints(cameraId).audio).toBe(false);
  });
});
