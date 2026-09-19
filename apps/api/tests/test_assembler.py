"""Unit tests for cue_api.speech.assembler.

Fixtures live in tests/fixtures/deepgram/*.json and are hand-crafted to
match Deepgram's documented live-streaming message shape. All tests are
offline: no network, no keys, no threads.
"""
from __future__ import annotations

import json
from pathlib import Path

from cue_api.speech.assembler import Assembler, Event, FinalUtterance, Provisional

FIXTURES = Path(__file__).parent / "fixtures" / "deepgram"


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def run_fixture(name: str, timeout_s: float | None = None) -> tuple[Assembler, list[Event]]:
    fix = load(name)
    asm = Assembler(
        timeout_s=timeout_s if timeout_s is not None else fix.get("timeout_s", 1.2),
        audio_epoch=fix.get("audio_epoch", 1),
    )
    events: list[Event] = []
    for step in fix["steps"]:
        if step.get("kind") == "reset":
            asm.reset(step["new_epoch"])
            continue
        events.extend(asm.feed(step["message"], step["at"]))
    return asm, events


def finals(events: list[Event]) -> list[FinalUtterance]:
    return [e for e in events if isinstance(e, FinalUtterance)]


def provisionals(events: list[Event]) -> list[Provisional]:
    return [e for e in events if isinstance(e, Provisional)]


# --- basic accumulate / endpoint behaviour ------------------------------------

def test_simple_intro_emits_exactly_one_final():
    _, events = run_fixture("simple_intro")
    assert len(finals(events)) == 1


def test_simple_intro_final_text_joins_both_segments():
    _, events = run_fixture("simple_intro")
    (f,) = finals(events)
    assert f.text == "please welcome Sarah Tan."


def test_simple_intro_words_carry_start_and_end():
    _, events = run_fixture("simple_intro")
    (f,) = finals(events)
    assert len(f.words) == 4
    assert f.words[0]["word"] == "please"
    assert f.started_at == 0.10
    assert f.ended_at == 1.90


def test_interim_only_produces_provisional_events():
    _, events = run_fixture("simple_intro")
    # Provisional appears at least on the first interim.
    provs = provisionals(events)
    assert provs, "expected at least one Provisional from the interim messages"
    # A Provisional must not become a FinalUtterance; those come strictly from
    # accumulated is_final segments plus an endpoint.
    for p in provs:
        assert isinstance(p, Provisional)
        assert p.text.strip()


def test_future_mention_endpoint_flushes_one_utterance():
    _, events = run_fixture("future_mention")
    (f,) = finals(events)
    assert f.text == "Sarah joins us after the break."


def test_correction_split_across_finals_yields_single_final():
    _, events = run_fixture("correction_split")
    fs = finals(events)
    assert len(fs) == 1
    # Both halves of the corrected sentence are in one utterance so the
    # semantic parser (not the assembler) resolves the final target.
    assert fs[0].text == "Please welcome Sarah actually, Daniel."


# --- endpoint variants --------------------------------------------------------

def test_long_pause_utteranceend_message_flushes():
    _, events = run_fixture("long_pause_endpoint")
    (f,) = finals(events)
    assert f.text == "Sarah please come up."


def test_missing_endpoint_timeout_flushes_before_next_message():
    _, events = run_fixture("missing_endpoint_timeout")
    fs = finals(events)
    assert len(fs) == 1
    assert fs[0].text == "Sarah joins us."
    # After the timeout flush, the resumed interim starts a fresh assembly
    # and emits a Provisional using only the new segment.
    provs_after_final = [e for e in events if isinstance(e, Provisional)]
    assert any("how are" in p.text for p in provs_after_final)


# --- epoch / reconnect --------------------------------------------------------

def test_reconnect_drops_pre_reset_buffer_and_emits_new_epoch():
    _, events = run_fixture("reconnect_epoch_change")
    fs = finals(events)
    assert len(fs) == 1
    assert fs[0].audio_epoch == 2
    assert fs[0].text == "Daniel, welcome."


def test_reconnect_ignores_stale_epoch_message_after_reset():
    _, events = run_fixture("reconnect_epoch_change")
    fs = finals(events)
    # The stale epoch-1 message that arrived after reset must not appear in
    # the final utterance text.
    assert "after the break" not in fs[0].text.lower()


# --- dedupe / idempotence -----------------------------------------------------

def test_duplicate_final_not_double_counted():
    _, events = run_fixture("duplicate_final")
    (f,) = finals(events)
    assert f.text.count("Sarah joins us") == 1
    assert f.text == "Sarah joins us after the break."


def test_utterance_ids_are_unique_within_epoch():
    asm = Assembler(timeout_s=1.2, audio_epoch=1)
    events: list[Event] = []
    # First utterance
    events.extend(asm.feed({"audio_epoch": 1, "type": "Results", "is_final": True,
                            "speech_final": True, "start": 0.0, "duration": 0.5,
                            "channel": {"alternatives": [{"transcript": "hello."}]}}, 0.5))
    # Second utterance
    events.extend(asm.feed({"audio_epoch": 1, "type": "Results", "is_final": True,
                            "speech_final": True, "start": 0.6, "duration": 0.6,
                            "channel": {"alternatives": [{"transcript": "goodbye."}]}}, 1.2))
    fs = finals(events)
    assert len(fs) == 2
    assert fs[0].utterance_id != fs[1].utterance_id


def test_empty_or_whitespace_final_emits_nothing():
    asm = Assembler(timeout_s=1.2)
    events = asm.feed(
        {"audio_epoch": 1, "type": "Results", "is_final": True, "speech_final": True,
         "start": 0.0, "duration": 0.2,
         "channel": {"alternatives": [{"transcript": "   "}]}},
        now=0.2,
    )
    assert events == []


def test_reset_before_endpoint_discards_utterance():
    asm = Assembler(timeout_s=1.2, audio_epoch=1)
    events = asm.feed(
        {"audio_epoch": 1, "type": "Results", "is_final": True, "speech_final": False,
         "start": 0.0, "duration": 0.5,
         "channel": {"alternatives": [{"transcript": "please welcome"}]}},
        now=0.5,
    )
    assert not finals(events)  # no endpoint yet
    asm.reset(new_epoch=2)
    # Now send an endpoint under new epoch; the "please welcome" segment
    # must not appear in the flushed text.
    events2 = asm.feed(
        {"audio_epoch": 2, "type": "Results", "is_final": True, "speech_final": True,
         "start": 0.0, "duration": 0.3,
         "channel": {"alternatives": [{"transcript": "clean slate."}]}},
        now=1.0,
    )
    (f,) = finals(events2)
    assert f.text == "clean slate."
    assert "please" not in f.text.lower()
