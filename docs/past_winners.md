# HackMIT past winners by track (2022–2025)

Compiled 2026-09-19. Public sources only; the official 2025 gallery (plume.hackmit.org) is login-gated — see "Gaps" at the bottom.

## Prize structure (same every year 2024–2026)

- **3 general prizes** (1st / 2nd / 3rd overall)
- **1 beginner prize** (most of the team at their first hackathon)
- **4 track prizes** (one per track)
- **Sponsor challenges** on top (2025: 22 of them; 2026: 23 already listed on Plume, e.g. "Best Use of Devin", "Signal in the Noise", "Touch Grass: Build Something That Understands the Real World", "Best Developer Tool", "ElevenLabs Challenge", "ASUS / Zenni Claw Challenge", "Best Use of Espressif Hardware"). In 2025 there was also a **Hardware** winner announced alongside the tracks.
- Overall winners in 2023 got Sony XM5s / an iPhone; Fetch.ai's 2025 sponsor pool was $2.5k/$1.5k/$1k.

## Tracks by year

| Year | Tracks |
|---|---|
| 2022 | New Frontiers (Web3/AI/ML/VR-AR), Sustainability, Education, Entertainment |
| 2023 | Interactive Media, Sustainability, Education, Health & Accessibility (+ Beginner) |
| 2024 | Interactive Media, Sustainability, Education, Healthcare (+ Beginner) |
| 2025 | Entertainment, Sustainability, Education, Healthcare (+ Beginner, General) |
| 2026 | Entertainment, Education, Sustainability, Healthcare (per hackmit.org) |

---

## 2025 (13–14 Sep 2025)

