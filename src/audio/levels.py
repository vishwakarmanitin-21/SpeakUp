"""How loud a recording was — so a too-quiet or wrong microphone is visible.

Live captions silently returned nothing for 4 of 4 dictations on 2026-11-05
while the batch fallback still found words in the same audio, which points at
a quiet signal; but SpeakUp logged no level and no device, so it couldn't be
told apart from a network or service problem.
"""
from __future__ import annotations

import math

import numpy as np

# Peak below this (dBFS) means the speech was barely captured. Normal speech
# at a working mic peaks around -10..-3 dBFS; conservative on purpose.
QUIET_PEAK_DBFS = -30.0


def _dbfs(x: float) -> float:
    return 20 * math.log10(x) if x > 0 else -120.0


def pcm16_levels(chunks: list[bytes]) -> tuple[float, float]:
    """(peak dBFS, speech RMS dBFS) of 16-bit PCM chunks.

    The RMS is over the loudest 20% of 50 ms frames, i.e. the speech, so a
    long pause doesn't make a normal recording look quiet.
    """
    if not chunks:
        return -120.0, -120.0
    a = np.frombuffer(b"".join(chunks), dtype="<i2").astype(np.float32) / 32768.0
    if not a.size:
        return -120.0, -120.0
    peak = float(np.max(np.abs(a)))
    frame = 800  # 50 ms at 16 kHz
    n = a.size // frame
    if n == 0:
        return _dbfs(peak), _dbfs(float(np.sqrt(np.mean(a ** 2))))
    rms = np.sqrt(np.mean(a[: n * frame].reshape(n, frame) ** 2, axis=1))
    top = np.sort(rms)[-max(1, n // 5):]
    return _dbfs(peak), _dbfs(float(np.mean(top)))


def input_device_name() -> str:
    """The mic a recording actually used (the chosen one, else the default)."""
    from src.audio.devices import active_input_name
    return active_input_name()
