"""Make C-owned service packages importable by tests without touching A/B/D dirs."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for sub in ("services/worker", "services/api"):
    p = str(REPO / sub)
    if p not in sys.path:
        sys.path.insert(0, p)
