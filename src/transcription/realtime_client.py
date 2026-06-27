"""Experimental: OpenAI Realtime API transcription — transcribe WHILE speaking.

Opt-in via config `transcription_realtime`. Streams microphone audio over a
WebSocket so the transcript is essentially ready the moment the hotkey is
released, instead of being uploaded and transcribed afterwards.

Requires the optional dependency:  pip install -e ".[realtime]"

⚠️ EXPERIMENTAL: the exact Realtime event strings are centralised in the
constants below so they can be adjusted against OpenAI's live docs without
hunting through the logic. If transcription comes back empty, set the logger to
DEBUG and check `flowai.log` for the `Realtime event:` lines to see the actual
event names the server is sending.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging

import numpy as np
import sounddevice as sd

from src.config import Config

logger = logging.getLogger("flowai")

_REALTIME_URL = "wss://api.openai.com/v1/realtime?intent=transcription"
_SAMPLE_RATE = 24000  # OpenAI Realtime expects 24 kHz PCM16 mono

# Event type strings (centralised for easy adjustment against live docs).
_EVT_SESSION_UPDATE = "session.update"  # GA shape (beta used transcription_session.update)
_EVT_AUDIO_APPEND = "input_audio_buffer.append"
_EVT_AUDIO_COMMIT = "input_audio_buffer.commit"
_SUFFIX_DELTA = "input_audio_transcription.delta"
_SUFFIX_COMPLETED = "input_audio_transcription.completed"


class RealtimeUnavailable(RuntimeError):
    """Realtime transcription could not be used (missing dep / connection / protocol)."""


async def _ws_connect(url: str, headers: dict):
    """Open a websocket, tolerating the header-kwarg rename across versions."""
    import websockets

    try:
        return await websockets.connect(url, additional_headers=headers, max_size=None)
    except TypeError:
        # Older websockets releases use `extra_headers`.
        return await websockets.connect(url, extra_headers=headers, max_size=None)


class RealtimeTranscriber:
    """Streams mic audio to the OpenAI Realtime API and returns the transcript."""

    def __init__(self) -> None:
        config = Config()
        self._api_key = config.openai_api_key
        model = config.whisper_model
        self._model = model if "transcribe" in model else "gpt-4o-transcribe"
        self._vocab = config.custom_vocabulary
        self._ws = None
        self._mic: sd.RawInputStream | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._audio_q: asyncio.Queue | None = None
        self._sender_task: asyncio.Future | None = None
        self._transcript_parts: list[str] = []
        self._active = False

    async def start(self) -> None:
        """Connect, configure a push-to-talk session, and begin streaming the mic."""
        try:
            import websockets  # noqa: F401
        except ImportError as e:
            raise RealtimeUnavailable(
                'websockets not installed. Run: pip install -e ".[realtime]"'
            ) from e

        self._loop = asyncio.get_event_loop()
        self._audio_q = asyncio.Queue()
        self._transcript_parts = []

        try:
            self._ws = await _ws_connect(
                _REALTIME_URL,
                {"Authorization": f"Bearer {self._api_key}"},
            )
        except Exception as e:
            raise RealtimeUnavailable(f"Realtime connect failed: {e}") from e

        # GA transcription-session shape. Kept minimal to avoid field-rejection;
        # custom vocabulary is still applied at the rewrite stage. (If gpt-4o-transcribe
        # is rejected here, "gpt-realtime-whisper" is the documented alternative.)
        await self._ws.send(json.dumps({
            "type": _EVT_SESSION_UPDATE,
            "session": {
                "type": "transcription",
                "audio": {
                    "input": {
                        "format": {"type": "audio/pcm", "rate": _SAMPLE_RATE},
                        "transcription": {"model": self._model, "language": "en"},
                        # Push-to-talk: disable server VAD so the whole hold is
                        # ONE segment, committed when the hotkey is released.
                        # (Default-on VAD was splitting speech at pauses.)
                        "turn_detection": None,
                    },
                },
            },
        }))

        # Mic capture runs on a PortAudio thread; hand frames to the loop safely.
        # Capture float32 and convert to PCM16 — same as the working batch path
        # (a raw int16 stream produced silence on some devices).
        def _cb(indata, frames, time_info, status) -> None:
            if not self._active or self._loop is None:
                return
            pcm16 = (np.clip(indata[:, 0], -1.0, 1.0) * 32767).astype("<i2").tobytes()
            self._loop.call_soon_threadsafe(self._audio_q.put_nowait, pcm16)

        self._active = True
        self._mic = sd.InputStream(
            samplerate=_SAMPLE_RATE, channels=1, dtype="float32", callback=_cb
        )
        self._mic.start()
        self._sender_task = asyncio.ensure_future(self._sender())
        logger.info(
            "Realtime transcription started (model=%s, rate=%d)",
            self._model, int(self._mic.samplerate),
        )

    async def _sender(self) -> None:
        """Drain captured audio and append it to the realtime buffer."""
        chunks = 0
        total = 0
        try:
            while True:
                data = await self._audio_q.get()
                if data is None:  # sentinel = stop
                    break
                chunks += 1
                total += len(data)
                await self._ws.send(json.dumps({
                    "type": _EVT_AUDIO_APPEND,
                    "audio": base64.b64encode(data).decode("ascii"),
                }))
        except Exception as e:
            logger.warning("Realtime audio sender stopped: %s", e)
        finally:
            logger.info("Realtime: sent %d audio chunks (%d bytes)", chunks, total)

    async def stop_and_transcribe(self, timeout: float = 20.0) -> str:
        """Stop the mic, commit the buffer, and return the final transcript."""
        self._active = False
        if self._mic is not None:
            try:
                self._mic.stop()
                self._mic.close()
            except Exception:
                pass
            self._mic = None
        if self._audio_q is not None:
            self._audio_q.put_nowait(None)  # release the sender
        if self._sender_task is not None:
            try:
                await self._sender_task
            except Exception:
                pass

        try:
            await self._ws.send(json.dumps({"type": _EVT_AUDIO_COMMIT}))
            transcript = await asyncio.wait_for(self._read_until_complete(), timeout)
        except RealtimeUnavailable:
            raise
        except Exception as e:
            raise RealtimeUnavailable(f"Realtime transcribe failed: {e}") from e
        finally:
            await self.close()
        return transcript.strip()

    async def _read_until_complete(self) -> str:
        async for raw in self._ws:
            try:
                event = json.loads(raw)
            except Exception:
                continue
            etype = event.get("type", "")
            logger.info("Realtime event: %s", etype)  # verbose for debugging
            if etype.endswith(_SUFFIX_DELTA):
                self._transcript_parts.append(event.get("delta", ""))
            elif etype.endswith(_SUFFIX_COMPLETED):
                transcript = event.get("transcript") or "".join(self._transcript_parts)
                logger.info("Realtime completed transcript: %r", transcript)
                return transcript
            elif etype == "error":
                msg = event.get("error", {}).get("message", "unknown error")
                logger.error("Realtime error event: %s", json.dumps(event)[:500])
                raise RealtimeUnavailable(f"Realtime server error: {msg}")
        return "".join(self._transcript_parts)

    async def close(self) -> None:
        self._active = False
        if self._mic is not None:
            try:
                self._mic.stop()
                self._mic.close()
            except Exception:
                pass
            self._mic = None
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
