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


def is_model_unavailable(exc: Exception | str) -> bool:
    """True when OpenAI rejected the MODEL itself (retired or unknown id).

    A retired model can still appear in models.list() while every call to it
    404s (gpt-4.1-nano, 2026-10-24), so this error text is the only reliable
    signal that the configured model is dead.
    """
    text = str(exc).lower()
    return "model_not_found" in text or (
        "model" in text and ("has been deprecated" in text or "does not exist" in text)
    )


def friendly_api_error(exc: Exception, action: str) -> str:
    """A message that names the ACTUAL problem.

    "Check your API key and internet connection" is actively misleading when the
    key and network are fine and the account has simply run out of credit — it
    sends you off debugging the wrong thing.
    """
    text = str(exc).lower()
    if "not scoped to a workspace" in text:
        return (f"{action} failed: your Anthropic key isn't inside a workspace. "
                "Create the key inside a workspace at console.anthropic.com, or "
                "add the workspace ID in Settings.")
    if is_model_unavailable(text):
        return f"{action} failed: OpenAI has retired or does not offer this model."
    if any(k in text for k in ("insufficient_quota", "credit_balance_exhausted",
                               "no credits remaining", "exceeded your current quota")):
        # Plain ASCII: this text is also written to the console logger, which on
        # Windows uses a codepage that cannot encode arrows and would raise.
        return ("Your OpenAI account is out of credits. Add credits at "
                "platform.openai.com (Settings > Billing), then try again.")
    if "rate_limit" in text or "429" in text:
        return f"{action} was rate-limited by OpenAI. Wait a moment and try again."
    if any(k in text for k in ("invalid_api_key", "incorrect api key", "401")):
        return f"{action} failed: the OpenAI API key was rejected. Check it in Settings."
    if any(k in text for k in ("getaddrinfo", "connection", "timeout", "ssl")):
        return f"{action} failed: could not reach OpenAI. Check your internet connection."
    return f"{action} failed. Check your API key and internet connection."


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
