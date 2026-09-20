# CUE demo — C-lane script (90 s)

My part of the 90-second demo, with fallback ladders and what is
automatic vs configured by hand.

## Preflight (60 s before "go")

```bash
python scripts/demo_preflight.py
```

Every line must read `[GO]`. If any read `[NO-GO]`, follow the ladder
below before starting. `--offline` skips network probes but still
covers env vars, roster, mic and fixture.

## What is automatic vs configured by hand

Automatic on stage:
- Deepgram ASR (Flux) streams words to the desk.
- Semantic parser turns each final sentence into a Cue.
- Director decides TAKE / STAY / SLATE.
- LiveLane emits the DecisionEvent to the compositor.

Configured by hand before the show:
- **Role-based mapping** (`role_map`): `sarah -> CAM-GUEST`,
  `daniel -> CAM-GUEST`, etc. Every decision this demo emits is
  stamped `identity="ROLE_BASED"`. Face verification is off.
- **Roster** (`apps/api/src/cue_api/semantics/roster.json`): 7 guests
  with names, aliases and role labels. The parser sees this exact
  list.
- **Deepgram keyterms**: the same 7 names + aliases boosted on the
  streaming request.
- **Endpointing** on nova-3 or **eager_eot_threshold** on Flux.

## Five spoken lines, in order

Each line is spoken by the host (me). "Point at" is where the eye
should go on screen the moment the decision lands.

| # | Say | Expected result | Operator key | Point at |
|---|---|---|---|---|
| 1 | "Please welcome Sarah Tan." | Cut to `CAM-GUEST`, plain_reason "CUE cut to Sarah." | none | PGM (guest camera) |
| 2 | "Priya, could you jump in?" | Cut to `CAM-GUEST` (priya → guest slot for demo) | none | UMD bar changes |
| 3 | "Actually Sarah — sorry, Daniel." | ONE cut, to Daniel (correction rule) | none | Decision log: single row |
| 4 | "Please welcome Sarah and Daniel." | Wide shot (`CAM-WIDE`) | none | PGM (wide shot) |
| 5 | "Thanks both. Back to me." | Cut to `CAM-HOST` | none | PGM (host) |

If I need to override at any point: press `1` / `2` / `3` for
Host / Guest / Wide. Press `H` to hold. `A` to resume auto.

## Fallback ladder

1. **OpenAI is down** — the parser can't run.
   - CUE switches to **ASSIST**: cues become suggestions that need my
     ACCEPT. I say aloud: "Semantic engine is down, I'm running in
     assist mode — you'll see suggestions, I confirm each."
   - I use `1` / `2` / `3` to accept suggestions or `S` to skip.
2. **Deepgram is down** — no captions arrive.
   - CUE goes to **captions only** → **manual only**. I say aloud:
     "ASR is down, I'll switch by hand."
   - I use `1` / `2` / `3` for every take.
3. **Everything is down** — nothing on the wire.
   - I run the **fixture timeline** (`python scripts/fixture_cues.py`).
   - The desk shows a big **FIXTURE** chip in the header AND every
     decision is stamped `source="FIXTURE"` in the log. I say aloud:
     "This is a scripted timeline, marked FIXTURE on screen."

## Key presses cheat-sheet

| Key | Action |
|---|---|
| 1 | Take `CAM-HOST` |
| 2 | Take `CAM-GUEST` |
| 3 | Take `CAM-WIDE` |
| H | Hold (freeze current) |
| A | Resume auto |

## Identity disclosure

Because we ship role-based, I say once during the intro:
"CUE is doing camera direction from role mappings — it isn't
face-recognising anyone tonight."
