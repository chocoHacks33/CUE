# Stage 0 integration check (A + B + C + D)

Run by D on the MacBook, 2026-09-19 (Boston). Base: A+B+C integration 4bcd179 plus D 88b4a9a. Leave physical items NOT RUN until they were run with the real laptops.

## Merge

- Conflicts: `apps/api/src/cue_api/main.py` (B's guest router wiring vs D's receiver endpoint) and `packages/contracts/src/index.ts` (B's `export * from "./vision"` vs D's receiver contracts). Both resolved by keeping both sides; no A/B/C behaviour removed. README auto-merged with all sections intact.
- Cross-lane check: `apps/api` does not import `cue_vision`; no export-name clashes between `vision.ts` and `index.ts`.

## Automated verification on the merged tree (macOS 26.3 arm64, Node 25.9.0, Python 3.14.5)

| Command | Result |
|---|---|
| `npm ci && npm run typecheck` | PASS, exit 0 |
| `npm test` | PASS: contracts 26 tests, web 38 tests |
| `npm run build` | PASS |
| `apps/api`: `python -m pytest -q` | PASS: 72 tests |
| `apps/api`: `python -m ruff check .` | PASS |
| `apps/vision` (core, no OpenCV, as CI does): `python -m pytest -q` | PASS: 61 tests |
| `apps/vision`: `python -m ruff check .` | PASS |
| In-process boot of `create_app()`: routes present | `/health/live`, `/health/ready`, `/api/v1/topology`, `/api/v1/stage0/publisher-token`, `/api/v1/stage0/receiver-token`, plus B's guest routes via router |
| Smoke with unconfigured settings | live 200, ready 503, topology lists CAM-HOST/CAM-GUEST/CAM-WIDE, both token endpoints 503 until LiveKit is configured |

Note: `ruff format --check` reports files that would be reformatted in `apps/api`; CI runs `ruff check` only, and no lane's files were reformatted during the merge.

## Physical verification (A's items 4 to 6)

| Item | Result | Needs |
|---|---|---|
| Central server starts on the Mac with real config | NOT RUN | `LIVEKIT_API_KEY` and `LIVEKIT_API_SECRET` in D's `.env` (URL and bootstrap secret are set) |
| Reachable from the three Windows laptops | NOT RUN | ngrok tunnel URL shared privately; A/B/C publisher pages on their laptops |
| All three camera feeds connect and stay stable | NOT RUN | A, B, C publishing `CAM-HOST`, `CAM-GUEST`, `CAM-WIDE` |
| Switching / producer output | NOT RUN, and not in scope of Stage 0 code: the receiver shows three tiles and records one selected slot; the compositor with TAKE/HOLD is Stage 2 in the v3 plan | |
| Stage 0 recording on the Mac (Test 2) | NOT RUN | see `docs/stage-0-d-mac-run.md` |

Stage 0 is complete only when the physical rows pass. Until then this commit is "automated checks green on the merged tree", nothing more.
