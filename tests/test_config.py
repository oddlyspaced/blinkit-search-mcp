from pathlib import Path

import pytest

from blinkit_mcp.config import Location, config_path, load_location, save_location


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    path = tmp_path / "sub" / "config.json"
    monkeypatch.setenv("BLINKIT_MCP_CONFIG", str(path))
    return path


def test_env_var_overrides_path(cfg):
    assert config_path() == cfg


def test_default_path(monkeypatch):
    monkeypatch.delenv("BLINKIT_MCP_CONFIG", raising=False)
    assert config_path() == Path.home() / ".config" / "blinkit-mcp" / "config.json"


def test_load_when_missing_returns_none(cfg):
    assert load_location() is None


def test_save_then_load_round_trip(cfg):
    loc = Location("Koramangala, Bengaluru", 12.9352, 77.6245, "43483")
    save_location(loc)
    assert cfg.exists()
    assert load_location() == loc


@pytest.mark.parametrize("content", ["", "{not json", "[]", '{"lat": "x"}'])
def test_empty_or_corrupt_file_returns_none(cfg, content):
    cfg.parent.mkdir(parents=True)
    cfg.write_text(content)
    assert load_location() is None
