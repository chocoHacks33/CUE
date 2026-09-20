# Person A Stage 3 preliminary handoff

This preliminary handoff is superseded by `docs/stage-3-a-handoff.md`.

Branch: `codex/person-a-stage-3-prep`

This branch prepared the reconnect, duplicate-slot, cleanup and reconciliation
boundaries without depending on D's final Stage 2 compositor merge. It is safe
to merge after Stage 2, but it does **not** pass the Stage 3 system gate by
itself. The exit gate still requires a genuine three-laptop live sequence on
D's MacBook.

## What is ready

- Trusted video attach/detach endpoints keyed by event, stable camera ID,
  approved participant identity and LiveKit track SID.
- Server-owned stream epochs. A republish, including attach after a clean
  detach, advances the epoch; a duplicate attach is idempotent.
- A late detach for an old track is ignored and cannot clear the replacement
  track.
- A transport event cannot take over a camera slot owned by another approved
  participant identity.
- Visual observations are invalidated when a track is replaced or detached,
  so identity evidence cannot cross a physical-stream boundary.
- A browser transport client plus a pure authoritative-binding reducer. The
  reducer rejects lower epochs and reports same-epoch identity conflicts.
- An explicit, idempotent event-end endpoint that ends control, revokes control
  sessions, removes readiness, pairing/binding state, guest references and live
  observations, then closes the event's control sockets.
- Ended event IDs are fenced for the lifetime of the API process. New pairing,
  media credentials, transport changes, control sessions and guest mutations
  receive HTTP 410.

## Integration work after D merges Stage 2

1. In D's real LiveKit receiver, call `video-attached` only from a trusted
   subscribed/published video-track event. Never accept a camera ID supplied by
   an unapproved browser without the existing pairing identity check.
2. Apply the returned binding with `applyAuthoritativeBinding` before mapping
   the MediaStreamTrack into a programme slot.
3. On unsubscribe/unpublish, call `video-detached` with the exact track SID.
   `STALE_DETACH_IGNORED` is expected when LiveKit delivers an old event late.
4. After a room reconnect, fetch the authoritative bindings, reconcile all
   three local slots, then send the existing `render.reconcile` message for the
   source actually drawn on the programme canvas.
5. Keep `CAM-HOST` as the only programme audio source. Video reconnects must
   never switch audio ownership.
6. Call the event-end endpoint only after the operator confirms shutdown. D
   must also disconnect the LiveKit room and stop local media/recording tracks;
   the API cannot stop browser-owned hardware remotely.

## Verification available now

From `apps/api`:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check src tests
```

From the repository root:

```powershell
npm.cmd test
npm.cmd run typecheck
npm.cmd run build
```

The automated checks cover direct republish, clean detach/reconnect, late old
detach, identity takeover rejection, ended-event fencing and cleanup. They do
not substitute for LiveKit callback ordering on the physical Mac.

## Stage 3 physical gate owned by A + D

Use `docs/results/a-stage3-integration-check.md` after this branch and D's
Stage 2 work are integrated. A leads fixes; D operates and records results on
the Mac. Until every required row passes, report: “A Stage 3 preliminaries
complete; live Stage 3 gate not yet run.”
