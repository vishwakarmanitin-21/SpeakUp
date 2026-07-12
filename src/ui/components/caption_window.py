"""Floating live-caption window — shows words forming as you speak.

A frameless, always-on-top, non-focus-stealing pill that appears above the
overlay while dictating and displays the live (partial) transcript. It must
never take focus, or it would change which window receives the pasted output.

Smoothness: the box is a FIXED size and is positioned ONCE (not resized/moved on
every word). A translucent frameless window flashes when it's resized or moved,
so per-word updates only repaint the label text — no geometry churn. Text is
bottom-aligned and word-wrapped like a subtitle; a rolling window of recent
characters keeps long dictations tidy (older lines scroll off the top).
"""
from __future__ import annotations

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QDesktopWidget, QLabel, QVBoxLayout, QWidget

_WIDTH = 560          # fixed width
_HEIGHT = 92          # fixed height (~2-3 lines) — never changes, so no flash
_MAX_CHARS = 150      # rolling window of recent text
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
        # Bottom-aligned so recent text sits low and long text scrolls off the top.
        self._label.setAlignment(Qt.AlignLeft | Qt.AlignBottom)
        self._label.setStyleSheet(
            "background: rgba(18,18,18,238); color: #f0f3f6;"
            "padding: 12px 18px; border-radius: 14px; font-size: 16px;"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._label)

        # FIXED size — the window never resizes, so it never flashes.
        self.setFixedSize(_WIDTH, _HEIGHT)
        self._pos: tuple[int, int] | None = None

        self._text = ""
        self._caret_on = True
        self._blinker = QTimer(self)
        self._blinker.setInterval(450)
        self._blinker.timeout.connect(self._blink)

    def show_caption(self, text: str) -> None:
        """Update and show the caption (positions once, then only repaints text)."""
        t = (text or "").strip()
        if len(t) > _MAX_CHARS:
            t = "…" + t[-_MAX_CHARS:]
        self._text = t or "Listening…"
        self._render()
        self._position_once()
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

    def _position_once(self) -> None:
        """Place the box bottom-centre; only actually move if the spot changed."""
        try:
            screen = QDesktopWidget().availableGeometry()
            x = max(screen.left(), screen.center().x() - _WIDTH // 2)
            y = max(screen.top(), screen.bottom() - _BOTTOM_GAP - _HEIGHT)
            pos = (x, y)
            if pos != self._pos:
                self._pos = pos
                self.move(x, y)
        except Exception:
            pass

    def hide_caption(self) -> None:
        self._blinker.stop()
        self.hide()
        self._text = ""
        self._label.setText("")
        self._pos = None
