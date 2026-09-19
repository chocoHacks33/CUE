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

## Stage 0 boundaries

Implemented now:

- browser webcam preview and publication;
- server-side, short-lived LiveKit token creation;
- fixed camera/audio topology;
- shared TypeScript and Python contract vocabulary;
- configuration/health endpoints and local tests.

Intentionally deferred:

- one-time pairing grants and producer approval;
- reconnect epochs and duplicate-slot arbitration;
- worker frame/PCM ingestion;
- producer/compositor/recording UI;
- face, speech, policy and automatic switching.
