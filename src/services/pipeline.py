from __future__ import annotations

import logging
import time
from typing import Callable

logger = logging.getLogger("speakup")

from src.audio.recorder import AudioRecorder
from src.audio.silence_detector import SilenceDetector
from src.config import Config
from src.context.context_builder import ContextBuilder
from src.context.session_memory import SessionMemory
from src.output.inserter import OutputInserter, OutputMode
from src.rewrite.engine import RewriteEngine
from src.rewrite.modes import RewriteMode
from src.transcription.factory import get_transcription_client


class PipelineState:
    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    REWRITING = "rewriting"
    DONE = "done"
    ERROR = "error"


class Pipeline:
    """Orchestrates the voice -> text -> rewrite -> output pipeline."""

    def __init__(self) -> None:
        config = Config()
        self._recorder = AudioRecorder(sample_rate=config.sample_rate)
        self._silence_detector = SilenceDetector(
            silence_duration_ms=config.silence_timeout_ms,
        )
        self._rewriter = RewriteEngine()
        self._session_memory = SessionMemory()
        self._context_builder = ContextBuilder(self._session_memory)
        self._inserter = OutputInserter()
        self._state = PipelineState.IDLE
        self._on_state_change: Callable[[str], None] | None = None
        self._on_silence_detected: Callable[[], None] | None = None
        self._cancelled = False
        # Active app at dictation time — drives Smart-mode formatting.
        self._active_app: tuple[str, str] = ("", "general")
        # Experimental realtime (transcribe-while-speaking) state.
        self._realtime = None
        self._use_realtime = False
        self._on_caption = None  # callable(str) for live captions (set by the UI)
        self._on_notice = None   # callable(str) for quiet hints (set by the UI)
        self._last_raw_text = ""  # last transcript, for "re-run in another mode"
        self._vocab_learner = None  # lazy VocabLearner (auto-learning dictionary)

        # Wire silence detection into audio callback
        self._config = config
        original_cb = self._recorder._audio_callback

        def _cb_with_silence(indata, frames, time_info, status):
            original_cb(indata, frames, time_info, status)
            if (
                self._config.auto_stop_on_silence
                and self._recorder.is_recording
                and self._silence_detector.feed(indata)
            ):
                self._recorder.stop()
                if self._on_silence_detected:
                    self._on_silence_detected()

        self._recorder._audio_callback = _cb_with_silence

    def set_state_callback(self, callback: Callable[[str], None]) -> None:
        self._on_state_change = callback

    def set_silence_callback(self, callback: Callable[[], None]) -> None:
        self._on_silence_detected = callback

    def set_caption_callback(self, callback) -> None:
        """Set a callback(str) that receives the live partial transcript."""
        self._on_caption = callback

    def set_notice_callback(self, callback) -> None:
        """Set a callback(str) for quiet, non-blocking hints (e.g. fallbacks)."""
        self._on_notice = callback

    def _notify(self, message: str) -> None:
        if self._on_notice:
            try:
                self._on_notice(message)
            except Exception:
                pass

    def _set_state(self, state: str) -> None:
        self._state = state
        if self._on_state_change:
            self._on_state_change(state)

    @property
    def state(self) -> str:
        return self._state

    def start_recording(self) -> None:
        self._cancelled = False
        self._silence_detector.reset()
        # Capture the foreground app now — by rewrite time focus may have moved.
        try:
            from src.context.active_window import detect_active_app
            self._active_app = detect_active_app()
        except Exception:
            self._active_app = ("", "general")

        self._set_state(PipelineState.RECORDING)

        # Warm the rewrite connection now (runs on the rewrite worker loop, so it
        # is safe) — keeps the TLS handshake off the critical path after release.
        try:
            self._rewriter.warm_up()
        except Exception:
            pass

        # Experimental: start streaming to the Realtime API (transcribe while
        # speaking). The mic starts synchronously here so no opening words are
        # lost. On any failure we fall back to normal batch recording.
        self._use_realtime = False
        self._realtime = None
        if self._config.transcription_realtime:
            try:
                if self._config.deepgram_api_key:
                    # Deepgram streams true word-by-word interim captions.
                    from src.transcription.deepgram_client import DeepgramTranscriber
                    self._realtime = DeepgramTranscriber(on_caption=self._on_caption)
                else:
                    from src.transcription.realtime_client import RealtimeTranscriber
                    self._realtime = RealtimeTranscriber(on_caption=self._on_caption)
                self._realtime.start()  # synchronous — capture begins immediately
                self._use_realtime = True
            except Exception as e:
                logger.warning("Realtime unavailable, using batch transcription: %s", e)
                self._use_realtime = False
                self._realtime = None

        if not self._use_realtime:
            self._recorder.start()

    def stop_recording(self) -> None:
        self._recorder.stop()

    def cancel(self) -> None:
        """Cancel the current pipeline run and stop recording if active."""
        self._cancelled = True
        if self._recorder.is_recording:
            self._recorder.stop()
        if self._realtime is not None:
            try:
                self._realtime.close()
            except Exception:
                pass
            self._realtime = None
            self._use_realtime = False
        self._set_state(PipelineState.IDLE)

    async def process(
        self,
        mode: RewriteMode,
        output_mode: str | None = None,
    ) -> tuple[str, str]:
        """Transcribe recorded audio, rewrite, and deliver output.

        Args:
            mode: The rewrite mode to apply.
            output_mode: Override output mode (uses config default if None).

        Returns:
            Tuple of (raw_transcription, rewritten_text).
        """
        self._cancelled = False
        _start = time.monotonic()
        config = Config()
        logger.info(
            "Pipeline run: mode=%s, model=%s, provider=%s",
            mode.value, config.gpt_model, config.transcription_provider,
        )
        try:
            # 1. Build context from clipboard, selection, session memory, VS Code
            context = self._context_builder.build()
            if self._cancelled:
                self._set_state(PipelineState.IDLE)
                return "", ""

            # 2. Transcribe — realtime (experimental) or batch (cloud/local)
            self._set_state(PipelineState.TRANSCRIBING)
            if self._use_realtime and self._realtime is not None:
                # start() never raises and stop_and_transcribe() falls back to the
                # standard cloud path internally, so live transcription can't lose
                # a dictation. A genuine error (e.g. network fully down) propagates
                # to the outer handler below.
                live_failed = False
                try:
                    raw_text = await self._realtime.stop_and_transcribe()
                    # Only a genuine connect/session failure counts — a short or
                    # silent clip that returns no segments is NOT "unavailable".
                    live_failed = bool(getattr(self._realtime, "live_failed", False))
                finally:
                    self._use_realtime = False
                    self._realtime = None
                if live_failed:
                    self._notify("Live transcription unavailable — used standard mode.")
            else:
                # If live was requested but couldn't start, this batch path IS the
                # silent fallback — surface a quiet hint so it's never mysterious.
                if self._config.transcription_realtime:
                    self._notify("Live transcription unavailable — used standard mode.")
                wav_bytes = self._recorder.get_wav_bytes()
                whisper = get_transcription_client()
                raw_text = await whisper.transcribe(wav_bytes)
            logger.info("Transcription: %d words (%d chars)", len(raw_text.split()), len(raw_text))
            if raw_text.strip():
                self._last_raw_text = raw_text  # cache for "re-run in another mode"
            if self._cancelled:
                self._set_state(PipelineState.IDLE)
                return "", ""

            # 3. Rewrite — stream-and-type for auto-paste (low perceived latency),
            #    otherwise generate the full text for clipboard/preview delivery.
            self._set_state(PipelineState.REWRITING)
            effective_output = output_mode or config.output_mode
            stream_output = (
                config.stream_output and effective_output == OutputMode.AUTO_PASTE
            )

            if stream_output:
                chunks: list[str] = []
                self._inserter.begin_stream()
                try:
                    async for delta in self._rewriter.rewrite_stream(
                        raw_text, mode, context, app_hint=self._active_app
                    ):
                        if self._cancelled:
                            break
                        chunks.append(delta)
                        self._inserter.feed_stream(delta)
                finally:
                    self._inserter.end_stream()
                rewritten = "".join(chunks)
            else:
                rewritten = await self._rewriter.rewrite(
                    raw_text, mode, context, app_hint=self._active_app
                )
            logger.info("Rewrite: %d words (%d chars)", len(rewritten.split()), len(rewritten))
            if self._cancelled:
                self._set_state(PipelineState.IDLE)
                return "", ""

            # 4. Store in session memory
            self._session_memory.add(raw_text, rewritten, mode.value)

            # 5. Deliver output (streaming already typed it at the cursor)
            if not stream_output:
                self._inserter.deliver(rewritten, output_mode)

            # 6. Record usage analytics (non-blocking, best-effort)
            if config.track_usage:
                try:
                    from src.services.usage_tracker import record_run
                    record_run(
                        raw_text=raw_text,
                        rewritten_text=rewritten,
                        mode=mode.value,
                        provider=config.transcription_provider,
                        duration_ms=int((time.monotonic() - _start) * 1000),
                    )
                except Exception:
                    pass

            # 7. Learn candidate dictionary terms from this dictation (best-effort)
            try:
                from src.services.vocab_learner import VocabLearner
                if self._vocab_learner is None:
                    self._vocab_learner = VocabLearner()
                self._vocab_learner.observe(rewritten or raw_text)
            except Exception:
                pass

            elapsed = time.monotonic() - _start
            logger.info("Pipeline complete in %.1fs", elapsed)
            self._set_state(PipelineState.DONE)
            return raw_text, rewritten

        except Exception as exc:
            logger.error("Pipeline error: %s", exc, exc_info=True)
            self._set_state(PipelineState.ERROR)
            raise

    async def rerun_last(
        self, mode: RewriteMode, output_mode: str | None = None
    ) -> tuple[str, str]:
        """Re-rewrite the LAST transcript in a different mode (no re-speaking).

        Uses the cached raw transcript, rewrites it in `mode`, and delivers it the
        usual way. Returns ("", "") if there's nothing to re-run yet.
        """
        raw_text = self._last_raw_text
        if not raw_text:
            return "", ""

        self._cancelled = False
        config = Config()
        # Deliver to wherever the cursor is now; re-detect the app for Smart mode.
        try:
            from src.context.active_window import detect_active_app
            app_hint = detect_active_app()
        except Exception:
            app_hint = self._active_app

        try:
            self._set_state(PipelineState.REWRITING)
            effective_output = output_mode or config.output_mode
            stream_output = (
                config.stream_output and effective_output == OutputMode.AUTO_PASTE
            )
            if stream_output:
                chunks: list[str] = []
                self._inserter.begin_stream()
                try:
                    async for delta in self._rewriter.rewrite_stream(
                        raw_text, mode, None, app_hint=app_hint
                    ):
                        chunks.append(delta)
                        self._inserter.feed_stream(delta)
                finally:
                    self._inserter.end_stream()
                rewritten = "".join(chunks)
            else:
                rewritten = await self._rewriter.rewrite(
                    raw_text, mode, None, app_hint=app_hint
                )
                self._inserter.deliver(rewritten, output_mode)

            self._session_memory.add(raw_text, rewritten, mode.value)
            logger.info("Re-run: mode=%s, %d words", mode.value, len(rewritten.split()))
            self._set_state(PipelineState.DONE)
            return raw_text, rewritten
        except Exception as exc:
            logger.error("Re-run error: %s", exc, exc_info=True)
            self._set_state(PipelineState.ERROR)
            raise
