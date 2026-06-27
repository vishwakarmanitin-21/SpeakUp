from __future__ import annotations

import io

from openai import AsyncOpenAI

from src.config import Config


class WhisperClient:
    """Transcribes audio using the OpenAI Whisper API."""

    def __init__(self) -> None:
        config = Config()
        self._client = AsyncOpenAI(api_key=config.openai_api_key)
        self._model = config.whisper_model

    async def transcribe(self, audio_buffer: io.BytesIO) -> str:
        """Send audio to Whisper API and return the transcription.

        Args:
            audio_buffer: In-memory WAV file (BytesIO with .name attribute).

        Returns:
            Transcribed text string.

        Raises:
            TranscriptionError: If the Whisper API call fails.
        """
        from src.services.error_handler import TranscriptionError

        # Bias recognition toward the user's custom vocabulary (names, jargon).
        kwargs: dict = {
            "model": self._model,
            "file": audio_buffer,
            "language": "en",
            "response_format": "text",
        }
        vocab = Config().custom_vocabulary
        if vocab:
            kwargs["prompt"] = "Terms: " + ", ".join(vocab)

        try:
            response = await self._client.audio.transcriptions.create(**kwargs)
            return response.strip()
        except Exception as e:
            raise TranscriptionError(
                f"Whisper transcription failed: {e}",
                "Transcription failed. Check your API key and internet connection.",
            ) from e
