# D role guide: Mac runtime, producer desk, compositor, recording

For D. Built from the v3 plan (CUE_HackMIT_2026_Plan_v3_Laptop_Cameras_Mac_Server.md) and the PRD. Read this, then keep the v3 plan open for the stage tables. Where the two disagree, v3 wins on hardware and ownership.

## 1. Your role in one paragraph

Your MacBook is the only machine that runs the show. A, B, and C are the three cameras. You receive all three feeds from LiveKit, show them to yourself as previews, draw the chosen one onto a canvas with A's audio, and record that canvas. The backend and analysis worker also run on your Mac, but A writes the backend and B and C write the worker modules. Your code is the browser side: the producer desk, the compositor, the recorder, and the manual controls. Your other job is operator: you pull whatever A merges, run it on the Mac, prove it works there, and you are the one at the keyboard during the demo.

Your Mac does not publish a camera or a microphone. Ever, by default.

## 2. Own, hand over, never do

| Own | Hand over | Never do |
|---|---|---|
| Producer UI (three previews, programme output, mode, log) | Working clean output and playable recordings | Reconcile incompatible schemas at the last minute |
| Compositor (canvas, hard cuts, fixed audio) | Browser readiness contract | Assume receiving a command proves a rendered cut |
| Reusable recorder and test page | Mac compatibility proof for every merged commit | Publish the Mac camera or mic |
| Actual render ACK | Final demo evidence: recording, screenshots, Mac config | Merge without an explicit handoff from A |
| Manual TAKE, HOLD, Resume, slate | | Upgrade dependencies on your own on the last day |
| Local degraded controls when the backend is gone | | |
| Deployment and operation on the Mac | | |

## 3. Your code

Branch: `codex/d-producer-output`. Your directories:

```text
apps/web/src/producer/     director desk
apps/web/src/compositor/   canvas, switching, audio, ACK
apps/web/src/recording/    shared recorder used by every test on every machine
```

You also own the common web shell and styles. A owns root dependencies, lockfiles, CI, and `packages/contracts/`. If you need a contract field, propose it to A rather than adding it.

Keep everything portable. No hardcoded paths, no assumed GPU, no copied virtual environments.

## 4. How your pieces connect

```text
 A-WIN webcam + mic ─┐
 B-WIN webcam ───────┼─ WebRTC ─> LiveKit Cloud room
 C-WIN webcam ───────┘                │
                         ┌────────────┴────────────┐
                         ▼                         ▼
                   YOUR BROWSER               YOUR WORKER (A/B/C code)
                   3 previews, always decoding   frames -> B vision
                   canvas = selected source      audio  -> C speech
                   A audio, never switched              │
                   recorder                     semantic + policy
                         ▲                             │
                         └── decision ◄── YOUR BACKEND (A code)
                                │
                          render ACK ──►
```

Three separate links to keep straight:

- **Git** moves code. A merges, you pull and run.
- **HTTPS/WSS** moves control and state. Your Mac exposes it through a tunnel. A/B/C open it to join and see status.
- **LiveKit** moves video and audio. Nobody's video goes through the tunnel.

## 5. Stage 0, right now (H0 to H1)

H0 is Saturday 19 September 11:00 Boston, 23:00 Singapore. Your Stage 0 list from the plan: Python, browser, and runtime setup on the Mac; producer preview and recorder skeleton; HTTPS endpoint with A. Exit gate: dependencies install on the Mac and one real Windows webcam appears in your preview.

### 5.1 Record the Mac (5 minutes)

Run these and paste the output into `docs/results/d-media-check.md` under a "Machine" heading:

```bash
sw_vers
uname -m                      # arm64 = Apple silicon, x86_64 = Intel
sysctl -n hw.memsize | awk '{print $1/1073741824 " GB RAM"}'
df -h ~ | tail -1             # free disk for recordings
python3 --version
node --version
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --version
```

The Intel versus Apple silicon answer matters because A and B need it to pick wheels for OpenCV and LiveKit.

### 5.2 Stop the Mac from sleeping

Plug in. Open a terminal tab and leave this running for the whole event:

```bash
caffeinate -dims
```

Also turn off "Lock screen after inactivity" in System Settings for the duration. Lid stays open.

### 5.3 Prove the Python runtime

