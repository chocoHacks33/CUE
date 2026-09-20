# Desk UI on the team stack

`hemadassani/cue-desk-ui` is a static operator page that speaks C's desk-prototype WebSocket contract. This wires it to the Stage 7 team stack without changing who is in charge: the compositor on the producer page stays the only renderer and acknowledger, and every take or mode change still goes through A's routes with the producer secret.

## Open it

On the Mac, with the API on 8000 and the web app in dev mode:

```bash
npm run dev:web                       # serves /desk.html and proxies /api, /health and /ws to the API
open http://localhost:5173/desk.html  # or ?event=<event id>
```

The page asks once for the producer secret (kept in this tab's sessionStorage, never sent anywhere but this Mac's API), then authenticates the desk socket with it.

For captions and CUE's decisions, run C's live lane with the feed flag:

```bash
cd apps/api && CUE_PRODUCER_SECRET=… .venv/bin/python ../../scripts/live_lane.py --source mic --desk-feed http://127.0.0.1:8000
```

## What the desk shows, and where it comes from

| Desk element | Source on the team stack |
|---|---|
| Camera tiles | subscribe-only LiveKit tracks, attached by each publisher's server-set camera id, the same way the producer page does; the socket hands the page an OBSERVER credential |
| Programme view | the live camera's own track, mirrored when the compositor confirms a cut; it is not the compositor canvas, so slate and overlays are not shown here |
| Mode line | A's control snapshot: AUTO, ASSIST, MANUAL_HOLD; SETUP, READY, DEGRADED and ENDED read as "manual" |
| Captions, Deepgram tab, decisions with reasons and latencies | C's live lane, posted to `POST /api/v1/events/{event}/desk/feed` with the producer secret when started with `--desk-feed` |
| Operator takes in the feed | the compositor going live on a camera with no policy render pending |
| Camera "Ready / Not ready" | the compositor's readiness report to A |
| Roster and Deepgram key terms | C's frozen `config/demo_roster.json`, with each guest's `camera_hint` |
| Suggestion card | a decision from C's lane while the mode is ASSIST; Take it is a manual take of that camera through A's route; Skip is local |
| Right call / Wrong call | stored in the feed on the API, not acted on |

## Security posture

- The desk socket at `/ws` is read-only after authentication and closes with 4401 without the producer secret.
- `manual_take`, `set_mode` and `accept_suggestion` never travel over the socket; the page calls A's `/take` and `/mode` with the secret, the epoch of the bound camera and the current mode revision, so stale or duplicate commands are refused exactly as they would be from the producer page.
- The LiveKit credential is subscribe-only with the OBSERVER role and its own identity; the desk can never publish or acknowledge.

## Sign-up and dashboard pages

`dashboard.html`, `signup.html` and `config.example.js` from the same upstream are served from `apps/web/public/`. They talk to a Google Apps Script web app described in the upstream README, not to this API; copy `config.example.js` to `apps/web/public/config.js` (gitignored: the URL is a capability) and paste the deployed `/exec` URL. Sheet sign-ups do not enrol themselves anywhere on the team stack; B's enrolment and C's roster stay the sources.

## Limits, on purpose

- Nothing on the desk claims a name from a face; identity stays with B's readiness verdict shown on the producer page.
- Decisions on the desk are only as live as C's lane posting them; if the lane is not running with the flag, the desk says so in its caption status.
- The programme mirror shows a camera track, not the compositor's output.

## Verified (this Mac, 2026-09-20)

| Check | Result |
|---|---|
| `apps/api` pytest | 792 passed (11 new: translation, feed store, feed client, and the socket over a bare app with fakes) |
| `apps/api` ruff | clean |
| `npm run typecheck`, `npm test`, `npm run build` | clean, 209 passed, build emits `dist/desk.html` beside the app |
| live, fresh API plus the dev server on free ports, through the proxy | `/desk.html`, `/dashboard.html` and `/signup.html` serve; a wrong secret is refused with 4401; the right one gets a subscribe-only OBSERVER LiveKit credential for the real project URL and the head in contract order; nothing is sent while nothing changes; a caption and a decision posted to the feed with the producer secret arrive on the desk within the tick |

Not run: a live LiveKit room with three publishers into the tiles, and C's lane with real keys posting real captions.
