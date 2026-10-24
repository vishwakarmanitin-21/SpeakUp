"""Live transcription via Deepgram streaming — true word-by-word captions.

Deepgram's streaming API emits interim (partial) results as you speak, giving
the smooth live-caption experience OpenAI's segment-based transcription can't.
Used for the live path when DEEPGRAM_API_KEY is set; OpenAI still does the
rewrite. Falls back to OpenAI batch transcription on any failure.

Same interface as RealtimeTranscriber (start / stop_and_transcribe / close), so
the pipeline can use either interchangeably.

Requires the 'realtime' extra (websockets):  pip install -e ".[realtime]"
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import threading
import time
import urllib.parse
from concurrent.futures import Future

import numpy as np
import sounddevice as sd
from scipy.io.wavfile import write as wav_write

from src.config import Config

logger = logging.getLogger("speakup")

_SAMPLE_RATE = 16000  # Deepgram streams linear16 PCM; 16 kHz is plenty
_DG_PARAMS = {
    # nova-3 measurably beats nova-2 on this user's real voice: 13/13 dictionary
    # terms vs 12/13, and 11.6% vs 16.3% word error rate (verified at the 16 kHz
    # this client streams). It also takes richer term biasing — see _build_url.
    "model": "nova-3",
    "language": "en",
    "encoding": "linear16",
    "sample_rate": str(_SAMPLE_RATE),
    "channels": "1",
    "interim_results": "true",
    "smart_format": "true",
    "punctuate": "true",
}
_DG_HOSTS = ("api.deepgram.com", "api.eu.deepgram.com")
_DG_URL = "wss://{host}/v1/listen?"
# Chosen once per run by _probe_hosts(); until then the US default.
_dg_host = _DG_HOSTS[0]
_probe_started = False
_KEYWORD_BOOST = 2    # nova-2 default is 1; higher raises false positives
_MAX_KEYWORDS = 100   # Deepgram's per-request limit


def _build_url() -> str:
    """Build the listen URL, boosting the user's personal-dictionary terms.

    Without this the transcriber has never heard of "Vestora" or "WealQuest" and
    reliably mangles them — the dictionary was only reaching the rewrite step,
    which is too late to recover a badly mis-heard name. nova-2 takes repeated
    `keywords=TERM:INTENSIFIER` params.
    """
    params: list[tuple[str, str]] = list(_DG_PARAMS.items())
    try:
        from src.services.phonetic import _is_ordinary_word

        terms: list[str] = []
        for term in Config().custom_vocabulary:
            term = (term or "").strip()
            # Boosting everyday words ("Order", "Additionally") raises false
            # positives — Deepgram's own guidance — so only boost real names.
            if not term or _is_ordinary_word(term):
                continue
            # Boost the whole term, plus its distinctive parts if multi-word,
            # so "Wealducate Ecosystem" helps even when only one word is spoken.
            for piece in [term] + (term.split() if " " in term else []):
                piece = piece.strip()
                if len(piece) >= 3 and piece not in terms:
                    terms.append(piece)
        # nova-3 replaced weighted `keywords` with plain `keyterm` (no
        # intensifiers). Sending the wrong one silently loses all biasing —
        # Deepgram returns 200 for unknown parameters — and biasing is what
        # makes the difference here: without the dictionary nova-3 dropped from
        # 13/13 terms to 7/13.
        keyterm_style = str(_DG_PARAMS.get("model", "")).startswith("nova-3")
        for term in terms[:_MAX_KEYWORDS]:
            if keyterm_style:
                params.append(("keyterm", term))
            else:
                params.append(("keywords", f"{term}:{_KEYWORD_BOOST}"))
        if terms:
            logger.info("Deepgram: boosting %d dictionary term(s) via %s",
                        len(terms[:_MAX_KEYWORDS]),
                        "keyterm" if keyterm_style else "keywords")
    except Exception as e:  # a bad dictionary must never stop transcription
        logger.debug("Could not add dictionary keywords: %s", e)
    return _DG_URL.format(host=_dg_host) + urllib.parse.urlencode(params)


def _tcp_connect_ms(host: str, tries: int = 2) -> float:
    import socket

    best = float("inf")
    for _ in range(tries):
        t = time.monotonic()
        try:
            socket.create_connection((host, 443), timeout=3).close()
        except OSError:
            continue
        best = min(best, (time.monotonic() - t) * 1000)
    return best


def _probe_hosts() -> None:
    """Pick the closer Deepgram endpoint (US or EU) for this run.

    Opening the live-caption socket costs ~4 network round trips before any
    words come back. From India (2026-10-24) a round trip is ~305 ms to the
    US endpoint and ~165 ms to the EU one: the socket opened ~0.4 s sooner
    on EU with an identical transcript. Deepgram's EU endpoint takes the
    same keys and billing. Measured, not assumed, so it suits anyone.
    """
    global _dg_host
    timings = {h: _tcp_connect_ms(h) for h in _DG_HOSTS}
    best = min(timings, key=timings.get)
    if timings[best] != float("inf"):
        _dg_host = best
    logger.info("Deepgram endpoint: %s (%s)", _dg_host,
                ", ".join(f"{h} {t:.0f} ms" for h, t in timings.items()))


def start_endpoint_probe() -> None:
    """Run _probe_hosts() once, in the background (never on the hotkey path)."""
    global _probe_started
    if _probe_started:
        return
    _probe_started = True
    threading.Thread(target=_probe_hosts, daemon=True, name="dg-probe").start()


async def _ws_connect(url: str, headers: dict):
    import websockets

    try:
        return await websockets.connect(url, additional_headers=headers, max_size=None)
    except TypeError:
        return await websockets.connect(url, extra_headers=headers, max_size=None)


class DeepgramTranscriber:
    """Streams mic audio to Deepgram for live word-by-word captions + final text."""

    def __init__(self, on_caption=None) -> None:
        self._on_caption = on_caption
        self._mic: sd.InputStream | None = None
        self._pcm_buffer: list[bytes] = []
        self._active = False
        self._stop = False
        self._thread: threading.Thread | None = None
        self._result: Future = Future()
        self.used_fallback = False  # True if we dropped to batch transcription
        self.live_failed = False    # True ONLY when the live session errored/couldn't connect

    def start(self) -> None:
        """Start capturing immediately (sync) and open the Deepgram stream."""
        self._pcm_buffer = []
        self._result = Future()
        self._stop = False
        self.used_fallback = False
        self.live_failed = False

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
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            asyncio.run(self._session())
        except Exception as e:  # pragma: no cover
            logger.warning("Deepgram session thread error: %s", e)
        finally:
            if not self._result.done():
                self._result.set_result(None)

    async def _session(self) -> None:
        ws = None
        try:
            # Retry connect — the first DNS lookup of a fresh host on Windows's
            # threaded event loop intermittently fails with getaddrinfo; a retry
            # after the resolver warms up succeeds (same fix as the OpenAI path).
            key = Config().deepgram_api_key
            headers = {"Authorization": f"Token {key}"}
            for attempt in range(3):
                try:
                    ws = await _ws_connect(_build_url(), headers)
                    break
                except Exception as e:
                    if attempt < 2:
                        logger.warning("Deepgram connect failed (%s); retrying", e)
                        await asyncio.sleep(0.5)
                        continue
                    raise
            logger.info("Deepgram live transcription started")

            loop = asyncio.get_running_loop()
            finals: list[str] = []
            interim = ""
            sent = 0
            stop_at = 0.0
            closed = False
            last_event = loop.time()
            hard_deadline = loop.time() + 600.0

            while True:
                # Stream newly-captured audio as binary frames (from frame 0).
                buf = self._pcm_buffer
                while sent < len(buf):
                    await ws.send(buf[sent])
                    sent += 1

                # On release: flush the tail, then tell Deepgram to finalize.
                if self._stop and not closed:
                    while sent < len(buf):
                        await ws.send(buf[sent])
                        sent += 1
                    try:
                        await ws.send(json.dumps({"type": "CloseStream"}))
                    except Exception:
                        pass
                    closed = True
                    stop_at = loop.time()
                    last_event = loop.time()

                # Poll for one message.
                raw = None
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=0.05)
                except asyncio.TimeoutError:
                    pass
                except Exception:
                    break

                if raw:
                    try:
                        msg = json.loads(raw)
                    except Exception:
                        msg = None
                    if msg and msg.get("type") == "Results":
                        alts = msg.get("channel", {}).get("alternatives") or [{}]
                        t = (alts[0].get("transcript") or "").strip()
                        if t:
                            last_event = loop.time()
                            if msg.get("is_final"):
                                # Guard against a duplicate final segment being
                                # emitted twice (would repeat a phrase in output).
                                if not finals or finals[-1] != t:
                                    finals.append(t)
                                interim = ""
                            else:
                                interim = t
                            self._emit_caption((" ".join(finals) + " " + interim).strip())

                if closed:
                    now = loop.time()
                    if now - last_event > 0.8 or now - stop_at > 3.0:
                        break
                if loop.time() > hard_deadline:
                    break

            transcript = (" ".join(finals) + " " + interim).strip()
            logger.info("Deepgram: %d final segment(s), %d chars", len(finals), len(transcript))
            self._result.set_result(transcript or None)
        except Exception as e:
            self.live_failed = True
            logger.warning("Deepgram session failed (%s); using batch fallback", e)
            if not self._result.done():
                self._result.set_result(None)
        finally:
            if ws is not None:
                try:
                    await ws.close()
                except Exception:
                    pass

    def _emit_caption(self, text: str) -> None:
        cb = self._on_caption
        if cb:
            try:
                cb(text)
            except Exception:
                pass

    async def stop_and_transcribe(self, timeout: float = 25.0) -> str:
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
            logger.warning("Deepgram result unavailable (%s); using batch fallback", e)

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
        self.used_fallback = True
        wav = self._wav_from_buffer()
        if wav is None:
            logger.error("Deepgram fallback: no audio captured")
            return ""
        logger.info("Deepgram fallback: batch-transcribing %d captured chunks",
                    len(self._pcm_buffer))
        from src.transcription.whisper_client import WhisperClient
        text = await WhisperClient().transcribe(wav)
        return text.strip()

    def close(self) -> None:
        self._active = False
        self._stop = True
        if self._mic is not None:
            try:
                self._mic.stop()
                self._mic.close()
            except Exception:
                pass
            self._mic = None