| Prize | Project | What it was |
|---|---|---|
| 1st / 2nd / 3rd overall | *unknown* | Announced on Instagram (image only, caption doesn't name them) |
| **Entertainment track** | **EyeCraft** | Minecraft accessibility mod: head-tracking + facial expressions + voice commands as input. Mouth "O" = forward, wink = click, tilt head = hotbar, voice for crafting. Team of 4 (Northeastern). Judged strongly on the demo: "how well the demo worked and how everything flowed together." Repo: github.com/qihongw08/eyecraft-mod |
| **Sustainability track** | **Griddy** | Micro-grid powered by *homemade iron-air batteries* from fertiliser-derived chemicals, casings built in MIT makerspaces. Physical hardware + real chemistry, not an app. Team of 3 (Northeastern + MIT). |
| Education track | *unknown* | |
| Healthcare track | *unknown* | |
| Beginner | *unknown* | |
| Hardware | *unknown* | |
| EigenCloud sponsor (1st) | **Kava** | AI insurance-claim generator: upload housing docs + damage photos → complete claim. Inspired by Jan 2025 LA wildfires. Team of 2. |
| EigenCloud (prize) | **Diagonalize** | Privacy-preserving OAuth on TEEs + WebAuthn; demo consumer = pseudonymous verified-employee forum. github.com/dheerajt10/diagonalize |
| Mentra sponsor (1st) | Handyman for smart glasses | Chained two glasses (Mentra Live camera + Even Realities G1 display): scan barcode → pull instructions → show step-by-step on the display. Demoed live assembling a Target dresser and a LEGO set. Team of 4 across UVA/UT/Duke. |
| Infosys sponsor (1st) | **EcoAI** | LLM prompt rewriter that cuts tokens, with a carbon/energy estimate. Flask. github.com/aaditisinghal/ecoai-hackmit |
| Fetch.ai sponsor (1st) | **Mercury** | Adjusts homes based on climate (agentic). |
| Fetch.ai sponsor | **MediData** | github.com/Jaysuun01/MediData |
| Sponsor (1st, unnamed) | **Rhythm Flow** | Collaborative workspace analysing *contribution rhythm* (talk-time, keystroke bursts) not content; Whisper for voice. |
| "HackMIT winner" (unspecified) | **Showcase** | Codebase/URL → auto-generated demo video with AI avatar. Cerebras + RunwayML pipeline. |

## 2024 (14–15 Sep 2024)

| Prize | Project | What it was |
|---|---|---|
| 1st / 2nd overall | *unknown* | |
| 3rd overall | AI Journaling Assistant | Only known from a GitHub profile line; no details. |
| **Healthcare track** | **MindScape** | MRI slices → custom 2D neural radiance field (PyTorch, trained on laptops) → SAM segmentation for tumours → trimesh → Three.js 3D/AR viewer. Clerk auth "for HIPAA". github.com/arjun-banerjee/Mindscape |
| **Education track** | **PalmLabs** | ASL learning: Chrome extension highlights words you can learn in ASL while browsing; web app uses a CNN (HuggingFace model) to check your signing in real time. React/TS + Convex + FastAPI + Clerk. github.com/VishnuK1947/PalmLabs |
| **Sustainability track** | *unnamed* | Palantir's CTO tweeted the Sustainability grand-prize team used Foundry as backend and also won 3 sponsor challenges. Likely **Echosystem** (below) but unconfirmed. |
| Interactive Media track | *unknown* | |
| **Beginner** | **Get Away** | Safer routes for cyclists/pedestrians: users mark unlit / no-bike-lane zones, router avoids them. Open-source maps. Solo front+back end (Tec de Monterrey). |
| Best Hardware Hack | **telepathy** | Sunglasses + ESP32 + mic embedded in a foam earplug *worn in the nostril*; tongue taps on the palate → vibrations → Morse → text. Silent, invisible input. github.com/MingkuanY/telepathy |
| Best UX | **RememberMe** | Pi Pico + e-ink handheld that stores messages/pixel-art/time-capsules people send you via a Pi 4 web server; fully offline. github.com/EncryptEx/HackMIT24 |
| Skylo 1st, InterSystems 2nd | **Echosystem** | Nicla Vision mic → Raspberry Pi running TinyML bird-call classifier → Skylo satellite uplink → IRIS vector DB. Deployable anywhere with no cellular. |
| InterSystems 1st (GenAI/IRIS) | **Memora** | Face recognition + conversation summaries as a "second brain" for Alzheimer's patients. |
| InterSystems 3rd | **Rewind** | AR memory-preservation app; Gaussian splatting from user video, viewed on Vision Pro. |
| Baseten (best use of Flux) | **a.phrase.ia** | Emoji sequences → natural spoken sentences for aphasia patients; n-gram Markov recommender trained on synthetic emoji data. |
| Fetch.ai 3rd | **Stud.ai** | Teacher-side Chrome extension estimates assignment time and blocks it into students' Google Calendars. |

## 2023 (16–17 Sep 2023) — full list, from Devpost

| Prize | Project | What it was | Stack |
|---|---|---|---|
| **1st overall** | **Muse** | Ask any question → curated playlist of *minute-level snippets* from MIT OCW lecture videos. Transcripts chunked to 1-min segments, embedded with OpenAI, stored in Lantern (Postgres vector DB), nearest-match retrieval. | Next.js, Prisma, Postgres/Lantern, OpenAI |
| **2nd overall** | **lettuce** | Scan grocery receipts (OCR) → pantry inventory → expiry alerts → offer surplus to friends → recipes from combined pantries. | React, Bootstrap, Firebase, image-to-text model |
| **3rd overall** | **BeeMovr** | Map tool for beekeepers (weather + location data to protect hives). Fully open-sourced. | Next.js, TS, Mapbox, Open-Meteo, Docker/nginx |
| Education track | Handwriting Teacher | LLM generates phrases targeting letters you struggle with; you write on a p5.js canvas or upload a photo; OCR scores it with sequence alignment. | Flask, EasyOCR, ChatGPT, p5.js |
| Health & Accessibility track | Fluxus | Natural-language → SQL workspace over EHRs on InterSystems IRIS, using IntegratedML for instant predictive queries. | Vue, Flask, IRIS, RabbitMQ, GPT |
| Interactive Media track | Pathosense | "Bring emotion into technology" — hardware sensor + amplifier/filter + Keras classifier (description withheld by team). | Hardware, Keras, scikit-learn |
| Sustainability track | PantryPuzzle | Photo of food → Google Vision extracts item + expiry → inventory → expiry alerts, recipes, donation routing to food pantries. | React, Flask, Firebase, Google Cloud Vision |
| Beginner track | Catmosphere | Cozy cat platformer through five layers of the atmosphere; custom art and music. | Unity, HTML/JS |
| Arrowstreet (GenAI data analysis) | InSightAI | Screen capture + voice explanation → GPT-4 answers with on-screen annotations and spoken reply. Mathpix for diagrams. | Flask, Google Speech, Mathpix, GPT-4 |

Unverified: a UCSC news piece (Oct 2023) says "Echo" (biometric MFA with NFT login records) won 1st in Interactive Media — but Devpost shows Pathosense. Possibly a sponsor prize or a different year.

## 2022 (1 Oct 2022)

- New Frontiers track winner: **PlugLess** (github.com/ayushzenith/PlugLess). Other track winners not found.

---

## What the winners have in common

1. **The demo is the product.** Every winner with a write-up credits a working, end-to-end demo (EyeCraft: "a product that you could use"; Mentra: "physically show that this has real-world applicability"). Judges walk table to table for ~3 minutes; a live thing beats slides.
2. **Physical / hardware projects punch above their weight.** Griddy (batteries), telepathy (nostril mic), RememberMe (e-ink), Echosystem (satellite + Pi), the Mentra glasses hack. Hardware is rarer at HackMIT, so it stands out — and there's a dedicated Hardware prize now. Your AR-glasses/GESTUS background is directly relevant here.
3. **Accessibility framing wins tracks repeatedly.** EyeCraft (Entertainment 2025), PalmLabs (Education 2024), a.phrase.ia, Handwriting Teacher, Fluxus. "Who can't do X today, and now can" is the clearest impact story.
4. **Overall winners tend to be polished software with one clever data/ML trick**, not the most ambitious idea: Muse = OCW transcripts + vector search; lettuce/PantryPuzzle = receipt/photo OCR + expiry. Narrow scope, finished.
5. **Track winners are literal about the track.** Education = teaching a skill (handwriting, ASL); Sustainability = food waste / grid / biodiversity; Healthcare = clinical data or patient tooling.
6. **Sponsor challenges are the easiest wins.** ~22 challenges, many with a $1k–2.5k pool; Griddy/Kava/Echosystem stacked track + sponsor prizes. Pick 2–3 sponsor challenges at the start and design so one build hits them all (Echosystem: Skylo + InterSystems + Modal from one project).
7. **Teams of 3–4 with split roles** (hardware / ML / frontend) are the norm among winners.

## Gaps and how to close them

- 2025 overall 1st–3rd, Education, Healthcare, Beginner and Hardware winners — and 2024 overall 1st/2nd, Sustainability, Interactive Media — are all in the login-gated Plume gallery. **You can see them by logging in at https://plume.hackmit.org/gallery?hackathon_id=hack-2025** (and `hack-2024`); winners carry an `is_winner_text` badge. If you paste me a session token I can pull the full list.
- 2026 tracks aren't yet on Plume's `/tracks` endpoint, but hackmit.org shows Entertainment / Education / Sustainability / Healthcare cards.

## Sources

- Devpost 2023: https://hack-mit-2023.devpost.com/project-gallery (and each project page)
- Plume API (public): https://plume.hackmit.org/api/v3/hackathons/hack-2025/categories, `/challenges`, `/hack-2026/challenges`
- Ballot 2024 public project endpoint (links found in public GitHub READMEs)
- Khoury/Northeastern on 2025 winners: https://www.khoury.northeastern.edu/khoury-undergrads-win-three-categories-at-prestigious-mit-hackathon
- UVA McIntire on Mentra 2025: https://experience.mcintire.virginia.edu/news/pierce-brookins-earns-top-spot-hackmit-event/
- Tec de Monterrey on Get Away 2024: https://conecta.tec.mx/en/news/monterrey/education/tec-student-wins-award-road-safety-project-hackmit-2024
- UCSC on Echo: https://engineering.ucsc.edu/news/cs-student-places-first-at-hackmit/
- Palantir CTO tweet (2024 sustainability): https://x.com/ssankar/status/1836076339691999679
- Instagram winner posts (images only): https://www.instagram.com/p/DOzgduujPIZ/ (2025 grand prizes), https://www.instagram.com/p/DOzfwPFjAM4/ (2025 track winners), https://www.instagram.com/p/CyHCDabOKWP/ (2023)
- GitHub repos linked inline above; archive sites: https://archive.hackmit.org/2022/ … /2025/
