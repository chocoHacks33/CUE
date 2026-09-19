# A/D Stage 0 media check

Never commit secrets or private recordings. Leave a result as NOT RUN until it was actually run with the physical devices.

- Date/time: build prepared 2026-09-19 (Boston); physical test NOT RUN
- Commit SHA: see `codex/person-d-stage-0` head at test time (base d064a4d)
- A Windows version/browser: NOT RUN
- D macOS/architecture/browser: macOS 26.3 (25D125), arm64 Apple silicon, Chrome 153
- LiveKit region/project label (no credentials): NOT RUN (LiveKit values not yet in D's `.env`)
- API `/health/ready`: NOT RUN
- A local `CAM-HOST` preview: NOT RUN
- A video visible on D with physical marker: NOT RUN
- A master audio audible/recordable on D: NOT RUN
- Participant metadata says `CAM-HOST`: NOT RUN
- Stop/republish produces a new track SID without changing camera ID: NOT RUN
- D's Mac publishes no camera or microphone: NOT RUN (token grant is `canPublish: false`; verified by unit test only)
- Issues/limitations: receiver built and unit-tested on the Mac; no live LiveKit session yet
- Tested by A:
- Tested by D:

## Mac build verification (not a media test)

Run on D's MacBook, 2026-09-19, branch `codex/person-d-stage-0`.

| Command | Result |
|---|---|
| `npm ci && npm run typecheck && npm test && npm run build` | PASS: typecheck clean, 35 tests (8 contracts, 27 web), build OK |
| `apps/api`: `python -m pytest`, `python -m ruff check .`, `ruff format --check` on Python 3.14.5 | PASS: 10 tests, ruff clean, formatted |
