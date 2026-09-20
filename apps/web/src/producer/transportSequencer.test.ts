import { describe, expect, it } from "vitest";

import { CameraTransportSequencer } from "./transportSequencer";

describe("CameraTransportSequencer", () => {
  it("preserves callback order for one camera", async () => {
    const sequencer = new CameraTransportSequencer();
    const order: string[] = [];
    let releaseFirst!: () => void;
    const firstGate = new Promise<void>((resolve) => {
      releaseFirst = resolve;
    });

    const first = sequencer.enqueue("CAM-HOST", async () => {
      order.push("attach-start");
      await firstGate;
      order.push("attach-end");
    });
    const second = sequencer.enqueue("CAM-HOST", async () => {
      order.push("detach");
    });

    await Promise.resolve();
    await Promise.resolve();
    expect(order).toEqual(["attach-start"]);
    releaseFirst();
    await Promise.all([first, second]);
    expect(order).toEqual(["attach-start", "attach-end", "detach"]);
  });

  it("does not let a failed mutation block the next callback", async () => {
    const sequencer = new CameraTransportSequencer();
    const failed = sequencer.enqueue("CAM-GUEST", async () => {
      throw new Error("network down");
    });
    const recovered = sequencer.enqueue("CAM-GUEST", async () => "recovered");

    await expect(failed).rejects.toThrow("network down");
    await expect(recovered).resolves.toBe("recovered");
    await sequencer.drain();
  });

  it("does not serialize unrelated cameras", async () => {
    const sequencer = new CameraTransportSequencer();
    let releaseHost!: () => void;
    const hostGate = new Promise<void>((resolve) => {
      releaseHost = resolve;
    });
    const host = sequencer.enqueue("CAM-HOST", () => hostGate);
    const wide = sequencer.enqueue("CAM-WIDE", async () => "wide-ready");

    await expect(wide).resolves.toBe("wide-ready");
    releaseHost();
    await host;
  });
});
