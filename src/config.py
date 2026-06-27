from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


def _find_project_root() -> Path:
    """Determine project root for user-writable files (config.json, .env)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _find_bundle_root() -> Path:
    """Determine root for bundled read-only files (config_defaults.json).

    In PyInstaller onefile mode, bundled data files are extracted to a
    temporary directory (sys._MEIPASS), not next to the exe.
    """
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent.parent


_PROJECT_ROOT = _find_project_root()
_BUNDLE_ROOT = _find_bundle_root()


class Config:
    """Singleton configuration manager.

    Loads settings from three layers (lowest to highest priority):
    1. config_defaults.json (committed defaults)
    2. config.json (user overrides, git-ignored)
    3. .env file (API keys only)
    """

    _instance: Config | None = None

    def __new__(cls) -> Config:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._loaded = False
        return cls._instance

    def __init__(self) -> None:
        if not self._loaded:
            self._load()
            self._loaded = True

    def _load(self) -> None:
        # Load .env for API keys
        env_path = _PROJECT_ROOT / ".env"
        load_dotenv(env_path, override=True)

        # Load defaults (bundled read-only file)
        defaults_path = _BUNDLE_ROOT / "config_defaults.json"
        with open(defaults_path, encoding="utf-8") as f:
            self._defaults: dict = json.load(f)

        # Load user overrides (if they exist)
        self._overrides: dict = {}
        overrides_path = _PROJECT_ROOT / "config.json"
        if overrides_path.exists():
            with open(overrides_path, encoding="utf-8") as f:
                self._overrides = json.load(f)

    def _get(self, key: str, fallback=None):
        """Get a config value: overrides > defaults > fallback."""
        if key in self._overrides:
            return self._overrides[key]
        if key in self._defaults:
            return self._defaults[key]
        return fallback

    def reload(self) -> None:
        """Reload config from disk (call after settings change to hot-reload)."""
        self._load()

    # --- Paths ---

    @property
    def env_path(self) -> Path:
        """Location of the .env file (next to the exe when frozen, else project root)."""
        return _PROJECT_ROOT / ".env"

    # --- API Keys (from environment) ---

    @property
    def openai_api_key(self) -> str:
        from src.services.error_handler import APIKeyError

        key = os.getenv("OPENAI_API_KEY", "")
        if not key:
            raise APIKeyError(
                "OPENAI_API_KEY not set. Copy .env.example to .env and add your key.",
                "OpenAI API key is not configured. Add it in Settings or your .env file.",
            )
        return key

    # --- Model Settings ---

    @property
    def whisper_model(self) -> str:
        return self._get("whisper_model", "gpt-4o-transcribe")

    @property
    def gpt_model(self) -> str:
        return self._get("gpt_model", "gpt-4o-mini")

    @property
    def temperature(self) -> float:
        return float(self._get("temperature", 0.2))

    @property
    def custom_vocabulary(self) -> list[str]:
        """User's personal dictionary (names, jargon, acronyms).

        Used to bias transcription and to correct phonetic near-misses during
        the rewrite so proper nouns keep their exact spelling.
        """
        value = self._get("custom_vocabulary", [])
        if isinstance(value, str):
            value = [v.strip() for v in value.replace("\n", ",").split(",")]
        return [v for v in value if v]

    # --- Audio Settings ---

    @property
    def sample_rate(self) -> int:
        return int(self._get("sample_rate", 16000))

    @property
    def silence_timeout_ms(self) -> int:
        return int(self._get("silence_timeout_ms", 2000))

    @property
    def auto_stop_on_silence(self) -> bool:
        return bool(self._get("auto_stop_on_silence", False))

    # --- Hotkey ---

    @property
    def hotkey(self) -> str:
        return self._get("hotkey", "ctrl+cmd")

    # --- Behavior ---

    @property
    def default_rewrite_mode(self) -> str:
        return self._get("default_rewrite_mode", "smart")

    @property
    def output_mode(self) -> str:
        return self._get("output_mode", "auto_paste")

    @property
    def stream_output(self) -> bool:
        """Stream the rewrite and type it word-by-word at the cursor.

        Only applies to auto-paste output; clipboard/preview need the full text.
        Greatly reduces perceived latency (text appears as it's written).
        """
        return bool(self._get("stream_output", True))

    @property
    def keep_on_clipboard(self) -> bool:
        """Whether to leave the dictated text on the clipboard after auto-paste.

        Default False — the previous clipboard contents are restored after
        pasting so dictation does not silently overwrite what the user had copied.
        """
        return bool(self._get("keep_on_clipboard", False))

    # --- Context Toggles ---

    @property
    def include_clipboard(self) -> bool:
        return bool(self._get("include_clipboard", True))

    @property
    def include_selection(self) -> bool:
        return bool(self._get("include_selection", True))

    @property
    def include_session_memory(self) -> bool:
        return bool(self._get("include_session_memory", True))

    @property
    def include_vscode_file(self) -> bool:
        return bool(self._get("include_vscode_file", False))

    # --- Transcription Provider ---

    @property
    def transcription_provider(self) -> str:
        """'cloud' (OpenAI Whisper API) or 'local' (faster-whisper)."""
        return self._get("transcription_provider", "cloud")

    @property
    def transcription_realtime(self) -> bool:
        """Experimental: stream audio over the OpenAI Realtime API while speaking.

        Opt-in. Requires the 'realtime' extra (websockets). When the realtime
        path fails, the pipeline falls back to the standard cloud transcription.
        """
        return bool(self._get("transcription_realtime", False))

    @property
    def whisper_local_model_size(self) -> str:
        """faster-whisper model size: tiny, base, small, medium, large."""
        return self._get("whisper_local_model_size", "base")

    # --- Widget Appearance ---

    @property
    def widget_position(self) -> str:
        """'bottom_right', 'bottom_left', or 'bottom_center'."""
        return self._get("widget_position", "bottom_right")

    @property
    def widget_scale(self) -> str:
        """'compact' (0.5x), 'normal' (1x), or 'large' (2x)."""
        return self._get("widget_scale", "normal")

    # --- Startup ---

    @property
    def auto_start(self) -> bool:
        """Whether FlowAI should start automatically with Windows."""
        return bool(self._get("auto_start", False))

    # --- Usage Analytics ---

    @property
    def track_usage(self) -> bool:
        return bool(self._get("track_usage", True))

    # --- Mutation ---

    def save_user_overrides(self, overrides: dict) -> None:
        """Write user overrides to config.json."""
        self._overrides.update(overrides)
        overrides_path = _PROJECT_ROOT / "config.json"
        with open(overrides_path, "w", encoding="utf-8") as f:
            json.dump(self._overrides, f, indent=4)

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton (useful for testing)."""
        cls._instance = None
