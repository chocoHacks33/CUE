import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

/**
 * One origin for page and API. A phone reaches the dev server through a single
 * HTTPS tunnel (`ngrok http 5173`); `/api` and `/health` are proxied to the
 * FastAPI process, WebSockets included (the control socket lives under /api).
 * LiveKit media never passes through here: the phone talks to LiveKit Cloud directly.
 */
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, "../..", "VITE_");
  const target = env.VITE_API_PROXY_TARGET || "http://127.0.0.1:8000";
  return {
    plugins: [react()],
    envDir: "../..",
    server: {
      host: true,
      port: 5173,
      proxy: {
        "/api": { target, changeOrigin: true, ws: true },
        "/health": { target, changeOrigin: true },
      },
    },
  };
});
