from __future__ import annotations

import asyncio
import logging
import re
import sys
import time

from PyQt5.QtCore import QPoint, QPropertyAnimation, QSize, Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QCursor
from PyQt5.QtWidgets import (
    QApplication,
    QDesktopWidget,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.config import Config

logger = logging.getLogger("speakup")
from src.output.inserter import OutputMode
from src.services.pipeline import Pipeline, PipelineState
from src.ui.components.caption_window import CaptionWindow
from src.ui.components.mic_button import MicButton
from src.ui.components.mode_selector import ModeSelector
from src.ui.components.preview_window import PreviewWindow
from src.ui.components.status_indicator import StatusIndicator
from src.ui.styles import OVERLAY_STYLE, OVERLAY_COMPACT_STYLE, SETTINGS_BUTTON_STYLE


class OverlayWidget(QWidget):
    """Floating always-on-top overlay widget."""

    # Signals for thread-safe communication from hotkey listener thread
    hotkey_pressed = pyqtSignal()
    hotkey_released = pyqtSignal()
    # Live caption text from the realtime worker thread (thread-safe via signal)
    caption_updated = pyqtSignal(str)
    # Quiet hints (e.g. fell back to standard transcription); shown as a tray balloon
    notice_updated = pyqtSignal(str)

    # Scale presets: (mic_size, font_factor, margins, spacing, gear_size)
    _SCALES = {
        "compact": (28, 0.75, (4, 3, 4, 3), 4, 20),
        "normal": (48, 1.0, (12, 8, 12, 8), 10, 28),
        "large": (72, 1.5, (18, 12, 18, 12), 14, 40),
    }

    def __init__(self, pipeline: Pipeline, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("overlay")
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint
            | Qt.FramelessWindowHint
            | Qt.Tool  # Prevents taskbar entry
        )
        self.setAttribute(Qt.WA_TranslucentBackground)

        self._pipeline = pipeline
        self._config = Config()
        self._drag_position: QPoint | None = None
        self._is_recording = False
        self._recording_start: float = 0.0
        self._MIN_RECORDING_SECS = 0.3
        self._preview_window: PreviewWindow | None = None
        self._hotkey_listener = None  # Set via set_hotkey_listener()
        self._is_compact = self._config.widget_scale == "compact"
        self._compact_expanded = False  # True while mouse hovers in compact mode

        # Polling timer to detect when mouse leaves the compact widget.
        # leaveEvent is unreliable for frameless translucent tool windows on Windows.
        self._hover_poll_timer = QTimer()
        self._hover_poll_timer.setInterval(300)
        self._hover_poll_timer.timeout.connect(self._check_hover)

        # Windows demotes always-on-top windows over time (fullscreen apps, UAC,
        # focus changes) so the overlay gets buried and looks "disappeared".
        # Re-assert topmost periodically WITHOUT stealing focus.
        self._topmost_timer = QTimer()
        self._topmost_timer.setInterval(2000)
        self._topmost_timer.timeout.connect(self._keep_on_top)
        self._topmost_timer.start()

        self._setup_ui()
        self._connect_signals()
        self._apply_scale()
        self._position_widget()

        # Live caption window (shown while dictating with realtime on)
        self._caption = CaptionWindow()
        self.caption_updated.connect(self._caption.show_caption)
        self._pipeline.set_caption_callback(lambda t: self.caption_updated.emit(t))
        self._pipeline.set_notice_callback(lambda m: self.notice_updated.emit(m))

        # Pipeline state changes update UI
        self._pipeline.set_state_callback(self._on_pipeline_state)
        self._pipeline.set_silence_callback(self._on_silence)

    def _setup_ui(self) -> None:
        # Main container with background
        self._container = QWidget(self)
        self._container.setObjectName("overlay")

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self._container)

        self._inner_layout = QHBoxLayout(self._container)

        # Mic button
        self._mic_btn = MicButton()
        self._inner_layout.addWidget(self._mic_btn)

        # Mode selector + status (vertical stack)
        self._info_widget = QWidget()
        info_layout = QVBoxLayout(self._info_widget)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(4)

        self._mode_selector = ModeSelector()
        info_layout.addWidget(self._mode_selector)

        self._status = StatusIndicator()
        info_layout.addWidget(self._status)

        self._inner_layout.addWidget(self._info_widget)

        # Settings gear button
        self._settings_btn = QPushButton("\u2699")  # gear character
        self._settings_btn.setStyleSheet(SETTINGS_BUTTON_STYLE)
        self._settings_btn.setCursor(Qt.PointingHandCursor)
        self._inner_layout.addWidget(self._settings_btn)

    def _apply_scale(self) -> None:
        """Apply the current scale preset to all child widgets."""
        scale = self._config.widget_scale
        mic_sz, font_f, margins, spacing, gear_sz = self._SCALES.get(
            scale, self._SCALES["normal"]
        )

        # Container style
        if scale == "compact":
            self._container.setStyleSheet(OVERLAY_COMPACT_STYLE)
        else:
            self._container.setStyleSheet(OVERLAY_STYLE)

        self._inner_layout.setContentsMargins(*margins)
        self._inner_layout.setSpacing(spacing)

        # Mic button
        self._mic_btn.setFixedSize(QSize(mic_sz, mic_sz))
        mic_font_px = max(10, int(18 * font_f))
        mic_radius = mic_sz // 2
        # Use regex on the CURRENT value so repeated scale changes re-patch
        # correctly (a literal replace only matches the unpatched default once).
        for state_key in ("idle", "recording", "processing"):
            from src.ui.styles import MIC_BUTTON_STYLES
            patched = re.sub(r"border-radius: \d+px",
                             f"border-radius: {mic_radius}px", MIC_BUTTON_STYLES[state_key])
            patched = re.sub(r"font-size: \d+px",
                             f"font-size: {mic_font_px}px", patched)
            MIC_BUTTON_STYLES[state_key] = patched
        self._mic_btn.set_state("idle")  # re-apply patched style

        # Settings button
        self._settings_btn.setFixedSize(gear_sz, gear_sz)
        gear_font_px = max(10, int(16 * font_f))
        self._settings_btn.setStyleSheet(
            re.sub(r"font-size: \d+px", f"font-size: {gear_font_px}px", SETTINGS_BUTTON_STYLE)
        )

        # Status / mode selector font scaling
        status_px = max(8, int(11 * font_f))
        from src.ui import styles as _st
        for k, v in _st.STATUS_STYLES.items():
            _st.STATUS_STYLES[k] = re.sub(
                r"font-size: \d+px", f"font-size: {status_px}px", v)
        self._status.set_state("idle")

        # Compact mode: hide detail widgets initially
        if scale == "compact":
            self._info_widget.setVisible(False)
            self._settings_btn.setVisible(False)

    def _position_widget(self) -> None:
        """Place widget according to config widget_position."""
        desktop = QDesktopWidget()
        screen = desktop.availableGeometry(desktop.primaryScreen())
        self.adjustSize()
        pos = self._config.widget_position
        margin = 20
        y = screen.height() - self.height() - margin

        if pos == "bottom_left":
            x = margin
        elif pos == "bottom_center":
            x = (screen.width() - self.width()) // 2
        else:  # bottom_right (default)
            x = screen.width() - self.width() - margin

        self.move(x, y)

    def reload_appearance(self) -> None:
        """Re-apply size/position from config without a restart (after Settings save)."""
        # Reset compact/hover state and any fixed-size constraints from collapsing.
        self._hover_poll_timer.stop()
        self._compact_expanded = False
        self._is_compact = self._config.widget_scale == "compact"
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)

        self._apply_scale()
        # Switching away from compact must re-show the detail widgets that
        # compact mode hides.
        if not self._is_compact:
            self._info_widget.setVisible(True)
            self._settings_btn.setVisible(True)

        self.adjustSize()
        self._position_widget()

    # --- Compact mode hover expand/collapse ---

    def enterEvent(self, event) -> None:
        if self._is_compact and not self._compact_expanded:
            self._compact_expanded = True
            self._info_widget.setVisible(True)
            self._settings_btn.setVisible(True)
            # Let layout expand naturally, then record expanded size
            self.setMinimumSize(0, 0)
            self.setMaximumSize(16777215, 16777215)
            self.adjustSize()
            self._hover_poll_timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)

    def _check_hover(self) -> None:
        """Poll cursor position; collapse compact widget when mouse leaves."""
        if not self._is_compact or not self._compact_expanded:
            self._hover_poll_timer.stop()
            return
        if self.geometry().contains(QCursor.pos()):
            return  # Mouse still over the widget — keep expanded
        self._hover_poll_timer.stop()
        self._compact_expanded = False
        self._info_widget.setVisible(False)
        self._settings_btn.setVisible(False)
        # Force widget to shrink to just the mic button
        mic_sz = self._SCALES["compact"][0]
        margins = self._SCALES["compact"][2]  # (left, top, right, bottom)
        w = mic_sz + margins[0] + margins[2]
        h = mic_sz + margins[1] + margins[3]
        self.setFixedSize(w, h)
        self._position_widget()
        # Re-allow resizing for next expand
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)

    def _connect_signals(self) -> None:
        self.hotkey_pressed.connect(self._start_recording)
        self.hotkey_released.connect(self._stop_recording_and_process)
        self._mic_btn.clicked.connect(self._toggle_recording)
        self._settings_btn.clicked.connect(self.open_settings)

    def keyPressEvent(self, event) -> None:
        """Cancel a running pipeline with Escape."""
        if event.key() == Qt.Key_Escape and self._is_recording:
            self._cancel_pipeline()
        super().keyPressEvent(event)

    # --- Dragging support ---

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_position = (
                event.globalPos() - self.frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_position is not None:
            self.move(event.globalPos() - self._drag_position)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._drag_position = None

    # --- Hotkey callbacks (called from pynput thread) ---

    def on_hotkey_pressed(self) -> None:
        """Called from the pynput thread. Emits a Qt signal for thread safety."""
        self.hotkey_pressed.emit()

    def on_hotkey_released(self) -> None:
        """Called from the pynput thread. Emits a Qt signal for thread safety."""
        self.hotkey_released.emit()

    # --- Recording control ---

    @pyqtSlot()
    def _start_recording(self) -> None:
        logger.info("_start_recording called (is_recording=%s)", self._is_recording)
        if self._is_recording:
            return
        self._is_recording = True
        self._recording_start = time.monotonic()
        self._caption.hide_caption()  # clear any stale caption
        self._mic_btn.set_state("recording")
        self._status.set_state("listening")
        self._pipeline.start_recording()

    @pyqtSlot()
    def _stop_recording_and_process(self) -> None:
        logger.info("_stop_recording_and_process called (is_recording=%s)", self._is_recording)
        if not self._is_recording:
            return
        elapsed = time.monotonic() - self._recording_start
        if elapsed < self._MIN_RECORDING_SECS:
            # Too short — discard silently to avoid "audio too short" API errors
            logger.info("Recording too short (%.2fs), discarded", elapsed)
            self._is_recording = False
            self._pipeline.cancel()
            self._caption.hide_caption()
            self._mic_btn.set_state("idle")
            self._status.set_state("idle")
            return
        logger.info("Recording stopped after %.2fs, starting pipeline", elapsed)
        self._is_recording = False
        self._pipeline.stop_recording()
        self._mic_btn.set_state("processing")
        self._status.set_state("processing")
        asyncio.ensure_future(self._run_pipeline())

    def _toggle_recording(self) -> None:
        """Toggle recording via mic button click."""
        if self._is_recording:
            self._stop_recording_and_process()
        else:
            self._start_recording()

    def _cancel_pipeline(self) -> None:
        """Cancel the current recording or pipeline run."""
        self._is_recording = False
        self._pipeline.cancel()
        self._caption.hide_caption()
        self._mic_btn.set_state("idle")
        self._status.set_state("idle")

    async def _run_pipeline(self) -> None:
        """Run the transcription + rewrite pipeline."""
        from src.services.error_handler import SpeakUpError

        mode = self._mode_selector.current_mode()
        output_mode = self._config.output_mode
        try:
            raw_text, rewritten = await self._pipeline.process(
                mode, output_mode=output_mode
            )
            print(f"\n[Raw] {raw_text}")
            print(f"\n[{mode.display_name}]\n{rewritten}\n")

            # Show preview window if output mode is preview
            if output_mode == OutputMode.PREVIEW:
                self._show_preview(rewritten)

        except Exception as e:
            msg = e.user_message if isinstance(e, SpeakUpError) else str(e)
            self._status.set_state("error", msg)
            logger.error("Pipeline failed: %s", e, exc_info=True)
        finally:
            self._caption.hide_caption()

    def rerun_last(self, mode) -> None:
        """Re-run the last dictation through `mode` (triggered from the tray)."""
        asyncio.ensure_future(self._run_rerun(mode))

    async def _run_rerun(self, mode) -> None:
        from src.services.error_handler import SpeakUpError

        output_mode = self._config.output_mode
        try:
            raw_text, rewritten = await self._pipeline.rerun_last(mode)
            if not raw_text:
                self._status.set_state("idle", "Nothing to re-run yet — dictate something first.")
                return
            if output_mode == OutputMode.PREVIEW:
                self._show_preview(rewritten)
        except Exception as e:
            msg = e.user_message if isinstance(e, SpeakUpError) else str(e)
            self._status.set_state("error", msg)
            logger.error("Re-run failed: %s", e, exc_info=True)

    def _show_preview(self, text: str) -> None:
        """Show the preview window with the rewritten text."""
        if self._preview_window is None:
            self._preview_window = PreviewWindow()
        self._preview_window.show_result(text)

    # --- Pipeline state updates ---

    def _on_pipeline_state(self, state: str) -> None:
        """Update UI based on pipeline state changes."""
        state_map = {
            PipelineState.IDLE: ("idle", "idle"),
            PipelineState.RECORDING: ("recording", "listening"),
            PipelineState.TRANSCRIBING: ("processing", "processing"),
            PipelineState.REWRITING: ("processing", "processing"),
            PipelineState.DONE: ("idle", "done"),
            PipelineState.ERROR: ("idle", "error"),
        }
        mic_state, status_state = state_map.get(state, ("idle", "idle"))
        self._mic_btn.set_state(mic_state)
        self._status.set_state(status_state)

        if state in (PipelineState.DONE, PipelineState.ERROR):
            self._is_recording = False
            # Reset hotkey listener state so next activation works even if
            # the OS swallowed a key release (common with the Windows key)
            if self._hotkey_listener is not None:
                self._hotkey_listener.reset_state()
            # Auto-collapse compact widget if mouse is no longer hovering
            if self._is_compact and self._compact_expanded:
                self._hover_poll_timer.start()

    def _on_silence(self) -> None:
        """Called when silence is detected during recording."""
        self._stop_recording_and_process()

    # --- Public API ---

    def set_hotkey_listener(self, listener) -> None:
        """Store a reference to the hotkey listener for live hotkey updates."""
        self._hotkey_listener = listener

    def toggle_visibility(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self._keep_on_top()

    def _keep_on_top(self) -> None:
        """Re-assert always-on-top without stealing focus (Windows demotes it)."""
        if not self.isVisible():
            return
        # Don't jump above an open dialog (Settings/onboarding are modal).
        if QApplication.activeModalWidget() is not None:
            return
        if sys.platform == "win32":
            try:
                import ctypes
                HWND_TOPMOST = -1
                SWP_NOSIZE = 0x0001
                SWP_NOMOVE = 0x0002
                SWP_NOACTIVATE = 0x0010
                ctypes.windll.user32.SetWindowPos(
                    int(self.winId()), HWND_TOPMOST, 0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
                )
            except Exception:
                pass
        else:
            self.raise_()

    def open_settings(self) -> None:
        """Open the settings dialog."""
        from src.ui.components.settings_dialog import SettingsDialog

        dialog = SettingsDialog(self, hotkey_listener=self._hotkey_listener)
        if dialog.exec_():  # Save (Accepted) — apply appearance changes live
            self.reload_appearance()
