# CUE v3 — three Windows webcam feeds, one MacBook director

Updated 20 September 2026 (Singapore). This is the current build plan. It **supersedes the phone-based hardware assumptions and Windows-central-server assignments in v1/v2**. Keep the original PRD's contextual directing, privacy, identity checks and manual override requirements; use this document for hardware, ownership, connections and build order.

This is a proposed implementation and test plan, not a report that the four computers have already been connected or tested.

## 1. The setup you are building

**Yes: A, B and C use their Windows laptop webcams as three live cameras. Person D's MacBook is the central application server, AI-analysis host, live switcher and recorder. No phones are required.**

| Person / machine | Live camera role | Audio | Engineering responsibility |
|---|---|---|---|
| **A — Windows laptop** | `CAM-HOST`: host close/medium view | **Only master microphone** | Publisher/camera connections, backend, shared contracts and code integration |
| **B — Windows laptop** | `CAM-GUEST`: guest/stage view | Microphone disabled | Enrolment, visual identity, quality checks and privacy |
| **C — Windows laptop** | `CAM-WIDE`: approved safety/group view | Microphone disabled | Transcription, contextual interpretation and deterministic directing policy |
| **D — MacBook** | No camera publication needed; receives all three | Receives A's audio; headphones for monitoring | Central runtime, producer UI, compositor, manual controls and official recording |

Machine owners and on-camera people are separate concepts. A's camera can show whoever is hosting; the system must not assume the person is A. Likewise, a guest-camera label is not proof that Sarah is in that frame.

The core demo remains:

> “Sarah joins us after the break.” → hold the host.
> “Sarah, please join us now.” → take a usable view with fresh verified Sarah evidence.
> Guest camera covered → take the approved healthy wide view.
> Producer presses HOLD → late AI suggestions cannot override it.

### Exactly what “MacBook is the server” means

The MacBook runs FastAPI, the analysis worker containing B/C's modules, the authoritative directing policy, the producer browser and the official programme recording. The Windows laptops do not need to run their development backends during the final demo.

**LiveKit Cloud remains the media relay.** The video path is Windows webcam → LiveKit → MacBook, not a screen share, remote-desktop session or Windows-to-Windows chain. The MacBook is the application/directing server, not a self-hosted replacement for LiveKit's media infrastructure.

