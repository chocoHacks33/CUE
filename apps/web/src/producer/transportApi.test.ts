import { describe, expect, it, vi } from "vitest";

import { attachVideoTrack, detachVideoTrack, endEvent } from "./transportApi";

function response(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("Stage 3 transport API", () => {
  it("reports real attach and detach events with the producer credential", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockImplementation(async () => response({ outcome: "ATTACHED" }));

    await attachVideoTrack(
      "https://mac.local/",
      "producer-secret",
      "event one",
      "CAM-HOST",
      "publisher:host",
      "TR-1",
      fetchMock,
    );
    await detachVideoTrack(
      "https://mac.local/",
      "producer-secret",
      "event one",
      "CAM-HOST",
      "publisher:host",
      "TR-1",
      fetchMock,
    );

    expect(fetchMock.mock.calls[0][0]).toBe(
      "https://mac.local/api/v1/events/event%20one/transport/video-attached",
    );
    expect(fetchMock.mock.calls[1][0]).toContain("video-detached");
    const init = fetchMock.mock.calls[0][1];
    expect(init?.headers).toMatchObject({ "X-CUE-Producer-Secret": "producer-secret" });
    expect(JSON.parse(String(init?.body))).toEqual({
      cameraId: "CAM-HOST",
      participantIdentity: "publisher:host",
      trackSid: "TR-1",
    });
  });

  it("ends an event through the explicit cleanup endpoint", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValue(response({ eventId: "demo", mode: "ENDED" }));
    await endEvent(
      "http://127.0.0.1:8000",
      "producer-secret",
      "demo",
      fetchMock,
    );
    expect(fetchMock.mock.calls[0][0]).toBe(
      "http://127.0.0.1:8000/api/v1/events/demo/end",
    );
    expect(fetchMock.mock.calls[0][1]?.method).toBe("POST");
  });
});
