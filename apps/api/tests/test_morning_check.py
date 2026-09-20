"""Smoke tests for scripts/morning_check.py pure-logic helpers.

Audio-dependent flows (b/c/d) and subprocess flows (a/e/f) are covered
by running the script itself on the demo host; these tests only exercise
the deterministic helpers so a broken math function fails CI.
"""
from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "morning_check.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("morning_check", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["morning_check"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_tokens_strips_punct_and_lowercases():
    m = _load_module()
    assert m._tokens("Please welcome Sarah Tan!") == [
        "please", "welcome", "sarah", "tan",
    ]


def test_wer_perfect_match_is_zero():
    m = _load_module()
    assert m._wer("Please welcome Sarah Tan.", "please welcome Sarah Tan") == 0.0


def test_wer_single_substitution_scales_by_ref_length():
    m = _load_module()
    # 4-word ref, one substitution -> 0.25
    w = m._wer("Please welcome Sarah Tan", "Please welcome Sarah Chan")
    assert math.isclose(w, 0.25, abs_tol=1e-6)


def test_wer_completely_wrong_at_or_above_one():
    m = _load_module()
    assert m._wer("hello there", "totally different unrelated") >= 1.0


def test_dbfs_full_scale_int16_is_near_zero_db():
    m = _load_module()
    # RMS at full scale (32768) -> 0 dBFS.
    assert math.isclose(m._dbfs(32768.0), 0.0, abs_tol=1e-6)


def test_dbfs_zero_rms_returns_floor():
    m = _load_module()
    assert m._dbfs(0.0) == -120.0


def test_dbfs_10x_ratio_is_20_db():
    m = _load_module()
    # A 10x RMS jump is 20 dB regardless of anchor.
    q = m._dbfs(3276.8) - m._dbfs(327.68)
    assert math.isclose(q, 20.0, abs_tol=1e-3)


def test_snr_min_threshold_is_10_db():
    m = _load_module()
    # Guard against silent lowering of the SNR bar.
    assert m.SNR_MIN_DB == 10.0


def test_guest_accuracy_min_is_85_percent():
    m = _load_module()
    assert m.GUEST_ACC_MIN == 0.85


def test_demo_sentences_are_the_runbook_five():
    m = _load_module()
    assert m.DEMO_SENTENCES == [
        "Please welcome Sarah Tan.",
        "Priya, could you jump in?",
        "Actually Sarah, sorry, Daniel.",
        "Please welcome Sarah and Daniel.",
        "Thanks both. Back to me.",
    ]


def test_step_result_no_go_is_blocker():
    m = _load_module()
    r_go = m.StepResult(name="x", verdict="GO")
    r_ng = m.StepResult(name="x", verdict="NO-GO")
    r_skip = m.StepResult(name="x", verdict="SKIP")
    r_nr = m.StepResult(name="x", verdict="NOT RUN")
    assert not r_go.is_blocker()
    assert r_ng.is_blocker()
    assert not r_skip.is_blocker()
    assert not r_nr.is_blocker()
