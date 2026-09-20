import type { PublisherMetadata } from "@cue/contracts";
import { describe, expect, it } from "vitest";

import {
  reconcileAuthoritativeBindings,
  applyAuthoritativeBinding,
  applyStallCheck,
  claimSlot,
  clearVideoTrack,
  emptySlots,
  markFrame,
  releaseParticipant,
  setAudioPlayback,
  setAudioTrack,
  setVideoTrack,
  shouldSubscribe,
} from "./slotState";

const EVENT = "hackmit-demo";

function metadataFor(cameraId: PublisherMetadata["cameraId"], epoch = 1): PublisherMetadata {
  const audioPolicy = cameraId === "CAM-HOST" ? "MASTER" : "DISABLED";
  const role = cameraId === "CAM-HOST" ? "HOST" : cameraId === "CAM-GUEST" ? "GUEST" : "WIDE";
  return { contractVersion: "0.1.0", eventId: EVENT, cameraId, role, audioPolicy, streamEpoch: epoch };
}

describe("slot assignment", () => {
  it("starts with three fixed slots and audio expected only on CAM-HOST", () => {
    const slots = emptySlots();
    expect(Object.keys(slots)).toEqual(["CAM-HOST", "CAM-GUEST", "CAM-WIDE"]);
    expect(slots["CAM-HOST"].audioState).toBe("waiting");
    expect(slots["CAM-GUEST"].audioState).toBe("not-applicable");
    expect(slots["CAM-WIDE"].audioState).toBe("not-applicable");
  });

  it("binds by server metadata, not by join order", () => {
    let slots = emptySlots();
    ({ slots } = claimSlot(slots, "publisher:x:CAM-WIDE", "C", metadataFor("CAM-WIDE"), EVENT));
    ({ slots } = claimSlot(slots, "publisher:x:CAM-HOST", "A", metadataFor("CAM-HOST"), EVENT));

    expect(slots["CAM-WIDE"].publisherIdentity).toBe("publisher:x:CAM-WIDE");
    expect(slots["CAM-HOST"].publisherIdentity).toBe("publisher:x:CAM-HOST");
    expect(slots["CAM-GUEST"].publisherIdentity).toBeNull();
    expect(slots["CAM-HOST"].videoState).toBe("publisher-connected");
  });

  it("leaves participants without valid metadata unassigned", () => {
    const { slots, result } = claimSlot(emptySlots(), "someone", "Name", null, EVENT);
    expect(result.kind).toBe("unassigned");
    expect(Object.values(slots).every((slot) => slot.publisherIdentity === null)).toBe(true);
  });

  it("refuses metadata from a different event", () => {
    const foreign = { ...metadataFor("CAM-HOST"), eventId: "other-event" };
    const { result } = claimSlot(emptySlots(), "publisher:other:CAM-HOST", "A", foreign, EVENT);
    expect(result.kind).toBe("unassigned");
  });

  it("keeps the first holder when a second participant claims the same camera", () => {
    let slots = emptySlots();
    ({ slots } = claimSlot(slots, "first", "A", metadataFor("CAM-HOST"), EVENT));
    const second = claimSlot(slots, "second", "Impostor", metadataFor("CAM-HOST"), EVENT);

    expect(second.result).toEqual({ kind: "conflict", cameraId: "CAM-HOST", holder: "first" });
    expect(second.slots["CAM-HOST"].publisherIdentity).toBe("first");
    expect(second.slots["CAM-HOST"].conflictIdentities).toEqual(["second"]);
  });

  it("re-claiming by the same identity updates epoch without changing state", () => {
    let slots = emptySlots();
    ({ slots } = claimSlot(slots, "a", "A", metadataFor("CAM-HOST", 1), EVENT));
    slots = setVideoTrack(slots, "CAM-HOST", "TR_1");
    const again = claimSlot(slots, "a", "A", metadataFor("CAM-HOST", 2), EVENT);

    expect(again.result.kind).toBe("already-assigned");
    expect(again.slots["CAM-HOST"].streamEpoch).toBe(2);
    expect(again.slots["CAM-HOST"].videoTrackSid).toBe("TR_1");
  });

  it("does not let stale participant metadata rewind an authoritative epoch", () => {
    let slots = emptySlots();
    ({ slots } = claimSlot(slots, "a", "A", metadataFor("CAM-HOST", 3), EVENT));
    const stale = claimSlot(slots, "a", "A", metadataFor("CAM-HOST", 1), EVENT);

    expect(stale.result.kind).toBe("already-assigned");
    expect(stale.slots["CAM-HOST"].streamEpoch).toBe(3);
  });
});

