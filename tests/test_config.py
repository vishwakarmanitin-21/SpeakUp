"""Tests for Config singleton."""
from __future__ import annotations

import os
import json
import pytest
from pathlib import Path
from unittest.mock import patch


def _reset_config():
    from src.config import Config
    Config.reset()


def test_config_loads_defaults():
    """Config reads values from config_defaults.json."""
    _reset_config()
    from src.config import Config

    config = Config()
    assert config.whisper_model == "gpt-4o-transcribe"  # modernised default
    assert config.gpt_model == "gpt-4o-mini"
    assert config.sample_rate == 16000
    assert config.hotkey == "ctrl+cmd"


def test_config_singleton():
    """Two Config() calls return the same instance."""
    _reset_config()
    from src.config import Config

    a = Config()
    b = Config()
    assert a is b


def test_config_reload(tmp_path, monkeypatch):
    """Config.reload() re-reads config.json overrides from disk."""
    _reset_config()
    from src.config import Config

    # Point config at a temp directory with our own defaults
    defaults = {
        "whisper_model": "whisper-1",
        "gpt_model": "gpt-4o",
        "temperature": 0.3,
        "hotkey": "ctrl+shift+space",
        "sample_rate": 16000,
        "silence_timeout_ms": 2000,
        "auto_stop_on_silence": False,
        "default_rewrite_mode": "clean_grammar",
        "output_mode": "clipboard",
        "include_clipboard": True,
        "include_selection": True,
        "include_session_memory": True,
    }
    (tmp_path / "config_defaults.json").write_text(json.dumps(defaults))

    import src.config as cfg_module
    monkeypatch.setattr(cfg_module, "_BUNDLE_ROOT", tmp_path)
    monkeypatch.setattr(cfg_module, "_PROJECT_ROOT", tmp_path)
    _reset_config()

    config = Config()
    assert config.gpt_model == "gpt-4o"

    # Write an override and reload
    (tmp_path / "config.json").write_text(json.dumps({"gpt_model": "gpt-4o-mini"}))
    config.reload()
    assert config.gpt_model == "gpt-4o-mini"


def test_openai_api_key_raises_when_missing():
    """openai_api_key raises APIKeyError when env var is not set."""
    _reset_config()
    from src.config import Config
    from src.services.error_handler import APIKeyError

    # Patch os.getenv at the config module level so the .env file is ignored
    with patch("src.config.os.getenv", return_value=""):
        config = Config()
        with pytest.raises(APIKeyError):
            _ = config.openai_api_key


def test_openai_api_key_returns_value():
    """openai_api_key returns the env var value when set."""
    _reset_config()
    from src.config import Config

    with patch("src.config.os.getenv", return_value="sk-test-abc"):
        config = Config()
        assert config.openai_api_key == "sk-test-abc"
