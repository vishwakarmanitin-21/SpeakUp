"""First-run onboarding wizard: API key → mic test → quick tutorial.

Shown once on first launch (tracked by config `onboarding_complete`). Fully
skippable — the app always opens, and the key can be added later in Settings.
"""
from __future__ import annotations

import logging
import os

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.config import Config

logger = logging.getLogger("speakup")

_STYLE = """
    QDialog { background-color: #262626; }
    QLabel { color: #e8e8e8; }
    QLabel#title { color: #4FC3F7; font-size: 18px; font-weight: bold; }
    QLabel#step { color: #9aa4b0; font-size: 12px; }
    QLineEdit, QComboBox {
        padding: 7px 10px; border: 1px solid #555; border-radius: 7px;
        background-color: #3a3a3a; color: #ffffff;
    }
    QProgressBar {
        border: 1px solid #555; border-radius: 7px; background-color: #3a3a3a;
        text-align: center; color: #e8e8e8; height: 18px;
    }
    QProgressBar::chunk { background-color: #4FC3F7; border-radius: 6px; }
    QPushButton {
        background-color: #3d3d3d; color: #ffffff; border: none;
        border-radius: 7px; padding: 8px 16px;
    }
    QPushButton:hover { background-color: #4a4a4a; }
    QPushButton:disabled { color: #777; }
    QPushButton#primary { background-color: #4FC3F7; color: #062430; font-weight: bold; }
    QPushButton#primary:hover { background-color: #6fd0fb; }
    QPushButton#link { background: none; color: #4FC3F7; padding: 8px 4px; }
"""


