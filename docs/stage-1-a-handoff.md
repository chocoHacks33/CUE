# Person A Stage 1 handoff

Base: D-verified Stage 0 integration commit `18eeb22`.

## Delivered

- Short-lived, single-use pairing capabilities. The producer secret stays on D's Mac and is never put in a publisher URL, pairing payload or publisher form.
- Explicit producer approval before a device can exchange its claim for a LiveKit credential.
- Server-owned camera assignment. The pairing token fixes the camera ID, role and audio policy; a publisher cannot choose a different slot.
- One active grant, claim or binding per event/camera slot. Replays and duplicate claims fail closed.
- Stable device-session/participant bindings. A changed video track SID advances the stream epoch without changing the camera ID.
- Publisher flow for claim, matching physical verification code, approval check, local preview and one-time credential exchange.
- Producer-side TypeScript API adapter for D's UI.
- Validated decoded-frame and master-PCM contracts, capacity-one frame delivery and PCM continuity checks.

## Pairing API

Producer calls use `X-CUE-Producer-Secret`. Publisher calls use only short-lived capabilities.

| Endpoint | Caller | Purpose |
|---|---|---|
| `POST /api/v1/events/{event}/pairing` | Producer | Mint a token for one fixed camera slot |
| `POST /api/v1/pairing/claim` | Publisher | Consume the token and create a pending claim |
| `GET /api/v1/events/{event}/pairing-claims` | Producer | View claims and verification codes |
| `POST /api/v1/events/{event}/devices/{claim}/approve` | Producer | Approve or reject the physical device |
| `POST /api/v1/pairing/status` | Publisher | Check approval using its claim capability |
| `POST /api/v1/pairing/exchange` | Publisher | Exchange one approved claim for a media token |
| `GET /api/v1/events/{event}/bindings` | Producer | Inspect authoritative camera/device bindings |

The old `/api/v1/stage0/*` endpoints remain temporarily available for D's Stage 0 receiver. New publisher sessions use Stage 1 pairing.

## Configuration

Add these to D's private `.env`. The producer secret must differ from the bootstrap secret.

```dotenv
CUE_PRODUCER_SECRET=<long random value kept only on D's Mac>
CUE_PAIRING_TTL_SECONDS=120
CUE_CLAIM_TTL_SECONDS=300
```

The publisher page accepts only a single-use token. D can use `apps/web/src/producer/pairingApi.ts` when adding producer pairing controls.

## Frame contract for B

`cue_api.media_contracts.DecodedVideoFrame` includes event, fixed camera ID, stream epoch, LiveKit track SID, monotonic sequence, dimensions, stride, real pixel format, orientation/mirroring, receive/capture times and validated raw bytes.

`LatestFrameSlot` has capacity one. A new frame replaces an unconsumed frame; stale epochs/sequences and track changes without an epoch change are rejected. B processes the latest frame instead of draining a latency-growing queue.

## PCM contract for C

`cue_api.media_contracts.DecodedAudioChunk` includes the `CAM-HOST` master track, audio epoch, actual sample rate/channels/format, sequence, sample offset, derived sample-frame count, receive time and complete raw PCM frames.

`PcmContinuityGuard` rejects stale epochs, repeated or overlapping chunks, and track/format changes inside an epoch. It reports gaps. C may resample once at its boundary; the input is never falsely labelled 16 kHz.

## Automated verification

```bash
npm run typecheck
npm test
npm run build

cd apps/api
python -m ruff check .
python -m pytest -q
```

The tests cover replay, wrong secrets, pending/rejected claims, duplicate slots, one-time exchange, bindings, track epochs, frame layouts, capacity-one delivery, PCM offsets, gaps and format/epoch changes.

## Physical A + D exit test

These require the real Windows webcam, LiveKit project and D's Mac. Unit tests cannot mark them passed.

1. D creates a `CAM-HOST` grant and gives A only the pairing token.
2. A claims it. Both devices show the same colour/code. D verifies A's physical laptop and approves.
3. A previews and records a short local clip with a fresh marker, then plays it outside the app.
4. A publishes. D confirms decoded frames, fixed `CAM-HOST` mapping and exactly one master-audio track.
5. D records a remote A clip and plays it outside the app. Record camera ID, participant identity, track SID and epoch.
6. Reuse the pairing token and try another claim for the occupied slot; both must fail.
7. During worker integration, republish and confirm a changed track SID advances the epoch without changing `CAM-HOST`.

Save truthful results in `docs/results/a-stage1-media-check.md`. Private recordings never enter Git.
