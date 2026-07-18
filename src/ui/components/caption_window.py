"""Floating live-caption window — shows words forming as you speak.

A frameless, always-on-top, non-focus-stealing pill that appears above the
overlay while dictating and displays the live (partial) transcript. It must
never take focus, or it would change which window receives the pasted output.

Expandable WITHOUT flashing: a translucent frameless window flashes on Windows
whenever its own geometry is resized or moved, so the *window* stays a FIXED
size — a tall, fully-transparent, click-through pane whose bottom sits at the
caption position. Inside it, the dark rounded pill is just a bottom-anchored
label that is sized to its text; as you speak it grows UPWARD within the fixed
pane, so the caption appears to expand while the window never resizes (nothing
to flash). It grows up to _MAX_LINES; beyond that it behaves like a subtitle,
rolling whole words off the front so the text never exceeds the pane.

Live-transcription engines emit interim results in 2-3 word chunks (several a
beat, then a pause), so even a steady repaint lands the text in jumps. So the
caption doesn't just show the latest text — it *reveals* toward it a few
characters per frame (a typewriter effect). show_caption() records the target
text, and a ~30fps timer walks the displayed text toward it with an ease-out
(faster when far behind, so it stays near-live), producing a smooth flow out of
chunky data.
"""
from __future__ import annotations

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QDesktopWidget, QLabel, QVBoxLayout, QWidget

_WIDTH = 560          # fixed width
_MAX_LINES = 6        # caption grows up to this many lines, then rolls old words off
_PAD_X = 18           # horizontal text padding (inside the pill)
_PAD_Y = 12           # vertical text padding (inside the pill)
_FONT_PX = 16         # caption font size
_BOTTOM_GAP = 120     # px above the screen bottom (pill bottom sits here)
_PAINT_MS = 33        # reveal cadence (~30fps) — smooth typewriter animation
_MIN_STEP = 1         # min chars revealed per frame
_EASE = 5             # reveal ~1/EASE of the remaining gap per frame (catch-up)