class OnboardingDialog(QDialog):
    """Three-step first-run setup."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Welcome to SpeakUp")
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.setMinimumWidth(480)
        self.setStyleSheet(_STYLE)

        self._config = Config()
        self._mic_stream = None
        self._level = 0.0

        self._stack = QStackedWidget()
        self._stack.addWidget(self._page_welcome())
        self._stack.addWidget(self._page_mic())
        self._stack.addWidget(self._page_tutorial())

        self._step_lbl = QLabel()
        self._step_lbl.setObjectName("step")

        self._back_btn = QPushButton("Back")
        self._next_btn = QPushButton("Next")
        self._next_btn.setObjectName("primary")
        self._skip_btn = QPushButton("Skip setup")
        self._skip_btn.setObjectName("link")
        self._back_btn.clicked.connect(self._go_back)
        self._next_btn.clicked.connect(self._go_next)
        self._skip_btn.clicked.connect(self._finish)

        nav = QHBoxLayout()
        nav.addWidget(self._skip_btn)
        nav.addStretch()
        nav.addWidget(self._step_lbl)
        nav.addStretch()
        nav.addWidget(self._back_btn)
        nav.addWidget(self._next_btn)

        root = QVBoxLayout(self)
        root.addWidget(self._stack)
        root.addLayout(nav)

        self._meter_timer = QTimer(self)
        self._meter_timer.setInterval(60)
        self._meter_timer.timeout.connect(self._update_meter)

        self._stack.currentChanged.connect(self._on_page_change)
        self._update_nav()

    # --- Pages ---

    def _page_welcome(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        title = QLabel("Welcome to SpeakUp")
        title.setObjectName("title")
        lay.addWidget(title)
        lay.addWidget(QLabel(
            "SpeakUp turns your speech into clean, structured text anywhere you "
            "type.\nLet's get you set up in under a minute."
        ))
        lay.addSpacing(8)
        lay.addWidget(QLabel("Paste your OpenAI API key (powers transcription + cleanup):"))
        self._key_input = QLineEdit()
        self._key_input.setEchoMode(QLineEdit.Password)
        self._key_input.setPlaceholderText("sk-…")
        self._key_input.setText(os.getenv("OPENAI_API_KEY", ""))
        lay.addWidget(self._key_input)
        hint = QLabel(
            "No key yet? Get one at platform.openai.com/api-keys. You can also "
            "skip and add it later in Settings."
        )
        hint.setObjectName("step")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        lay.addStretch()
        return w

    def _page_mic(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        title = QLabel("Test your microphone")
        title.setObjectName("title")
        lay.addWidget(title)
        lay.addWidget(QLabel("Pick your input device, then speak — the bar should move."))
        self._device_combo = QComboBox()
        self._device_combo.currentIndexChanged.connect(self._restart_mic)
        lay.addWidget(self._device_combo)
        self._meter = QProgressBar()
        self._meter.setRange(0, 100)
        self._meter.setValue(0)
        lay.addWidget(self._meter)
        self._mic_status = QLabel("")
        self._mic_status.setObjectName("step")
        lay.addWidget(self._mic_status)
        lay.addStretch()
        return w

    def _page_tutorial(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        title = QLabel("How to use SpeakUp")
        title.setObjectName("title")
        lay.addWidget(title)
        steps = QLabel(
            "1.  Click into any text field (email, chat, document).\n\n"
            "2.  Hold  Ctrl + Windows  and speak.\n\n"
            "3.  Release — your cleaned-up text appears at the cursor.\n\n"
            "•  Pick a style (Smart, Email, Notes…) from the bar.\n"
            "•  The tray icon (bottom-right) has Settings and the User Guide.\n"
            "•  Turn on Live transcription in Settings to see captions as you talk."
        )
        steps.setWordWrap(True)
        lay.addWidget(steps)
        lay.addStretch()
        return w

    # --- Navigation ---

    def _update_nav(self) -> None:
        i = self._stack.currentIndex()
        last = self._stack.count() - 1
        self._back_btn.setEnabled(i > 0)
        self._next_btn.setText("Finish" if i == last else "Next")
        self._step_lbl.setText(f"Step {i + 1} of {self._stack.count()}")

    def _go_back(self) -> None:
        if self._stack.currentIndex() > 0:
            self._stack.setCurrentIndex(self._stack.currentIndex() - 1)

    def _go_next(self) -> None:
        if self._stack.currentIndex() >= self._stack.count() - 1:
            self._finish()
        else:
            self._stack.setCurrentIndex(self._stack.currentIndex() + 1)

    def _on_page_change(self, index: int) -> None:
        self._update_nav()
        if index == 1:
            self._start_mic()
        else:
            self._stop_mic()

    # --- Microphone test ---

    def _start_mic(self) -> None:
        if self._device_combo.count() == 0:
            self._populate_devices()
        self._restart_mic()
        self._meter_timer.start()

    def _populate_devices(self) -> None:
        try:
            import sounddevice as sd

            self._device_combo.blockSignals(True)
            self._device_combo.clear()
            try:
                default_in = sd.default.device[0]
            except Exception:
                default_in = None
            for idx, dev in enumerate(sd.query_devices()):
                if dev.get("max_input_channels", 0) > 0:
                    self._device_combo.addItem(dev.get("name", f"Device {idx}"), idx)
            self._device_combo.blockSignals(False)
            if default_in is not None:
                for i in range(self._device_combo.count()):
                    if self._device_combo.itemData(i) == default_in:
                        self._device_combo.setCurrentIndex(i)
                        break
        except Exception as e:
            self._mic_status.setText("Microphone unavailable on this system.")
            logger.debug("populate devices failed: %s", e)

    def _restart_mic(self) -> None:
        if self._stack.currentIndex() != 1:
            return
        self._stop_mic()
        try:
            import numpy as np
            import sounddevice as sd

            device = self._device_combo.currentData()

            def _cb(indata, frames, time_info, status):
                try:
                    self._level = float(np.sqrt(np.mean(indata[:, 0] ** 2)))
                except Exception:
                    self._level = 0.0

            self._mic_stream = sd.InputStream(
                samplerate=16000, channels=1, dtype="float32",
                device=device, callback=_cb,
            )
            self._mic_stream.start()
            self._mic_status.setText("Listening… speak to see the bar move.")
        except Exception as e:
            self._mic_status.setText("Couldn't open this microphone — try another device.")
            logger.debug("mic start failed: %s", e)

    def _update_meter(self) -> None:
        # Scale RMS to a lively 0–100 bar (speech RMS is small).
        level = min(1.0, self._level * 8.0)
        self._meter.setValue(int(level * 100))

    def _stop_mic(self) -> None:
        self._meter_timer.stop()
        if self._mic_stream is not None:
            try:
                self._mic_stream.stop()
                self._mic_stream.close()
            except Exception:
                pass
            self._mic_stream = None
        self._meter.setValue(0)

    # --- Finish / persistence ---

    def _save_key_if_entered(self) -> None:
        key = self._key_input.text().strip()
        if not key or key == os.getenv("OPENAI_API_KEY", ""):
            return
        os.environ["OPENAI_API_KEY"] = key
        try:
            env_path = self._config.env_path
            lines, found = [], False
            if env_path.exists():
                with open(env_path, encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("OPENAI_API_KEY="):
                            lines.append(f"OPENAI_API_KEY={key}\n")
                            found = True
                        else:
                            lines.append(line)
            if not found:
                lines.append(f"OPENAI_API_KEY={key}\n")
            with open(env_path, "w", encoding="utf-8") as f:
                f.writelines(lines)
            self._config.reload()
            logger.info("API key saved from onboarding")
        except Exception as e:
            logger.error("Could not save API key: %s", e)

    def _finish(self) -> None:
        self._stop_mic()
        self._save_key_if_entered()
        try:
            self._config.save_user_overrides({"onboarding_complete": True})
            self._config.reload()
        except Exception as e:
            logger.warning("Could not mark onboarding complete: %s", e)
        self.accept()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt signature)
        self._stop_mic()
        # Treat any close as completing onboarding so it doesn't reappear.
        self._save_key_if_entered()
        try:
            self._config.save_user_overrides({"onboarding_complete": True})
            self._config.reload()
        except Exception:
            pass
        super().closeEvent(event)

    @staticmethod
    def has_api_key() -> bool:
        key = os.getenv("OPENAI_API_KEY", "").strip()
        return bool(key) and key != "sk-your-key-here"
