# CUE — HackMIT 2026 Project Instructions

CUE is a context-aware live director: three phones + a laptop select shots from the meaning of the host's speech, the event programme, who is visible, and camera health. HackMIT 2026, 19–20 September, MIT. Main track: Entertainment (confirm in Plume at submission).

## Read First

- `docs/CUE_Product_Requirements.md` — the PRD and build plan (v1.0, 19 Sep 2026). Section 21 is the 90-second judging demo; section 9 has the language tests that define correct behaviour; section 20 is the scope-cut order.
- `docs/sponsor_challenges_2026.md` — official briefs, criteria and prizes for all sponsor challenges (from dayof.hackmit.org).
- `docs/hackmit_prizes_2026.md` — HackMIT's own prize tiers (overall 1st/2nd/3rd, track 1st/2nd/3rd).
- `docs/past_winners.md` — what won each track 2022–2025 and the patterns (working demo over ambition; hardware stands out; accessibility framing; stack track + 2–3 sponsor prizes).

## Sponsor challenges CUE qualifies for

From the actual briefs, not the titles:

- Deepgram "Build Something Worth Talking To" — must call a Deepgram API; $200 credit, starter repo, on-site audio help.
- OpenAI Challenge — OpenAI API plus a concrete demo of how Codex helped build it; only submitters get credits.
- Long Lake "Convince a Non-Believer" — AI experience a sceptic would try, love, reuse.
- ASUS "Build What's Next" — only if ASUS hardware / Zenni Claw is actually checked out.
- The Token Company LLM cost saving — one semantic call per completed utterance, no per-frame LLM, bounded context (PRD §17).
- Ramp "Save Time. Save Money." — free to submit.

Does NOT qualify: Arduino "Touch Grass" (needs UNO Q sensors), Voloridge "Signal in the Noise" (needs their datasets), MongoDB (no challenge this year), SpaceXAI (needs Cursor + Grok).

## Build Order (from the PRD)

1. Reliable three-camera programme with stable master audio, manual cuts, recording.
2. Verified guest evidence — role-based first; face ID is a timeboxed spike, dropped if it can't reject unknowns.
3. Semantic directing — hold on future mentions/negations, cut on confirmed "now" cues, visible decision log.
4. Sponsor extras only after the end-to-end show works.

## Rules For Agents

- Never present a recorded example as live execution, or manual assignments as face recognition. Disclose reduced scope in the demo and submission.
- Do not purchase services or incur charges because a plan mentions them; use approved credits.
- Keep API keys and room-signing secrets out of the repo and out of QR codes.
- Face references/embeddings stay local and in memory; never log crops or embeddings.
- Related admin (forms, travel, team chat, application) lives in `03_Career/Applications/Hackathons/HackMIT/`, not here.

## Repository Shape

Team repo: https://github.com/chocoHacks33/CUE

Code goes in subfolders alongside `docs/` — suggested: `backend/` (FastAPI control + analysis worker), `web/` (React producer desk + phone publisher), `tests/` (semantic fixture corpus, replay fixtures). Adjust to whatever the team's repo establishes.
