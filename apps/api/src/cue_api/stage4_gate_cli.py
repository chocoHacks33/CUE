from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from cue_api.stage4_gate import GateStatus, TrialResult, assess_stage4


def _load_trials(path: Path) -> list[TrialResult]:
    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    values = raw.get("trials") if isinstance(raw, dict) else raw
    if not isinstance(values, list):
        raise ValueError("report must be a JSON list or an object containing a trials list")
    if not all(isinstance(value, dict) for value in values):
        raise ValueError("every trial must be a JSON object")
    return [TrialResult.from_mapping(value) for value in values]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate Person A's Stage 4 evidence")
    parser.add_argument("report", type=Path, help="JSON report containing Stage 4 trials")
    args = parser.parse_args(argv)
    try:
        assessment = assess_stage4(_load_trials(args.report))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(json.dumps(assessment.to_mapping(), indent=2, sort_keys=True))
    return 0 if assessment.status is GateStatus.PASS else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
