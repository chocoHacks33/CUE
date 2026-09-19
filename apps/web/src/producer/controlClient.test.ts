import { describe, expect, it, vi } from "vitest";

import {
  ControlSocketClient,
  controlSocketUrl,
  parseControlServerMessage,
  reconnectDelayMs,
} from "./controlClient";

class FakeSocket {
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  sent: string[] = [];

  send(data: string): void {
    this.sent.push(data);
  }

  open(): void {
    this.readyState = 1;
    this.onopen?.();
  }

  message(value: unknown): void {
    this.onmessage?.({ data: JSON.stringify(value) });
  }

  close(): void {
    this.readyState = 3;
    this.onclose?.();
  }
}

const command = {
  decisionId: "decision-1",
  eventId: "demo",
  controlGeneration: "generation-1",
  decisionSequence: 1,
  modeRevision: 1,
  target: "CAMERA",
  cameraId: "CAM-GUEST",
  streamEpoch: 3,
  reasonCode: "FIXTURE_TAKE",
  createdAtMs: 1_000,
  expiresAtMs: 3_000,
};

describe("control client", () => {
  it("builds a WSS URL without putting the credential in the query string", () => {
    const url = controlSocketUrl("https://mac.local/base/?discarded=yes", "event one");
    expect(url).toBe("wss://mac.local/base/api/v1/events/event%20one/control");
    expect(url).not.toContain("token");
  });

  it("validates server messages before exposing them", () => {
    expect(
      parseControlServerMessage(JSON.stringify({ type: "render.command", command })),
    ).toEqual({ type: "render.command", command });
    expect(
      parseControlServerMessage(
        JSON.stringify({ type: "render.command", command: { ...command, streamEpoch: 0 } }),
      ),
    ).toBeNull();
    expect(parseControlServerMessage("not-json")).toBeNull();
  });

  it("authenticates first, sends ACKs and reconnects with bounded backoff", () => {
    const sockets: FakeSocket[] = [];
    const connectionChanges: boolean[] = [];
    const messages = vi.fn();
    let retry: (() => void) | null = null;
    let retryDelay = -1;
    const client = new ControlSocketClient({
      apiBaseUrl: "http://127.0.0.1:8000",
      eventId: "demo",
      token: "socket-secret",
      onMessage: messages,
      onConnectionChange: (connected) => connectionChanges.push(connected),
      socketFactory: () => {
        const socket = new FakeSocket();
        sockets.push(socket);
        return socket;
      },
      schedule: (callback, delay) => {
        retry = callback;
        retryDelay = delay;
        return 1;
      },
      cancelScheduled: () => undefined,
    });

    client.start();
    sockets[0].open();
    expect(JSON.parse(sockets[0].sent[0])).toEqual({
      type: "control.authenticate",
      token: "socket-secret",
    });
    sockets[0].message({ type: "control.authenticated", role: "DIRECTOR", eventId: "demo" });
    expect(connectionChanges).toContain(true);

    client.acknowledge({
      decisionId: "decision-1",
      controlGeneration: "generation-1",
      decisionSequence: 1,
      status: "APPLIED",
      actualTarget: "CAMERA",
      actualCameraId: "CAM-GUEST",
      actualStreamEpoch: 3,
      appliedAtMs: 1_100,
    });
    expect(JSON.parse(sockets[0].sent[1]).type).toBe("render.ack");

    sockets[0].close();
    expect(retryDelay).toBe(250);
    expect(retry).not.toBeNull();
    (retry as unknown as () => void)();
    expect(sockets).toHaveLength(2);
    client.stop();
  });

  it("caps reconnect delay", () => {
    expect(reconnectDelayMs(0)).toBe(250);
    expect(reconnectDelayMs(20)).toBe(4_000);
  });
});