describe("republish and release", () => {
  it("applies a higher authoritative epoch and refuses stale reconciliation", () => {
    let slots = emptySlots();
    ({ slots } = claimSlot(slots, "a", "A", metadataFor("CAM-HOST", 1), EVENT));
    slots = setVideoTrack(slots, "CAM-HOST", "TR_old");
    const binding = {
      contractVersion: "0.1.0" as const,
      eventId: EVENT,
      cameraId: "CAM-HOST" as const,
      participantIdentity: "a",
      deviceSessionId: "device-a",
      displayName: "A",
      currentVideoTrackSid: "TR_new",
      streamEpoch: 2,
      bindingRevision: 2,
    };

    const advanced = applyAuthoritativeBinding(slots, binding, EVENT);
    expect(advanced.result).toEqual({
      kind: "applied",
      cameraId: "CAM-HOST",
      epochAdvanced: true,
    });
    expect(advanced.slots["CAM-HOST"].videoTrackSid).toBe("TR_new");
    expect(advanced.slots["CAM-HOST"].previousVideoTrackSids).toEqual(["TR_old"]);
    expect(advanced.slots["CAM-HOST"].frameCount).toBe(0);

    const stale = applyAuthoritativeBinding(
      advanced.slots,
      { ...binding, currentVideoTrackSid: "TR_stale", streamEpoch: 1 },
      EVENT,
    );
    expect(stale.result.kind).toBe("stale");
    expect(stale.slots).toBe(advanced.slots);

    const delayedSnapshot = applyAuthoritativeBinding(
      advanced.slots,
      {
        ...binding,
        currentVideoTrackSid: null,
        streamEpoch: 2,
        bindingRevision: 1,
      },
      EVENT,
    );
    expect(delayedSnapshot.result.kind).toBe("stale");
    expect(delayedSnapshot.slots["CAM-HOST"].videoTrackSid).toBe("TR_new");
  });

  it("fails closed on two identities claiming the same authoritative epoch", () => {
    let slots = emptySlots();
    ({ slots } = claimSlot(slots, "first", "A", metadataFor("CAM-HOST", 2), EVENT));
    const conflicting = applyAuthoritativeBinding(
      slots,
      {
        contractVersion: "0.1.0",
        eventId: EVENT,
        cameraId: "CAM-HOST",
        participantIdentity: "second",
        deviceSessionId: "device-b",
        displayName: "Other",
        currentVideoTrackSid: "TR_other",
        streamEpoch: 2,
        bindingRevision: 2,
      },
      EVENT,
    );
    expect(conflicting.result).toEqual({
      kind: "conflict",
      cameraId: "CAM-HOST",
      holder: "first",
    });
    expect(conflicting.slots).toBe(slots);
  });

  it("reconciles a complete binding snapshot and removes absent owners", () => {
    let slots = emptySlots();
    ({ slots } = claimSlot(slots, "old-host", "Old", metadataFor("CAM-HOST"), EVENT));
    ({ slots } = claimSlot(slots, "guest", "B", metadataFor("CAM-GUEST"), EVENT));
    slots = setVideoTrack(slots, "CAM-HOST", "TR_old");

    const snapshot = reconcileAuthoritativeBindings(
      slots,
      [
        {
          contractVersion: "0.1.0",
          eventId: EVENT,
          cameraId: "CAM-GUEST",
          participantIdentity: "guest",
          deviceSessionId: "device-b",
          displayName: "B",
          currentVideoTrackSid: "TR_guest",
          streamEpoch: 2,
          bindingRevision: 2,
        },
      ],
      EVENT,
    );

    expect(snapshot.removedCameraIds).toEqual(["CAM-HOST"]);
    expect(snapshot.slots["CAM-HOST"].publisherIdentity).toBeNull();
    expect(snapshot.slots["CAM-HOST"].previousVideoTrackSids).toEqual(["TR_old"]);
    expect(snapshot.slots["CAM-GUEST"].videoTrackSid).toBe("TR_guest");
    expect(snapshot.slots["CAM-GUEST"].streamEpoch).toBe(2);
  });

  it("keeps the camera ID and remembers the old SID when the publisher leaves", () => {
    let slots = emptySlots();
    ({ slots } = claimSlot(slots, "a", "A", metadataFor("CAM-HOST"), EVENT));
    slots = setVideoTrack(slots, "CAM-HOST", "TR_old");
    slots = releaseParticipant(slots, "a");

    const host = slots["CAM-HOST"];
    expect(host.cameraId).toBe("CAM-HOST");
    expect(host.publisherIdentity).toBeNull();
    expect(host.videoTrackSid).toBeNull();
    expect(host.videoState).toBe("waiting");
    expect(host.previousVideoTrackSids).toEqual(["TR_old"]);
  });

  it("a republish lands in the same slot with a new SID and the old one on record", () => {
    let slots = emptySlots();
    ({ slots } = claimSlot(slots, "a", "A", metadataFor("CAM-HOST"), EVENT));
    slots = setVideoTrack(slots, "CAM-HOST", "TR_old");
    slots = releaseParticipant(slots, "a");
    ({ slots } = claimSlot(slots, "a", "A", metadataFor("CAM-HOST"), EVENT));
    slots = setVideoTrack(slots, "CAM-HOST", "TR_new");

    expect(slots["CAM-HOST"].videoTrackSid).toBe("TR_new");
    expect(slots["CAM-HOST"].previousVideoTrackSids).toEqual(["TR_old"]);
    expect(slots["CAM-GUEST"].publisherIdentity).toBeNull();
  });

  it("releasing a conflicting identity removes it from the conflict list", () => {
    let slots = emptySlots();
    ({ slots } = claimSlot(slots, "first", "A", metadataFor("CAM-HOST"), EVENT));
    ({ slots } = claimSlot(slots, "second", "B", metadataFor("CAM-HOST"), EVENT));
    slots = releaseParticipant(slots, "second");
    expect(slots["CAM-HOST"].publisherIdentity).toBe("first");
    expect(slots["CAM-HOST"].conflictIdentities).toEqual([]);
  });

  it("clearing a video track returns to publisher-connected while the publisher stays", () => {
    let slots = emptySlots();
    ({ slots } = claimSlot(slots, "a", "A", metadataFor("CAM-HOST"), EVENT));
    slots = setVideoTrack(slots, "CAM-HOST", "TR_1");
    slots = clearVideoTrack(slots, "CAM-HOST");
    expect(slots["CAM-HOST"].videoState).toBe("publisher-connected");
    expect(slots["CAM-HOST"].previousVideoTrackSids).toEqual(["TR_1"]);
  });
});

