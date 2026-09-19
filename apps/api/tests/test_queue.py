"""Unit tests for cue_api.semantics.queue.SemanticQueue."""
from __future__ import annotations

from cue_api.semantics.parser import Action, Cue, Intent, Scope, TemporalIntent
from cue_api.semantics.queue import SemanticQueue


def _ok_cue(text: str) -> tuple[Cue, float]:
    return Cue(
        target_guest_ids=["sarah"] if "sarah" in text.lower() else [],
        scope=Scope.SINGLE if "sarah" in text.lower() else Scope.NONE,
        intent=Intent.INTRODUCE,
        temporal_intent=TemporalIntent.NOW,
        action=Action.SHOW if "sarah" in text.lower() else Action.HOLD,
        evidence_text=text,
    ), 5.0


def _raising(exc: Exception):
    def _fn(_text: str) -> tuple[Cue, float]:
        raise exc
    return _fn


# ---- coalescing behaviour ---------------------------------------------------

def test_first_submit_populates_in_flight_only():
    q = SemanticQueue(parse_fn=_ok_cue)
    q.submit("please welcome Sarah", mode_revision=0, now=0.0)
    assert q.in_flight is not None
    assert q.in_flight.utterance == "please welcome Sarah"
    assert q.pending is None
    assert q.dropped == []


def test_second_submit_goes_to_pending():
    q = SemanticQueue(parse_fn=_ok_cue)
    q.submit("first", 0, 0.0)
    q.submit("second", 0, 0.1)
    assert q.in_flight.utterance == "first"
    assert q.pending.utterance == "second"
    assert q.dropped == []


def test_third_submit_drops_older_pending_and_logs_it():
    q = SemanticQueue(parse_fn=_ok_cue)
    q.submit("first", 0, 0.0)
    q.submit("second", 0, 0.1)
    q.submit("third", 0, 0.2)
    assert q.in_flight.utterance == "first"
    assert q.pending.utterance == "third"
    assert len(q.dropped) == 1
    assert q.dropped[0].utterance == "second"
    assert q.dropped[0].reason == "superseded_by_newer_pending"


def test_two_fast_utterances_leave_only_latest_pending_after_many_submits():
    q = SemanticQueue(parse_fn=_ok_cue)
    utts = ["u1", "u2", "u3", "u4", "u5"]
    for i, u in enumerate(utts):
        q.submit(u, 0, float(i))
    assert q.in_flight.utterance == "u1"
    assert q.pending.utterance == "u5"
    assert [d.utterance for d in q.dropped] == ["u2", "u3", "u4"]


# ---- drain advances the queue ----------------------------------------------

def test_drain_returns_none_when_empty():
    q = SemanticQueue(parse_fn=_ok_cue)
    assert q.drain(0.0) is None


def test_drain_returns_cue_with_evidence_text_from_utterance():
    q = SemanticQueue(parse_fn=_ok_cue)
    q.submit("please welcome Sarah Tan.", mode_revision=0, now=0.0)
    cue = q.drain(now=0.1)
    assert cue is not None
    assert cue.evidence_text == "please welcome Sarah Tan."


def test_drain_promotes_pending_to_in_flight():
    q = SemanticQueue(parse_fn=_ok_cue)
    q.submit("first", 0, 0.0)
    q.submit("second", 0, 0.1)
    q.drain(0.2)
    assert q.in_flight is not None
    assert q.in_flight.utterance == "second"
    assert q.pending is None
    q.drain(0.3)
    assert q.in_flight is None
    assert q.pending is None


# ---- mode_revision tagging -------------------------------------------------

def test_drain_stamps_mode_revision_captured_at_submit():
    q = SemanticQueue(parse_fn=_ok_cue)
    q.submit("please welcome Sarah", mode_revision=7, now=0.0)
    cue = q.drain(0.1)
    assert cue.mode_revision == 7


def test_mode_revision_is_per_entry_not_global():
    q = SemanticQueue(parse_fn=_ok_cue)
    q.submit("first",  mode_revision=1, now=0.0)
    q.submit("second", mode_revision=2, now=0.1)
    c1 = q.drain(0.2)
    c2 = q.drain(0.3)
    assert c1.mode_revision == 1
    assert c2.mode_revision == 2


# ---- timeout & error paths --------------------------------------------------

def test_timeout_produces_safe_hold_cue():
    q = SemanticQueue(parse_fn=_ok_cue, timeout_s=1.0)
    q.submit("please welcome Sarah", mode_revision=3, now=100.0)
    # `now` is well past timeout_s; the queue should short-circuit to HOLD
    # WITHOUT calling parse_fn.
    cue = q.drain(now=102.5)
    assert cue.action == Action.HOLD
    assert cue.target_guest_ids == []
    assert cue.mode_revision == 3


def test_timeoutError_from_parse_produces_safe_hold_cue():
    q = SemanticQueue(parse_fn=_raising(TimeoutError("provider slow")))
    q.submit("hi", mode_revision=5, now=0.0)
    cue = q.drain(0.1)
    assert cue.action == Action.HOLD
    assert cue.mode_revision == 5


def test_generic_exception_from_parse_produces_safe_hold_cue():
    q = SemanticQueue(parse_fn=_raising(ValueError("bad schema")))
    q.submit("hi", mode_revision=5, now=0.0)
    cue = q.drain(0.1)
    assert cue.action == Action.HOLD
    assert cue.mode_revision == 5


# ---- introspection ---------------------------------------------------------

def test_to_summary_snapshots_state():
    q = SemanticQueue(parse_fn=_ok_cue)
    q.submit("a", 0, 0.0)
    q.submit("b", 0, 0.1)
    q.submit("c", 0, 0.2)
    s = q.to_summary()
    assert s["in_flight"]["utterance"] == "a"
    assert s["pending"]["utterance"] == "c"
    assert s["dropped_count"] == 1


def test_clear_wipes_slots_but_preserves_dropped_log():
    q = SemanticQueue(parse_fn=_ok_cue)
    q.submit("a", 0, 0.0)
    q.submit("b", 0, 0.1)
    q.submit("c", 0, 0.2)
    q.clear()
    assert q.in_flight is None
    assert q.pending is None
    assert len(q.dropped) == 1  # "b" was already dropped before clear
