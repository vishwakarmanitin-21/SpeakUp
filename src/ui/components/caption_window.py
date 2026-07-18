"""Floating live-caption window — shows words forming as you speak.

A frameless, always-on-top, non-focus-stealing pill that appears above the
overlay while dictating and displays the live (partial) transcript. It must
never take focus, or it would change which window receives the pasted output.

Smoothness: the box is a FIXED size and is positioned ONCE (not resized/moved on
every word). A translucent frameless window flashes when it's resized or moved,
so the geometry never changes — only the label text repaints. To stay within the
fixed box, the caption behaves like a subtitle: it shows only the last few lines
that FIT (measured with real font metrics), dropping whole words off the front as
new ones arrive. This is a line-aware rolling window — the text never overflows
the box (which caused clipping/flashing) and never chops a word mid-way.

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
from PyQt5.QtWidgets import QDesktopWidget, QLabel, QVBoxLayout, QWidget

_WIDTH = 560          # fixed width
_MAX_LINES = 3        # subtitle depth — text is trimmed to the last N lines that fit
_PAD_X = 18           # horizontal text padding (matches the stylesheet)
_PAD_Y = 12           # vertical text padding (matches the stylesheet)
_LINE_PX = 22         # approx line height at 16px font (for sizing the box)
_HEIGHT = _MAX_LINES * _LINE_PX + 2 * _PAD_Y + 6   # fixed height that holds N lines
_BOTTOM_GAP = 120     # px above the screen bottom (sits above the overlay)
_PAINT_MS = 33        # reveal cadence (~30fps) — smooth typewriter animation
_MIN_STEP = 1         # min chars revealed per frame
_EASE = 5             # reveal ~1/EASE of the remaining gap per frame (catch-up)


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

        self._pending = ""      # latest text requested (may change many times/beat)
        self._display = ""      # text currently committed to the label
        self._caret_on = True

        # Text repaints are throttled to a steady cadence (smooth flow); the
        # caret blinks on its own slower timer.
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

    def _fit(self, text: str) -> str:
        """Return the longest TAIL of `text` (whole words) that fits in the box.

        Uses real font metrics so the caption never exceeds _MAX_LINES — older
        words scroll off the front instead of overflowing and clipping/flashing.
        Grows the tail from the end, so cost is ~(visible words), not total length.
        """
        words = text.split(" ")
        if not words:
            return text
        try:
            fm = self._label.fontMetrics()
            text_w = max(50, self.width() - 2 * _PAD_X)
            max_h = _MAX_LINES * fm.lineSpacing()
            keep: list[str] = []
            for w in reversed(words):
                candidate = " ".join([w] + keep)
                h = fm.boundingRect(
                    0, 0, text_w, 100000, Qt.TextWordWrap, candidate + " ▌"
                ).height()
                if h > max_h and keep:      # one more word would overflow — stop
                    break
                keep.insert(0, w)
            return " ".join(keep)
        except Exception:
            return text

    def _render(self) -> None:
        caret = "▌" if self._caret_on else " "
        self._label.setText(f"{self._fit(self._display)} {caret}")

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
        self._painter.stop()
        self._blinker.stop()
        self.hide()
        self._pending = ""
        self._display = ""
        self._label.setText("")
        self._pos = None
