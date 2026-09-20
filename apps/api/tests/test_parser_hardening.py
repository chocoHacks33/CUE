"""Stage-3 hardening rules for cue_api.semantics.parser.

Offline-only. We do not import the real OpenAI parse() into these tests;
we exercise validate() (deterministic guard) and the parse() safe-HOLD
paths that don't need a network call. The prompt text itself is checked
so the LLM sees the hardened instructions.
"""
from __future__ import annotations

import pytest

from cue_api.semantics.parser import (
    Action,
    Cue,
    Intent,
    ProgrammeContext,
    Scope,
    TemporalIntent,
    _ambiguity_note,
    _bounded_context,
    _duplicate_first_names,
    _safe_hold_cue,
    parse,
    validate,
)

DUPLICATE_ROSTER = {
    "guests": [
        {"id": "sarah-tan",   "name": "Sarah Tan",
         "aliases": ["Ms Tan", "Sarah Tan"], "role": "guest of honour"},
        {"id": "sarah-cohen", "name": "Sarah Cohen",
         "aliases": ["Sarah Cohen"], "role": "judge"},
        {"id": "daniel",      "name": "Daniel Reyes",
         "aliases": ["Dan"], "role": "speaker"},
    ]
}


def _base_show(target: str, evidence: str) -> Cue:
    return Cue(
        target_guest_ids=[target], scope=Scope.SINGLE, intent=Intent.INTRODUCE,
        temporal_intent=TemporalIntent.NOW, action=Action.SHOW,
        evidence_text=evidence,
    )


# ---- duplicate first names ------------------------------------------------

def test_duplicate_first_names_detected():
    assert _duplicate_first_names(DUPLICATE_ROSTER) == {"sarah"}


def test_ambiguous_first_name_forces_uncertain_hold():
    """Bare 'Sarah' with two Sarahs on the roster must not cut."""
    cue = _base_show("sarah-tan", "Please welcome Sarah.")
    out = validate(cue, roster=DUPLICATE_ROSTER)
    assert out.action == Action.HOLD
    assert out.temporal_intent == TemporalIntent.UNCERTAIN
    assert out.target_guest_ids == []


def test_full_name_disambiguates_duplicate():
    cue = _base_show("sarah-tan", "Please welcome Sarah Tan to the stage.")
    out = validate(cue, roster=DUPLICATE_ROSTER)
    assert out.action == Action.SHOW
    assert out.target_guest_ids == ["sarah-tan"]


def test_unique_alias_disambiguates_duplicate():
    cue = _base_show("sarah-tan", "Now Ms Tan will explain.")
    out = validate(cue, roster=DUPLICATE_ROSTER)
    assert out.action == Action.SHOW
    assert out.target_guest_ids == ["sarah-tan"]


def test_ambiguity_note_only_when_duplicates_exist():
    assert _ambiguity_note(DUPLICATE_ROSTER).strip() != ""
    unique_roster = {"guests": [
        {"id": "x", "name": "Alice Alpha", "aliases": [], "role": "guest"},
        {"id": "y", "name": "Bob Bravo",   "aliases": [], "role": "guest"},
    ]}
    assert _ambiguity_note(unique_roster).strip() == ""


# ---- programme context / role resolution ----------------------------------

def test_role_scope_resolves_with_single_holder():
    programme = ProgrammeContext(
        segment="keynote",
        segment_roles={"keynote": ["maya"]},
        programme_revision=3,
    )
    cue = Cue(
        target_guest_ids=[], scope=Scope.ROLE, intent=Intent.INTRODUCE,
        temporal_intent=TemporalIntent.NOW, action=Action.SHOW,
        evidence_text="Now our keynote takes the floor.",
    )
    roster = {"guests": [
        {"id": "maya", "name": "Maya Chen", "aliases": ["Maya"], "role": "keynote"},
    ]}
    out = validate(cue, roster=roster, programme=programme)
    assert out.action == Action.SHOW
    assert out.target_guest_ids == ["maya"]
    assert out.scope == Scope.SINGLE


