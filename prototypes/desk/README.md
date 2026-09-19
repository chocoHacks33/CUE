# CUE desk prototype (C-lane, localhost)

Standalone. Does not touch `apps/web/` or any A/B/D file. Serves one page and one WebSocket, both routed through the exact same `CLane` A will use in production.

## Install (once)

```bash
cd apps/api
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[dev,desk]"
```

The `desk` extra pulls in `deepgram-sdk`, `sounddevice`, and `python-multipart` in addition to A's base deps. FastAPI + uvicorn are already in the base install.

## Start

From the repo root, with `apps/api`'s venv activated:

```bash
python -m prototypes.desk.server --source fixture   # scripted timeline
python -m prototypes.desk.server --source mic       # laptop mic + Deepgram
```

Then open `http://127.0.0.1:8765` in a browser. `DEEPGRAM_API_KEY` stays server-side; the page never sees it.

### Modes

| `--source` | What it does | Requires |
|---|---|---|
| `fixture` | Replays the scripted demo timeline (future mention → intro → guest camera blocked → manual HOLD → correction). Every event is tagged `FIXTURE` in the UI. | nothing beyond the install |
| `mic` | Captures the laptop microphone with `sounddevice`, streams to Deepgram Listen v1, feeds captions + finals into `CLane`. | `DEEPGRAM_API_KEY` in `.env` |

If `CUE_PROVIDER != openai` or `OPENAI_API_KEY` / `CUE_MODEL` are missing, the server flips to **captions-only** mode: captions still flow, directing decisions are safely-HOLDed, and the UI shows a banner *"Captions live. Directing needs the production model."*

## Keyboard

| key | effect |
|---|---|
| `1` / `2` / `3` | Manual TAKE `CAM-HOST` / `CAM-GUEST` / `CAM-WIDE` |
| `h` | HOLD (producer takes over) |
| `a` | RESUME_AUTO |

The big button under the caption swaps between **Take over** (in AUTO) and **Let CUE direct** (in HOLD / after reconnect / after speech-down).

## What the page shows

- **Programme view** on the left with a red `LIVE` border. Uses `navigator.mediaDevices.getUserMedia` for this laptop's webcam; a placeholder if permission is denied.
- **Three tiles** on the right (`CAM-HOST`, `CAM-GUEST`, `CAM-WIDE`) — labelled placeholders until real feeds exist. Clicking a tile issues a manual TAKE.
- **Caption row** — provisional in grey, final in white.
- **Plain-language reason** in large type, coloured by outcome (green TAKE, amber HOLD, red SLATE, white STAY).
- **Details** toggle reveals the technical panel: who / when / scope / decision / reason / latencies / decision_seq / mode_revision / decision log.

## What crosses the WebSocket (`/ws`)

Server → browser:

- `caption_provisional {text}`
- `caption_final {text, utterance_id, source: LIVE|FIXTURE}`
- `decision {record: DecisionRecord + plain_reason, source_mode}`
- `mode {current_camera, mode, auto_paused, directing_enabled, source}`
- `banner {text}` — captions-only banner, or Deepgram error

Browser → server (all routed through `CLane.on_manual`):

- `manual_take {camera: "CAM-HOST"|"CAM-GUEST"|"CAM-WIDE"}`
- `hold`
- `resume_auto`

## Files

```
prototypes/desk/
  server.py     FastAPI + uvicorn. Composes CLane, mic pump (deferred imports),
                fixture pump. DEEPGRAM_API_KEY never leaves the server.
  index.html    One file. Vanilla JS. No build step.
  README.md     this file.
```
