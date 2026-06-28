"""Tests for Pipeline cancel and state machine."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock, patch


def _make_pipeline():
    """Create a Pipeline with all external dependencies mocked."""
    with (
        patch("src.services.pipeline.AudioRecorder"),
        patch("src.services.pipeline.SilenceDetector"),
        patch("src.services.pipeline.RewriteEngine"),
        patch("src.services.pipeline.SessionMemory"),
        patch("src.services.pipeline.ContextBuilder"),
        patch("src.services.pipeline.OutputInserter"),
    ):
        from src.services.pipeline import Pipeline
        pipeline = Pipeline()
    return pipeline


def test_cancel_sets_cancelled_flag():
    """cancel() sets _cancelled to True and resets state to IDLE."""
    from src.services.pipeline import PipelineState

    pipeline = _make_pipeline()
    pipeline._recorder.is_recording = False
    pipeline.cancel()
    assert pipeline._cancelled is True
    assert pipeline.state == PipelineState.IDLE


def test_cancel_stops_active_recording():
    """cancel() calls recorder.stop() when recording is active."""
    pipeline = _make_pipeline()
    pipeline._recorder.is_recording = True
    pipeline.cancel()
    pipeline._recorder.stop.assert_called_once()


def test_start_recording_resets_cancelled_flag():
    """start_recording() clears _cancelled before starting."""
    pipeline = _make_pipeline()
    pipeline._cancelled = True
    pipeline.start_recording()
    assert pipeline._cancelled is False


@pytest.mark.asyncio
async def test_process_happy_path():
    """process() calls transcribe, rewrite, and returns results."""
    from src.rewrite.modes import RewriteMode
    from src.services.pipeline import PipelineState

    pipeline = _make_pipeline()
    pipeline._recorder.get_wav_bytes.return_value = b"fake_wav"
    pipeline._rewriter.rewrite = AsyncMock(return_value="Hello World.")
    pipeline._context_builder.build.return_value = None

    mock_client = MagicMock()
    mock_client.transcribe = AsyncMock(return_value="hello world")

    # Use clipboard output so the non-streaming rewrite() path runs (streaming is
    # the default for auto-paste and would instead use rewrite_stream()).
    with patch("src.services.pipeline.get_transcription_client", return_value=mock_client):
        raw, rewritten = await pipeline.process(
            RewriteMode.CLEAN_GRAMMAR, output_mode="clipboard"
        )

    assert raw == "hello world"
    assert rewritten == "Hello World."
    assert pipeline.state == PipelineState.DONE
