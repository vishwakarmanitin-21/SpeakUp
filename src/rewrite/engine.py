from __future__ import annotations

from openai import AsyncOpenAI

from src.config import Config
from src.rewrite.modes import RewriteMode
from src.rewrite.prompts import SYSTEM_PROMPT, build_user_prompt


class RewriteEngine:
    """Sends transcribed text to GPT for intelligent rewriting.

    The OpenAI client is built lazily per call (reading the current API key and
    model from config), so the app can launch without a key — it's only needed
    when you actually dictate, and settings changes apply without a restart.
    """

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
        client = AsyncOpenAI(api_key=config.openai_api_key)

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
        client = AsyncOpenAI(api_key=config.openai_api_key)

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
