import { afterEach, describe, expect, it, vi } from "vitest";

import { createPairingGrant, decidePairingClaim } from "./pairingApi";

afterEach(() => vi.unstubAllGlobals());

describe("producer pairing API", () => {
  it("keeps the producer credential in a header, never the pairing payload", async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ pairingToken: "cuepair_value" }), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetch);

    await createPairingGrant(
      "https://mac.example/",
      "producer-secret",
      "demo-event",
      "CAM-HOST",
    );

    const [url, init] = fetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("https://mac.example/api/v1/events/demo-event/pairing");
    expect(init.headers).toHaveProperty("X-CUE-Producer-Secret", "producer-secret");
    expect(init.body).toBe(JSON.stringify({ cameraId: "CAM-HOST" }));
    expect(init.body).not.toContain("producer-secret");
  });

  it("sends an explicit producer approval decision", async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "APPROVED" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetch);

    await decidePairingClaim(
      "https://mac.example",
      "producer-secret",
      "demo-event",
      "claim_12345678",
      true,
    );

    const [url, init] = fetch.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/devices/claim_12345678/approve");
    expect(init.body).toBe(JSON.stringify({ approved: true }));
  });
});
