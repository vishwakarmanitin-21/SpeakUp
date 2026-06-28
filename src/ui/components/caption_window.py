"""Floating live-caption window — shows words forming as you speak.

A frameless, always-on-top, non-focus-stealing pill that appears above the
overlay while dictating and displays the live (partial) transcript. It must
never take focus, or it would change which window receives the pasted output.

For a smooth "live typing" feel it keeps a FIXED width and is anchored to a
fixed bottom edge (so the box grows upward instead of jumping around as text
arrives), shows a blinking caret, and displays only a rolling window of the
most recent words so long dictations stay compact.
"""
from __future__ import annotations

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QDesktopWidget, QLabel, QVBoxLayout, QWidget

_WIDTH = 560          # fixed width so the box never jumps horizontally
_MAX_CHARS = 180      # rolling window of recent text
_BOTTOM_GAP = 120     # px above the screen bottom (sits above the overlay)


class CaptionWindow(QWidget):
    """A smooth, blinking live-transcript caption shown bottom-centre."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        # Critical: showing the caption must NOT steal focus from the app the
        # user is dictating into (otherwise the pasted output goes elsewhere).
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.NoFocus)

        self._label = QLabel("")
        self._label.setWordWrap(True)
        self._label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._label.setStyleSheet(
            "background: rgba(18,18,18,238); color: #f0f3f6;"
            "padding: 12px 18px; border-radius: 14px; font-size: 16px;"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._label)
        self.setFixedWidth(_WIDTH)

        self._text = ""
        self._caret_on = True
        self._blinker = QTimer(self)
        self._blinker.setInterval(450)
        self._blinker.timeout.connect(self._blink)

    def show_caption(self, text: str) -> None:
        """Update and show the caption (creating it on first call)."""
        t = (text or "").strip()
        if len(t) > _MAX_CHARS:
            t = "…" + t[-_MAX_CHARS:]
        self._text = t or "Listening…"
        self._render()
        self._reposition()
        if not self.isVisible():
            self.show()
        if not self._blinker.isActive():
            self._blinker.start()

    def _render(self) -> None:
        caret = "▌" if self._caret_on else " "
        self._label.setText(f"{self._text} {caret}")

    def _blink(self) -> None:
        self._caret_on = not self._caret_on
        self._render()

    def _reposition(self) -> None:
        try:
            screen = QDesktopWidget().availableGeometry()
            self.setFixedWidth(_WIDTH)
            self.adjustSize()  # fixed width -> only height changes
            x = screen.center().x() - self.width() // 2
            bottom = screen.bottom() - _BOTTOM_GAP
            y = bottom - self.height()  # anchored bottom: grows upward
            self.move(max(screen.left(), x), max(screen.top(), y))
        except Exception:
            pass

    def hide_caption(self) -> None:
        self._blinker.stop()
        self.hide()
        self._text = ""
        self._label.setText("")
