# What can break the demo

| # | Risk | Test | Fallback | Owner | Status |
|---|------|------|----------|-------|--------|
| 1 | Venue Wi-Fi drops phone video | 3 phones, 10 min, at the demo table | Phone hotspot, drop to 2 cameras, 480p | | |
| 2 | Hall noise wrecks transcription | 5 sentences at full hall noise | Clip-on or handheld mic close to mouth | | |
| 3 | Speech to cut takes over 2 s | Timed from last word to cut | Faster model, clause commits, shorter prompt | | |
| 4 | API key or credit runs out | Check dashboards at hour 20 | Second key ready in .env | | |
| 5 | Phone sleeps or overheats | 20 min soak on charger | Wake lock, auto-lock off, spare phone | | |
| 6 | Judge says a name not on roster | Try 3 random names | HOLD plus visible "not on roster" | | |
| 7 | Laptop browser tab stalls | 20 min soak | Reload hotkey, keep manual keys working | | |
| 8 | Two judges talk at once | Try it | Host holds the mic | | |
