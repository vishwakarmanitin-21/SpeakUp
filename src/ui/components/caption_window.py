"""Floating live-caption window — shows words forming as you speak.

A frameless, always-on-top, non-focus-stealing pill that appears above the
overlay while dictating and displays the live (partial) transcript. It must
never take focus, or it would change which window receives the pasted output.
"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDesktopWidget, QLabel, QVBoxLayout, QWidget


class CaptionWindow(QWidget):
    """A small live-transcript caption shown bottom-centre while speaking."""

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
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setStyleSheet(
            "background: rgba(18,18,18,235); color: #f0f3f6;"
            "padding: 10px 18px; border-radius: 14px; font-size: 15px;"
        )
        self._label.setMaximumWidth(600)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._label)

    def show_caption(self, text: str) -> None:
        """Update and show the caption (creating it on first call)."""
        self._label.setText(text or "Listening…")
        self.adjustSize()
        self._reposition()
        if not self.isVisible():
            self.show()

    def _reposition(self) -> None:
        try:
            screen = QDesktopWidget().availableGeometry()
            self.adjustSize()
            x = screen.center().x() - self.width() // 2
            y = screen.bottom() - self.height() - 120  # above the bottom overlay
            self.move(max(screen.left(), x), max(screen.top(), y))
        except Exception:
            pass

    def hide_caption(self) -> None:
        self.hide()
        self._label.setText("")