describe("frames and stalls", () => {
  it("becomes video-ready on the first decoded frame and stalls after the threshold", () => {
    let slots = emptySlots();
    ({ slots } = claimSlot(slots, "a", "A", metadataFor("CAM-HOST"), EVENT));
    slots = setVideoTrack(slots, "CAM-HOST", "TR_1");
    expect(slots["CAM-HOST"].videoState).toBe("subscribing");

    slots = markFrame(slots, "CAM-HOST", 1000, 1280, 720);
    expect(slots["CAM-HOST"].videoState).toBe("video-ready");
    expect(slots["CAM-HOST"].frameCount).toBe(1);
    expect(slots["CAM-HOST"].width).toBe(1280);

    expect(applyStallCheck(slots, 1500)).toBe(slots);
    const stalled = applyStallCheck(slots, 2100);
    expect(stalled["CAM-HOST"].videoState).toBe("stalled");

    const recovered = markFrame(stalled, "CAM-HOST", 2200, 1280, 720);
    expect(recovered["CAM-HOST"].videoState).toBe("video-ready");
  });

  it("ignores frames for a slot with no attached track", () => {
    const slots = emptySlots();
    expect(markFrame(slots, "CAM-GUEST", 10, 640, 360)).toBe(slots);
  });
});

describe("audio", () => {
  it("tracks playback permission only where an audio track is attached", () => {
    let slots = emptySlots();
    ({ slots } = claimSlot(slots, "a", "A", metadataFor("CAM-HOST"), EVENT));
    slots = setAudioTrack(slots, "CAM-HOST", "TR_A", false);
    expect(slots["CAM-HOST"].audioState).toBe("playback-blocked");

    slots = setAudioPlayback(slots, true);
    expect(slots["CAM-HOST"].audioState).toBe("audio-ready");
    expect(slots["CAM-GUEST"].audioState).toBe("not-applicable");
  });

  it("subscribes to camera video from any bound publisher", () => {
    expect(shouldSubscribe(metadataFor("CAM-HOST"), "camera", EVENT)).toBe(true);
    expect(shouldSubscribe(metadataFor("CAM-GUEST"), "camera", EVENT)).toBe(true);
    expect(shouldSubscribe(metadataFor("CAM-WIDE"), "camera", EVENT)).toBe(true);
  });

  it("subscribes to a microphone only from CAM-HOST", () => {
    expect(shouldSubscribe(metadataFor("CAM-HOST"), "microphone", EVENT)).toBe(true);
    expect(shouldSubscribe(metadataFor("CAM-GUEST"), "microphone", EVENT)).toBe(false);
    expect(shouldSubscribe(metadataFor("CAM-WIDE"), "microphone", EVENT)).toBe(false);
  });

  it("never subscribes to screen share, unknown sources, or other events", () => {
    expect(shouldSubscribe(metadataFor("CAM-HOST"), "screen_share", EVENT)).toBe(false);
    expect(shouldSubscribe(metadataFor("CAM-HOST"), "unknown", EVENT)).toBe(false);
    expect(shouldSubscribe(null, "camera", EVENT)).toBe(false);
    expect(shouldSubscribe(metadataFor("CAM-HOST"), "camera", "another-event")).toBe(false);
  });
});
