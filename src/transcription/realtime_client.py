"""Experimental: OpenAI Realtime API transcription — transcribe WHILE speaking.

Opt-in via config `transcription_realtime`. Streams microphone audio over a
WebSocket so the transcript is essentially ready the moment the hotkey is
released, instead of being uploaded and transcribed afterwards.

Requires the optional dependency:  pip install -e ".[realtime]"

Key design points:
  * The mic starts SYNCHRONOUSLY the instant recording begins, and every frame
    is appended to a shared buffer from frame zero — so the start of speech is
    never clipped, even while the WebSocket is still connecting.
  * The WebSocket runs on its OWN asyncio loop in a background thread, isolated
    from qasync (whose DNS resolution is unreliable on Windows).
  * The session streams the WHOLE buffer (index 0 onward), so audio captured
    before/during connect is still sent.
  * On ANY realtime failure the captured audio is transcribed via the standard
    cloud path (WhisperClient) — a dictation is never lost.
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

    def __init__(self, on_caption=None) -> None:
        config = Config()
        model = config.whisper_model
        self._model = model if "transcribe" in model else "gpt-4o-transcribe"
        self._on_caption = on_caption        # callable(str) — live partial text (best-effort)
        self._mic: sd.InputStream | None = None
        self._pcm_buffer: list[bytes] = []   # ALL captured frames (shared, append-only)
        self._active = False
        self._stop = False
        self._thread: threading.Thread | None = None
        self._result: Future = Future()      # worker sets: transcript str or None
        self.used_fallback = False            # True if we dropped to batch transcription

    def start(self) -> None:
        """Start capturing IMMEDIATELY (sync) and spin up the realtime session.

        Synchronous so the mic begins the instant the hotkey is pressed — no
        opening words are lost while the WebSocket connects.
        """
        self._pcm_buffer = []
        self._result = Future()
        self._stop = False
        self.used_fallback = False

        def _cb(indata, frames, time_info, status) -> None:
            if self._active:
                self._pcm_buffer.append(
                    (np.clip(indata[:, 0], -1.0, 1.0) * 32767).astype("<i2").tobytes()
                )

        self._active = True
        self._mic = sd.InputStream(
            samplerate=_SAMPLE_RATE, channels=1, dtype="float32", callback=_cb
        )
        self._mic.start()

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
            # Server VAD so the API transcribes WHILE speaking (for live captions);
            # we accumulate every finalized segment for the full transcript.
            # Shorter silence_duration_ms = segments close on shorter pauses =
            # more frequent / less-laggy captions (config-tunable).
            silence_ms = int(Config().realtime_vad_silence_ms)
            await ws.send(json.dumps({
                "type": _EVT_SESSION_UPDATE,
                "session": {
                    "type": "transcription",
                    "audio": {
                        "input": {
                            "format": {"type": "audio/pcm", "rate": _SAMPLE_RATE},
                            "transcription": {"model": self._model, "language": "en"},
                            "turn_detection": {
                                "type": "server_vad",
                                "threshold": 0.5,
                                "prefix_padding_ms": 200,
                                "silence_duration_ms": silence_ms,
                            },
                        },
                    },
                },
            }))
            logger.info("Realtime transcription started (model=%s)", self._model)

            loop = asyncio.get_running_loop()
            finalized: list[str] = []
            partial = ""
            sent = 0
            deltas = 0
            stop_at = 0.0
            last_event = loop.time()
            hard_deadline = loop.time() + 600.0

            while True:
                # Stream newly-captured audio (server VAD transcribes it live).
                sent = await self._flush_from(ws, sent)

                # On release: send the tail. Do NOT commit — server VAD already
                # consumes the buffer, so a manual commit hits an empty buffer.
                if self._stop and stop_at == 0.0:
                    sent = await self._flush_from(ws, sent)
                    stop_at = loop.time()
                    last_event = loop.time()

                # Poll for one event.
                raw = None
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=0.05)
                except asyncio.TimeoutError:
                    pass
                except Exception:
                    break  # connection closed

                if raw:
                    try:
                        event = json.loads(raw)
                    except Exception:
                        event = None
                    if event:
                        etype = event.get("type", "")
                        if etype.endswith(_SUFFIX_DELTA):
                            deltas += 1
                            partial += event.get("delta", "")
                            last_event = loop.time()
                            self._emit_caption((" ".join(finalized) + " " + partial).strip())
                        elif etype.endswith(_SUFFIX_COMPLETED):
                            seg = (event.get("transcript") or partial).strip()
                            if seg:
                                finalized.append(seg)
                            partial = ""
                            last_event = loop.time()
                            self._emit_caption(" ".join(finalized).strip())
                        elif etype == "error":
                            logger.warning("Realtime error event: %s",
                                           event.get("error", {}).get("message", "?"))

                # After release: finish once transcripts go quiet (or a hard cap).
                if stop_at:
                    now = loop.time()
                    if now - last_event > 0.8 or now - stop_at > 3.0:
                        break
                if loop.time() > hard_deadline:
                    break

            transcript = (" ".join(finalized) + " " + partial).strip()
            logger.info("Realtime: %d delta(s), %d segment(s), %d chars",
                        deltas, len(finalized), len(transcript))
            self._result.set_result(transcript or None)
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

    async def _flush_from(self, ws, sent: int) -> int:
        buf = self._pcm_buffer
        while sent < len(buf):
            await ws.send(json.dumps({
                "type": _EVT_AUDIO_APPEND,
                "audio": base64.b64encode(buf[sent]).decode("ascii"),
            }))
            sent += 1
        return sent

    def _emit_caption(self, text: str) -> None:
        cb = self._on_caption
        if cb:
            try:
                cb(text)
            except Exception:
                pass

    async def stop_and_transcribe(self, timeout: float = 25.0) -> str:
        """Stop the mic, finish the session, and return the transcript or fallback."""
        self._active = False
        self._stop = True
        if self._mic is not None:
            try:
                self._mic.stop()
                self._mic.close()
            except Exception:
                pass
            self._mic = None

        transcript = None
        try:
            transcript = await asyncio.wait_for(asyncio.wrap_future(self._result), timeout)
        except Exception as e:
            logger.warning("Realtime result unavailable (%s); using batch fallback", e)

        if transcript:
            return transcript
        return await self._fallback_batch()

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
        self.used_fallback = True
        wav = self._wav_from_buffer()
        if wav is None:
            logger.error("Realtime fallback: no audio captured")
            return ""
        logger.info("Realtime fallback: batch-transcribing %d captured chunks",
                    len(self._pcm_buffer))
        from src.transcription.whisper_client import WhisperClient
        text = await WhisperClient().transcribe(wav)
        return text.strip()

    def close(self) -> None:
        """Stop capturing and signal the worker to wind down (sync)."""
        self._active = False
        self._stop = True
        if self._mic is not None:
            try:
                self._mic.stop()
                self._mic.close()
            except Exception:
                pass
            self._mic = None