A owns the exact pinned list. Your job is proving that list installs and imports on this Mac. Until A's list exists, prove the three packages that historically break on Macs:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install livekit opencv-python numpy fastapi uvicorn
python -c "import livekit.rtc, cv2, numpy; print('opencv', cv2.__version__)"
python -c "import cv2; print('YuNet available:', hasattr(cv2, 'FaceDetectorYN'))"
python -c "import cv2; print('SFace available:', hasattr(cv2, 'FaceRecognizerSF'))"
```

All three prints must succeed. If OpenCV lacks the face classes, tell B now. B will pair with you to load the actual model files and run one inference on your Mac. Be available for that.

### 5.4 Prove the browser can record

Open Chrome on the Mac, open DevTools console on any page, and run:

```js
['video/webm;codecs=vp8,opus','video/webm;codecs=vp9,opus','video/webm','video/mp4']
  .map(t => t + ' -> ' + MediaRecorder.isTypeSupported(t)).join('\n')
```

Write down which return true. Prefer VP8 plus Opus if it is true. This is the format your recorder will use. Chrome is the baseline; Safari is extra coverage only.

### 5.5 Set up the HTTPS endpoint with A

A's backend will listen on something like `127.0.0.1:8000` on your Mac. The Windows laptops need an HTTPS address for it, because browsers refuse camera access on plain HTTP. A tunnel gives you that address without any deployment.

Options with free tiers, pick one with A:

```bash
# Cloudflare quick tunnel: no account, random URL, supports WebSockets
cloudflared tunnel --url http://127.0.0.1:8000

