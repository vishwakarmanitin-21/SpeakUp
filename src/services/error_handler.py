from __future__ import annotations

import logging
from pathlib import Path


logger = logging.getLogger("speakup")


class SpeakUpError(Exception):
    """Base exception for SpeakUp."""

    def __init__(self, message: str, user_message: str | None = None) -> None:
        super().__init__(message)
        self.user_message = user_message or message


class APIKeyError(SpeakUpError):
    """Raised when API key is missing or invalid."""
    pass


class RecordingError(SpeakUpError):
    """Raised when audio recording fails."""
    pass


class TranscriptionError(SpeakUpError):
    """Raised when Whisper API fails."""
    pass


class RewriteError(SpeakUpError):
    """Raised when GPT API fails."""
    pass


def setup_logging() -> None:
    """Configure application logging."""
    # Use the per-user data dir so the log PERSISTS for the packaged exe — a
    # __file__-relative path lands in the PyInstaller temp dir, which is wiped.
    try:
        from src.config import Config
        log_dir = Config().data_dir
    except Exception:
        log_dir = Path(__file__).resolve().parent.parent.parent
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(
                log_dir / "speakup.log", encoding="utf-8"
            ),
        ],
    )
