"""Tests for cue_api.config.demo_profile."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cue_api.config.demo_profile import (
    DemoProfile,
    as_public_dict,
    load_demo_profile,
)


@pytest.fixture
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in (
        "CUE_PROFILE", "CUE_MODEL", "DEEPGRAM_MODEL", "CUE_MODE_DEFAULT",
        "DEEPGRAM_ENDPOINTING_MS", "DEEPGRAM_UTTERANCE_END_MS",
        "DEEPGRAM_KEYTERMS", "CUE_LIFETIME_S", "MIN_SHOT_S", "CUE_ROLE_BASED",
    ):
        monkeypatch.delenv(k, raising=False)


def _fixture_env(tmp_path: Path) -> Path:
    p = tmp_path / "demo.example.env"
    p.write_text(
        "# demo env\n"
        "OPENAI_API_KEY=\n"
        "DEEPGRAM_API_KEY=\n"
        "CUE_MODEL=gpt-5-mini-2025-08-07\n"
        "DEEPGRAM_MODEL=nova-3\n"
        "DEEPGRAM_ENDPOINTING_MS=300\n"
        "DEEPGRAM_UTTERANCE_END_MS=1000\n"
        "DEEPGRAM_KEYTERMS=Sarah,Daniel,Priya Shah\n"
        "CUE_LIFETIME_S=3.0\n"
        "MIN_SHOT_S=2.5\n"
        "CUE_MODE_DEFAULT=ASSIST\n"
        "CUE_ROLE_BASED=1\n",
        encoding="utf-8",
    )
    return p


def _fixture_roster(tmp_path: Path, guests: list[dict]) -> Path:
    p = tmp_path / "demo_roster.json"
    p.write_text(json.dumps({
        "guests": guests,
        "role_map": {g["id"]: g["camera_hint"] for g in guests},
    }), encoding="utf-8")
    return p


def test_profile_unset_returns_none(_clean_env, tmp_path):
    env_p = _fixture_env(tmp_path)
    ros_p = _fixture_roster(tmp_path, [
        {"id": "sarah", "name": "Sarah Tan", "camera_hint": "CAM-GUEST"},
    ])
    assert load_demo_profile(env_path=env_p, roster_path=ros_p) is None


def test_profile_demo_loads_defaults(_clean_env, tmp_path, monkeypatch):
    monkeypatch.setenv("CUE_PROFILE", "demo")
    env_p = _fixture_env(tmp_path)
    ros_p = _fixture_roster(tmp_path, [
        {"id": "sarah", "name": "Sarah Tan", "camera_hint": "CAM-GUEST"},
        {"id": "daniel", "name": "Daniel Reyes", "camera_hint": "CAM-GUEST"},
    ])
    p = load_demo_profile(env_path=env_p, roster_path=ros_p)
    assert isinstance(p, DemoProfile)
    assert p.cue_model == "gpt-5-mini-2025-08-07"
    assert p.deepgram_model == "nova-3"
    assert p.endpointing_ms == 300
    assert p.utterance_end_ms == 1000
    assert p.keyterms == ("Sarah", "Daniel", "Priya Shah")
    assert p.cue_lifetime_s == 3.0
    assert p.min_shot_s == 2.5
    assert p.mode_default == "ASSIST"
    assert p.role_based is True
    assert len(p.guests) == 2
    assert p.role_map == {"sarah": "CAM-GUEST", "daniel": "CAM-GUEST"}


def test_profile_live_env_overrides_example(_clean_env, tmp_path, monkeypatch):
    monkeypatch.setenv("CUE_PROFILE", "demo")
    monkeypatch.setenv("CUE_MODEL", "override-model-id")
    monkeypatch.setenv("MIN_SHOT_S", "3.5")
    env_p = _fixture_env(tmp_path)
    ros_p = _fixture_roster(tmp_path, [
        {"id": "sarah", "name": "Sarah Tan", "camera_hint": "CAM-GUEST"},
    ])
    p = load_demo_profile(env_path=env_p, roster_path=ros_p)
    assert p is not None
    assert p.cue_model == "override-model-id"
    assert p.min_shot_s == 3.5


def test_profile_rejects_more_than_four_guests(_clean_env, tmp_path,
                                                monkeypatch):
    monkeypatch.setenv("CUE_PROFILE", "demo")
    env_p = _fixture_env(tmp_path)
    ros_p = _fixture_roster(tmp_path, [
        {"id": f"g{i}", "name": f"G {i}", "camera_hint": "CAM-GUEST"}
        for i in range(5)
    ])
    with pytest.raises(ValueError, match="four"):
        load_demo_profile(env_path=env_p, roster_path=ros_p)


def test_profile_public_dict_carries_no_secret_keys(_clean_env, tmp_path,
                                                     monkeypatch):
    monkeypatch.setenv("CUE_PROFILE", "demo")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("DEEPGRAM_API_KEY", "dg-should-not-leak")
    env_p = _fixture_env(tmp_path)
    ros_p = _fixture_roster(tmp_path, [
        {"id": "sarah", "name": "Sarah Tan", "camera_hint": "CAM-GUEST"},
    ])
    p = load_demo_profile(env_path=env_p, roster_path=ros_p)
    assert p is not None
    pub = as_public_dict(p)
    flat = json.dumps(pub)
    assert "OPENAI_API_KEY" not in flat
    assert "DEEPGRAM_API_KEY" not in flat
    assert "sk-should-not-leak" not in flat
    assert "dg-should-not-leak" not in flat
    assert "openai_api_key" not in flat.lower()
    assert "deepgram_api_key" not in flat.lower()


def test_repo_shipped_files_load_when_profile_set(_clean_env, monkeypatch):
    """The default files at repo config/ must load without error."""
    monkeypatch.setenv("CUE_PROFILE", "demo")
    p = load_demo_profile()
    assert p is not None
    # These are the values shipped in the repo. Guard against silent drift.
    assert p.deepgram_model == "nova-3"
    assert p.endpointing_ms == 300
    assert p.utterance_end_ms == 1000
    assert 1 <= len(p.guests) <= 4
