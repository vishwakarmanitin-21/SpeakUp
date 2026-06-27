from __future__ import annotations

import io

from openai import AsyncOpenAI

from src.config import Config


class WhisperClient:
    """Transcribes audio using the OpenAI Whisper API.

    The client is built lazily inside transcribe() (reading the current key and
    model), so the app can launch without an API key — it's only required when
    you actually dictate.
    """

    async def transcribe(self, audio_buffer: io.BytesIO) -> str:
        """Send audio to the transcription API and return the text.

        Raises:
            TranscriptionError: If the API call fails.
        """
        from src.services.error_handler import TranscriptionError

        config = Config()
        # Raises APIKeyError (a user-friendly SpeakUpError) if no key is set yet.
        client = AsyncOpenAI(api_key=config.openai_api_key)

        kwargs: dict = {
            "model": config.whisper_model,
            "file": audio_buffer,
            "language": "en",
            "response_format": "text",
        }
        # Bias recognition toward the user's custom vocabulary (names, jargon).
        vocab = config.custom_vocabulary
        if vocab:
            kwargs["prompt"] = "Terms: " + ", ".join(vocab)

        try:
            response = await client.audio.transcriptions.create(**kwargs)
            return response.strip()
        except Exception as e:
            raise TranscriptionError(
                f"Whisper transcription failed: {e}",
                "Transcription failed. Check your API key and internet connection.",
            ) from e
