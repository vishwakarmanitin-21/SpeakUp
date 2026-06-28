from __future__ import annotations

import logging

from openai import AsyncOpenAI

from src.config import Config
from src.rewrite.modes import RewriteMode
from src.rewrite.prompts import SYSTEM_PROMPT, build_user_prompt

logger = logging.getLogger("speakup")


class RewriteEngine:
    """Sends transcribed text to GPT for intelligent rewriting.

    The OpenAI client is built lazily on first dictation (so the app can launch
    without a key) and then REUSED across dictations with a long HTTP keep-alive,
    so each request rides a warm connection instead of paying a fresh TLS
    handshake — cutting first-token latency. It's rebuilt only if the key changes.
    """

    def __init__(self) -> None:
        self._client: AsyncOpenAI | None = None
        self._client_key: str | None = None

    def _get_client(self, api_key: str) -> AsyncOpenAI:
        if self._client is not None and self._client_key == api_key:
            return self._client
        try:
            import httpx

            http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(60.0, connect=10.0),
                limits=httpx.Limits(max_keepalive_connections=4, keepalive_expiry=120.0),
            )
            self._client = AsyncOpenAI(api_key=api_key, http_client=http_client)
        except Exception as e:  # pragma: no cover - httpx version/edge cases
            logger.warning("Falling back to default OpenAI client (%s)", e)
            self._client = AsyncOpenAI(api_key=api_key)
        self._client_key = api_key
        return self._client

    async def rewrite(
        self,
        raw_text: str,
        mode: RewriteMode,
        context: str | None = None,
        app_hint: tuple[str, str] | None = None,
    ) -> str:
        """Rewrite raw_text using the specified mode."""
        from src.services.error_handler import RewriteError

        config = Config()
        vocabulary = config.custom_vocabulary or None
        user_prompt = build_user_prompt(
            mode, raw_text, context, app_hint=app_hint, vocabulary=vocabulary
        )
        # Raises APIKeyError (a user-friendly SpeakUpError) if no key is set yet.
        client = self._get_client(config.openai_api_key)

        try:
            response = await client.chat.completions.create(
                model=config.gpt_model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=config.temperature,
                max_tokens=2000,
            )
            content = response.choices[0].message.content
            return (content or "").strip()
        except Exception as e:
            raise RewriteError(
                f"GPT rewrite failed: {e}",
                "Rewrite failed. Check your API key and internet connection.",
            ) from e

    async def rewrite_stream(
        self,
        raw_text: str,
        mode: RewriteMode,
        context: str | None = None,
        app_hint: tuple[str, str] | None = None,
    ):
        """Stream the rewritten text as deltas arrive (for low-latency output).

        Yields incremental string chunks. The caller accumulates the full text.
        """
        from src.services.error_handler import RewriteError

        config = Config()
        vocabulary = config.custom_vocabulary or None
        user_prompt = build_user_prompt(
            mode, raw_text, context, app_hint=app_hint, vocabulary=vocabulary
        )
        client = self._get_client(config.openai_api_key)

        try:
            stream = await client.chat.completions.create(
                model=config.gpt_model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=config.temperature,
                max_tokens=2000,
                stream=True,
            )
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except Exception as e:
            raise RewriteError(
                f"GPT rewrite failed: {e}",
                "Rewrite failed. Check your API key and internet connection.",
            ) from e
