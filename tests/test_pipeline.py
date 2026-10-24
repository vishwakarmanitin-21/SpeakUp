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


# --- Clean-up failure must not lose the dictation ---------------------------

_RETIRED = (
    "Error code: 404 - {'error': {'message': 'The model `gpt-4.1-nano` has been "
    "deprecated, learn more here: https://platform.openai.com/docs/deprecations', "
    "'type': 'invalid_request_error', 'param': None, 'code': 'model_not_found'}}"
)


def _fake_config(model="gpt-4.1-nano", default="gpt-4o-mini", stream=True):
    cfg = MagicMock()
    cfg.gpt_model = model
    cfg.default.side_effect = lambda key, fallback=None: default
    cfg.stream_output = stream
    cfg.output_mode = "auto_paste"
    cfg.log_transcripts = False
    cfg.track_usage = False
    cfg.transcription_provider = "cloud"
    return cfg


def _stream_then_fail(*deltas):
    from src.services.error_handler import RewriteError

    async def _gen(*_a, **_kw):
        for d in deltas:
            yield d
        raise RewriteError(f"GPT rewrite failed: {_RETIRED}", "Rewrite failed.")
    return _gen


async def _process(pipeline, cfg, output_mode=None):
    from src.rewrite.modes import RewriteMode

    pipeline._recorder.get_wav_bytes.return_value = b"fake_wav"
    pipeline._context_builder.build.return_value = None
    client = MagicMock()
    client.transcribe = AsyncMock(return_value="hello world")
    with (
        patch("src.services.pipeline.Config", return_value=cfg),
        patch("src.services.pipeline.get_transcription_client", return_value=client),
    ):
        return await pipeline.process(RewriteMode.CLEAN_GRAMMAR, output_mode=output_mode)


@pytest.mark.asyncio
async def test_stream_failure_types_the_transcript_instead():
    """A clean-up that fails before any text is typed pastes the raw words."""
    from src.services.pipeline import PipelineState

    pipeline = _make_pipeline()
    pipeline._rewriter.rewrite_stream = _stream_then_fail()
    raw, rewritten = await _process(pipeline, _fake_config())

    assert (raw, rewritten) == ("hello world", "hello world")
    pipeline._inserter.feed_stream.assert_called_once_with("hello world")
    pipeline._inserter.end_stream.assert_called_once()
    assert pipeline.state == PipelineState.DONE


@pytest.mark.asyncio
async def test_stream_failure_midway_keeps_partial_without_duplicating():
    pipeline = _make_pipeline()
    pipeline._rewriter.rewrite_stream = _stream_then_fail("Hello ")
    raw, rewritten = await _process(pipeline, _fake_config())

    assert rewritten == "Hello "
    pipeline._inserter.feed_stream.assert_called_once_with("Hello ")


@pytest.mark.asyncio
async def test_non_stream_failure_delivers_the_transcript():
    from src.services.error_handler import RewriteError

    pipeline = _make_pipeline()
    pipeline._rewriter.rewrite = AsyncMock(side_effect=RewriteError(_RETIRED, "x"))
    raw, rewritten = await _process(pipeline, _fake_config(), output_mode="clipboard")

    assert rewritten == "hello world"
    pipeline._inserter.deliver.assert_called_once_with("hello world", "clipboard")


@pytest.mark.asyncio
async def test_retired_model_switches_to_the_default():
    pipeline = _make_pipeline()
    notices: list[str] = []
    pipeline.set_notice_callback(notices.append)
    pipeline._rewriter.rewrite_stream = _stream_then_fail()
    cfg = _fake_config(model="gpt-4.1-nano", default="gpt-4o-mini")
    await _process(pipeline, cfg)

    cfg.save_user_overrides.assert_called_once_with({"gpt_model": "gpt-4o-mini"})
    assert any("gpt-4.1-nano" in n and "gpt-4o-mini" in n for n in notices)


@pytest.mark.asyncio
async def test_retired_default_model_does_not_loop():
    pipeline = _make_pipeline()
    pipeline._rewriter.rewrite_stream = _stream_then_fail()
    cfg = _fake_config(model="gpt-4o-mini", default="gpt-4o-mini")
    raw, rewritten = await _process(pipeline, cfg)

    cfg.save_user_overrides.assert_not_called()
    assert rewritten == "hello world"
