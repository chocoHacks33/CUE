"""scripts/latency_report.py aggregation over a synthetic decision log."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPTS = REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import latency_report  # noqa: E402


def test_aggregate_final_and_cue_hops_yield_percentiles():
    decisions = [
        {"at": 100.0, "decision_seq": 1,
         "latencies_ms": {"final_ms": 200, "cue_decide_ms": 800}},
        {"at": 101.0, "decision_seq": 2,
         "latencies_ms": {"final_ms": 300, "cue_decide_ms": 900}},
        {"at": 102.0, "decision_seq": 3,
         "latencies_ms": {"final_ms": 500, "cue_decide_ms": 1100}},
    ]
    summary = latency_report.aggregate(decisions, acks_by_seq=None)
    assert summary["final_ms"]["count"] == 3
    assert summary["final_ms"]["p50"] == 300
    assert summary["cue_decide_ms"]["p50"] == 900
    # No acks -> ack_ms bucket is empty; total_ms still populated per-decision.
    assert summary["ack_ms"]["count"] == 0
    assert summary["total_ms"]["count"] == 3


def test_ack_map_indexes_by_decision_seq():
    acks = [
        {"decision_seq": 1, "applied": True, "at_monotonic_s": 100.2},
        {"decisionSeq": 2, "applied": True, "atMs": 101_400},
    ]
    idx = latency_report._index_acks(acks)
    assert set(idx.keys()) == {1, 2}
    assert idx[1] == 100.2
    assert idx[2] == 101.4


def test_aggregate_computes_ack_hop_from_paired_logs():
    decisions = [
        {"at": 100.0, "decision_seq": 1,
         "latencies_ms": {"final_ms": 200, "cue_decide_ms": 800}},
        {"at": 101.0, "decision_seq": 2,
         "latencies_ms": {"final_ms": 300, "cue_decide_ms": 900}},
    ]
    acks_by_seq = {1: 100.2, 2: 101.4}  # 200ms, 400ms
    summary = latency_report.aggregate(decisions, acks_by_seq=acks_by_seq)
    assert summary["ack_ms"]["count"] == 2
    # p50 of [200, 400] is 300 (median of two = mean).
    assert summary["ack_ms"]["p50"] == 300


def test_read_jsonl_ignores_junk_lines(tmp_path):
    p = tmp_path / "d.jsonl"
    p.write_text(
        '{"decision_seq": 1, "latencies_ms": {"final_ms": 100}}\n'
        "\n"
        "not-json\n"
        '{"decision_seq": 2, "latencies_ms": {"final_ms": 200}}\n',
        encoding="utf-8",
    )
    out = latency_report._read_jsonl(p)
    assert [d["decision_seq"] for d in out] == [1, 2]


def test_percentiles_empty_bucket():
    assert latency_report._percentiles([]) == {
        "p50": None, "p95": None, "count": 0,
    }


def test_main_prints_summary(tmp_path, capsys):
    d = tmp_path / "d.jsonl"
    d.write_text(
        '{"at": 100.0, "decision_seq": 1, "latencies_ms": '
        '{"final_ms": 100, "cue_decide_ms": 500}}\n',
        encoding="utf-8",
    )
    rc = latency_report.main([str(d), "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["decisions"] == 1
    assert payload["hops"]["final_ms"]["p50"] == 100
