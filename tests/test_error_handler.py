"""Tests for custom exception hierarchy."""
from __future__ import annotations

from src.services.error_handler import (
    SpeakUpError,
    APIKeyError,
    RecordingError,
    TranscriptionError,
    RewriteError,
)


def test_speakup_error_is_exception():
    err = SpeakUpError("base error")
    assert isinstance(err, Exception)
    assert str(err) == "base error"
    assert err.user_message == "base error"


def test_user_message_override():
    err = SpeakUpError("internal msg", "User-friendly message")
    assert err.user_message == "User-friendly message"
    assert str(err) == "internal msg"


def test_subclasses_are_speakup_errors():
    for cls in (APIKeyError, RecordingError, TranscriptionError, RewriteError):
        err = cls("test")
        assert isinstance(err, SpeakUpError)
        assert isinstance(err, Exception)


def test_api_key_error_user_message():
    err = APIKeyError("OPENAI_API_KEY not set", "Please add your key in Settings.")
    assert err.user_message == "Please add your key in Settings."


def test_recording_error_user_message():
    err = RecordingError("PortAudioError", "Microphone not found.")
    assert err.user_message == "Microphone not found."


def test_retired_model_is_recognised():
    from src.services.error_handler import friendly_api_error, is_model_unavailable

    # Exact text OpenAI returned for gpt-4.1-nano on 2026-10-24.
    retired = (
        "Error code: 404 - {'error': {'message': 'The model `gpt-4.1-nano` has been "
        "deprecated, learn more here: https://platform.openai.com/docs/deprecations', "
        "'type': 'invalid_request_error', 'param': None, 'code': 'model_not_found'}}"
    )
    assert is_model_unavailable(retired)
    assert "retired" in friendly_api_error(Exception(retired), "Rewrite")
    # "404" alone must not be mistaken for an unrelated failure category.
    assert "API key" not in friendly_api_error(Exception(retired), "Rewrite")


def test_ordinary_errors_are_not_model_errors():
    from src.services.error_handler import is_model_unavailable

    assert not is_model_unavailable("Connection error.")
    assert not is_model_unavailable("Error code: 429 - rate_limit_exceeded")
