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

## What A does (Stage 1 pairing, replaces the shared secret for publishers)

1. D, on the producer page: enter the producer secret (from this Mac's `.env`, `CUE_PRODUCER_SECRET`), click **Mint pairing token** on CAM-HOST, click **Copy token**, send A the token only.
2. A on Windows: `npm run dev:web`, open `http://localhost:5173/`, set Mac API URL to D's `https://....ngrok-free.dev`, paste the pairing token, enter display name and device label, submit the claim. A's page shows a verification code.
3. D: the claim appears in the panel with the same code. Look at A's physical laptop, confirm the code matches, click **Approve**.
4. A: Test local preview, then Publish. A's page exchanges the approved claim for a one-time media token.
5. D: the CAM-HOST slot shows "bound" with A's device session and epoch, and the preview tile binds by metadata as before.

Tokens expire in 2 minutes and are single use. A second claim for an occupied slot fails closed. The old Stage 0 publisher-token path still exists but new publishers use pairing.

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

Then run the **Recording test** with `CAM-HOST + master audio`: Start, wait 30 to 60 s while A speaks a marker and waves, Stop, play inline, Download, and play the file in VLC or Chrome (WebM does not open in QuickTime). Record the real container (expected `video/webm;codecs=vp8,opus`), duration and outcome in the results file.

## Stage 3: control link, evidence and modes

- Enter the **producer secret** in the session panel (it is also what the pairing panel uses). With the LiveKit link up, the compositor connects to A's control socket as DIRECTOR. The mode strip shows the link state and the backend's mode, revision and live camera.
- While linked, TAKE and HOLD go through the backend and the compositor applies the returned command. SLATE is always local. If the link drops, the strip says DEGRADED and every control works locally.
- Each tile shows a "Who" line from B's observations: a name only for a confirmed consenting guest, with age and whether a named take is allowed. It reads "evidence off" until connected, and "unavailable" if B's routes are down.
- A switch that draws no frame within 1 s is acknowledged FAILED and reverted; a red banner says so.

## Stage 5: freeze, capture, backup

Freeze means: the commit A tags is the commit running here, and nothing on this Mac changes after that (no dependency upgrades, no `git pull` past the tag).

1. Confirm the running commit: `git rev-parse HEAD` in the terminal that started uvicorn, and the same in the web build's terminal.
2. Capture the configuration: `apps/api/.venv/bin/python scripts/mac_config_snapshot.py` and paste it into `docs/results/d-stage5-freeze.md` (names only, no secrets).
3. After the official session: `Stop recording`, `Download recording`, then
   `apps/api/.venv/bin/python scripts/verify_recording.py <file.webm> --min-seconds 120 --backup <private dir> --markdown`.
   Paste the table. A `FAIL` row means the file is not the deliverable; keep it, note why, and rerun the session if there is time.
4. Play the file yourself, start to end, in VLC or Chrome (`file://`). WebM does not open in QuickTime. Listen for audio restarts at cuts: there must be none.
5. `Save programme still` for the shots listed in the freeze file. Keep stills with the recording, out of Git.
6. Only then fill D's fields in A's `docs/results/stage5-release-approval.json`.

Venv note: the API venv has `livekit-api` but not `livekit`; the worker (`worker_ingest`) needs the repo-root `.venv`, which has `livekit` 1.1.19. Do not "fix" this on the night by installing packages; start the worker from the venv that already works.

## Sunday morning: re-establish (plan Stage 7, D)

Framing is invalid after the laptops moved. Before claiming anything:

- Three feeds decoding with visual markers, mapping verified physically.
- A's audio attached and audible on headphones; `refreshAudioSource` log shows one master track.
- One clap/flash per angle; `scripts/av_skew.py` on a short recording.
- A 20-minute soak if time allows, else a 5-minute one, exported; note which.
- Play the recording outside the app before the pitch.

## Stage 4: measurements and failure drills

All of this needs the three Windows webcams, A's mic and the worker running. Export files and recordings are private; fill `docs/results/d-stage4-check.md` from them.

- **Cuts.** Press 1/2/3 at least 30 times over a few minutes with all three renderable. The "Manual cuts" row shows press-to-picture p50/p95 and the gate. Backend-routed cuts (control link up) measure from the key press, not from the returned command.
- **Failovers.** Ten times: cover the on-air webcam (or close its lid, or kill its publisher tab). Watch the tally go to the safety shot; the "Failovers" row shows loss-detected-to-picture and from-last-frame. Vary which camera fails and how.
- **Soak.** Start the programme recording, then `Start 20-minute soak`. Leave the tab visible (a hidden tab throttles the draw loop and fails the run). After 20 minutes: `Stop soak`, `Export Stage 4 measurements`, `Stop recording`, `Download recording`, play the file in VLC or Chrome (WebM does not open in QuickTime).
- **Clap tests.** Three claps in front of a light at the start and three after 15 minutes, per angle. Then `apps/api/.venv/bin/python scripts/av_skew.py <recording> --events 6`.
- **HOLD drill.** With AUTO on and C's lane cutting, press H. The compositor holds at once; a cut that was already in flight is rejected with `STALE_MODE_REVISION` in the timeline.
- **Link drill.** Stop uvicorn: the strip says DEGRADED, keys still work locally. Start it again: the link reconnects, and if the backend still says AUTO the compositor stays in ASSIST, shows a banner, and asks the backend to step down. Press `Enable AUTO` to re-arm.
- **Recorder drill.** Fill or deny storage (Chrome site settings) mid-recording: red banner, live view continues, chunks so far are recoverable from the interrupted list after reload.

## Stage 2 controls (compositor)

On the producer page, top of the right column. Keys work only when no input has focus.

| Control | Key | Effect |
|---|---|---|
| TAKE CAM-HOST / CAM-GUEST / CAM-WIDE | 1 / 2 / 3 | Hard cut to that camera if it is renderable now. Tally goes red on the first drawn frame |
| SLATE | 0 | Static safe picture, always allowed |
| HOLD | H | Freeze against policy decisions; press again to release to ASSIST. Health failover keeps working |
| Enable AUTO | button only | Lets validated policy decisions execute. Nothing resumes AUTO on its own |
| Start / Stop programme recording | buttons | Canvas plus master audio, chunks persisted as they arrive; download with the real container extension |

If the on-air camera stops delivering frames for 1.5 s the compositor cuts to the wide view, then host, then guest, whichever has been healthy for 2 s, else the slate. Details: `docs/stage-2-d-handoff.md`.

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
