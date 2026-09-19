# Person D Stage 0: run the Mac receiver

Branch `codex/person-d-stage-0`, built on A's `codex/person-a-stage-0`. This page is the Mac startup and run guide. The physical A-to-D result lives in `docs/results/a-d-stage-0-media-check.md`.

## What this branch adds

- `apps/web/src/producer/`: subscribe-only receiver at `/producer`. Three fixed slots (`CAM-HOST`, `CAM-GUEST`, `CAM-WIDE`) bind to the camera ID in each participant's server-set metadata, never to join order or display name. Only `CAM-HOST`'s microphone is subscribed and played. The Mac publishes nothing; the token cannot publish.
- `apps/web/src/recording/`: reusable recording test component with runtime MIME probing, chunked capture, inline playback and download with the real container extension. It records existing tracks only and never opens a camera.
- `apps/api`: `POST /api/v1/stage0/receiver-token`, a subscribe-only LiveKit credential guarded by the same Stage 0 secret. Cross-owner change for A to review; A's publisher endpoint behaviour is unchanged apart from a shared admission helper and one extra allowed CORS header.
- `packages/contracts`: `ReceiverTokenRequest`, `ReceiverTokenResponse` and `parsePublisherMetadata`, which rejects metadata that is missing, malformed, names an unknown camera or contradicts the camera contract.
- Both API clients send `ngrok-skip-browser-warning: 1`, because free ngrok tunnels otherwise answer browser requests with an HTML page.

## Verified on this Mac

Recorded 2026-09-19 (Boston). All targets, not promises, until the physical test runs.

| Item | Result |
|---|---|
| Machine | macOS 26.3 (25D125), Apple silicon arm64, 16 GB RAM |
| Toolchain | Node v25.9.0, npm 11.13, Python 3.14.5, Chrome 153 |
| `npm ci`, `npm run typecheck`, `npm test`, `npm run build` | pass |
| `apps/api` venv on Python 3.14.5: `pip install -e ".[dev]"`, `pytest`, `ruff check .` | pass |
| Mac-specific compatibility problems | none found. CI pins Python 3.11; `pyproject.toml` allows 3.11+; 3.14 worked without changes |
| MediaRecorder on Chrome 153 | `video/webm;codecs=vp8,opus` supported and chosen |

## One-time setup

```bash
# Repo root
cp .env.example .env          # then fill LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET
openssl rand -hex 32          # paste as CUE_BOOTSTRAP_SECRET
npm ci

cd apps/api
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

`.env` is gitignored. Never paste its values into chat, screenshots or docs. `CUE_CORS_ORIGINS` defaults to `http://localhost:5173`, which is where A's publisher page and D's producer page both run in Stage 0. Add the tunnel origin only if a page is ever loaded through the tunnel.

## Keep the Mac awake

```bash
caffeinate -dims
```

Leave that running in its own terminal for the whole session. Plug in, lid open, auto-lock off.

## Start (three terminals)

```bash
# 1. API on the Mac
cd apps/api && source .venv/bin/activate
uvicorn cue_api.main:app --host 127.0.0.1 --port 8000
curl -s http://127.0.0.1:8000/health/ready     # expect "status":"ready"

# 2. Web app
npm run dev:web
# open http://localhost:5173/producer   (or http://localhost:5173/#/producer)

# 3. Tunnel so A's Windows laptop can reach the API
ngrok http 8000
```

Tunnel notes from this venue, 2026-09-19: cloudflared is blocked (port 7844). ngrok on 443 works. The URL changes every time ngrok restarts, so record the current one in the runbook and tell A privately. The API only is tunnelled; nobody loads the web page through it in Stage 0.

## Connect the receiver

1. Open `/producer` on the Mac in Chrome.
2. Event ID `hackmit-demo`, display name `Person D`, Mac API URL `http://localhost:8000`, paste the bootstrap secret.
3. Click **Connect subscribe-only**. Status goes requesting-token, connecting, connected. Room shows `cue-hackmit-demo`. Local identity starts with `receiver:`. "Mac publishes" must read `nothing (0 local tracks)`.
4. If "Browser playback" says blocked, click **Enable audio playback**.
5. Put on headphones. Mute the monitor if the room has speakers; that never affects the received track.

## What A does

1. On Windows, `npm run dev:web`, open `http://localhost:5173/`.
2. Camera source `CAM-HOST`, event ID `hackmit-demo`, Mac API URL set to D's current `https://....ngrok-free.dev`, same bootstrap secret.
3. Test local preview, then Publish.

## What "pass" looks like on the Mac

Maps one to one onto A's verification list.

| Check | Where to look |
|---|---|
| A's real webcam appears | `CAM-HOST` tile shows live picture; badge `video ready`; last-frame age under 100 ms; frame count climbing |
| D sees `CAM-HOST`, not an inferred label | Tile is chosen by `parsePublisherMetadata(participant.metadata).cameraId`; log line `CAM-HOST bound to publisher:hackmit-demo:CAM-HOST (stream epoch 1)` |
| A's mic is the sole audio | Master audio panel `audio ready` with one track SID; no other participant's audio is ever subscribed (log shows `Ignored microphone ...` if one appears) |
| Mac publishes nothing | "Mac publishes: nothing (0 local tracks)"; token has `canPublish: false` |
| Stop and reconnect keeps `CAM-HOST` stable | A clicks Stop, then Publish again. Same tile rebinds; `Video SID` changes; `Earlier SIDs` lists the old one; camera ID never moves |
| No secrets in Git or browser logs | `.env` ignored; the log panel prints identities and SIDs only |

Then run the **Recording test** with `CAM-HOST + master audio`: Start, wait 30 to 60 s while A speaks a marker and waves, Stop, play inline, Download, and play the file in QuickTime or VLC. Record the real container (expected `video/webm;codecs=vp8,opus`), duration and outcome in the results file.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| 503 "Stage 0 admission is not configured" or "LiveKit is not configured" | `.env` incomplete or the API was started from a directory where it cannot find `.env` |
| 401 "Invalid Stage 0 admission secret" | Secret mismatch between `.env` and the page |
| CORS error in the browser console | Page origin not in `CUE_CORS_ORIGINS` |
| A gets HTML back from the API | ngrok interstitial; both API clients send `ngrok-skip-browser-warning`, so this means an old build on A's side |
| Tile says publisher connected but no video | Publisher has not published yet, or the subscription failed; check the log for `Subscription failed` |
| Tile stalls | No decoded frame for over 1 s; A's network or webcam stopped. It recovers on the next frame |
| Participant listed as unassigned | Its metadata is missing, for another event, or contradicts the camera contract. It is deliberately not attached |
| Audio blocked | Chrome autoplay policy; click Enable audio playback |

## Not in this branch

No compositor canvas, no manual TAKE/HOLD, no contextual switching, no face or speech processing. Those are Stage 2 and later per the v3 plan.