class CaptionWindow(QWidget):
    """A smooth, blinking live-transcript caption that grows with your speech."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        # Critical: showing the caption must NOT steal focus from the app the
        # user is dictating into (otherwise the pasted output goes elsewhere).
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        # The pane is tall and mostly invisible — let clicks pass through it to
        # whatever is underneath so it never blocks the app being dictated into.
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.NoFocus)

        self._label = QLabel("")
        self._label.setWordWrap(True)
        self._label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        # Set the font explicitly (not via the stylesheet) so fontMetrics() is
        # accurate — stylesheet font-size does not reflect back into metrics.
        font = QFont(self._label.font())
        font.setPixelSize(_FONT_PX)
        self._label.setFont(font)
        self._label.setStyleSheet(
            "background: rgba(18,18,18,238); color: #f0f3f6;"
            f"padding: {_PAD_Y}px {_PAD_X}px; border-radius: 14px;"
        )

        # A stretch above the label pins the pill to the BOTTOM of the pane, so
        # the pill grows upward as its text height increases.
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addStretch(1)
        layout.addWidget(self._label)

        # Fixed pane height = room for _MAX_LINES (measured with the real font).
        self._line_h = self._label.fontMetrics().lineSpacing()
        self._window_h = _MAX_LINES * self._line_h + 2 * _PAD_Y + 8
        self.setFixedSize(_WIDTH, self._window_h)
        self._label_h = 0
        self._pos: tuple[int, int] | None = None

        self._pending = ""      # latest target text (may change many times/beat)
        self._display = ""      # text currently revealed toward the target
        self._caret_on = True

        # Text reveals on a steady cadence (smooth flow); the caret blinks on a
        # slower timer of its own.
        self._painter = QTimer(self)
        self._painter.setInterval(_PAINT_MS)
        self._painter.timeout.connect(self._tick_paint)
        self._blinker = QTimer(self)
        self._blinker.setInterval(450)
        self._blinker.timeout.connect(self._blink)

    def show_caption(self, text: str) -> None:
        """Record the target caption; a timer reveals toward it smoothly (~30fps)."""
        self._pending = (text or "").strip() or "Listening…"
        self._position_once()
        if not self.isVisible():
            self.show()
        if not self._painter.isActive():
            self._painter.start()
        if not self._blinker.isActive():
            self._blinker.start()

    @staticmethod
    def _reveal_len(cur: str, target: str) -> int:
        """How many chars of `target` to show this frame, walking up from `cur`.

        Pure helper (no Qt) so the typewriter behaviour is unit-testable.
        """
        # Longest common prefix of what's shown and where we're heading.
        n = 0
        limit = min(len(cur), len(target))
        while n < limit and cur[n] == target[n]:
            n += 1

        if n == len(cur) and len(target) > len(cur):
            # Pure growth (the usual case): reveal forward, faster when far behind.
            gap = len(target) - len(cur)
            step = max(_MIN_STEP, gap // _EASE)
            return min(len(target), len(cur) + step)
        if n == len(target):
            # The target is shorter (interim shrank / finalized) — snap to it.
            return len(target)
        # The interim was revised mid-word — drop back to the shared prefix and
        # start revealing the new tail from there.
        return min(len(target), n + _MIN_STEP)

    def _tick_paint(self) -> None:
        """Walk the displayed text one step toward the target (typewriter reveal)."""
        target, cur = self._pending, self._display
        if cur == target:
            return
        if target == "Listening…":
            # Placeholder should appear at once, not type itself out.
            self._display = target
        else:
            self._display = target[: self._reveal_len(cur, target)]
        self._render()

    def _text_height(self, text: str) -> int:
        """Wrapped pixel height of `text` at the pill's text width."""
        fm = self._label.fontMetrics()
        text_w = max(50, _WIDTH - 2 * _PAD_X)
        return fm.boundingRect(0, 0, text_w, 100000, Qt.TextWordWrap, text).height()

    def _fit(self, text: str) -> str:
        """Longest TAIL of `text` (whole words) that fits in _MAX_LINES.

        Below the cap the whole text fits, so the pill simply grows. Once the
        text would exceed _MAX_LINES, older words scroll off the front instead of
        overflowing the pane. Grows the tail from the end, so cost is
        ~(visible words), not total length.
        """
        words = text.split(" ")
        if not words:
            return text
        try:
            max_h = _MAX_LINES * self._label.fontMetrics().lineSpacing()
            keep: list[str] = []
            for w in reversed(words):
                candidate = " ".join([w] + keep)
                if self._text_height(candidate + " ▌") > max_h and keep:
                    break               # one more word would overflow — stop
                keep.insert(0, w)
            return " ".join(keep)
        except Exception:
            return text

    def _render(self) -> None:
        caret = "▌" if self._caret_on else " "
        fitted = self._fit(self._display)
        # Size the pill to its text so it grows upward within the fixed pane.
        try:
            new_h = min(self._window_h, self._text_height(fitted + " ▌") + 2 * _PAD_Y)
            if new_h != self._label_h:
                self._label_h = new_h
                self._label.setFixedHeight(new_h)
        except Exception:
            pass
        self._label.setText(f"{fitted} {caret}")

    def _blink(self) -> None:
        self._caret_on = not self._caret_on
        self._render()

    def _position_once(self) -> None:
        """Place the pane so the pill's bottom sits above the overlay.

        Only actually moves if the spot changed (moving a translucent window
        flashes), so it is safe to call on every caption update.
        """
        try:
            screen = QDesktopWidget().availableGeometry()
            x = max(screen.left(), screen.center().x() - _WIDTH // 2)
            y = max(screen.top(), screen.bottom() - _BOTTOM_GAP - self._window_h)
            pos = (x, y)
            if pos != self._pos:
                self._pos = pos
                self.move(x, y)
        except Exception:
            pass

    def hide_caption(self) -> None:
        self._painter.stop()
        self._blinker.stop()
        self.hide()
        self._pending = ""
        self._display = ""
        self._label_h = 0
        self._label.setText("")
        self._pos = None
