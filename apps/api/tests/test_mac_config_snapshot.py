"""scripts/mac_config_snapshot.py: names, never values; renders on any machine."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPTS = REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import mac_config_snapshot as snap  # noqa: E402


def test_env_names_keeps_names_and_drops_values_comments_and_exports():
    text = """
# comment
OPENAI_API_KEY=sk-live-secret-value
export DEEPGRAM_API_KEY="dg-secret"
CUE_BOOTSTRAP_SECRET = spaced-value
not a variable
=novalue
LIVEKIT_URL=wss://x.livekit.cloud
"""
    names = snap.env_names(text)
    assert names == ["CUE_BOOTSTRAP_SECRET", "DEEPGRAM_API_KEY", "LIVEKIT_URL", "OPENAI_API_KEY"]
    assert not any("secret" in name.lower() and "value" in name.lower() for name in names)


def test_env_summary_reports_missing_names_without_reading_values(tmp_path: Path):
    (tmp_path / ".env.example").write_text(
        "OPENAI_API_KEY=\nDEEPGRAM_API_KEY=\nCUE_PRODUCER_SECRET=\n"
    )
    (tmp_path / ".env").write_text(
        "OPENAI_API_KEY=sk-live-hunter2\nCUE_PRODUCER_SECRET=topsecret\n"
    )
    summary = snap.env_summary(tmp_path)
    assert summary["files"][".env"]["names"] == ["CUE_PRODUCER_SECRET", "OPENAI_API_KEY"]
    assert summary["files"]["apps/api/.env"]["present"] is False
    assert summary["missingFromExample"] == ["DEEPGRAM_API_KEY"]
    assert "hunter2" not in repr(summary) and "topsecret" not in repr(summary)


def test_render_never_leaks_a_value(tmp_path: Path):
    (tmp_path / ".env").write_text("CUE_PRODUCER_SECRET=hunter2\n")
    snapshot = {
        "capturedAt": "2026-09-20T03:00:00+00:00",
        "hostname": "d-mac",
        "macos": {
            "productVersion": "26.3",
            "build": "25D125",
            "arch": "arm64",
            "chip": "Apple M2 Pro",
            "memoryGb": 16.0,
        },
        "disk": {"path": str(tmp_path), "freeGb": 200.0},
        "git": {
            "branch": "main",
            "commit": "abc123",
            "dirty": False,
            "tagsAtHead": [],
            "remote": "git@x",
        },
        "python": {
            "version": "3.14.5",
            "executable": "/venv/bin/python",
            "packages": {"fastapi": "0.141.1", "numpy": None},
        },
        "node": {"node": "v25.9.0", "npm": "11.0.0"},
        "chrome": "153.0.8010.53",
        "ffmpeg": "ffmpeg version 7.1",
        "env": snap.env_summary(tmp_path),
        "processes": ["uvicorn"],
    }
    text = snap.render(snapshot)
    assert "CUE_PRODUCER_SECRET" in text
    assert "hunter2" not in text
    assert "untagged" in text and "clean" in text
    assert "numpy absent" in text


def test_gather_runs_on_this_machine_without_raising():
    snapshot = snap.gather(REPO_ROOT)
    assert snapshot["python"]["version"]
    assert "packages" in snapshot["python"]
    assert isinstance(snapshot["processes"], list)
    # Whatever this machine has, the render must not choke on None fields.
    assert "| Python |" in snap.render(snapshot)


def test_processes_from_listing_matches_names_with_spaces_and_drops_arguments():
    listing = (
        "123 /Applications/Google Chrome.app/Contents/MacOS/Google Chrome --flag\n"
        "456 /Users/d/.venv/bin/python -m uvicorn cue_api.main:app --port 8000\n"
        "789 ngrok http 8000 --authtoken=SHOULD-NOT-APPEAR\n"
        "321 /Applications/Visual Studio Code.app/Contents/MacOS/Electron\n"
    )
    found = snap.processes_from_listing(listing)
    assert found == ["Google Chrome", "ngrok", "uvicorn"]
    assert "SHOULD-NOT-APPEAR" not in " ".join(found)
