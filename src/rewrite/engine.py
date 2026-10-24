from __future__ import annotations

import asyncio
import logging
import os
import queue
import re
import threading
import time

from openai import AsyncOpenAI

from src.config import Config
from src.rewrite.modes import RewriteMode
from src.rewrite.prompts import SYSTEM_PROMPT, build_user_prompt

logger = logging.getLogger("speakup")

_SENTINEL = object()
_MAX_OUTPUT_TOKENS = 2000


def completion_kwargs(model: str, temperature: float) -> dict:
    """Request parameters that `model` accepts.

    GPT-5 onwards and the o-series are reasoning models: they reject
    `max_tokens` and `temperature`, and think before answering unless told
    not to — which would add seconds to a light clean-up (gpt-6-luna's
    default reasoning roughly triples time-to-first-word). Verified against
    the live API on 2026-10-24: gpt-5.x and gpt-6 accept reasoning_effort
    "none"; the original gpt-5 / -mini / -nano only "minimal" or higher.
    """
    name = model.lower()
    match = re.match(r"gpt-(\d+)(\.\d+)?", name)
    major = int(match.group(1)) if match else 0
    if name.startswith(("o1", "o3", "o4")):
        effort = "low"
    elif major < 5 or "-chat" in name:
        return {"temperature": temperature, "max_tokens": _MAX_OUTPUT_TOKENS}
    elif major == 5 and not match.group(2):
        effort = "minimal"
    else:
        effort = "none"
    return {"reasoning_effort": effort, "max_completion_tokens": _MAX_OUTPUT_TOKENS}


def is_claude(model: str) -> bool:
    return model.lower().startswith("claude-")


def claude_request_kwargs() -> dict:
    """Claude Messages API settings for a fast, light clean-up.

    Haiku 5.5 thinks by default, which costs seconds before the first word;
    "disabled" is accepted at effort high or below. No temperature: current
    Claude models reject non-default sampling parameters.
    """
    return {
        "max_tokens": _MAX_OUTPUT_TOKENS,
        "thinking": {"type": "disabled"},
        "output_config": {"effort": "low"},
    }


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
        self._claude_client = None
        self._claude_key: tuple[str, str] | None = None
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
                limits=httpx.Limits(max_keepalive_connections=4, keepalive_expiry=180.0),
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
            # Warm whichever provider does the clean-up.
            claude = is_claude(Config().gpt_model)
            key = os.getenv("ANTHROPIC_API_KEY" if claude else "OPENAI_API_KEY", "")
            # Throttle < the background heartbeat interval (60s) so a heartbeat
            # always fires, and < the connection keep-alive (180s) so the socket
            # never goes cold between dictations.
            if not key or time.monotonic() - self._last_warm < 50.0:
                return
            self._ensure_worker()

            async def _warm() -> None:
                try:
                    if claude:
                        await self._get_claude_client(key).models.list(limit=1)
                    else:
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
        model: str | None = None,
    ) -> str:
        """Rewrite raw_text using the specified mode (non-streaming).

        `model` overrides the configured one (used for the backup provider).
        """
        parts = []
        async for delta in self.rewrite_stream(raw_text, mode, context, app_hint, model):
            parts.append(delta)
        return "".join(parts).strip()

    async def rewrite_stream(
        self,
        raw_text: str,
        mode: RewriteMode,
        context: str | None = None,
        app_hint: tuple[str, str] | None = None,
        model: str | None = None,
    ):
        """Stream the rewritten text as deltas arrive (for low-latency output)."""
        from src.services.error_handler import RewriteError, friendly_api_error

        messages, model, temperature, key = self._prepare(
            raw_text, mode, context, app_hint, model
        )
        self._ensure_worker()
        self._last_warm = time.monotonic()

        q: queue.Queue = queue.Queue()

        async def _bg() -> None:
            try:
                if is_claude(model):
                    await self._stream_claude(key, model, messages, q.put)
                else:
                    await self._stream_openai(key, model, messages, temperature, q.put)
            except Exception as e:  # surface to the consumer
                q.put(("__error__", str(e)))
            finally:
                q.put(_SENTINEL)

        asyncio.run_coroutine_threadsafe(_bg(), self._loop)  # type: ignore[arg-type]
        main_loop = asyncio.get_running_loop()
        provider = "Claude" if is_claude(model) else "GPT"
        while True:
            item = await main_loop.run_in_executor(None, q.get)
            if item is _SENTINEL:
                break
            if isinstance(item, tuple) and item and item[0] == "__error__":
                raise RewriteError(
                    f"{provider} rewrite failed ({model}): {item[1]}",
                    friendly_api_error(item[1], "Rewrite"),
                )
            yield item

    # --- Providers (run on the worker loop) ---

    async def _stream_openai(self, key, model, messages, temperature, emit) -> None:
        stream = await self._get_client(key).chat.completions.create(
            model=model, messages=messages, stream=True,
            **completion_kwargs(model, temperature),
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                emit(delta)

    async def _stream_claude(self, key, model, messages, emit) -> None:
        system = messages[0]["content"]
        async with self._get_claude_client(key).messages.stream(
            model=model, system=system, messages=messages[1:],
            **claude_request_kwargs(),
        ) as stream:
            async for text in stream.text_stream:
                if text:
                    emit(text)

    def _get_claude_client(self, api_key: str):
        """Persistent Anthropic client on the worker loop (same reasons as OpenAI)."""
        # A key created at the organisation level (not inside a workspace) is
        # rejected unless every request names the workspace to bill.
        workspace = os.getenv("ANTHROPIC_WORKSPACE_ID", "").strip()
        if self._claude_client is not None and self._claude_key == (api_key, workspace):
            return self._claude_client
        from anthropic import AsyncAnthropic

        headers = {"anthropic-workspace-id": workspace} if workspace else None
        # One retry only: this sits on the paste path, where a long retry
        # chain is worse than falling back to the unformatted transcript.
        self._claude_client = AsyncAnthropic(
            api_key=api_key, max_retries=1, timeout=30.0, default_headers=headers
        )
        self._claude_key = (api_key, workspace)
        return self._claude_client

    # --- Helpers ---

    def _prepare(self, raw_text, mode, context, app_hint, model=None):
        """Build messages + read model/temperature/key on the caller's loop.

        The API key is read here (may raise APIKeyError if unset) so the worker
        thread never touches the config singleton.
        """
        config = Config()
        model = model or config.gpt_model
        vocabulary = config.custom_vocabulary or None
        user_prompt = build_user_prompt(
            mode, raw_text, context, app_hint=app_hint, vocabulary=vocabulary
        )
        if is_claude(model):
            key = config.anthropic_api_key
            if not key:
                from src.services.error_handler import APIKeyError
                raise APIKeyError(
                    "ANTHROPIC_API_KEY not set",
                    "Anthropic API key is not configured. Add it in Settings.",
                )
        else:
            key = config.openai_api_key  # raises APIKeyError if not set
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        return messages, model, config.temperature, key
