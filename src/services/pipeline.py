from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger("speakup")

from src.audio.recorder import AudioRecorder
from src.audio.silence_detector import SilenceDetector
from src.config import Config
from src.context.context_builder import ContextBuilder
from src.context.session_memory import SessionMemory
from src.output.inserter import OutputInserter, OutputMode
from src.rewrite.engine import RewriteEngine
from src.rewrite.modes import RewriteMode
from src.services.error_handler import RewriteError, is_model_unavailable
from src.transcription.factory import get_transcription_client


class PipelineState:
    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    REWRITING = "rewriting"
    DONE = "done"
    ERROR = "error"


@dataclass
class _Take:
    """Everything one dictation needs after the key is released."""

    realtime: Any            # live transcriber session, or None for batch
    wav_bytes: bytes | None  # batch audio
    wav_error: Exception | None
    record_started_at: float | None
    active_app: tuple[str, str]
    cancel_gen: int


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
        # cancel() bumps this; a run is cancelled when its take's value is stale.
        # Per-run (not a shared bool) so a new dictation can't un-cancel an old one.
        self._cancel_gen = 0
        self._pending_take: _Take | None = None
        # Serialises rewrite+paste so overlapping dictations never interleave.
        self._output_lock = asyncio.Lock()
        # Active app at dictation time — drives Smart-mode formatting.
        self._active_app: tuple[str, str] = ("", "general")
        # Experimental realtime (transcribe-while-speaking) state.
        self._realtime = None
        self._use_realtime = False
        self._on_caption = None  # callable(str) for live captions (set by the UI)
        self._on_notice = None   # callable(str) for quiet hints (set by the UI)
        self._last_raw_text = ""  # last transcript, for "re-run in another mode"
        self._record_started_at: float | None = None  # for billable audio length
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

    def _recover_from_rewrite_error(
        self, exc: RewriteError, config: Config, partial: bool = False
    ) -> None:
        """Explain a clean-up failure, and switch away from a retired model.

        OpenAI retires models without notice (gpt-4.1-nano, 2026-10-24); left
        alone, every later dictation would fail the same way.
        """
        logger.warning(
            "Rewrite failed%s: %s",
            " part-way; kept the text already typed" if partial
            else ", delivered the unformatted transcript", exc,
        )
        outcome = (
            "Clean-up stopped part-way through." if partial
            else "Pasted your words without clean-up."
        )
        model = config.gpt_model
        default = config.default("gpt_model")
        # Only switch TO a different model — if the default itself is retired,
        # switching would just loop.
        if is_model_unavailable(exc) and default and model != default:
            config.save_user_overrides({"gpt_model": default})
            logger.warning("Clean-up model %r is unavailable; switched to %r", model, default)
            self._notify(
                f"OpenAI retired the clean-up model '{model}'. Switched to "
                f"'{default}' for your next dictation. {outcome}"
            )
        else:
            self._notify(f"{outcome} {exc.user_message}")

    def _set_state(self, state: str) -> None:
        self._state = state
        if self._on_state_change:
            self._on_state_change(state)

    @property
    def state(self) -> str:
        return self._state

    def keep_warm(self) -> None:
        """Ping the rewrite connection so it never goes cold (background heartbeat).

        Called on a timer while the app is idle; the first dictation after a long
        pause is then as fast as a warm one instead of paying a reconnect tax.
        """
        try:
            self._rewriter.warm_up()
        except Exception:
            pass

    def start_recording(self) -> None:
        # Speech-to-text is billed per minute of AUDIO, so the recording's real
        # length is what determines cost — not the word count it produced.
        self._record_started_at = time.monotonic()
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
                # Which engine transcribes while you speak. 'auto' keeps the old
                # behaviour (Deepgram when a key is set); the explicit choices
                # let the two be compared in real use — they differ in both
                # accuracy and caption feel, so this is a judgement call.
                engine = self._config.live_engine
                has_deepgram = bool(self._config.deepgram_api_key)
                use_deepgram = has_deepgram and engine in ("auto", "deepgram")
                if engine == "deepgram" and not has_deepgram:
                    self._notify("Deepgram key not set — using OpenAI for live transcription.")

                if use_deepgram:
                    # Deepgram streams true word-by-word interim captions.
                    from src.transcription.deepgram_client import DeepgramTranscriber
                    self._realtime = DeepgramTranscriber(on_caption=self._on_caption)
                else:
                    from src.transcription.realtime_client import RealtimeTranscriber
                    self._realtime = RealtimeTranscriber(on_caption=self._on_caption)
                logger.info(
                    "Live engine: %s (setting=%s)",
                    "deepgram" if use_deepgram else "openai", engine,
                )
                self._realtime.start()  # synchronous — capture begins immediately
                self._use_realtime = True
            except Exception as e:
                logger.warning("Realtime unavailable, using batch transcription: %s", e)
                self._use_realtime = False
                self._realtime = None

        if not self._use_realtime:
            self._recorder.start()

    def stop_recording(self) -> None:
        """End capture and hand this dictation its own snapshot (_Take).

        The next hotkey press may start a new recording while this one is still
        being transcribed. Detaching everything process() needs here keeps the
        two runs from overwriting each other's live session and audio — seen
        2026-10-24, when the second run lost its audio entirely.
        """
        self._recorder.stop()
        self._pending_take = self._take_snapshot()

    def _take_snapshot(self) -> _Take:
        realtime = self._realtime if self._use_realtime else None
        self._realtime = None
        self._use_realtime = False
        wav_bytes, wav_error = None, None
        if realtime is not None:
            try:
                realtime.close()  # stop the mic now; the transcript is awaited later
            except Exception:
                pass
        else:
            try:
                wav_bytes = self._recorder.get_wav_bytes()
            except Exception as e:  # e.g. no audio — raised again in process()
                wav_error = e
        return _Take(
            realtime=realtime,
            wav_bytes=wav_bytes,
            wav_error=wav_error,
            record_started_at=self._record_started_at,
            active_app=self._active_app,
            cancel_gen=self._cancel_gen,
        )

    def discard_recording(self) -> None:
        """Drop the CURRENT recording only (e.g. a too-short tap).

        Unlike cancel(), a dictation already being processed keeps going.
        """
        if self._recorder.is_recording:
            self._recorder.stop()
        if self._realtime is not None:
            try:
                self._realtime.close()
            except Exception:
                pass
        self._realtime = None
        self._use_realtime = False

    def cancel(self) -> None:
        """Cancel every in-flight run and stop recording if active."""
        self._cancel_gen += 1
        self._pending_take = None
        self.discard_recording()
        self._set_state(PipelineState.IDLE)

    def _is_cancelled(self, gen: int) -> bool:
        return gen != self._cancel_gen

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
        take = self._pending_take or self._take_snapshot()
        self._pending_take = None
        gen = take.cancel_gen
        _start = time.monotonic()
        # How long the mic was actually open — the billable quantity for STT.
        _audio_seconds = (
            _start - take.record_started_at if take.record_started_at else None
        )
        config = Config()
        logger.info(
            "Pipeline run: mode=%s, model=%s, provider=%s",
            mode.value, config.gpt_model, config.transcription_provider,
        )
        try:
            # 1. Build context from clipboard, selection, session memory, VS Code
            context = self._context_builder.build()
            if self._is_cancelled(gen):
                self._set_state(PipelineState.IDLE)
                return "", ""

            # 2. Transcribe — realtime (experimental) or batch (cloud/local)
            self._set_state(PipelineState.TRANSCRIBING)
            if take.realtime is not None:
                # start() never raises and stop_and_transcribe() falls back to the
                # standard cloud path internally, so live transcription can't lose
                # a dictation. A genuine error (e.g. network fully down) propagates
                # to the outer handler below.
                raw_text = await take.realtime.stop_and_transcribe()
                # Only a genuine connect/session failure counts — a short or
                # silent clip that returns no segments is NOT "unavailable".
                if getattr(take.realtime, "live_failed", False):
                    self._notify("Live transcription unavailable — used standard mode.")
            else:
                # If live was requested but couldn't start, this batch path IS the
                # silent fallback — surface a quiet hint so it's never mysterious.
                if self._config.transcription_realtime:
                    self._notify("Live transcription unavailable — used standard mode.")
                if take.wav_error is not None:
                    raise take.wav_error
                whisper = get_transcription_client()
                raw_text = await whisper.transcribe(take.wav_bytes)
            logger.info("Transcription: %d words (%d chars)", len(raw_text.split()), len(raw_text))
            # Repair dictionary terms the transcriber mis-heard or split into
            # other words ("west or a" -> "Vestora") BEFORE the rewrite, so the
            # model sees the right proper nouns instead of guessing at them.
            try:
                from src.services.phonetic import build_corrector
                raw_text = build_corrector().correct(raw_text)
            except Exception as e:
                logger.debug("Phonetic correction skipped: %s", e)
            if config.log_transcripts:
                logger.info("RAW TRANSCRIPT: %r", raw_text)
            if raw_text.strip():
                self._last_raw_text = raw_text  # cache for "re-run in another mode"
            if self._is_cancelled(gen):
                self._set_state(PipelineState.IDLE)
                return "", ""
            # Nothing was said: a clean-up model handed an empty transcript
            # invents text (or echoes session memory) and it gets pasted —
            # 4 times in the log before 2026-10-24.
            if not any(ch.isalnum() for ch in raw_text):
                logger.info("No speech in this recording; nothing pasted")
                self._notify("No speech heard - nothing was pasted. Check your microphone.")
                self._set_state(PipelineState.DONE)
                return raw_text, ""

            # 3-5. Rewrite + deliver, one dictation at a time: transcription of
            # overlapping dictations can run in parallel, but their text must
            # reach the cursor in order and never interleave in the paste stream.
            async with self._output_lock:
                if self._is_cancelled(gen):
                    self._set_state(PipelineState.IDLE)
                    return "", ""
                rewritten = await self._rewrite_and_deliver(
                    raw_text, mode, context, take.active_app, output_mode,
                    config, gen, _start,
                )
            if self._is_cancelled(gen):
                self._set_state(PipelineState.IDLE)
                return "", ""

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
                        audio_seconds=_audio_seconds,
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

    async def _rewrite_and_deliver(
        self,
        raw_text: str,
        mode: RewriteMode,
        context: str | None,
        app_hint: tuple[str, str],
        output_mode: str | None,
        config: Config,
        gen: int,
        start: float,
    ) -> str:
        """Rewrite raw_text, put it at the cursor (or clipboard/preview), and
        record it in session memory. Returns the delivered text.

        Stream-and-type for auto-paste (low perceived latency), otherwise the
        full text is generated first. A failed clean-up never loses the
        dictation: the words were already transcribed, so they are delivered
        unformatted instead.
        """
        self._set_state(PipelineState.REWRITING)
        effective_output = output_mode or config.output_mode
        stream_output = (
            config.stream_output and effective_output == OutputMode.AUTO_PASTE
        )

        rewrite_error: RewriteError | None = None
        partial = False
        if stream_output:
            chunks: list[str] = []
            first_token = False
            self._inserter.begin_stream()
            try:
                try:
                    async for delta in self._rewriter.rewrite_stream(
                        raw_text, mode, context, app_hint=app_hint
                    ):
                        if self._is_cancelled(gen):
                            break
                        if not first_token:
                            first_token = True
                            # Time-to-first-word from key-release — this is the
                            # latency the user actually perceives (text appears).
                            logger.info(
                                "First word after %d ms",
                                int((time.monotonic() - start) * 1000),
                            )
                        chunks.append(delta)
                        self._inserter.feed_stream(delta)
                except RewriteError as e:
                    rewrite_error = e
                    # Only when nothing was typed yet — after a mid-stream
                    # failure the raw text would duplicate what is there.
                    partial = bool(chunks)
                    if not chunks and raw_text.strip() and not self._is_cancelled(gen):
                        chunks.append(raw_text)
                        self._inserter.feed_stream(raw_text)
            finally:
                self._inserter.end_stream()
            rewritten = "".join(chunks)
        else:
            try:
                rewritten = await self._rewriter.rewrite(
                    raw_text, mode, context, app_hint=app_hint
                )
            except RewriteError as e:
                rewrite_error = e
                rewritten = raw_text
        if rewrite_error is not None:
            if not raw_text.strip():
                raise rewrite_error
            self._recover_from_rewrite_error(rewrite_error, config, partial)
        logger.info("Rewrite: %d words (%d chars)", len(rewritten.split()), len(rewritten))
        if self._is_cancelled(gen):
            return rewritten

        self._session_memory.add(raw_text, rewritten, mode.value)
        # Streaming already typed it at the cursor.
        if not stream_output:
            self._inserter.deliver(rewritten, output_mode)
        return rewritten

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

        gen = self._cancel_gen
        config = Config()
        # Deliver to wherever the cursor is now; re-detect the app for Smart mode.
        try:
            from src.context.active_window import detect_active_app
            app_hint = detect_active_app()
        except Exception:
            app_hint = self._active_app

        try:
            async with self._output_lock:
                rewritten = await self._rewrite_and_deliver(
                    raw_text, mode, None, app_hint, output_mode,
                    config, gen, time.monotonic(),
                )
            logger.info("Re-run: mode=%s, %d words", mode.value, len(rewritten.split()))
            self._set_state(PipelineState.DONE)
            return raw_text, rewritten
        except Exception as exc:
            logger.error("Re-run error: %s", exc, exc_info=True)
            self._set_state(PipelineState.ERROR)
            raise
