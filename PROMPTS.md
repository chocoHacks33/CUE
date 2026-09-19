# Prompts to paste into Claude Code, one milestone per session

Tip: run `/clear` between milestones so old context does not leak in.
CLAUDE.md reloads automatically each session.

## Setup (once)
"Read CLAUDE.md. Create a Python venv, install requirements.txt, copy
.env.example to .env and tell me which keys I must fill in. Do not print keys.
Then run `git init` and make the first commit."

## M1 Semantic brain
"M1. Check that semantic/parser.py matches the installed openai SDK and fix the
call if needed. Run `python tests/run_semantic.py --models <A> <B>` with two
fast models I have access to. Show me the summary table. For every FAIL, tell me
whether the prompt, the test expectation, or the model is at fault. Change only
the prompt in SYSTEM. Do not special-case any test sentence."

Gate: 90%+ pass, zero wrong_cuts, p95 latency written down. Commit.

## M2 One phone feed
"M2. Smallest possible: a Vite React page `/cam` that publishes the rear camera
to a LiveKit room, and `/desk` that shows it. FastAPI endpoint mints LiveKit
tokens from .env. Give me the run commands and how to open it on a phone over
HTTPS."

Gate: a real phone shows up on the laptop on venue Wi-Fi. Commit.

## M3 Multi feed + manual switching
"M3. Support cameras A, B, C by URL param. Desk shows three previews and one
large programme view. Keys 1/2/3 switch programme. Audio comes only from
camera A and must never restart on a switch. Keep all three videos decoding."

Gate: 5 minutes of switching with no audio glitch. Commit.

## M4 Live speech to meaning
"M4. Backend subscribes to camera A audio, streams it to Deepgram with interim
results and roster names as keywords. On each finished clause call
semantic.parser.parse and push the Cue plus latency to the desk over WebSocket.
Show transcript and Cue live. No camera control yet."

Gate: say five test sentences aloud in the noisy hall. Log the end to end
latency from last word to Cue. Commit.

## M5 Director
"M5. Add backend/director.py: pure function (cue, camera_state, roster_map,
now) -> decision. Roster map: sarah=B, daniel=B, host=A, wide=C. Rules: min shot
1.5 s, one fast re-cut allowed on correction, unhealthy camera -> wide, manual
key press always wins and sets HOLD for 5 s. Unit tests first, then wire it to
the desk."

Gate: 'Sarah later' holds. 'Sarah, join us now' takes B. Commit.

## M6 Judge panel
"M6. One clean panel: last utterance, subject, intent, timing, action, chosen
camera, measured latency, and a scrolling decision log. Large type, readable
from two metres. No confidence percentages."

## M7 Optional face identity
Only if M1 to M6 are solid with 6+ hours left.
