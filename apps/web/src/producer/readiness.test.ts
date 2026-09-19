import { isReceiverReadiness, type PublisherMetadata } from "@cue/contracts";
import { describe, expect, it } from "vitest";

import { buildReadiness, type ReadinessContext } from "./readiness";
import { applyStallCheck, claimSlot, emptySlots, markFrame, setVideoTrack } from "./slotState";

const EVENT = "hackmit-demo";
const context: ReadinessContext = {
  eventId: EVENT,
  rendererId: "renderer-test",
  rendererGeneration: 2,
  receiverIdentity: "receiver:hackmit-demo:director:abcd1234",
  connected: true,
  audioPlaybackAllowed: true,
  audioAttached: false,
  currentSource: null,
};

const hostMetadata: PublisherMetadata = {
  contractVersion: "0.1.0",
  eventId: EVENT,
  cameraId: "CAM-HOST",
  role: "HOST",
  audioPolicy: "MASTER",
  streamEpoch: 1,
};

describe("readiness snapshot", () => {
  it("is a valid contract payload with three slots in fixed order", () => {
    const snapshot = buildReadiness(emptySlots(), 1000, context, null);
    expect(isReceiverReadiness(snapshot)).toBe(true);
    expect(snapshot.slots.map((slot) => slot.cameraId)).toEqual(["CAM-HOST", "CAM-GUEST", "CAM-WIDE"]);
    expect(snapshot.currentSource).toBeNull();
    expect(snapshot.rendererGeneration).toBe(2);
  });

  it("marks a slot renderable only after a decoded frame and while not stalled", () => {
    let slots = emptySlots();
    ({ slots } = claimSlot(slots, "a", "A", hostMetadata, EVENT));
    slots = setVideoTrack(slots, "CAM-HOST", "TR_1");

    let snapshot = buildReadiness(slots, 1000, context, null);
    expect(snapshot.slots[0].decoded).toBe(false);
    expect(snapshot.slots[0].renderable).toBe(false);

    slots = markFrame(slots, "CAM-HOST", 1000, 1280, 720);
    snapshot = buildReadiness(slots, 1050, context, snapshot);
    expect(snapshot.slots[0].decoded).toBe(true);
    expect(snapshot.slots[0].renderable).toBe(true);
    expect(snapshot.slots[0].framesProgressing).toBe(true);
    expect(snapshot.slots[0].lastFrameAgeMs).toBe(50);

    const stalled = applyStallCheck(slots, 2500);
    const later = buildReadiness(stalled, 2500, context, snapshot);
    expect(later.slots[0].decoded).toBe(true);
    expect(later.slots[0].renderable).toBe(false);
    expect(later.slots[0].framesProgressing).toBe(false);
    expect(later.slots[0].state).toBe("stalled");
  });

  it("reports the master audio slot even when nothing is attached", () => {
    const snapshot = buildReadiness(emptySlots(), 1, context, null);
    expect(snapshot.masterAudio).toEqual({
      cameraId: "CAM-HOST",
      trackSid: null,
      attached: false,
      playbackAllowed: true,
    });
  });
});