def test_role_scope_stays_hold_when_multiple_holders():
    programme = ProgrammeContext(
        segment="guest_intros",
        segment_roles={"guest of honour": ["sarah", "kai"]},
        programme_revision=5,
    )
    cue = Cue(
        target_guest_ids=[], scope=Scope.ROLE, intent=Intent.INTRODUCE,
        temporal_intent=TemporalIntent.NOW, action=Action.SHOW,
        evidence_text="Please welcome our guest of honour.",
    )
    roster = {"guests": [
        {"id": "sarah", "name": "Sarah T", "aliases": [], "role": "guest of honour"},
        {"id": "kai",   "name": "Kai N",   "aliases": [], "role": "guest of honour"},
    ]}
    out = validate(cue, roster=roster, programme=programme)
    assert out.action == Action.HOLD


def test_role_scope_stays_hold_without_programme():
    cue = Cue(
        target_guest_ids=[], scope=Scope.ROLE, intent=Intent.INTRODUCE,
        temporal_intent=TemporalIntent.NOW, action=Action.SHOW,
        evidence_text="Please welcome our next guest.",
    )
    out = validate(cue, roster=DUPLICATE_ROSTER, programme=None)
    assert out.action == Action.HOLD


# ---- temporal intent gating -----------------------------------------------

@pytest.mark.parametrize("temporal", [
    TemporalIntent.NEGATED,
    TemporalIntent.PAST,
    TemporalIntent.UNCERTAIN,
])
def test_non_now_temporal_never_cuts(temporal):
    cue = Cue(
        target_guest_ids=["daniel"], scope=Scope.SINGLE,
        intent=Intent.INTRODUCE, temporal_intent=temporal,
        action=Action.SHOW, evidence_text="Daniel.",
    )
    out = validate(cue, roster=DUPLICATE_ROSTER)
    assert out.action == Action.HOLD


def test_group_now_goes_wide():
    cue = Cue(
        target_guest_ids=["daniel", "sarah-tan"], scope=Scope.GROUP,
        intent=Intent.INTRODUCE, temporal_intent=TemporalIntent.NOW,
        action=Action.WIDE, evidence_text="Both of them.",
    )
    out = validate(cue, roster=DUPLICATE_ROSTER)
    assert out.action == Action.WIDE
    assert out.scope == Scope.GROUP


# ---- bounded context ------------------------------------------------------

def test_bounded_context_keeps_last_three():
    ctx = ["a", "b", "c", "d", "e"]
    assert _bounded_context(ctx) == "c | d | e"


def test_bounded_context_accepts_multiline_string():
    ctx = "a\nb\nc\nd"
    assert _bounded_context(ctx) == "b | c | d"


def test_bounded_context_empty_ok():
    assert _bounded_context(None) == ""
    assert _bounded_context("") == ""


# ---- safe HOLD paths ------------------------------------------------------

def test_parse_without_cue_model_returns_safe_hold(monkeypatch):
    monkeypatch.delenv("CUE_MODEL", raising=False)
    cue, ms = parse("Please welcome Sarah Tan.")
    assert cue.action == Action.HOLD
    assert cue.temporal_intent == TemporalIntent.UNCERTAIN
    assert "CUE_MODEL not set" in cue.evidence_text
    assert ms == 0.0


def test_safe_hold_cue_shape():
    cue = _safe_hold_cue("hello world", reason="TestErr: boom",
                         programme_revision=9)
    assert cue.action == Action.HOLD
    assert cue.temporal_intent == TemporalIntent.UNCERTAIN
    assert cue.programme_revision == 9
    assert cue.evidence_text.startswith("ERROR: TestErr")


def test_parse_hard_timeout_paths_to_safe_hold(monkeypatch):
    """A stuck OpenAI call must not wedge the queue."""
    monkeypatch.setenv("CUE_MODEL", "test-model")

    import cue_api.semantics.parser as parser_mod

    class SlowClient:
        class responses:
            @staticmethod
            def parse(*_a, **_kw):
                import time as _t
                _t.sleep(10)  # far beyond hard_timeout_s below
                raise RuntimeError("should have been cancelled")

    monkeypatch.setattr(parser_mod, "_client", SlowClient())
    monkeypatch.setattr(parser_mod, "_executor", None)  # rebuild

    cue, ms = parse("something", hard_timeout_s=0.1)
    assert cue.action == Action.HOLD
    assert "TimeoutError" in cue.evidence_text or "timeout" in cue.evidence_text
