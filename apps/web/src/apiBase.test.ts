import { describe, expect, it } from "vitest";

import { defaultApiBaseUrl } from "./apiBase";

describe("defaultApiBaseUrl", () => {
  it("uses the configured value when present", () => {
    expect(defaultApiBaseUrl(" https://api.example ", { protocol: "https:", hostname: "x", origin: "https://x" })).toBe(
      "https://api.example",
    );
  });

  it("points a local page at the local API", () => {
    expect(defaultApiBaseUrl(undefined, { protocol: "http:", hostname: "localhost", origin: "http://localhost:5173" })).toBe(
      "http://localhost:8000",
    );
    expect(defaultApiBaseUrl("", { protocol: "http:", hostname: "127.0.0.1", origin: "http://127.0.0.1:5173" })).toBe(
      "http://localhost:8000",
    );
  });

  it("points a tunnelled page at its own origin, where the proxy lives", () => {
    expect(
      defaultApiBaseUrl(undefined, { protocol: "https:", hostname: "abc.ngrok-free.dev", origin: "https://abc.ngrok-free.dev" }),
    ).toBe("https://abc.ngrok-free.dev");
  });
});
