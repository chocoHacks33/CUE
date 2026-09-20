import { describe, expect, it } from "vitest";

import { cameraOf, levelFrom } from "./tiles";

describe("desk tiles", () => {
  it("maps a publisher to its camera by server-set metadata only", () => {
    const metadata = JSON.stringify({
      contractVersion: "0.1.0",
      eventId: "hackmit-demo",
      cameraId: "CAM-GUEST",
      streamEpoch: 2,
      role: "GUEST",
      audioPolicy: "DISABLED",
      deviceSessionId: "dev-1",
    });
    expect(cameraOf(metadata)).toBe("CAM-GUEST");
    expect(cameraOf(null)).toBeNull();
    expect(cameraOf("{not json")).toBeNull();
    expect(cameraOf(JSON.stringify({ cameraId: "CAM-NOPE" }))).toBeNull();
  });

  it("measures level like the upstream page: silence is 0, a loud square wave saturates", () => {
    expect(levelFrom(new Uint8Array(0))).toBe(0);
    expect(levelFrom(new Uint8Array(512).fill(128))).toBe(0);
    const loud = new Uint8Array(512);
    for (let i = 0; i < loud.length; i += 1) loud[i] = i % 2 ? 255 : 1;
    expect(levelFrom(loud)).toBe(1);
  });
});
