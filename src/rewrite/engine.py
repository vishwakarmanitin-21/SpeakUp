from __future__ import annotations

from openai import AsyncOpenAI

from src.config import Config
from src.rewrite.modes import RewriteMode
from src.rewrite.prompts import SYSTEM_PROMPT, build_user_prompt


class RewriteEngine:
    """Sends transcribed text to GPT for intelligent rewriting."""

    def __init__(self) -> None:
        config = Config()
        self._client = AsyncOpenAI(api_key=config.openai_api_key)
        self._model = config.gpt_model
        self._temperature = config.temperature

    async def rewrite(
        self,
        raw_text: str,
        mode: RewriteMode,
        context: str | None = None,
        app_hint: tuple[str, str] | None = None,
    ) -> str:
        """Rewrite raw_text using the specified mode.

        Args:
            raw_text: The transcribed speech text.
            mode: The rewrite mode to apply.
            context: Optional context (clipboard, selection, etc.).
            app_hint: (label, surface) of the active app — used by SMART mode.

        Returns:
            Rewritten text.
        """
        from src.services.error_handler import RewriteError

        vocabulary = Config().custom_vocabulary or None
        user_prompt = build_user_prompt(
            mode, raw_text, context, app_hint=app_hint, vocabulary=vocabulary
        )

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self._temperature,
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

        Yields incremental string chunks. The caller is responsible for
        accumulating the full text (e.g. for session memory and usage stats).
        """
        from src.services.error_handler import RewriteError

        vocabulary = Config().custom_vocabulary or None
        user_prompt = build_user_prompt(
            mode, raw_text, context, app_hint=app_hint, vocabulary=vocabulary
        )

        try:
            stream = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self._temperature,
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
