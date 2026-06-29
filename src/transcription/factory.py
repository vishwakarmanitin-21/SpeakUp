"""Factory for transcription clients — returns cloud or local based on config."""
from __future__ import annotations

import logging

from src.config import Config

logger = logging.getLogger("speakup")


def get_transcription_client():
    """Return a transcription client based on the current config.

    Returns WhisperClient (cloud) or LocalWhisperClient (on-device).
    Reads config fresh on every call so settings changes take effect immediately.

    The local engine (faster-whisper) is not bundled in the packaged exe; if it's
    requested but unavailable, fall back to the cloud client so a stray setting
    can never dead-end a dictation.
    """
    config = Config()
    provider = config.transcription_provider

    if provider == "local":
        try:
            from src.transcription.local_whisper_client import LocalWhisperClient
            return LocalWhisperClient()
        except Exception as e:
            logger.warning(
                "Local transcription unavailable (%s); falling back to cloud.", e
            )

    from src.transcription.whisper_client import WhisperClient
    return WhisperClient()
