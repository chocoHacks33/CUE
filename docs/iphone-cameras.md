# iPhones as cameras, on the team stack

Answer to C's note "iPhone cameras for CUE" (2026-09-19). Written by D.

## What C's note describes, and what we run

C's note targets the standalone one-shot: its `/cam` page, JPEG-over-socket `/ingest`, `run_camera.bat` and the Chrome insecure-origin flag. The team stack has none of that. Cameras publish WebRTC to LiveKit Cloud from the publisher page at `/`, after claiming a single-use pairing token the producer issues and approves; the Mac subscribes. That design already gives everything the note's security section asks for, without a public ingest, a join code or a tunnel-only route:

| C's note | Team stack today |
|---|---|
| join code on `/cam` and `/ingest`, rotatable | single-use pairing token per camera slot, minted on the Mac, approved by D with a verification code |
| one publisher per camera id, replacement needs approval | server-owned camera bindings and stream epochs (A's Stage 3), duplicate slot rejected |
| video only from phones, one master mic | the media policy already refuses audio on CAM-GUEST and CAM-WIDE |
| only some routes reachable through the tunnel | the tunnel exposes the page and the API; every mutating route needs a secret or a token, and LiveKit media never crosses the tunnel |
| never put API keys in a page phones load | already true: browsers get scoped LiveKit tokens only |

So the only real question is the one C names first: the phone needs the page over HTTPS.

## The one blocker, and the venue fact

iPhone Safari gives camera access only to HTTPS pages. On this venue's network, **cloudflared does not work** (port 7844 is blocked; recorded in D's Stage 0 media check). **ngrok on 443 works** and is what the team already uses for the API. The note's `cloudflared tunnel` step would fail here; use ngrok.

The free ngrok plan runs one tunnel. This branch therefore makes the dev server proxy `/api` and `/health` to the FastAPI process, so **one tunnel on port 5173 serves the page and the API to a phone on the same origin**. LiveKit media goes from the phone to LiveKit Cloud directly and never touches the tunnel.

## What changed on this branch

- `apps/web/vite.config.ts`: proxy for `/api` (WebSockets included, the control socket lives there) and `/health`, target `VITE_API_PROXY_TARGET` or `http://127.0.0.1:8000`.
- `apps/web/src/apiBase.ts`: a page served from anything but localhost defaults its API URL to its own origin, which is the proxy. `VITE_API_BASE_URL` still wins.
- `apps/web/src/publisher/mediaPolicy.ts`: capture prefers the rear camera (`facingMode: environment`) so a phone does not open its selfie camera; an explicit device wins; `listVideoInputs` names each camera the browser exposes, which on an iPhone is one entry per lens (wide, ultra wide, telephoto).
- Publisher page: a "Camera lens" picker, populated after the first preview (labels exist only after a permission), which restarts the preview on change and is locked while publishing. The page already had inline muted video and a user-gesture Start.
- Producer page: the same API default.

The publisher page and media policy are A's files. This is a cross-owner edit, flagged in the PR for A's review.

## The 15-minute test (C's decision rule, on our stack)

On the Mac:

```bash
cd apps/api && .venv/bin/uvicorn cue_api.main:app --host 127.0.0.1 --port 8000   # as usual
npm run dev:web                                                                    # 5173, with the proxy
ngrok http 5173                                                                    # one tunnel, page and API
```

Set `CUE_CORS_ORIGINS` to include the ngrok origin only if you point a page at a different origin than it was served from; with the proxy, page and API share one origin and CORS is not involved.

On the iPhone, in Safari: open `https://<name>.ngrok-free.dev/`, tap through ngrok's one-time interstitial, leave the API URL as the page's own origin, paste the pairing token D minted for the slot, Claim pairing, Test local preview (allow the camera; the rear lens opens), pick a lens if wanted, wait for D's approval, Publish. D verifies the marker on the tile like any laptop.

If the picture is on the Mac within 15 minutes, iPhones are viable for that slot. If not, the laptops stay; nothing else changed.

## Phone setup so nothing dies mid-demo (from C's note, all still apply)

Plugged in; Low Power Mode off; Auto-Lock Never; Do Not Disturb on; Guided Access to lock Safari; landscape on a tripod or books; do not move after framing is approved; Safari in the foreground, since iOS pauses the camera in the background. iOS also pauses capture on lock, on an incoming call and on app switch: the publisher page shows reconnecting or error, and D's tile stalls, which is exactly the failover case the compositor already handles.

## Not done, on purpose

- **Virtual pan and zoom.** C's note ranks it a Sunday stretch after the three-camera demo is solid. It is also a media-path change, which the plan rules out overnight. Not built.
- **A phone as the master microphone.** Attractive for Deepgram accuracy, as C says, and allowed by the contract for CAM-HOST only. Untested; a phone mic on CAM-HOST would need A's echo and gain settings checked on the day.
- **Any of C's `/cam` and `/ingest` work in the one-shot.** That repository belongs to the one-shot session; C's prompt can be run there separately if the team wants that path as a fallback.

## Not run

No iPhone has published to this Mac. The lens picker and rear-camera default were exercised only through their unit tests and the production build.
