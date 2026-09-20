import { describe, expect, it } from "vitest";

import { fetchIdentityReadiness, fetchObservations, guestQueryUrl } from "./guestApi";

function fakeFetch(status: number, body: unknown): typeof fetch {
  return (async (input: RequestInfo | URL, init?: RequestInit) =>
    ({
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
      url: String(input),
      headers: init?.headers,
    }) as unknown as Response) as typeof fetch;
}

describe("guestQueryUrl", () => {
  it("passes the event as eventId, the alias B's routes accept, and encodes it", () => {
    expect(guestQueryUrl("https://api.example/", "observations", "hackmit-demo")).toBe(
      "https://api.example/api/v1/guests/observations?eventId=hackmit-demo",
    );
    expect(guestQueryUrl("http://127.0.0.1:8000", "readiness", "a b")).toBe(
      "http://127.0.0.1:8000/api/v1/guests/readiness?eventId=a%20b",
    );
  });
});

describe("fetchObservations", () => {
  it("throws with the status on a refused read instead of returning a fake snapshot", async () => {
    await expect(fetchObservations("http://x", "secret", "ev", fakeFetch(422, {}))).rejects.toThrow("observations 422");
  });
});

describe("fetchIdentityReadiness", () => {
  it("parses a ROLE_BASED verdict with its disclosure", async () => {
    const payload = {
      guestContractVersion: "0.1.0",
      eventId: "hackmit-demo",
      namingPolicy: "ROLE_BASED",
      roleBased: true,
      unattendedNamingPermitted: false,
      calibrationStatus: "PROVISIONAL_DEFAULT",
      disclosure: "Cameras are chosen by role, not by face recognition. Nothing on screen is identified by face.",
      blockingReasons: ["no identity report exists"],
      attestations: {},
    };
    const readiness = await fetchIdentityReadiness("http://x", "secret", "hackmit-demo", fakeFetch(200, payload));
    expect(readiness.namingPolicy).toBe("ROLE_BASED");
    expect(readiness.roleBased).toBe(true);
    expect(readiness.disclosure).toContain("chosen by role");
  });

  it("refuses a verdict that claims a name from a face without disclosure", async () => {
    const payload = {
      guestContractVersion: "0.1.0",
      eventId: "hackmit-demo",
      namingPolicy: "NAMED_ASSIST",
      roleBased: false,
      unattendedNamingPermitted: false,
      calibrationStatus: "MEASURED",
      disclosure: "   ",
      blockingReasons: [],
      attestations: {},
    };
    await expect(fetchIdentityReadiness("http://x", "secret", "hackmit-demo", fakeFetch(200, payload))).rejects.toThrow(
      /disclosure/,
    );
  });
});
