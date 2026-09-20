import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

/**
 * Two pages: the React app (publisher, producer, recorder) and the static desk
 * page. `/api`, `/health` and the desk socket `/ws` are proxied to the FastAPI
 * process so the desk talks to its own origin; LiveKit media never passes
 * through here.
 */
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, "../..", "VITE_");
  const target = env.VITE_API_PROXY_TARGET || "http://127.0.0.1:8000";
  return {
    plugins: [react()],
    envDir: "../..",
    build: {
      rollupOptions: {
        input: {
          main: "index.html",
          desk: "desk.html",
        },
      },
    },
    server: {
      host: true,
      port: 5173,
      proxy: {
        "/api": { target, changeOrigin: true, ws: true },
        "/health": { target, changeOrigin: true },
        "/ws": { target, changeOrigin: true, ws: true },
      },
    },
  };
});
