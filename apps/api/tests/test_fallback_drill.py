"""Smoke tests for scripts/fallback_drill.py."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "fallback_drill.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("fallback_drill", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["fallback_drill"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_ladder_has_three_rungs():
    m = _load_module()
    assert len(m.LADDER) == 3


def test_ladder_ids_are_the_three_named_outages():
    m = _load_module()
    assert {step["id"] for step in m.LADDER} == {
        "openai-down", "deepgram-down", "all-down",
    }


def test_every_rung_has_operator_line_and_confirmation():
    m = _load_module()
    for step in m.LADDER:
        assert step["operator_line"], f"missing operator_line: {step['id']}"
        assert step["confirmation_prompt"], (
            f"missing confirmation_prompt: {step['id']}"
        )
        assert step["what_the_desk_should_show"], (
            f"missing checklist: {step['id']}"
        )


def test_simulate_flag_names_follow_the_env_contract():
    m = _load_module()
    for step in m.LADDER:
        assert step["flag"].startswith("CUE_SIMULATE_"), step["flag"]


def test_dry_run_writes_report_without_prompting(tmp_path, monkeypatch,
                                                  capsys):
    m = _load_module()
    monkeypatch.setattr(m, "REPO_ROOT", tmp_path)
    rc = m.main(["--dry-run"])
    assert rc == 0
    md = tmp_path / "docs" / "results" / "C-stage7-fallback.md"
    assert md.exists()
    body = md.read_text(encoding="utf-8")
    assert "Semantic engine down" in body
    assert "ASR down" in body
    assert "fixture timeline" in body.lower()


def test_operator_line_for_all_down_mentions_fixture():
    m = _load_module()
    all_down = next(s for s in m.LADDER if s["id"] == "all-down")
    assert "FIXTURE" in all_down["operator_line"].upper()
