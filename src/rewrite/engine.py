from __future__ import annotations

import asyncio
import logging
import os
import queue
import threading
import time

from openai import AsyncOpenAI

from src.config import Config
from src.rewrite.modes import RewriteMode
from src.rewrite.prompts import SYSTEM_PROMPT, build_user_prompt

logger = logging.getLogger("speakup")

_SENTINEL = object()


class RewriteEngine:
    """Sends transcribed text to GPT for intelligent rewriting.

    All OpenAI calls run on ONE dedicated background thread/event loop with a
    persistent, kept-alive client. This gives two things at once:

      * Speed — the HTTPS connection stays warm, so we don't pay a fresh TLS
        handshake on every dictation (that cold handshake was the bulk of the
        post-release lag).
      * Stability — httpx/anyio lives entirely on its own single loop, so the
        "cancel scope" crash we hit when a shared client was used across the
        qasync loop (on stream cancellation) cannot happen. The public methods
        stay async and just shuttle results back to the caller's loop via a
        thread-safe queue, so they can be cancelled freely.
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._client: AsyncOpenAI | None = None
        self._client_key: str | None = None
        self._last_warm = 0.0

    # --- Background worker (dedicated loop) ---

    def _ensure_worker(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        ready = threading.Event()

        def _run() -> None:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            ready.set()
            self._loop.run_forever()

        self._thread = threading.Thread(target=_run, daemon=True, name="rewrite-loop")
        self._thread.start()
        ready.wait(timeout=5.0)

    def _get_client(self, api_key: str) -> AsyncOpenAI:
        """Persistent client on the worker loop; rebuilt only if the key changes."""
        if self._client is not None and self._client_key == api_key:
            return self._client
        try:
            import httpx

            http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(60.0, connect=10.0),
                limits=httpx.Limits(max_keepalive_connections=4, keepalive_expiry=120.0),
            )
            self._client = AsyncOpenAI(api_key=api_key, http_client=http_client)
        except Exception as e:  # pragma: no cover
            logger.warning("Falling back to default OpenAI client (%s)", e)
            self._client = AsyncOpenAI(api_key=api_key)
        self._client_key = api_key
        return self._client

    def warm_up(self) -> None:
        """Warm the connection (best-effort) so the first dictation is fast too.

        Runs a cheap request on the worker loop. Called on key-press; safe and
        silent — it can never affect a dictation.
        """
        try:
            key = os.getenv("OPENAI_API_KEY", "")
            if not key or time.monotonic() - self._last_warm < 90.0:
                return
            self._ensure_worker()

            async def _warm() -> None:
                try:
                    await self._get_client(key).models.list()
                except Exception:
                    pass

            asyncio.run_coroutine_threadsafe(_warm(), self._loop)  # type: ignore[arg-type]
            self._last_warm = time.monotonic()
        except Exception:
            pass

    # --- Public API (async, run on the caller's loop) ---

    async def rewrite(
        self,
        raw_text: str,
        mode: RewriteMode,
        context: str | None = None,
        app_hint: tuple[str, str] | None = None,
    ) -> str:
        """Rewrite raw_text using the specified mode (non-streaming)."""
        from src.services.error_handler import RewriteError

        messages, model, temperature, key = self._prepare(raw_text, mode, context, app_hint)
        self._ensure_worker()
        self._last_warm = time.monotonic()

        async def _bg() -> str:
            client = self._get_client(key)
            resp = await client.chat.completions.create(
                model=model, messages=messages, temperature=temperature, max_tokens=2000,
            )
            return (resp.choices[0].message.content or "").strip()

        try:
            fut = asyncio.run_coroutine_threadsafe(_bg(), self._loop)  # type: ignore[arg-type]
            return await asyncio.get_running_loop().run_in_executor(None, fut.result)
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
        """Stream the rewritten text as deltas arrive (for low-latency output)."""
        from src.services.error_handler import RewriteError

        messages, model, temperature, key = self._prepare(raw_text, mode, context, app_hint)
        self._ensure_worker()
        self._last_warm = time.monotonic()

        q: queue.Queue = queue.Queue()

        async def _bg() -> None:
            try:
                client = self._get_client(key)
                stream = await client.chat.completions.create(
                    model=model, messages=messages, temperature=temperature,
                    max_tokens=2000, stream=True,
                )
                async for chunk in stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta.content
                    if delta:
                        q.put(delta)
            except Exception as e:  # surface to the consumer
                q.put(("__error__", str(e)))
            finally:
                q.put(_SENTINEL)

        asyncio.run_coroutine_threadsafe(_bg(), self._loop)  # type: ignore[arg-type]
        main_loop = asyncio.get_running_loop()
        while True:
            item = await main_loop.run_in_executor(None, q.get)
            if item is _SENTINEL:
                break
            if isinstance(item, tuple) and item and item[0] == "__error__":
                raise RewriteError(
                    f"GPT rewrite failed: {item[1]}",
                    "Rewrite failed. Check your API key and internet connection.",
                )
            yield item

    # --- Helpers ---

    def _prepare(self, raw_text, mode, context, app_hint):
        """Build messages + read model/temperature/key on the caller's loop.

        The API key is read here (may raise APIKeyError if unset) so the worker
        thread never touches the config singleton.
        """
        config = Config()
        vocabulary = config.custom_vocabulary or None
        user_prompt = build_user_prompt(
            mode, raw_text, context, app_hint=app_hint, vocabulary=vocabulary
        )
        key = config.openai_api_key  # raises APIKeyError if not set
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        return messages, config.gpt_model, config.temperature, key