This retains the existing architecture and avoids adding a custom streaming protocol. If the team later requires a completely local, cloud-free network, that is a separate deployment decision requiring signalling, secure browser access and media-network testing. Do not assume this version works without internet. LiveKit documents both camera publishing and backend/browser subscriptions. [Publishing](https://docs.livekit.io/transport/media/publish/), [subscriptions](https://docs.livekit.io/transport/media/subscribe/)

**Output scope:** the MVP produces a genuinely live, clean switched programme on the MacBook and a local recording. Delivery to YouTube/Twitch/another public audience is an additional streaming-output integration, not automatically provided by receiving three feeds. Keep that optional until the switcher works.

## 2. Physical arrangement and important constraints

Place the three Windows laptops where their webcams provide useful, different views. They do not need to point at their owners.

```text
             HOST / GUEST / SMALL PERFORMANCE AREA

     A-WIN: host view       B-WIN: guest/stage view
                   C-WIN: wider safety view

           D-MAC: producer desk, facing operator
```

The diagram describes intended framing, not exact camera positions. Check actual webcam fields of view. A built-in webcam may not produce a useful wide angle from your table; move C far enough back and verify the image. Do not call an arbitrary close-up a safety-wide shot. If no usable safe view exists, reframe before enabling AUTO; slate is the final fallback.

### Before coding deeply

- Record each laptop's OS, CPU architecture, RAM, browser, webcam and free storage. Confirm whether the Mac is Intel or Apple silicon; no acceleration or compatible native package is assumed.
- A/D immediately prove the chosen Python environment, LiveKit worker and OpenCV model loading on **D's actual MacBook**. Windows-only success does not pass the runtime gate.
- Use one tested Chromium-based publisher-browser baseline across A/B/C where practical; D tests the selected Mac browser's decoding and recording. Other browsers are additional coverage.
- Open camera privacy shutters and grant the necessary OS/browser permission. Close conferencing/camera applications that could compete for the webcam.
- Leave lids open and machines on power; prevent sleep during rehearsals. Keep ventilation clear. Do not assume capture survives a closed lid or background throttling.
- Once live rehearsal starts, freeze camera placement. Moving a laptop, tilting its screen or changing webcam invalidates approved framing and may invalidate identity evidence.
- The Windows machines are also development computers. Finish active coding/merges before the final rehearsal; close heavy development workloads on all four machines, especially the central Mac, for the measured demo run.

### One microphone, not four

Only A publishes audio. B/C request video only; D does not silently replace the source with its own microphone. Video switches must not restart or select another audio track.

Test whether A's microphone hears the host **and the guest from their actual positions**. If not, improve positioning or explicitly configure a tested authorized external microphone. Three clear video feeds cannot compensate for inaudible speech.

Mute all local preview speakers and use headphones on D. Muting playback is different from muting the captured master track: the recording still needs A's audio. Never feed the programme back through the room speakers into A's mic.

## 3. Connections between the computers

```text
 A-WIN webcam + ONE mic ──┐
 B-WIN webcam only ───────┼── WebRTC ──> LiveKit Cloud room
 C-WIN webcam only ───────┘                      │
                                  ┌────────────┴─────────────┐
                                  ▼                          ▼
                             D-MAC browser              D-MAC worker
                             3 live previews            latest frames → B vision
                             selected canvas            master audio → C speech
                             fixed A audio                         │
                             local recorder              semantic interpretation
                                  ▲                          │
                                  └── decision ← D-MAC backend/policy
                                         │
                                  actual rendered ACK

 A/B/C publisher pages ← HTTPS/WSS → authenticated app on D-MAC
 All four Git clones  ← commits/reviews → shared code repository
```

There are three independent links:

1. **Git shares code.** A integrates reviewed modules; D pulls and deploys the approved commit on the Mac.
2. **HTTPS/WSS shares app state/control.** D exposes the app's authenticated endpoint; A/B/C use it for admission and status.
3. **LiveKit carries media.** Cameras publish once; D's browser and worker subscribe. Test observers can also subscribe when authorized, but do not become producers.

The other computers do not open D's `localhost`. A private-IP HTTP page is also not the default capture solution: browser camera access requires a secure context and permission. Use the verified HTTPS endpoint. [MDN camera access](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia)

### Connection setup, in order

These are proposed application behaviours to implement, not already-existing routes or provisioned services.

1. **A builds; D runs:** start the integrated FastAPI backend on D-MAC, with the built React app and API/control routes under one origin. A local listener such as `127.0.0.1:8000` can sit behind a tested HTTPS/WSS tunnel.
2. **D shares the actual app address privately.** Authenticate the app even though its address is internet-reachable. Expose app/control routes only, not shell access, model folders or the database.
3. **D creates one private event and three camera slots.** A's backend creates a short-lived, single-use link/code per slot. A/B/C click their assigned link; no QR scanning or phone setup is needed.
4. **D approves each publisher.** The server binds its identity to the slot and issues a scoped short-lived media token. A publisher cannot choose any camera ID or promote itself to producer.
5. **A/B/C choose the actual built-in webcam and click Start Camera.** A additionally enables the approved mic; B/C do not request/publish microphone tracks. Show local muted previews and publishing status.
6. **D verifies the mapping physically.** Each operator waves or shows a distinct number. `CAM-HOST`, `CAM-GUEST`, `CAM-WIDE` must match the actual laptop/view regardless of join order.
7. **Only decoded frames establish readiness.** A connected socket or published track is not enough. Approve framing after the frames arrive on D.
8. **D starts the master audio, clean programme and recording explicitly.** Show recording health separately from LIVE. Check file playback after stopping.
9. **A records the connection/runbook details:** central host D-MAC, current endpoint, event/room, build commit, roles, active renderer and safe view. Keep bearer tokens and provider keys out of shared logs/screenshots.

Give every publisher, worker and observer a distinct session identity. A second browser tab must not reuse the active compositor's identity. Test viewers receive subscribe-only media grants and a read-only app session; API/control permissions remain separate from LiveKit permissions. [LiveKit access grants](https://docs.livekit.io/frontends/reference/tokens-grants/)

If the venue network fails, diagnose service reachability and test an authorized alternative network. Do not disable system firewalls globally or assume that being on the same Wi-Fi means computers can directly reach one another.

## 4. Work delegation and file ownership

**A remains the code integration lead. D is the central-machine/runtime owner.** Having D's Mac host the server does not mean D must independently write everybody's backend code.

| Owner | Owns | Hands over | Must not do |
|---|---|---|---|
| **A — media/backend + integration** | Windows publisher page, camera admission, tokens, slot/track/epoch registry, worker ingestion, FastAPI infrastructure, control transport, shared contracts, logs and integration tests | Working publisher/media adapters; decoded-frame interface to B; PCM interface to C; committed integrated build/startup instructions to D | Create a second production backend on A-WIN during the normal demo or rewrite B/C's algorithms |
| **B — vision/privacy** | Guest/consent backend module, reference enrolment, YuNet/SFace adapter, quality checks, local tracking, calibrated identity matching/expiry, deletion and identity test report | Observation API plus examples/tests, exact model files/licences/checksums, Mac-verified inference results | Send camera commands directly, infer names from seats, or report raw similarity as calibrated confidence |
| **C — speech/context/policy** | PCM conversion, Deepgram, utterance assembly, OpenAI interpretation, programme/aliases, deterministic policy/state transitions, stale-event handling, semantic corpus | Tested speech/semantic/policy modules, cue fixtures, measured results and pitch draft | Let model output directly control a camera, assume diarization proves identity, or run duplicate production API pipelines |
| **D — Mac runtime/output** | Producer UI, compositor, fixed-audio path, reusable recorder/test page, actual render ACK, manual HOLD/TAKE/slate, local degraded controls, deployment on Mac | Working clean output/recordings, browser readiness contract, Mac compatibility and final demo evidence | Reconcile incompatible schemas at the last minute or assume receipt of a command proves a rendered cut |

### Repository boundary

```text
apps/web/src/publisher/                     A
apps/web/src/producer/                      D
apps/web/src/compositor/                    D
apps/web/src/recording/                     D (shared smoke-test recorder)
services/api/{auth,devices,control,logs}/    A
services/api/guests/                        B
services/api/policy/                        C; hosted by A's backend on D-MAC
services/worker/{runtime,ingest}/            A
services/worker/vision/                     B
services/worker/{speech,semantics}/         C
packages/contracts/                        A steward; all approve changes
tests/                                     each owner tests their module
docs/{RUNBOOK,RESULTS,BUILD_LOG,DEMO}.md      section ownership agreed by A
```

A owns root dependencies/lockfiles/CI and shared schema changes; D owns the common web shell/styles. Propose cross-owner edits before making them. Keep all source code portable: no hardcoded drive paths, copied Windows virtual environments or assumed CUDA on the Mac.

**Important handoff:** B/C's production modules run on D-MAC after merging, not on their Windows machines. Local Windows development is useful but does not certify the Mac deployment. A/B/C each pair with D for one genuine runtime smoke test of their module.

### Merge and deployment procedure

1. Use one repository and four branches: `codex/a-media-control`, `codex/b-vision`, `codex/c-speech-policy`, `codex/d-producer-output`. Each person uses their own clone.
2. Hand over small runnable changes every 60–90 active minutes: contract/stub, adapter, behaviour, robustness. No giant end-of-day merge.
3. The author provides commit/PR, changed contracts, test commands/results, required configuration names, known failures and next dependency.
4. A reviews with the affected owner and merges one change at a time. D pulls that exact commit, installs from pinned definitions and runs the Mac integration smoke test.
5. The author remains responsible until their module works on the Mac. A/D do not inherit every untested feature as a late deployment problem.
6. D tags the currently running build in the runbook. The code on four local branches is not the demo until it is merged and running there.

D is backup merger only after an explicit handoff from A. One person merges at a time; D remains the runtime operator. Every active-work hour, spend five minutes on working features, blocked contracts, next merge and necessary scope cuts.

## 5. Interfaces to agree before parallel work

Freeze a minimal shared schema and examples during the first hour. A maintains the contract definitions; B/C/D own the correctness of the fields they produce. Validate the same fixtures in Python and TypeScript.

| Interface | Producer → consumer | Minimum agreement |
|---|---|---|
| Camera binding | A infrastructure → everyone | Event, stable camera ID, authorized publisher, current track SID, stream epoch, selected webcam, approved role/framing |
| Decoded frame | A worker → B | Camera/epoch, sequence, pixel format, dimensions, orientation, receive time and optional capture estimate; capacity-one latest-frame queue |
| Decoded audio | A worker → C | Master track, audio epoch, actual PCM rate/channels/format, sample offsets; C resamples once if required |
| Visual observation | B → backend/policy/UI | Camera/epoch/local track, guest/reference version or unknown, status, provenance, box, quality, calibrated match/margin and expiry |
| Utterance/cue | C → backend | Utterance/audio epoch/revision, provisional/final/endpoint status, evidence text, temporal intent, targets, programme revision and deadline |
| Readiness | Active Mac compositor → backend | Locally decoded/renderable track and epoch, last frame age/progression, current rendered source |
| Decision/ACK | Backend ↔ active compositor | Decision sequence, control generation, mode revision, active renderer ID/generation, camera epoch, reason, expiry and actually applied/rejected result |

Use `target_guest_ids` plus a single/group/role/none scope for group introductions. “Sarah and Daniel” requests a suitable approved group/wide view, not an arbitrary solo close-up. That wider framing does not itself prove both identities.

Clock rules must be explicit: backend deadlines use its clock; browser/worker timestamps need mapped clock domains and uncertainty handling. Do not make old observations fresh merely because they arrived late. Expired or timing-uncertain decisions are rejected.

On re-publish, webcam change or ambiguous reconnect, advance the stream epoch and invalidate old evidence. On backend restart, change control generation. Manual actions advance mode revision. Only the designated active compositor may supply authoritative readiness/ACK; observer/test tabs cannot change LIVE state.

### Directing logic C owns

- Model output is a proposed interpretation. Deterministic policy decides whether any cut is allowed.
- Interim transcript may PREPARE a view but cannot commit a named-person TAKE. Assemble final segments through utterance completion; handle corrected names and deduplication.
- NOW with resolved target can nominate a named shot; future, past, negated, conditional/uncertain or unresolved mentions do not.
- Required gates: current camera epoch, healthy decodable frame on the Mac, suitable framing, and fresh confirmed identity for a named close-up.
- Manual HOLD defeats pending/late AI decisions. Emergency/failure safety still works. Resume AUTO is explicit, including after reconnect.
- Initial PRD tuning values: 1.5-second identity expiry, roughly 3-second cue lifetime, 2.5-second normal minimum shot duration. Measure and tune; these are not proven outcomes.
- If the target is unusable, stay on a relevant healthy view or approved wide. If none is available, use slate rather than guessing a guest.
- Corrected cue “Sarah… actually Daniel” must not cause two premature cuts. “Who is Sarah?” is not an introduction.
- Spoken or uploaded instructions are event content, not permission to run tools, change settings or reveal secrets.

Keep one active semantic request plus the latest pending utterance; bound requests and retries. Pin a model using a development corpus and measure a separate 40-case held-out release set. Structured output controls format, not truth. [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)

## 6. Individual recording tests: all four people must do them

Keep **local capture**, **network delivery**, and **final programme recording** as separate results. A clip saved directly from a webcam proves neither that it reached the Mac nor that contextual switching works.

D supplies one reusable recorder/test component; A integrates it into the publisher/test routes. Reuse the acquired webcam stream for local diagnostics rather than opening competing capture sessions. Recordings are private test artifacts, not committed to Git.

### Test 1 — each Windows laptop captures its own webcam, by H2

| Owner | Required local artifact | Expected audio |
|---|---|---|
| A | A 30–60 second local webcam clip with a distinctive spoken/wave marker | A's intended microphone is present |
| B | B 30–60 second local webcam clip with a distinctive visual marker | Video-only is correct; do not enable B's mic to satisfy the test |
| C | C 30–60 second local webcam clip with a distinctive visual marker | Video-only is correct; do not enable C's mic |

Each person stops/saves and independently plays their file outside the app. Record browser, OS/architecture, selected camera, actual recording format, duration and result. Check camera availability, privacy settings, blur and framing. These three tests can run in parallel.

### Test 2 — D records received video, by H2–3

D receives **A's actual network stream**, not a prerecorded upload or Mac webcam. Record 60 seconds on the Mac with a new visual/spoken marker, save it and play it independently. By H3, verify B and C on the Mac individually using their physical markers and stable IDs. No source passes network delivery solely from its local preview.

### Test 3 — Windows laptops also receive and record remotely, by H6

To retain the earlier requirement that everybody verifies reception on their own machine, A/B/C each open a distinct authorized observer/test session and record a brief clip from **at least one other Windows laptop**, with the designated A master-audio track. Save and play it locally.

Run these tests sequentially to limit traffic; keep each source publisher running. The observer gets a different identity from its publisher and cannot send producer commands/official ACKs. A test canvas cut affects only that test recording. Close observer tabs after the test. Do not count receiving one's own local webcam preview as this test.

### Test 4 — the complete three-feed programme, by H6

D records a two-minute programme on the Mac: `CAM-HOST → CAM-GUEST → CAM-WIDE → CAM-HOST`. All three previews stay warm; A's audio remains continuous. Use visual numbered markers to verify the mapping and keep the host speaking during cuts. Stop, save and independently play the file.

Check output aspect ratio, non-mirrored outgoing image, correct order, continuous sound and usable A/V timing. Probe supported MIME types at runtime and keep the real container/extension. A successful support probe alone does not prove the machine has enough resources to record reliably. [MediaRecorder](https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder), [format support](https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder/isTypeSupported_static)

### Report ownership

| Person | Must personally verify |
|---|---|
| A | Own webcam/mic recording; another laptop's received recording; A feed/mic received correctly on D; backend runs on Mac |
| B | Own video-only recording; another laptop's received recording; B feed reaches D; vision and identity expiry run on Mac |
| C | Own video-only recording; another laptop's received recording; C feed reaches D; ASR/policy use the intended master audio |
| D | Remote A clip with audio; correct three-source programme; worker + browser + recording sustained together on the actual Mac |

Write `docs/results/<person>-media-check.md` with commit, device/browser, camera ID/epoch, local-vs-remote proof, format, duration, audio source, playback outcome, errors and a private artifact location. A witness helps, but cannot substitute for the owner's own test. Leave results NOT RUN until executed.

Obtain consent covering recording on all four laptops and explain cloud video relay/audio transcription. Keep face references/embeddings in memory on the Mac by default; restart requires re-enrolment. Remove temporary uploads and unneeded local clips on every machine. Default operational-log retention remains 24 hours with deletion controls; sharing any recording is a separate permission step.

## 7. Stage-by-stage implementation and integration

H0 = Saturday 19 September, 11:00 **Boston time**. The official window ends Sunday 20 September, 11:00 Boston / 23:00 Singapore. If starting late, use the remaining time honestly: cut optional features, not testing or the official deadline.

### Stage 0 — H0–1: freeze the new topology and prove the Mac runtime

- **A:** shared repository/contracts; camera publisher skeleton; backend/LiveKit connectivity; create Plume project and get all four to join.
- **B:** model-weight/licence check, consent roster and Mac face-inference spike with D. Keep calibration and release captures separate.
- **C:** development language cases, separate held-out cases, policy stub, authorized Deepgram/OpenAI checks.
- **D:** Python/browser/runtime setup on Mac; producer preview and reusable recorder skeleton; HTTPS endpoint with A.
- **Integration:** A/D verify one real Windows webcam appears on the Mac. All agree on source IDs and one-master-mic rule.
- **Exit gate:** Mac dependency installation and one live feed work. If native packages or capture fail, fix these before building elaborate UI.

### Stage 1 — H1–3: every device proves its part

- **A:** secure slot admission and stable bindings; deliver decoded frame and real PCM contracts; own local/remote tests.
- **B:** own video-only capture; enrolment/reference module; confirm B feed reaches the Mac.
- **C:** own video-only capture; utterance assembler with fixtures and live audio smoke test; confirm C feed reaches Mac.
- **D:** own remotely received A recording; all three source previews; recorder/test UI available to teammates.
- **Integration:** A merges small adapters; D runs that commit. A/B/C physically verify their camera markers on D.
- **Exit gate:** local recordings on all Windows machines, actual network receipt of all three on D, and a playable Mac recording with A audio. A connection icon alone fails.

### Stage 2 — H3–6: join the whole system before AI is polished

- **A:** control socket, revisions/generations, worker ingestion, camera health, observer isolation and integration fixtures.
- **B:** live observations with UNKNOWN/AMBIGUOUS, expiry, consent deletion and track/epoch association.
- **C:** deterministic policy with manual precedence, future/negation/stale-event tests and a fixture cue producer.
- **D:** three continuously decoded previews, actual render ACK, manual TAKE/HOLD/slate, fixed audio and local recording persistence.
- **Everyone:** complete their remote-reception clip. Close nonessential observers after testing.
- **Integration:** by H4, fixture observation + cue → real policy → real Mac-rendered cut + ACK. By H6, record and play a real three-camera programme; run an early clap/flash test.
- **Exit gate:** manual three-camera production works and HOLD rejects stale commands. Mac load is acceptable with worker active. Test fixtures are clearly labelled, not passed off as real recognition.

### Stage 3 — H6–9: real contextual switching

- **A:** replace transport fixtures, reconnect/duplicate-slot handling, cleanup and state reconciliation; keep integrating.
- **B:** calibrate guest matching, test held-out/unenrolled people on Mac, remove identity on reframe or lost track.
- **C:** completed live utterances → structured cues → policy, including future, negation, correction, group and duplicate-name cases.
- **D:** evidence ages/reasons, failed-ACK/recording warnings and explicit ASSIST/AUTO/DEGRADED UI.
- **Integration:** A leads the release integration; D operates the Mac. Run future mention → unscripted immediate introduction → covered camera → manual HOLD.
- **Exit gate:** one genuine end-to-end live sequence using the actual webcams and mic. No hardcoded named-camera switch masquerading as recognition.

### Stage 4 — H9–12: failure tests and scope decision

- **A:** routing/reconnect, source loss, backend/provider failure, event access and observer/control tests.
- **B:** positive and unknown/ambiguous identity trials; change seats, angles and lighting; consent/deletion test.
- **C:** 40 held-out semantic cases plus live cue-latency measurements; stale replies after HOLD.
- **D:** 20-minute three-feed Mac soak, cut latency, A/V timing, disk recording and independent playback under full workload.
- **Integration:** A merges one fix at a time; D reruns affected Mac tests. Authors remain responsible for their module.
- **Exit gate:** choose named AUTO only if evidence supports it. At H10, unreliable wrong-person rejection means disclosed operator-confirmed/role-based ASSIST. Freeze feature scope by H12.
- **Admin:** save a substantial Plume draft and verify all members before 23:00 Saturday, ahead of the midnight membership deadline.

### Stage 5 — H12–13.25 / Saturday 23:00–Sunday 00:15: freeze and capture

- **A:** tag the passing release; verify clean startup/runbook and saved submission.
- **B:** measured identity report, consented-data cleanup, limitations and licences.
- **C:** six-minute pitch and honest 90-second demo capture; one concrete Codex contribution example.
- **D:** independently play official recording, make a permitted backup copy, save screenshots and exact Mac configuration.
- **Everyone:** final live rehearsal, then pack safely before the venue closure. Moving laptops means framing must be revalidated next morning.

### Stage 6 — overnight until Sunday 08:00: permitted accommodation and rest

The last checked day-of schedule closes venues 00:30–08:00. Follow current organizer announcements. Do not plan overnight camera tests at an unavailable venue.

Use a short agreed handoff for documentation/offline regression checks if needed, then rest. No new media architecture, model migration or major feature. Hardware-dependent fixes remain unverified until tested on the actual setup.

### Stage 7 — Sunday 08:00–10:00: re-establish and validate

- **A:** network/auth/reconnect preflight and exact release commit; confirm assigned judging location/power.
- **B:** reframe guest camera, re-enrol after memory-clearing restart, check unknown rejection in current lighting.
- **C:** reframe safe view and run real speech cases from actual speaker positions.
- **D:** recheck all mappings, A audio, clap/flash timing, 20-minute final soak and recording playback; rehearse the pitch.
- **Exit gate:** claims match today's conditions. If a capability fails, disable/disclose it and update the saved submission.

### Stage 8 — Sunday 10:00–11:00: final saved submission

- **A:** final repository and fields; save by internal deadline **10:30**, reopen to verify persistence. Coordinate any essential last fix with D.
- **B:** final identity/privacy/attribution check.
- **C:** final pitch, impact explanation, sponsor evidence and limitations.
- **D:** final playable demo/media links, stable runtime and power. No independent last-minute dependency upgrades.
- Stop coding at the official end. Afterward, reset/rehearse the demonstrated build rather than continuing development unless organizers explicitly permit it.

## 8. Explicit handoff checklist

| Boundary | Responsible people | Due | Proof |
|---|---|---|---|
| Windows publisher → Mac preview | A + D; B/C each test theirs | H1–3 | Physical marker, stable ID, decoded live frame |
| Recording component → all four machines | D → A/B/C | H2–3 | Local clips and Mac remote clip actually play |
| Raw frames → vision | A + B, verified with D | H2–4 | Correct pixel/orientation/epoch; no growing backlog |
| Master PCM → ASR | A + C, verified with D | H2–4 | Correct rate/channels/offsets; real marker transcribed |
| Cue + observation → policy → renderer | A + B + C + D | H4 fixture, H9 live | Correct cut and actual ACK; HOLD/stale rejection |
| Full output path | D + all | H6 | Three real feeds, continuous A audio, saved cut order |
| Final deployment | A merges; D installs/runs | Every integrated milestone | Exact commit tested on Mac, not just on Windows |

## 9. Quality gates and fallback rules

These remain targets from the original PRD, not guaranteed measurements.

| Area | Owner | Required check |
|---|---|---|
| Camera identity | A | Zero swaps in 20 disconnect/rejoin/device-change trials; physical verification |
| Manual switching | D | At least 30 cuts; p95 TAKE-to-render below 300 ms |
| Preview delay | A/D | Visible timer/flash measurement; p95 below 800 ms target |
| Semantics | C | At least 90% on 40 held-out cases; no future/negated false takes in the release gate |
| Named-person selection | B/C | At least 30 clear positives and 30 unknown/ambiguous trials; zero wrong-person cuts; at least 90% correct completion on clear positives |
| Live cue latency | C/D | 30 positive cues with eligible target visible; p95 below 2.5 s from final disambiguating word |
| Failover | A/D | 10 deliberate camera failures; safe cut within 1.5 s of sustained loss/obstruction detection where safe view exists |
| Audio/video | D | Recorded output p95 absolute skew below 150 ms; clap tests per angle initially and after 15 minutes |
| Stability | Everyone; D records | 20-minute Mac run with all publishers, worker, inference and recorder; no unbounded memory growth or audio-source changes |
| Privacy/control | A/B | End/deletion invalidates identity; unauthorized publishers/observers cannot control the show |

### Must-pass scenarios

- “Sarah later,” “not yet,” past reference and ambiguous names: no inappropriate cut.
- “Sarah… actually Daniel”: corrected target; “Sarah and Daniel”: safe group/wide handling.
- Guest changes seat or moves to another camera: old seat/track identity does not follow them automatically.
- Guest feed disappears, then wide disappears: approved healthy fallback, otherwise slate.
- A microphone stops: visible failure and no new stale-speech cuts; no automatic B/C/D microphone substitution.
- Webcam permission denied, device busy, shutter closed, browser reloaded, laptop sleeps or lid closes: useful warning and safe recovery/epoch handling.
- Late model reply after HOLD, backend restart, old control generation, expired identity or missed ACK: rejected or reconciled safely.
- Browser receives three feeds but recorder/storage fails: alert separately, preserve available chunks, keep healthy live view if possible.
- Programme/transcript contains hostile instructions: content only, no administrative authority.

A face detector finding a person does not identify Sarah. Use opt-in event-scoped enrolment and calibrated match/margin with repeated observations. Unknown people stay unknown. Keep face references/embeddings out of the language-model requests and logs, and delete them at event end by default.

### Performance and fallback

Start with a requested 720p stream per Windows camera at a practical frame rate; measure actual capabilities. Reduce frame rate, then resolution if needed, and lower analysis frequency/drop obsolete frames before changing architecture. No lowering identity thresholds to hide blurry/tiny faces.

At an illustrative 1.5 Mbps per camera, three publishers send about 4.5 Mbps video before overhead; Mac browser plus full-rate worker subscriptions receive about 9 Mbps video before overhead. Extra observers add traffic. These are budgeting estimates, not evidence of venue capacity or SDK rates. Close diagnostics before final measurements.

If Mac resource limits persist, first preserve manual output/recording, then disable named AUTO or reduce inference workload. Moving vision to a Windows worker is a separate explicit change requiring authenticated observation transport, clock/freshness validation and another integration test; do not silently distribute the runtime.

### No spare-machine illusion

All four laptops are already in use: three cameras and one director. D's MacBook is therefore a single central failure point in this MVP.

- If only the Mac backend loses connection but its browser survives, keep local recording/manual safety controls visibly degraded; reconnect into ASSIST and reject stale commands.
- If the programme browser fails, restart it explicitly with a new renderer generation, fresh readiness and a new recording file. Do not claim uninterrupted output.
- If the Mac hardware fails, pause the live demo and use clearly labelled saved evidence. A Windows laptop can become a recovery host only after its simultaneous publisher/server/worker/compositor workload has actually been rehearsed. Otherwise restarting on Windows may require a disclosed reduced-camera configuration.
- Any host migration must fence the old authority and use deliberate event/control reconciliation or a fresh event/room, with possible re-pairing/re-enrolment. No automatic takeover just because a heartbeat timed out.

Do not spend the core hackathon building distributed high availability. A reliably demonstrated fallback is sufficient; never pass replay off as live.

## 10. Copyable Codex prompts for each teammate

Attach the original PRD and **this v3 plan**, not v2 as the current hardware specification. These prompts are for use after the official hacking start.

### Shared instruction

```text
Read CUE_Product_Requirements.md and
CUE_HackMIT_2026_Plan_v3_Laptop_Cameras_Mac_Server.md completely.
V3 overrides phone-based assumptions: A/B/C Windows webcams publish; D's MacBook
is the production backend, analysis worker, compositor and recording host.
Implement only my owned modules/current stage. Agree shared contracts with A;
do not overwrite teammates' changes or redesign another lane. Keep secrets,
raw recordings and biometric references out of Git/logs. Distinguish live input
from fixtures and report tests actually run. My module is not release-ready until
the integrated build passes its tests on D's Mac. Provide changed files, test commands/results, configuration
names, known limitations and next handoff. Do not buy services or deploy publicly
without human approval. Follow the per-device recording tests in section 6.
```

### A — Windows publisher/media/backend and integration

```text
Own apps/web/src/publisher, API infrastructure, worker ingestion, shared contracts
and integration tests. My Windows laptop is CAM-HOST with the only master mic,
NOT the central runtime. Build secure browser admission and stable camera mapping,
scoped tokens, frame/PCM adapters, control generations and renderer-only ACK checks.
Host B's guest/vision and C's policy modules without rewriting them. D deploys the
merged build on the Mac; pair with D on native runtime/HTTPS startup immediately.
First deliver one actual Windows webcam on D's preview and a recordable audio/video
path. Test my own capture, remote reception, mapping and Mac backend execution.
```

### B — Windows guest camera and visual identity

```text
Own guest/consent/reference services, vision adapter and vision tests. My Windows
webcam is CAM-GUEST, video only; do not enable its mic. Develop on Windows, verify
model loading and inference on D's Mac early, then hand over a tested portable
module. Match only enrolled consenting guests; calibrate with separate held-out
evaluation, reject unknown/ambiguous cases, expire stale identities and invalidate
reframes/epochs/withdrawn consent. Emit observations, never camera commands.
Test local video-only recording, real delivery to D, remote observer recording
and identity behaviour on the actual Mac runtime.
```

### C — Windows safety camera and contextual directing

```text
Own speech, semantics, deterministic policy and their tests. My Windows webcam is
CAM-WIDE, video only; verify it really offers a usable safety view. Consume A's
master audio through the Mac worker, not my own microphone. Implement actual PCM
conversion, completed-utterance assembly, epochs/deduplication, schema-constrained
OpenAI interpretation and a pure policy reducer. Handle future/past/negation,
correction, groups, aliases and uncertainty. Manual HOLD, readiness, fresh identity
and deadlines gate every take. Use development cues for tuning and a separate
40-case release set. Test my capture/reception and the full speech path on D's Mac.
```

### D — central Mac server/operator, producer UI and output

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

## 11. HackMIT rules, sponsor choices and final submission

The following preserves the research snapshot from the earlier plan. Recheck current organizer announcements; this revision changes the engineering topology, not the event rules.

### Deadlines and judging

- Maximum **four team members**. [Day-of FAQ](https://dayof.hackmit.org/resources/faq)
- Hacking window: Saturday 19 September 11:00 through Sunday 20 September 11:00 Boston time. Create/join the project before Saturday midnight. Judging rubric: innovation 30%, technical complexity 30%, impact 30%, learning/collaboration 10%. [Hacker Guide](https://docs.google.com/document/d/1q274BZIY80GCnuP3uVdfOzQCoi27AqkSia0uxj8ziIA/preview)
- Plume uses the latest saved project; there is no separate submit button. Save all required fields strictly before Sunday 11:00; our internal target is 10:30. Request power, check the assigned zone/table and attend it. Prepare approximately six minutes presenting plus two minutes answering questions. [Plume Guide](https://docs.google.com/document/d/14CvrBQ9DKfVDvkNXMDJwiiCmUbFt_RoAsF_AmJ-WHOo/preview)
- Last checked live schedule: venue closure Sunday 00:30–08:00, expo/sponsor judging 12:30–14:10. The live schedule/announcements override older guide times. [Day-of schedule](https://dayof.hackmit.org/)
- Track naming conflicts: homepage says **Entertainment**, guide says **Interactive Media**. C confirms the actual Plume choice with organizers; select at most one named track. [Homepage](https://hackmit.org/?lang=en), [Hacker Guide](https://docs.google.com/document/d/1q274BZIY80GCnuP3uVdfOzQCoi27AqkSia0uxj8ziIA/preview)

Original project code must be built during the event; public open-source code/libraries are excepted. Disclose dependencies/APIs and what you implemented. Confirm participant eligibility with organizers; public materials differ on the MIT age exception. Follow badge, conduct and accommodation rules, including no sleeping in campus buildings other than dormitories. [Code of Conduct](https://docs.google.com/document/d/1JvFElQz90s64ak7T5R7LHcgSDpJi11Zx5djskxF8gAg/preview)

### Sponsor focus

| Sponsor | Relevant published brief | Our implementation choice |
|---|---|---|
| OpenAI | API-powered product plus meaningful Codex contribution and a concrete example | Semantic cue interpretation; document real planning/testing/debugging assistance |
| Deepgram | Project must call its API | Live master-audio transcription |
| Long Lake | AI experience that persuades a sceptical user | Demonstrate useful contextual production rather than promise hypothetical savings |
| ASUS | ASUS products and/or Zenni Claw; both receive bonus consideration | Only if genuinely used and verified; do not replace the user's chosen Mac topology just for a logo |
| ElevenLabs | Agentic depth, interaction quality, creative integration and novelty beyond basic TTS | Optional private crew instructions only after core gates; never mix into programme audio |

Source: [official sponsor challenges](https://docs.google.com/document/d/1JxZA0eiX2iWj_-B5xtCo59FylUDlv3I35n5n8W0aIVs/preview). Eligibility and additional booth/form requirements must be checked against what was actually built. Runpod's reviewed brief was still unannounced; do not build a dependency on an assumed challenge.

Core access needed: authorized LiveKit project, Deepgram and OpenAI API access, tested HTTPS endpoint and licensed model weights. Check the [credit brief](https://docs.google.com/document/d/1C9PKlS44LmYnQ8Y2qRap1VqLx5rSfb-5/preview); advertised credits are not already-available team credentials. Provider/signing keys live in D's ignored configuration or secret store; browsers get scoped tokens only. B/C need development credentials only when genuinely required, not to view a feed.

Keep human-approved spend/session caps, bounded context and calls; one production pipeline runs on D. No per-frame LLM calls, automatic credit purchases or duplicate cloud workers on A/B/C.

### Final deliverables

- Complete saved Plume project, all four members, confirmed track and accurate sponsor selections.
- Accessible code/release link, exact Mac and Windows setup instructions, pinned dependencies, variable names without values, and licences/attribution.
- Four individual test reports; Mac live-device results clearly separated from fixtures.
- Consent-permitted demo video and playable official programme, with limitations and actual measured trial counts.
- One real example of Codex improving the build/test process; no fabricated success story.
- Private runbook listing central D-MAC, current endpoint, source roles, startup/shutdown and degraded recovery.
- No credentials, biometric references or raw private recordings in the public repository.

A prepares and verifies the saved submission; D certifies the exact deployed Mac build. B certifies identity/privacy claims; C certifies semantic/policy claims. All four are responsible for their own recording/reception evidence.

## 12. Six-minute demo outline

1. **0:00–0:40 — C:** small entertainment productions need watchable coverage without constant manual switching.
2. **0:40–1:10 — A/D:** show the three Windows webcams and Mac director desk; explain one continuous mic.
3. **1:10–2:40 — live sequence:** future mention holds; unscripted immediate cue takes a verified guest; cover that webcam for wide fallback; demonstrate manual HOLD. D operates the Mac; B manages consenting guest positions.
4. **2:40–3:40 — A/C:** show context → evidence → policy → rendered ACK, not just a keyword trigger.
5. **3:40–4:30 — B/D:** playback, measured checks, abstentions and limitations.
6. **4:30–5:20 — C:** substantive API use and one genuine Codex contribution.
7. **5:20–6:00 — team:** what was built during the event, user value and remaining limitations; leave time for questions.

The judge can invent a spoken cue without enrolling their own face. Use consenting participants as the subjects. Laptop cameras must actually frame the demonstration; no prerecorded scene masquerading as a live feed.

**Final picture: three Windows machines are the cameras; D's MacBook is the brain, producer desk and recorder. A integrates the code; D runs the integrated product.**
