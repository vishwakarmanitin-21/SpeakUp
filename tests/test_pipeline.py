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
    # Never the user's real settings: with live transcription on, a test that
    # calls start_recording() would open the real microphone and Deepgram.
    pipeline._config = MagicMock(transcription_realtime=False, auto_stop_on_silence=False)
    return pipeline


def test_cancel_cancels_in_flight_runs():
    """cancel() marks every pending run cancelled and resets state to IDLE."""
    from src.services.pipeline import PipelineState

    pipeline = _make_pipeline()
    pipeline._recorder.is_recording = False
    pipeline.stop_recording()
    gen = pipeline._pending_take.cancel_gen
    pipeline.cancel()
    assert pipeline._is_cancelled(gen)
    assert pipeline.state == PipelineState.IDLE


def test_cancel_stops_active_recording():
    """cancel() calls recorder.stop() when recording is active."""
    pipeline = _make_pipeline()
    pipeline._recorder.is_recording = True
    pipeline.cancel()
    pipeline._recorder.stop.assert_called_once()


def test_new_recording_after_cancel_is_not_cancelled():
    pipeline = _make_pipeline()
    pipeline.cancel()
    pipeline.start_recording()
    pipeline.stop_recording()
    assert not pipeline._is_cancelled(pipeline._pending_take.cancel_gen)


def test_discarding_a_short_tap_does_not_cancel_the_previous_dictation():
    pipeline = _make_pipeline()
    pipeline.stop_recording()
    gen = pipeline._pending_take.cancel_gen
    pipeline.start_recording()
    pipeline.discard_recording()
    assert not pipeline._is_cancelled(gen)


# --- Overlapping dictations (2026-10-24: the second one lost its audio) -------

def _live_session(text):
    s = MagicMock()
    s.stop_and_transcribe = AsyncMock(return_value=text)
    s.live_failed = False
    return s


@pytest.mark.asyncio
async def test_finishing_dictation_does_not_steal_the_next_ones_live_session():
    from src.rewrite.modes import RewriteMode

    pipeline = _make_pipeline()
    pipeline._context_builder.build.return_value = None
    pipeline._rewriter.rewrite = AsyncMock(side_effect=lambda raw, *a, **k: raw.upper())
    first, second = _live_session("first"), _live_session("second")

    pipeline._realtime, pipeline._use_realtime = first, True
    pipeline.stop_recording()          # release #1
    first.close.assert_called_once()   # mic stopped at release, not later
    pipeline._realtime, pipeline._use_realtime = second, True  # press #2

    with patch("src.services.pipeline.Config", return_value=_fake_config(stream=False)):
        raw, _ = await pipeline.process(RewriteMode.CLEAN_GRAMMAR, output_mode="clipboard")

    assert raw == "first"
    assert pipeline._realtime is second and pipeline._use_realtime  # untouched
    second.stop_and_transcribe.assert_not_called()


@pytest.mark.asyncio
async def test_overlapping_dictations_paste_one_after_the_other():
    """Two runs in flight never interleave their streamed pastes."""
    import asyncio
    from src.rewrite.modes import RewriteMode

    pipeline = _make_pipeline()
    pipeline._context_builder.build.return_value = None
    events: list[str] = []
    pipeline._inserter.begin_stream.side_effect = lambda: events.append("begin")
    pipeline._inserter.end_stream.side_effect = lambda: events.append("end")

    async def slow_stream(raw, *a, **k):
        for word in (raw, " done"):
            await asyncio.sleep(0.01)
            yield word
    pipeline._rewriter.rewrite_stream = slow_stream

    takes = []
    for text in ("one", "two"):
        pipeline._realtime, pipeline._use_realtime = _live_session(text), True
        pipeline.stop_recording()
        takes.append(pipeline._pending_take)
        pipeline._pending_take = None

    async def run(take):
        pipeline._pending_take = take
        return await pipeline.process(RewriteMode.CLEAN_GRAMMAR)

    with patch("src.services.pipeline.Config", return_value=_fake_config()):
        results = await asyncio.gather(run(takes[0]), run(takes[1]))

    assert sorted(r[0] for r in results) == ["one", "two"]
    assert events == ["begin", "end", "begin", "end"]


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
    cfg.backup_model = ""
    cfg.anthropic_api_key = ""
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


@pytest.mark.asyncio
async def test_silent_recording_pastes_nothing():
    """An empty transcript must never reach the clean-up model or the cursor."""
    pipeline = _make_pipeline()
    pipeline._rewriter.rewrite_stream = MagicMock()
    pipeline._realtime, pipeline._use_realtime = _live_session(" . "), True
    pipeline.stop_recording()
    raw, rewritten = await _process(pipeline, _fake_config())

    assert rewritten == ""
    pipeline._rewriter.rewrite_stream.assert_not_called()
    pipeline._inserter.begin_stream.assert_not_called()


# --- Backup clean-up model -----------------------------------------------------

def _stream_by_model(fail_models):
    """rewrite_stream fake: fails for models in fail_models (None = primary)."""
    from src.services.error_handler import RewriteError
    calls = []

    async def _gen(raw, *_a, model=None, **_kw):
        calls.append(model)
        if model in fail_models:
            raise RewriteError(f"GPT rewrite failed: {_RETIRED}", "Rewrite failed.")
        yield f"[{model}] {raw}"
    return _gen, calls


@pytest.mark.asyncio
async def test_backup_model_cleans_up_when_primary_fails():
    pipeline = _make_pipeline()
    notices: list[str] = []
    pipeline.set_notice_callback(notices.append)
    gen, calls = _stream_by_model({None})
    pipeline._rewriter.rewrite_stream = gen
    cfg = _fake_config(model="gpt-4.1-nano", default="gpt-6-luna")
    cfg.backup_model = "claude-haiku-5-5"
    cfg.anthropic_api_key = "sk-test"
    raw, rewritten = await _process(pipeline, cfg)

    assert calls == [None, "claude-haiku-5-5"]
    assert rewritten == "[claude-haiku-5-5] hello world"
    pipeline._inserter.feed_stream.assert_called_once_with(rewritten)
    # The retired primary is still replaced, and the notice says who cleaned up.
    cfg.save_user_overrides.assert_called_once_with({"gpt_model": "gpt-6-luna"})
    assert any("backup" in n for n in notices)


@pytest.mark.asyncio
async def test_backup_without_its_key_is_skipped():
    pipeline = _make_pipeline()
    gen, calls = _stream_by_model({None})
    pipeline._rewriter.rewrite_stream = gen
    cfg = _fake_config()
    cfg.backup_model = "claude-haiku-5-5"   # but no ANTHROPIC_API_KEY
    raw, rewritten = await _process(pipeline, cfg)

    assert calls == [None]
    assert rewritten == "hello world"


@pytest.mark.asyncio
async def test_both_models_failing_still_pastes_the_transcript():
    pipeline = _make_pipeline()
    gen, calls = _stream_by_model({None, "claude-haiku-5-5"})
    pipeline._rewriter.rewrite_stream = gen
    cfg = _fake_config()
    cfg.backup_model, cfg.anthropic_api_key = "claude-haiku-5-5", "sk-test"
    raw, rewritten = await _process(pipeline, cfg)

    assert calls == [None, "claude-haiku-5-5"]
    assert rewritten == "hello world"
