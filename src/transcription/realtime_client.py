"""Experimental: OpenAI Realtime API transcription — transcribe WHILE speaking.

Opt-in via config `transcription_realtime`. Streams microphone audio over a
WebSocket so the transcript is essentially ready the moment the hotkey is
released, instead of being uploaded and transcribed afterwards.

Requires the optional dependency:  pip install -e ".[realtime]"

Why a dedicated thread + loop:
  The WebSocket runs on its OWN asyncio event loop in a background thread,
  isolated from qasync. qasync's event loop resolves DNS unreliably on Windows
  (intermittent `getaddrinfo failed`), which made live mode fall back to batch.
  A clean asyncio loop resolves DNS normally, so live mode actually connects.

Resilience — realtime can NEVER lose a dictation:
  * The microphone starts capturing immediately; every frame is kept in a local
    buffer regardless of WebSocket state.
  * Connect is attempted (with one retry) but never fatal.
  * On ANY realtime failure (connect, protocol, timeout, empty result) the
    captured audio is transcribed via the standard cloud path (WhisperClient).
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import threading
from concurrent.futures import Future

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
    """Streams mic audio to the OpenAI Realtime API on its own thread/loop."""

    def __init__(self) -> None:
        config = Config()
        model = config.whisper_model
        self._model = model if "transcribe" in model else "gpt-4o-transcribe"
        self._mic: sd.InputStream | None = None
        self._pcm_buffer: list[bytes] = []          # local copy for batch fallback
        self._active = False
        # Cross-thread coordination with the realtime worker loop.
        self._worker_loop: asyncio.AbstractEventLoop | None = None
        self._aq: asyncio.Queue | None = None
        self._thread: threading.Thread | None = None
        self._result: Future = Future()             # worker sets: transcript str or None

    async def start(self) -> None:
        """Start mic capture and the background realtime session (non-blocking)."""
        self._pcm_buffer = []
        self._result = Future()
        self._worker_loop = None
        self._aq = None

        # Mic capture runs on a PortAudio thread. Always buffer; also hand frames
        # to the worker loop once it exists.
        def _cb(indata, frames, time_info, status) -> None:
            if not self._active:
                return
            pcm16 = (np.clip(indata[:, 0], -1.0, 1.0) * 32767).astype("<i2").tobytes()
            self._pcm_buffer.append(pcm16)
            loop, aq = self._worker_loop, self._aq
            if loop is not None and aq is not None:
                try:
                    loop.call_soon_threadsafe(aq.put_nowait, pcm16)
                except RuntimeError:
                    pass  # worker loop already closed

        self._active = True
        self._mic = sd.InputStream(
            samplerate=_SAMPLE_RATE, channels=1, dtype="float32", callback=_cb
        )
        self._mic.start()

        # Run the realtime session on a dedicated thread with a clean asyncio loop.
        self._thread = threading.Thread(target=self._run_session, daemon=True)
        self._thread.start()

    def _run_session(self) -> None:
        try:
            asyncio.run(self._session())
        except Exception as e:  # pragma: no cover - thread/loop edge cases
            logger.warning("Realtime session thread error: %s", e)
        finally:
            if not self._result.done():
                self._result.set_result(None)

    async def _session(self) -> None:
        self._worker_loop = asyncio.get_running_loop()
        self._aq = asyncio.Queue()
        ws = None
        try:
            for attempt in range(2):
                try:
                    headers = {"Authorization": f"Bearer {Config().openai_api_key}"}
                    ws = await _ws_connect(_REALTIME_URL, headers)
                    break
                except Exception as e:
                    if attempt == 0:
                        logger.warning("Realtime connect failed (%s); retrying", e)
                        await asyncio.sleep(0.4)
                        continue
                    raise
            await ws.send(json.dumps({
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
            logger.info("Realtime transcription started (model=%s)", self._model)

            # Stream audio until the main thread signals stop (None sentinel).
            sent = 0
            while True:
                data = await self._aq.get()
                if data is None:
                    break
                sent += 1
                await ws.send(json.dumps({
                    "type": _EVT_AUDIO_APPEND,
                    "audio": base64.b64encode(data).decode("ascii"),
                }))
            logger.info("Realtime: sent %d audio chunks", sent)

            await ws.send(json.dumps({"type": _EVT_AUDIO_COMMIT}))
            transcript = await asyncio.wait_for(self._read_until_complete(ws), 20.0)
            self._result.set_result(transcript.strip() or None)
        except Exception as e:
            logger.warning("Realtime session failed (%s); using batch fallback", e)
            if not self._result.done():
                self._result.set_result(None)
        finally:
            if ws is not None:
                try:
                    await ws.close()
                except Exception:
                    pass

    @staticmethod
    async def _read_until_complete(ws) -> str:
        parts: list[str] = []
        async for raw in ws:
            try:
                event = json.loads(raw)
            except Exception:
                continue
            etype = event.get("type", "")
            if etype.endswith(_SUFFIX_DELTA):
                parts.append(event.get("delta", ""))
            elif etype.endswith(_SUFFIX_COMPLETED):
                return event.get("transcript") or "".join(parts)
            elif etype == "error":
                raise RuntimeError(event.get("error", {}).get("message", "realtime error"))
        return "".join(parts)

    async def stop_and_transcribe(self, timeout: float = 25.0) -> str:
        """Stop the mic, finish the session, and return the transcript or fallback."""
        self._active = False
        if self._mic is not None:
            try:
                self._mic.stop()
                self._mic.close()
            except Exception:
                pass
            self._mic = None

        # Tell the worker loop to stop streaming and commit.
        self._signal_stop()

        # Await the worker's result from the qasync loop without blocking it.
        transcript = None
        try:
            transcript = await asyncio.wait_for(asyncio.wrap_future(self._result), timeout)
        except Exception as e:
            logger.warning("Realtime result unavailable (%s); using batch fallback", e)

        if transcript:
            return transcript
        return await self._fallback_batch()

    def _signal_stop(self) -> None:
        loop, aq = self._worker_loop, self._aq
        if loop is not None and aq is not None:
            try:
                loop.call_soon_threadsafe(aq.put_nowait, None)
            except RuntimeError:
                pass

    def _wav_from_buffer(self) -> io.BytesIO | None:
        if not self._pcm_buffer:
            return None
        arr = np.frombuffer(b"".join(self._pcm_buffer), dtype="<i2")
        buf = io.BytesIO()
        wav_write(buf, _SAMPLE_RATE, arr)
        buf.seek(0)
        buf.name = "recording.wav"
        return buf

    async def _fallback_batch(self) -> str:
        """Transcribe the locally-captured audio via the reliable cloud path."""
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
        self._signal_stop()
