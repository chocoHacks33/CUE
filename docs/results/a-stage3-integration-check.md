# Person A Stage 3 live integration check

Status: **NOT RUN — physical Mac and three Windows publishers required**

Commit tested: `________________`

Operator/date/network: `________________`

| Required check | Result | Evidence / notes |
|---|---|---|
| All three approved camera IDs map to the correct physical laptops | NOT RUN | |
| Duplicate participant cannot take an occupied slot | NOT RUN | |
| Disconnect/rejoin advances stream epoch and restores the same stable slot | NOT RUN | |
| Late old-track detach does not clear the replacement track | NOT RUN | |
| Old identity observation disappears on reframe, detach and republish | NOT RUN | |
| D reconnects and reconciles the source actually visible on programme | NOT RUN | |
| `CAM-HOST` audio remains continuous through reconnects and cuts | NOT RUN | |
| Future mention causes no cut | NOT RUN | |
| Unscripted immediate introduction selects the supported live camera | NOT RUN | |
| Covered/unusable camera produces safe behaviour, not a false named take | NOT RUN | |
| Manual HOLD rejects a late automated command | NOT RUN | |
| End event closes control, deletes event identity state and blocks re-entry | NOT RUN | |
| The resulting programme recording plays independently | NOT RUN | |

Stage 3 passes only with a genuine end-to-end sequence using the real webcams
and master microphone. A hardcoded named-camera switch or fixture is not a pass.

