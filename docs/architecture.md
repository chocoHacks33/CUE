# Architecture contract

## Runtime boundary

```text
A/B/C Windows webcam browsers
       | camera video (+ A microphone only)
       v
   LiveKit Cloud SFU
       |
       +--> D Mac browser/director (Stage 0 receiver proof)
       +--> D Mac analysis worker (later stage)

D Mac FastAPI service --> short-lived, scoped LiveKit join tokens
```

The HTTPS API transports admission/control data only. It does not proxy frames, PCM, or base64 media.

## Stable source IDs

- `CAM-HOST`: Person A, host view, camera plus the only master microphone.
- `CAM-GUEST`: Person B, guest view, camera only.
- `CAM-WIDE`: Person C, wide/safety view, camera only.

Source identity comes from the server-issued contract and LiveKit participant metadata, never tile order, screen position, face recognition, or a user-entered display name.

## Stage 1 admission and media boundaries

Implemented now:

- browser webcam preview and publication;
- server-side, short-lived LiveKit token creation;
- single-use camera-slot pairing with explicit producer approval;
- stable event/camera/device-session bindings and track-driven stream epochs;
- validated decoded-frame and real PCM handoff contracts;
- fixed camera/audio topology;
- shared TypeScript and Python contract vocabulary;
- configuration/health endpoints and local tests.

Intentionally deferred:

- live worker frame/PCM ingestion from LiveKit;
- full reconnect reconciliation and binding release at event end;
- producer/compositor/recording UI;
- face, speech, policy and automatic switching.
