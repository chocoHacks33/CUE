# CUE

CUE is a context-aware live director for small productions. The current Stage 0 foundation connects a Windows webcam publisher to LiveKit while D's MacBook runs the backend and receives the feed.

## Stage 0 topology

| Source | Camera contract | Audio contract |
|---|---|---|
| Person A's Windows laptop | `CAM-HOST` | sole master microphone |
| Person B's Windows laptop | `CAM-GUEST` | video only |
| Person C's Windows laptop | `CAM-WIDE` | video only |
| Person D's MacBook | central backend/director | subscribes; publishes no mic/camera |

LiveKit Cloud relays media. The FastAPI service on D's Mac issues short-lived, room-scoped publisher tokens; LiveKit credentials never enter the browser. The Stage 0 bootstrap secret is a temporary admission guard and must be replaced by single-use pairing in Stage 1.

## Quick start

Prerequisites: an even-numbered Node.js LTS release (20, 22 or 24+), Python 3.11+, and an authorised LiveKit Cloud project.

1. Copy `.env.example` to `.env` and fill in the LiveKit settings and a random `CUE_BOOTSTRAP_SECRET`.
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

4. Open `http://localhost:5173`, keep `CAM-HOST` selected for Person A, enter the Stage 0 bootstrap secret, preview the camera, then publish.

Camera access works on `localhost` or HTTPS. A different laptop cannot use D's `localhost`; D must expose the web/API endpoint through the team's approved authenticated HTTPS setup.

## Guest identity (Person B)

`CAM-GUEST` is video only. Identifying anyone on it is opt-in and event-scoped:
references live in memory on D's Mac, are deleted on withdrawal or at event end,
and an unknown face stays unknown. See [docs/guest-privacy.md](docs/guest-privacy.md),
[docs/vision-models.md](docs/vision-models.md) and
[docs/stage-0-1-b-handoff.md](docs/stage-0-1-b-handoff.md).

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

## Producer receiver (Person D's Mac)

`/producer` on the same web app is the subscribe-only Stage 0 receiver. It requests a credential from `POST /api/v1/stage0/receiver-token` (same Stage 0 secret, `canPublish: false`), joins the same room, and binds `CAM-HOST`, `CAM-GUEST` and `CAM-WIDE` tiles from each participant's server-set metadata. Only `CAM-HOST`'s microphone is played. The Mac never publishes.

Mac startup, tunnel and verification steps: [docs/stage-0-d-mac-run.md](docs/stage-0-d-mac-run.md).
