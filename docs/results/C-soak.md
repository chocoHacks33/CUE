# C-lane · Soak run

- Duration: 2.0 min (requested 2.0 min)
- Timeline loops: 12
- Decisions emitted: 79
- Duplicate `decision_seq`s: 0
- Max queue depth: 1
- Memory: 0.0 MB → 0.0 MB (Δ 0.0 MB)
- Log size: 59307 bytes

## Invariants
| Invariant | Result |
|---|---|
| `no_duplicate_decisions` | PASS |
| `bounded_queue_depth` | PASS |
| `bounded_memory_growth_50mb` | PASS |
| `bounded_log_size_12mb` | PASS |

**All invariants passed: True**
