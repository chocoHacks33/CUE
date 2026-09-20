# CUE

CUE is a context-aware live director for small productions. The current Stage 0 foundation connects a Windows webcam publisher to LiveKit while D's MacBook runs the backend and receives the feed.

## Stage 0 topology

| Source | Camera contract | Audio contract |
|---|---|---|
| Person A's Windows laptop | `CAM-HOST` | sole master microphone |
| Person B's Windows laptop | `CAM-GUEST` | video only |
| Person C's Windows laptop | `CAM-WIDE` | video only |
| Person D's MacBook | central backend/director | subscribes; publishes no mic/camera |

LiveKit Cloud relays media. The FastAPI service on D's Mac issues short-lived, room-scoped publisher tokens; LiveKit credentials never enter the browser. Stage 1 publishers use single-use camera-slot pairing and explicit producer approval. The producer credential stays on D's Mac.

## Quick start

Prerequisites: an even-numbered Node.js LTS release (20, 22 or 24+), Python 3.11+, and an authorised LiveKit Cloud project.

1. Copy `.env.example` to `.env` and fill in the LiveKit settings, a random `CUE_BOOTSTRAP_SECRET` for the temporary Stage 0 receiver and a different `CUE_PRODUCER_SECRET` for Stage 1 pairing.
2. Start the API:

   ```bash
   cd apps/api
   python -m venv .venv
   # Windows: .venv\Scripts\activate
   # macOS/Linux: source .venv/bin/activate
   python -m pip install -e ".[dev]"
   uvicorn cue_api.main:app --reload --host 0.0.0.0 --port 8000
   ```

3. In another terminal, start the web publisher:

   ```bash
   npm install
   npm run dev:web
   ```

4. D creates a camera-slot pairing grant. Open `http://localhost:5173`, claim its single-use token, compare the verification code with D, obtain approval, preview the camera, then publish.

Camera access works on `localhost` or HTTPS. A different laptop cannot use D's `localhost`; D must expose the web/API endpoint through the team's approved authenticated HTTPS setup.

## Guest identity (Person B)

`CAM-GUEST` is video only. Identifying anyone on it is opt-in and event-scoped:
references live in memory on D's Mac, are deleted on withdrawal or at event end,
and an unknown face stays unknown.

Person B's work is one document per stage:

- [docs/b-stage-0.md](docs/b-stage-0.md) — model weights and licences, consent roster, privacy behaviour
- [docs/b-stage-prep-1.md](docs/b-stage-prep-1.md) — contracts and cross-language fixtures
- [docs/b-stage-1.md](docs/b-stage-1.md) — video-only capture, enrolment/reference module, feed to the Mac
- [docs/b-stage-2-prep.md](docs/b-stage-2-prep.md) — live observations, abstention, expiry and track/epoch association, offline
- [docs/b-stage-2.md](docs/b-stage-2.md) — the live wiring: A's frames in, observations posted, epochs and withdrawals handled
- [docs/b-stage-3-prep.md](docs/b-stage-3-prep.md) — the measuring instrument: calibration fitting, threshold selection, identity-report tallies
- [docs/b-stage-3.md](docs/b-stage-3.md) — carrying a fitted calibration, and the tooling that runs the held-out trials
- [docs/b-stage-4-prep.md](docs/b-stage-4-prep.md) — the AUTO-vs-ASSIST exit gate, the consent/deletion test, and the capture envelope
- [docs/b-stage-4.md](docs/b-stage-4.md) — the readiness endpoint, and the trials recorded as NOT RUN
- [docs/b-stage-5-prep.md](docs/b-stage-5-prep.md) — verified consented-data cleanup, limitations and licences
- [docs/b-stage-5.md](docs/b-stage-5.md) — the freeze made enforceable, and the operator run sheet
- [docs/b-stage-6-prep.md](docs/b-stage-6-prep.md) — the overnight handoff, and `python scripts/b_offline_regression.py`

B's submission statement, written for a sceptical reader: [docs/b-limitations-and-licences.md](docs/b-limitations-and-licences.md). On the night, use [docs/b-run-sheet.md](docs/b-run-sheet.md).

```bash
python -m pip install -e "apps/api[dev]"           # core, no OpenCV needed
python -m pip install -e "apps/api[vision,dev]"    # plus live inference
```

## Verification

```bash
npm run typecheck
npm test
npm run build

cd apps/api
python -m pytest
python -m ruff check .

cd ../vision
python -m pytest
python -m ruff check .
```

See [docs/stage-0-a-handoff.md](docs/stage-0-a-handoff.md) for the A-to-D live proof and the exact exit criteria that still require the physical MacBook.

Person A's Stage 1 protocol, frame/PCM contracts and physical handoff are in [docs/stage-1-a-handoff.md](docs/stage-1-a-handoff.md).

Person A's Stage 2 control, health, ingestion and integration work is documented in [docs/stage-2-a-handoff.md](docs/stage-2-a-handoff.md). A's automated fixture is complete; D's real three-camera Mac acceptance rows remain the system gate.

Person A's complete Stage 3 transport/reconnect integration is documented in [docs/stage-3-a-handoff.md](docs/stage-3-a-handoff.md). The automated implementation is complete; the real three-laptop live sequence on D's Mac remains the Stage 3 system gate.

Person A's Stage 4 failure hardening and fail-closed evidence gate are documented in [docs/stage-4-a-handoff.md](docs/stage-4-a-handoff.md). The code and automated checks are complete; D must still run the listed physical failure trials before A's gate can authorise AUTO.

Person A's Stage 5 release preflight, exact-commit manifest and guarded tag finalizer are documented in [docs/stage-5-a-handoff.md](docs/stage-5-a-handoff.md). They refuse release certification until the real Stage 4, Mac and saved-submission evidence is complete.

## Producer receiver (Person D's Mac)

`/producer` on the same web app is the subscribe-only Stage 0 receiver. It requests a credential from `POST /api/v1/stage0/receiver-token` (same Stage 0 secret, `canPublish: false`), joins the same room, and binds `CAM-HOST`, `CAM-GUEST` and `CAM-WIDE` tiles from each participant's server-set metadata. Only `CAM-HOST`'s microphone is played. The Mac never publishes.

Mac startup, tunnel and verification steps: [docs/stage-0-d-mac-run.md](docs/stage-0-d-mac-run.md).

`/recorder` is the standalone local recording test for any laptop (Stage 1, Test 1): capture your own webcam under the publisher's media policy, record, download, play outside the app. Stage 1 notes: [docs/stage-1-d-handoff.md](docs/stage-1-d-handoff.md).
