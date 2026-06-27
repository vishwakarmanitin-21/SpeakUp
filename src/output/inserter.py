from __future__ import annotations

import logging
import time

import pyperclip
from pynput.keyboard import Controller, Key

from src.config import Config

logger = logging.getLogger("speakup")


class OutputMode:
    AUTO_PASTE = "auto_paste"
    CLIPBOARD = "clipboard"
    PREVIEW = "preview"


class OutputInserter:
    """Delivers rewritten text to the user."""

    def __init__(self) -> None:
        self._config = Config()
        self._keyboard = Controller()
        self._stream_buffer = ""
        self._saved_clipboard: str | None = None

    def deliver(self, text: str, mode: str | None = None) -> str:
        """Deliver text using the specified output mode.

        Args:
            text: The rewritten text to deliver.
            mode: Override output mode (uses config default if None).

        Returns:
            The output mode that was used.
        """
        mode = mode or self._config.output_mode
        logger.info("Delivering output: mode=%s, length=%d chars", mode, len(text))

        try:
            if mode == OutputMode.AUTO_PASTE:
                self._auto_paste(text)
            elif mode == OutputMode.CLIPBOARD:
                self._copy_to_clipboard(text)
            elif mode == OutputMode.PREVIEW:
                # Preview is handled by the UI layer
                self._copy_to_clipboard(text)
            else:
                self._copy_to_clipboard(text)
        except Exception as e:
            logger.error("Output delivery failed: %s", e, exc_info=True)

        return mode

    def _auto_paste(self, text: str) -> None:
        """Copy to clipboard, simulate Ctrl+V, then restore the prior clipboard.

        Pasting requires the text on the clipboard momentarily. Unless the user
        has opted to keep it (keep_on_clipboard), we snapshot the previous
        clipboard and put it back afterwards so dictation doesn't clobber it.
        """
        keep = self._config.keep_on_clipboard
        previous = ""
        if not keep:
            try:
                previous = pyperclip.paste()
            except Exception:
                previous = ""

        pyperclip.copy(text)
        time.sleep(0.05)
        self._keyboard.press(Key.ctrl)
        self._keyboard.press("v")
        self._keyboard.release("v")
        self._keyboard.release(Key.ctrl)

        if not keep:
            # Let the paste consume the clipboard before restoring the old value.
            time.sleep(0.1)
            try:
                pyperclip.copy(previous)
            except Exception:
                logger.warning("Could not restore previous clipboard contents")

    def _copy_to_clipboard(self, text: str) -> None:
        """Just copy to clipboard."""
        pyperclip.copy(text)

    def _paste(self, text: str) -> None:
        """Put text on the clipboard and send Ctrl+V (atomic, no dropped chars)."""
        pyperclip.copy(text)
        time.sleep(0.04)
        self._keyboard.press(Key.ctrl)
        self._keyboard.press("v")
        self._keyboard.release("v")
        self._keyboard.release(Key.ctrl)
        time.sleep(0.03)

    # --- Streaming output (reliable: paste in chunks, never per-character) ---

    def begin_stream(self) -> None:
        """Start a streaming insert. Snapshots the clipboard for later restore."""
        self._stream_buffer = ""
        self._saved_clipboard = None
        if not self._config.keep_on_clipboard:
            try:
                self._saved_clipboard = pyperclip.paste()
            except Exception:
                self._saved_clipboard = None

    def feed_stream(self, delta: str) -> None:
        """Add a delta to the buffer; flush a chunk when a natural boundary is hit."""
        if not delta:
            return
        self._stream_buffer += delta
        if self._should_flush(self._stream_buffer):
            self._flush_stream()

    def end_stream(self) -> None:
        """Flush any remaining text and restore the original clipboard."""
        self._flush_stream()
        if not self._config.keep_on_clipboard and self._saved_clipboard is not None:
            time.sleep(0.05)
            try:
                pyperclip.copy(self._saved_clipboard)
            except Exception:
                logger.warning("Could not restore previous clipboard contents")
        self._saved_clipboard = None

    @staticmethod
    def _should_flush(buf: str) -> bool:
        """Flush on a line break, end of sentence/clause, or a long run with a space."""
        if "\n" in buf:
            return True
        if buf.endswith((". ", "! ", "? ", "; ", ": ", ", ")):
            return True
        return len(buf) >= 60 and buf.endswith(" ")

    def _flush_stream(self) -> None:
        if not self._stream_buffer:
            return
        chunk = self._stream_buffer
        self._stream_buffer = ""
        try:
            self._paste(chunk)
        except Exception as e:
            logger.warning("Streaming paste failed: %s", e)
