import { afterEach, describe, expect, it, vi } from "vitest";

import { claimPairing, exchangePairing, readPairingStatus } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("Stage 1 publisher admission API", () => {
  it("claims a single-use token without sending the producer secret", async () => {
    const fetch = vi.fn().mockResolvedValue(
      jsonResponse({
        claimId: "claim_12345678",
        claimSecret: "cueclaim_secret",
        verificationCode: "BLUE-123",
        camera: { cameraId: "CAM-HOST" },
        status: "PENDING",
      }),
    );
    vi.stubGlobal("fetch", fetch);

    await claimPairing("https://mac.example/", {
      pairingToken: "cuepair_secret",
      displayName: "Person A",
      deviceLabel: "A laptop",
    });

    expect(fetch).toHaveBeenCalledOnce();
    const [url, options] = fetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("https://mac.example/api/v1/pairing/claim");
    expect(options.headers).not.toHaveProperty("X-CUE-Producer-Secret");
    expect(options.headers).toHaveProperty("ngrok-skip-browser-warning", "1");
  });

  it("uses the device-held claim capability for status and exchange", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ status: "APPROVED" }))
      .mockResolvedValueOnce(jsonResponse({ participantToken: "livekit" }, 201));
    vi.stubGlobal("fetch", fetch);
    const capability = {
      claimId: "claim_12345678",
      claimSecret: "cueclaim_secret_that_is_long_enough",
    };

    await readPairingStatus("https://mac.example", capability);
    await exchangePairing("https://mac.example", capability);

    expect(fetch.mock.calls[0]?.[0]).toBe("https://mac.example/api/v1/pairing/status");
    expect(fetch.mock.calls[1]?.[0]).toBe("https://mac.example/api/v1/pairing/exchange");
    expect(JSON.parse(fetch.mock.calls[1]?.[1]?.body as string)).toEqual(capability);
  });

  it("surfaces an API rejection detail", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ detail: "Producer approval is pending" }, 409)),
    );

    await expect(
      exchangePairing("https://mac.example", {
        claimId: "claim_12345678",
        claimSecret: "cueclaim_secret_that_is_long_enough",
      }),
    ).rejects.toThrow("Producer approval is pending");
  });
});
