# CUE demo: D's operator card (the live segment, 1:10 to 2:40)

D operates the Mac. The compositor is the programme; the audience sees the canvas and hears A's mic only. Four beats, then hand back. Nothing on this card is automatic: every beat says what you press and what you should see. If you do not see it, say so on stage and move to the fallback.

## Before "go" (60 s)

```bash
apps/api/.venv/bin/python scripts/d_morning_preflight.py --api http://127.0.0.1:8000 --event hackmit-demo
```

Every automated line reads `GO`. Then, on the producer page:

- Mode strip reads **ASSIST** (not AUTO, not DEGRADED). The disclosure line shows B's text.
- Three tiles renderable with fresh frame ages; on air CAM-HOST; tally LIVE.
- Recording running (REC counter moving), with master audio.
- Stage 4 block open below the controls, Start soak pressed if the soak is part of the take.

## Beat 1: future mention, no cut (host says "Sarah joins us after the break")

- Press nothing. Expected: no suggestion, no cut, CAM-HOST stays live. The timeline shows either nothing or a REJECTED entry with the policy's reason.
- Say: "It heard a name and did nothing, because 'after the break' is not now."
- Fallback: if a suggestion appears anyway, do not take it. Say the policy proposed and the desk declined; that is the ASSIST gate working.

## Beat 2: unscripted introduction (host says "Sarah, please join us now")

- Expected in ASSIST: a suggestion banner "Policy suggests CAM-GUEST" with the transcript span as evidence. Press **TAKE suggestion**. Tally goes SWITCHING then LIVE CAM-GUEST within a frame.
- Say: "The model produced meaning, the deterministic policy nominated a shot, and the desk confirmed it."
- Fallback: no suggestion within 3 s: press **2** yourself and say the cut was manual. Never claim it was automatic.
- If the event is in AUTO by team decision, the cut lands without a press; say so.

## Beat 3: covered camera, safe fallback (someone covers the guest webcam)

- Press nothing. Expected: the "No new frame" warning under the canvas counts up; at about 2.5 s the tally goes to CAM-WIDE with reason FAILOVER_SAFE. The Failovers row adds a trial.
- Say: "Frames stopped, so it went to the approved wide view. It never shows a frozen frame as live."
- Fallback: if it does not cut by 4 s, press **0** (slate) and say the failover did not fire in time; that number goes in the results, not under the rug.

## Beat 4: manual HOLD beats late AI (host keeps talking)

- Press **H**. Expected: mode strip MANUAL HOLD at once, button reads HOLDING. Any policy cut that arrives now shows REJECTED with STALE_MODE_REVISION or OPERATOR_HOLD in the timeline.
- Say: "The operator always wins. HOLD does not wait for the network."
- Release with **H** again (back to ASSIST) before handing over.

## Never on stage

- Do not press Enable AUTO unless the team decided AUTO for the show.
- Do not touch the master audio; a video cut never restarts sound. If audio drops, say so; do not plug in another mic.
- Do not read a number you did not measure today.

## After the segment

Stop recording, Download recording, then:

```bash
apps/api/.venv/bin/python scripts/verify_recording.py <file.webm> --min-seconds 60 --backup <private dir> --markdown
```

Export Stage 4 measurements, save one programme still per beat, and fill `docs/results/d-stage7-morning.md`.