# ngrok: needs a free account and auth token
ngrok http 8000
```

Test it: put any tiny HTTP server on port 8000, open the tunnel URL from your phone or another machine over HTTPS, then confirm a WebSocket connects through it too. A quick-tunnel URL changes every restart, so record the current one in the runbook each time and share it privately. Do not buy a plan. Do not expose anything except the app routes.

### 5.6 Build the two skeletons

**Recorder component.** One reusable piece that every machine uses for every test. It must:

- Accept an existing `MediaStream`. Never open its own camera. A/B/C reuse their publisher stream.
- Probe `MediaRecorder.isTypeSupported` and use the first supported type.
- Record with a timeslice of about one second and keep the ordered chunks, including the first one which carries the initialisation data.
- On stop, assemble a Blob, show the real MIME type, duration, and size, and offer download plus inline playback.
- Save with the real extension. A WebM file is not renamed to `.mp4`.

A integrates this into the publisher page so A/B/C can run Test 1 by H2.

**Producer preview page.** A page that:

- Joins the LiveKit room with a subscribe-only token from A. It publishes nothing.
- Shows one tile per camera ID from A's camera-binding contract: `CAM-HOST`, `CAM-GUEST`, `CAM-WIDE`. Tiles are keyed by camera ID, never by join order.
- Shows "no frames yet" until decoded frames arrive, then shows last-frame age.
- Turns adaptive stream off so hidden or small tiles keep decoding.
- Mutes all tile audio. A's audio goes to the canvas path later, not to the tiles.

### 5.7 Join Plume

A creates the project. Join it before Saturday midnight or you are not on the team as far as the organisers are concerned.

### 5.8 Stage 0 exit gate

- Python imports pass on the Mac.
- Chrome reports a supported recording type.
- Tunnel URL works over HTTPS and WSS from another device.
- One real Windows webcam, published by A, shows decoded frames in your preview tile.

If the last one fails, that is the whole team's problem to fix before anyone builds more UI.

### What you need from teammates at Stage 0

- **From A:** LiveKit project URL, a subscribe-only token or the endpoint that issues one, the backend start command, the pinned dependency list, the camera-binding contract shape.
- **From B:** model files and checksums for the Mac inference spike.
- **From C:** nothing yet.

### What you give at Stage 0

Mac spec record, confirmed runtime, tunnel URL, recorder skeleton, preview skeleton, and a draft of the readiness contract shape for A to review (see section 8).

## 6. What comes after Stage 0

Your lines only. Full tables are in v3 section 7.

| Stage | Hours | You build or do | You must prove |
|---|---|---|---|
| 1 | H1 to H3 | All three previews; recorder UI available to teammates | Test 2: record A's real network feed with audio on the Mac, play it back |
| 2 | H3 to H6 | Continuous decoding of all three; render ACK; TAKE/HOLD/slate; fixed audio; chunk persistence | Test 4: two-minute HOST, GUEST, WIDE, HOST programme, played back from disk; early clap test |
| 3 | H6 to H9 | Evidence ages and reasons on tiles; failed-ACK and recording warnings; ASSIST/AUTO/DEGRADED UI | Operate the Mac for the first live sequence |
| 4 | H9 to H12 | Nothing new | 20-minute soak with worker, browser, recorder all running; cut latency; A/V skew; playback |
| 5 | H12 to H13.25 | Nothing new | Play the official recording independently; backup copy; screenshots; exact Mac config |
| 7 | Sunday 08:00 to 10:00 | Nothing new | Recheck mappings, A audio, clap test, final 20-minute soak, playback; rehearse |
| 8 | Sunday 10:00 to 11:00 | Nothing new | Demo links final; runtime stable; power connected; no dependency changes |

Every merged commit: you pull it, install from the pinned definitions, run the Mac smoke test, and tag the running build in the runbook. The author stays responsible until their module works on your Mac. Do not absorb their bugs.

## 7. Tests with your name on them

Three separate results, never conflated: local capture, network delivery, final programme recording.

- **Test 2 (by H2 to H3).** A's actual stream arrives over LiveKit. You record 60 seconds on the Mac with a fresh visual or spoken marker, save, and play it outside the app. Then verify B and C individually by their physical markers and stable IDs.
- **Test 4 (by H6).** Two-minute programme cutting HOST to GUEST to WIDE to HOST. All previews stay warm. A's audio continuous through every cut. Check aspect ratio, no mirroring, correct order, sound never drops, A/V timing usable. Play from disk.
- **Soak (Stage 4).** 20 minutes with all publishers, worker, inference, and recorder running together on the Mac. No crash, no memory growth, no audio source change.

Write `docs/results/d-media-check.md` with commit, device and browser, camera ID and epoch, local versus remote proof, format, duration, audio source, playback outcome, errors, and where the private clip lives. Recordings never go in Git. Leave a result as NOT RUN until you ran it.

## 8. Contracts you produce

You own the correctness of two interface rows from v3 section 5. Agree the shapes with A during Stage 0.

**Readiness, compositor to backend.** For each camera: track SID, stream epoch, whether it is locally decoded and renderable, last-frame age, whether frames are progressing. Plus the currently rendered source and your renderer ID and generation.

**Decision and ACK, backend to compositor and back.** Backend sends decision sequence, control generation, mode revision, target camera and epoch, reason, expiry. You check the target really has fresh frames locally, draw it, then reply with the decision sequence, the camera and epoch actually rendered, the applied time, your renderer generation, and applied or rejected.

Rules that follow from these:

- LIVE tally turns red only after your ACK. A decision is not a cut.
- Only the one active compositor tab sends authoritative readiness or ACK. A second tab, a test observer, or a teammate's viewer cannot change LIVE state.
- If a decision arrives with an old control generation, an old mode revision, an expired deadline, or a camera epoch that no longer matches, reject it and say why.
- If the target camera has no fresh frames when the decision lands, reject it. Do not retry a dead camera from an old command.
- Every manual action you take bumps the mode revision, which is how a late AI reply gets ignored.

## 9. Compositor rules

From PRD section 11. These are not negotiable.

- Decode all three sources continuously. The two you are not showing must stay warm so a cut is instant and failover is immediate.
- Draw the selected source to a 1280x720 canvas. Hard cuts only.
- Preserve aspect ratio. Letterbox a portrait source. Never stretch. Never mirror.
- The audio is A's track and only A's track. It attaches once to the recording stream and does not change, restart, or get replaced when video cuts. Mute every preview tile. Wear headphones. Room speakers stay off so the programme cannot feed back into A's mic.
- Recording is canvas capture plus A's audio in one stream. Chunks persist as they arrive. Assemble and validate on stop.
- The programme canvas shows video and intentional graphics only. Boxes, names, confidences, transcript, and logs live on the producer side.
- Recording indicator and recording-failed warning are separate from LIVE.
- If the backend disappears, keep rendering what you already have, keep recording, and expose the 1/2/3 keys and slate directly. On reconnect, come back in ASSIST and reject anything replayed.

## 10. Producer desk rules

From PRD section 12.

Screens: event setup, pairing and preflight, director desk, review and export. The director desk is the one that matters for the demo.

Each tile shows: fixed camera ID, role, LIVE or STANDBY as text plus colour, last-frame age, quality warnings, and visible guests with evidence age and provenance, written like "Sarah: face match, 0.4 s ago" or "Sarah: operator-confirmed". Never a percentage.

| Mode | What your UI does |
|---|---|
| SETUP | No automatic cuts; pairing and consent edits allowed |
| READY | Preflight passed; producer can start |
| ASSIST | AI suggests a shot; you press TAKE |
| AUTO | Policy cuts on its own; you watch |
| MANUAL HOLD | You own the shot; pending AI decisions are dropped |
| DEGRADED | Lists what is unavailable; manual control still works |
| ENDED | Publishers disconnected, cleanup |

Controls: keys 1, 2, 3 for cameras; a visible HOLD button; Resume Auto; an emergency slate button you have actually pressed in rehearsal. Shortcuts are ignored while a form field has focus. After a restart or full reconnect the desk comes up in ASSIST, never AUTO. Health failover still works during MANUAL HOLD, and the UI says so.

Decision log lines read like: "Held host: Sarah was mentioned for later." "Took CAM-GUEST: Sarah matched; shot fresh and unobstructed." "Used wide: Sarah's face match is ambiguous." "Ignored old recommendation: operator is holding CAM-HOST."

## 11. When your Mac is the problem

There is no spare machine. Your Mac is the single point of failure and the plan accepts that.

- **Backend dies, browser survives.** Keep recording, keep manual controls, show DEGRADED. Reconnect into ASSIST. Reject stale commands.
- **Browser dies.** Restart it with a new renderer generation, fresh readiness, and a new recording file. Say the output was interrupted. Do not claim it was continuous.
- **Mac hardware dies.** Pause the live demo and show the saved recording, labelled as saved. A Windows laptop becomes a recovery host only if that has been rehearsed, which it will not have been.
- Never let a takeover happen automatically because a heartbeat timed out.

Do not spend time building high availability. Rehearse the fallback once so you can do it calmly.

## 12. Gates you are measured on

| Check | Target | How |
|---|---|---|
| Manual cut latency | p95 under 300 ms from TAKE to rendered | 30 or more cuts with ACK timestamps |
| Preview delay (with A) | p95 under 800 ms | Visible timer or flash recorded through the path |
| Live cue latency (with C) | p95 under 2.5 s from final disambiguating word | 30 positive cues, target already visible |
| Failover (with A) | Safe cut within 1.5 s of sustained loss | 10 deliberate camera failures |
| A/V skew | p95 under 150 ms in the recording | Clap or flash test per camera at start and after 15 min |
| Stability | 20 minutes, everything running, no crash, leak, or audio change | Soak with logs |

All are targets, not promises. Report the sample size and what failed.

## 13. Glossary for D

- **Room, participant, track.** LiveKit's words for the event, one connected device, and one camera or mic stream.
- **Track SID.** LiveKit's ID for a track. It changes when a laptop republishes. Never use it as the camera's identity.
- **Camera ID.** Ours. `CAM-HOST`, `CAM-GUEST`, `CAM-WIDE`. Stable for the event. Tiles and decisions key on this.
- **Stream epoch.** A counter A bumps whenever a camera republishes, changes webcam, or reconnects ambiguously. Anything observed under an old epoch is invalid.
- **Control generation.** A counter that changes when the backend restarts. Commands from an old generation are rejected.
- **Mode revision.** A counter that bumps on every manual action. A decision computed before your last button press carries an old revision and is ignored.
- **Renderer ID and generation.** Your compositor tab's identity, and a counter that bumps if you restart the tab. Only the current one can ACK.
- **ACK.** Your message back to the backend saying "I actually drew camera X, epoch Y, at time Z."
- **Tally.** The red LIVE indicator. On only after ACK.
- **TAKE.** Cut to a camera now. **HOLD.** Freeze on the current shot and ignore AI. **Slate.** A static safe image shown when nothing else is usable.
- **ASSIST versus AUTO.** AI recommends and you press TAKE, versus AI cuts on its own.
- **Canvas capture.** The browser API that turns what you draw on a canvas into a video stream that MediaRecorder can record.
- **MediaRecorder and MIME type.** The browser recorder and the container plus codec string it supports, such as WebM with VP8 and Opus.
- **Observer.** A subscribe-only session a teammate uses for their remote-reception test. It cannot send commands or ACKs.

## 14. Your Codex prompt

Copy this exactly when you start a Codex session. Attach the PRD and the v3 plan, not v2.

```text
My MacBook is the central deployment computer. Own producer/compositor/recording
UI, reusable media-test recorder and runtime operation. A writes/integrates server
infrastructure; help A validate and run it here instead of duplicating the backend.
Receive all three Windows webcams via LiveKit. Keep all previews decoded; render
the selected source to a clean canvas with A's continuous master audio. Implement
TAKE/HOLD/Resume/slate, renderer identity/generation, actual render ACK, visible
fault states and playable recording with tested MIME/storage behaviour. No Mac
camera or mic is published by default. Prove remote A recording by H2–3 and the
three-feed programme by H6; run the final full-load soak on this actual Mac.
```

Prefix it with the shared instruction from v3 section 10.
