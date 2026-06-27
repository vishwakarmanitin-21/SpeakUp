"""Local transcription using faster-whisper (runs on-device, no API call)."""
from __future__ import annotations

import asyncio
import io
import logging

from src.config import Config

logger = logging.getLogger("speakup")

# Module-level model cache — only loaded once per session
_cached_model = None
_cached_model_size: str | None = None


def _load_model(model_size: str):
    """Load (or reuse) the faster-whisper model."""
    global _cached_model, _cached_model_size

    if _cached_model is not None and _cached_model_size == model_size:
        return _cached_model

    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise ImportError(
            "faster-whisper is not installed. Run: pip install faster-whisper"
        ) from exc

    logger.info("Loading faster-whisper model '%s'…", model_size)
    _cached_model = WhisperModel(model_size, device="cpu", compute_type="int8")
    _cached_model_size = model_size
    logger.info("faster-whisper model loaded.")
    return _cached_model


class LocalWhisperClient:
    """Transcribes audio locally using faster-whisper (no internet required)."""

    def __init__(self) -> None:
        config = Config()
        self._model_size = config.whisper_local_model_size

    async def transcribe(self, audio_buffer: io.BytesIO) -> str:
        """Transcribe in-memory WAV bytes using the local faster-whisper model.

        Runs inference in a thread pool so the Qt event loop stays unblocked.

        Args:
            audio_buffer: In-memory WAV BytesIO.

        Returns:
            Transcribed text string.

        Raises:
            TranscriptionError: If inference fails.
        """
        from src.services.error_handler import TranscriptionError

        try:
            model = _load_model(self._model_size)
            loop = asyncio.get_event_loop()

            def _run():
                # faster-whisper accepts a file-like object or file path
                audio_buffer.seek(0)
                segments, _ = model.transcribe(
                    audio_buffer,
                    language="en",
                    beam_size=5,
                    vad_filter=True,       # skip silence
                    vad_parameters={"min_silence_duration_ms": 500},
                )
                return " ".join(seg.text for seg in segments).strip()

            return await loop.run_in_executor(None, _run)

        except ImportError as e:
            raise TranscriptionError(
                str(e),
                "faster-whisper is not installed. Run: pip install faster-whisper",
            ) from e
        except Exception as e:
            raise TranscriptionError(
                f"Local Whisper transcription failed: {e}",
                "Local transcription failed. Try switching to Cloud mode in Settings.",
            ) from e
