"""Experimental: OpenAI Realtime API transcription — transcribe WHILE speaking.

Opt-in via config `transcription_realtime`. Streams microphone audio over a
WebSocket so the transcript is essentially ready the moment the hotkey is
released, instead of being uploaded and transcribed afterwards.

Requires the optional dependency:  pip install -e ".[realtime]"

Design — realtime can NEVER lose a dictation:
  * The microphone starts capturing immediately and every frame is kept in a
    local buffer, regardless of WebSocket state.
  * The WebSocket connect is attempted (with one retry) but never fatal.
  * On ANY realtime failure (connect, protocol, empty result), we transcribe
    the captured audio via the standard cloud path (WhisperClient), which uses
    the SDK's reliable DNS resolution.

⚠️ EXPERIMENTAL: the exact Realtime event strings are centralised below so they
can be adjusted against OpenAI's live docs without hunting through the logic.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging

import numpy as np
import sounddevice as sd
from scipy.io.wavfile import write as wav_write

from src.config import Config

logger = logging.getLogger("speakup")

_REALTIME_URL = "wss://api.openai.com/v1/realtime?intent=transcription"
_SAMPLE_RATE = 24000  # OpenAI Realtime expects 24 kHz PCM16 mono

# Event type strings (centralised for easy adjustment against live docs).
_EVT_SESSION_UPDATE = "session.update"  # GA shape (beta used transcription_session.update)
_EVT_AUDIO_APPEND = "input_audio_buffer.append"
_EVT_AUDIO_COMMIT = "input_audio_buffer.commit"
_SUFFIX_DELTA = "input_audio_transcription.delta"
_SUFFIX_COMPLETED = "input_audio_transcription.completed"


async def _ws_connect(url: str, headers: dict):
    """Open a websocket, tolerating the header-kwarg rename across versions."""
    import websockets

    try:
        return await websockets.connect(url, additional_headers=headers, max_size=None)
    except TypeError:
        # Older websockets releases use `extra_headers`.
        return await websockets.connect(url, extra_headers=headers, max_size=None)


class RealtimeTranscriber:
    """Streams mic audio to the OpenAI Realtime API; falls back to batch on failure."""

    def __init__(self) -> None:
        config = Config()
        model = config.whisper_model
        self._model = model if "transcribe" in model else "gpt-4o-transcribe"
        self._vocab = config.custom_vocabulary
        self._ws = None
        self._mic: sd.InputStream | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._audio_q: asyncio.Queue | None = None
        self._sender_task: asyncio.Future | None = None
        self._transcript_parts: list[str] = []
        self._pcm_buffer: list[bytes] = []  # local copy for batch fallback
        self._active = False
        self._connected = False

    async def start(self) -> None:
        """Start capturing immediately, then try to connect (never fatal)."""
        self._loop = asyncio.get_event_loop()
        self._audio_q = asyncio.Queue()
        self._transcript_parts = []
        self._pcm_buffer = []
        self._connected = False

        # 1. Start the mic FIRST so audio is captured no matter what the WS does.
        def _cb(indata, frames, time_info, status) -> None:
            if not self._active or self._loop is None:
                return
            pcm16 = (np.clip(indata[:, 0], -1.0, 1.0) * 32767).astype("<i2").tobytes()
            self._pcm_buffer.append(pcm16)            # always kept for fallback
            self._loop.call_soon_threadsafe(self._audio_q.put_nowait, pcm16)

        self._active = True
        self._mic = sd.InputStream(
            samplerate=_SAMPLE_RATE, channels=1, dtype="float32", callback=_cb
        )
        self._mic.start()

        # 2. Try to connect the realtime WS (one retry for transient DNS blips).
        for attempt in range(2):
            try:
                # Read the key here so a missing key falls back to batch cleanly.
                headers = {"Authorization": f"Bearer {Config().openai_api_key}"}
                self._ws = await _ws_connect(_REALTIME_URL, headers)
                await self._ws.send(json.dumps({
                    "type": _EVT_SESSION_UPDATE,
                    "session": {
                        "type": "transcription",
                        "audio": {
                            "input": {
                                "format": {"type": "audio/pcm", "rate": _SAMPLE_RATE},
                                "transcription": {"model": self._model, "language": "en"},
                                "turn_detection": None,  # push-to-talk: one segment
                            },
                        },
                    },
                }))
                self._connected = True
                self._sender_task = asyncio.ensure_future(self._sender())
                logger.info("Realtime transcription started (model=%s, rate=%d)",
                            self._model, int(self._mic.samplerate))
                return
            except Exception as e:
                if attempt == 0:
                    logger.warning("Realtime connect attempt failed (%s); retrying", e)
                    await asyncio.sleep(0.4)
                    continue
                logger.warning(
                    "Realtime unavailable (%s); capturing locally for batch fallback", e
                )
                self._connected = False
                self._ws = None

    async def _sender(self) -> None:
        """Drain captured audio and append it to the realtime buffer."""
        chunks = 0
        try:
            while True:
                data = await self._audio_q.get()
                if data is None:  # sentinel = stop
                    break
                chunks += 1
                await self._ws.send(json.dumps({
                    "type": _EVT_AUDIO_APPEND,
                    "audio": base64.b64encode(data).decode("ascii"),
                }))
        except Exception as e:
            logger.warning("Realtime audio sender stopped: %s", e)
        finally:
            logger.info("Realtime: sent %d audio chunks", chunks)

    async def stop_and_transcribe(self, timeout: float = 20.0) -> str:
        """Stop the mic; return the realtime transcript, or batch-fallback text."""
        self._active = False
        if self._mic is not None:
            try:
                self._mic.stop()
                self._mic.close()
            except Exception:
                pass
            self._mic = None

        # Try the live path if we ever connected.
        if self._connected and self._ws is not None:
            try:
                if self._audio_q is not None:
                    self._audio_q.put_nowait(None)
                if self._sender_task is not None:
                    await self._sender_task
                await self._ws.send(json.dumps({"type": _EVT_AUDIO_COMMIT}))
                transcript = await asyncio.wait_for(self._read_until_complete(), timeout)
                if transcript.strip():
                    return transcript.strip()
                logger.warning("Realtime returned empty transcript; using batch fallback")
            except Exception as e:
                logger.warning("Realtime transcribe failed (%s); using batch fallback", e)
            finally:
                await self.close()

        # Fallback: transcribe the locally-captured audio via the standard path.
        return await self._fallback_batch()

    async def _read_until_complete(self) -> str:
        async for raw in self._ws:
            try:
                event = json.loads(raw)
            except Exception:
                continue
            etype = event.get("type", "")
            if etype.endswith(_SUFFIX_DELTA):
                self._transcript_parts.append(event.get("delta", ""))
            elif etype.endswith(_SUFFIX_COMPLETED):
                return event.get("transcript") or "".join(self._transcript_parts)
            elif etype == "error":
                msg = event.get("error", {}).get("message", "unknown error")
                raise RuntimeError(f"Realtime server error: {msg}")
        return "".join(self._transcript_parts)

    def _wav_from_buffer(self) -> io.BytesIO | None:
        """Build an in-memory WAV from the captured PCM16 frames."""
        if not self._pcm_buffer:
            return None
        arr = np.frombuffer(b"".join(self._pcm_buffer), dtype="<i2")
        buf = io.BytesIO()
        wav_write(buf, _SAMPLE_RATE, arr)
        buf.seek(0)
        buf.name = "recording.wav"
        return buf

    async def _fallback_batch(self) -> str:
        """Transcribe the captured audio with the reliable cloud path."""
        wav = self._wav_from_buffer()
        if wav is None:
            logger.error("Realtime fallback: no audio captured")
            return ""
        logger.info("Realtime fallback: batch-transcribing %d captured chunks",
                    len(self._pcm_buffer))
        from src.transcription.whisper_client import WhisperClient
        text = await WhisperClient().transcribe(wav)
        return text.strip()

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
        self._connected = False
