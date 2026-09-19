# Person A — Stage 2 preliminary handoff

Branch: `codex/person-a-stage-2-prep`

This branch prepares A's Stage 2 interfaces without claiming that Stage 1 has
been integrated or physically verified. The control tests use synthetic
fixtures; they are not a recording of a real three-camera cut.

## Prepared now

- Authoritative per-event control state with a process generation, monotonic
  decision sequence, mode revision and idempotency keys.
- Authenticated mode and manual TAKE endpoints with expected-revision checks.
- Role-scoped control WebSocket sessions. Directors may acknowledge a render;
  observers are read-only.
- Render commands that expire and bind to one camera, stream epoch, mode
  revision and control generation.
- LIVE state changes only after the compositor acknowledges the exact command.
- Separate camera health fields plus the one-second stall and two-second
  recovery hysteresis from the PRD.
- An in-process capacity-one frame bridge for the vision worker. Old analysis
  work is replaced rather than queued, and raw video is not sent through REST
  or the control socket.
- TypeScript contracts and a clearly labelled Stage 2 integration fixture.

## Attach after Stage 1 integration

1. D maps each continuously decoded slot to the health tracker and worker
   ingestor using its real `cameraId`, `trackSid` and `streamEpoch`.
2. D's compositor opens a `DIRECTOR` control session, checks every render
   command against its local track readiness, performs the cut, then returns
   `render.ack`.
3. Producer/diagnostic tabs use `OBSERVER` unless they genuinely operate the
   compositor. Observers never receive permission to acknowledge or mutate.
4. B feeds live observations from the capacity-one worker path. C feeds fixture
   cues first, then the actual semantic policy. Neither lane emits camera
   commands directly.
5. Run the fixture cue → policy → render command → Mac cut → ACK gate before
   enabling automated cuts.

## Still required before Stage 2 is complete

- Stage 1 physical checks for A, B and C feeds on D's Mac.
- D's real compositor, manual HOLD/slate and persistent recording path.
- Wiring of the current stream epoch from D's decoded slot into every command.
- Real three-camera programme recording and clap/flash timing test.
- Mac load measurement with the worker running.

## Local verification

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest .\apps\api\tests
.\.venv\Scripts\python.exe -m ruff check .\apps\api\src .\apps\api\tests
npm.cmd test
npm.cmd run typecheck
npm.cmd run build
```

