import { describe, expect, it } from "vitest";

import { fitContain, isThrottled, PROGRAM_HEIGHT, PROGRAM_WIDTH } from "./canvasRenderer";

describe("programme canvas geometry", () => {
  it("fills the canvas for a 16:9 source of any size", () => {
    expect(fitContain(1920, 1080)).toEqual({ x: 0, y: 0, width: 1280, height: 720 });
    expect(fitContain(640, 360)).toEqual({ x: 0, y: 0, width: 1280, height: 720 });
  });

  it("letterboxes a portrait source instead of stretching it", () => {
    const rect = fitContain(720, 1280);
    expect(rect.height).toBe(PROGRAM_HEIGHT);
    expect(rect.width).toBe(405);
    expect(rect.x).toBe(Math.round((PROGRAM_WIDTH - 405) / 2));
    expect(rect.y).toBe(0);
  });

  it("pillarboxes a 4:3 source", () => {
    const rect = fitContain(640, 480);
    expect(rect).toEqual({ x: 160, y: 0, width: 960, height: 720 });
  });

  it("falls back to the full canvas for a source with no dimensions", () => {
    expect(fitContain(0, 0)).toEqual({ x: 0, y: 0, width: 1280, height: 720 });
  });

  it("flags draw intervals beyond the budget as throttled", () => {
    expect(isThrottled(33)).toBe(false);
    expect(isThrottled(1000)).toBe(true);
  });
});
