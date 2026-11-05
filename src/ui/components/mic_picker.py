"""Microphone chooser with a live level bar and a plain-words verdict.

SpeakUp used to record from whatever Windows called the default mic. On
2026-11-05 that was a USB mic delivering digital silence and every dictation
failed with nothing on screen to say why. This shows which mic is used and
whether it actually hears you, before you dictate.
"""
from __future__ import annotations

import logging
import math
import threading

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QComboBox, QLabel, QProgressBar, QVBoxLayout, QWidget

logger = logging.getLogger("speakup")

# Loudest-point thresholds (dBFS) for the verdict. A muted mic measured -84;
# a live built-in mic idles around -50 and speech peaks around -20..-5.
_SILENT_DBFS = -60.0
_QUIET_DBFS = -35.0


class MicPicker(QWidget):
    """Combo of input devices + level bar. Call start() / stop() around use."""

    def __init__(self, current: str = "", parent=None) -> None:
        super().__init__(parent)
        self._stream = None
        self._lock = threading.Lock()
        self._peak = 0.0          # loudest sample since the last UI tick
        self._recent_max = -120.0  # loudest dBFS over the last ~2 s, for the verdict
        self._ticks = 0

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.combo = QComboBox()
        # Long device names must not widen the whole Settings dialog.
        self.combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.combo.setMinimumContentsLength(24)
        self.combo.setToolTip(
            "The microphone SpeakUp records from. 'Windows default' follows\n"
            "whatever Windows Sound settings choose; picking one here keeps\n"
            "SpeakUp on that mic even if Windows switches."
        )
        lay.addWidget(self.combo)
        self.meter = QProgressBar()
        self.meter.setRange(0, 100)
        self.meter.setTextVisible(False)
        self.meter.setMaximumHeight(10)
        lay.addWidget(self.meter)
        self.verdict = QLabel("")
        self.verdict.setWordWrap(True)
        lay.addWidget(self.verdict)

        self._timer = QTimer(self)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._tick)
        self._populate(current)
        self.combo.currentIndexChanged.connect(lambda _i: self._restart())

    # --- Devices ---

    def _populate(self, current: str) -> None:
        from src.audio.devices import default_input_name, list_input_devices

        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem(f"Windows default ({default_input_name()})", "")
        names = list_input_devices()
        for name in names:
            self.combo.addItem(name, name)
        if current and current not in names:
            # Remember a chosen mic that's unplugged right now, rather than
            # silently dropping the choice.
            self.combo.addItem(f"{current} (not connected)", current)
        idx = self.combo.findData(current)
        self.combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.combo.blockSignals(False)

    def selected_name(self) -> str:
        """'' for the Windows default, else the device name to save."""
        return self.combo.currentData() or ""

    # --- Live level ---

    def start(self) -> None:
        self._restart()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self._close_stream()
        self.meter.setValue(0)

    def _close_stream(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

    def _restart(self) -> None:
        self._close_stream()
        self._recent_max = -120.0
        self._ticks = 0
        try:
            import numpy as np
            import sounddevice as sd

            from src.audio.devices import resolve_input_device

            device = resolve_input_device(self.selected_name()) if self.selected_name() else None

            def _cb(indata, frames, time_info, status):
                peak = float(np.max(np.abs(indata[:, 0]))) if frames else 0.0
                with self._lock:
                    self._peak = max(self._peak, peak)

            self._stream = sd.InputStream(
                samplerate=16000, channels=1, dtype="float32", device=device, callback=_cb
            )
            self._stream.start()
            self.verdict.setText("Listening… say something.")
        except Exception as e:
            logger.info("Mic picker could not open the microphone: %s", e)
            self.verdict.setText("Couldn't open this microphone — pick another one.")

    def _tick(self) -> None:
        with self._lock:
            peak, self._peak = self._peak, 0.0
        db = 20 * math.log10(peak) if peak > 0 else -120.0
        # -60..0 dBFS across the bar, so a muted mic sits at zero.
        self.meter.setValue(int(max(0.0, min(1.0, (db + 60) / 60)) * 100))
        self._recent_max = max(self._recent_max, db)
        self._ticks += 1
        if self._stream is not None and self._ticks % 33 == 0:  # every ~2 s
            self.verdict.setText(self.verdict_for(self._recent_max))
            self._recent_max = -120.0

    @staticmethod
    def verdict_for(peak_dbfs: float) -> str:
        if peak_dbfs < _SILENT_DBFS:
            return ("Silent — this mic isn't hearing anything. Check it isn't muted, "
                    "raise its input volume in Windows Sound settings, or pick another mic.")
        if peak_dbfs < _QUIET_DBFS:
            return "Very quiet — speak up, or raise this mic's input volume in Windows."
        return "Hearing you ✓"
