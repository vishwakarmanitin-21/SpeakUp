from __future__ import annotations

import logging
import queue
import threading
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
        self._first_chunk_done = False
        self._saved_clipboard: str | None = None
        # Background paste worker (set up per streaming run)
        self._paste_queue: queue.Queue | None = None
        self._paste_worker: threading.Thread | None = None

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
        """Put text on the clipboard and send Ctrl+V (atomic, no dropped chars).

        The two short sleeps guard against the clipboard not being set before
        Ctrl+V (would paste stale text) and the next chunk overwriting before
        this paste is consumed. Kept minimal for snappy streaming.
        """
        pyperclip.copy(text)
        time.sleep(0.025)
        self._keyboard.press(Key.ctrl)
        self._keyboard.press("v")
        self._keyboard.release("v")
        self._keyboard.release(Key.ctrl)
        time.sleep(0.018)

    # --- Streaming output (background paste thread: overlaps with generation) ---

    def begin_stream(self) -> None:
        """Start a streaming insert with a background paste worker.

        Pasting (clipboard + Ctrl+V + short sleeps) runs on its own thread so it
        OVERLAPS with the model still generating — the event loop keeps reading
        deltas while text is being inserted, instead of stalling on each chunk.
        A single worker draining a FIFO queue preserves insertion order.
        """
        self._stream_buffer = ""
        self._first_chunk_done = False
        self._saved_clipboard = None
        if not self._config.keep_on_clipboard:
            try:
                self._saved_clipboard = pyperclip.paste()
            except Exception:
                self._saved_clipboard = None
        self._paste_queue = queue.Queue()
        self._paste_worker = threading.Thread(target=self._paste_loop, daemon=True)
        self._paste_worker.start()

    def feed_stream(self, delta: str) -> None:
        """Add a delta to the buffer; enqueue a chunk when a boundary is hit."""
        if not delta:
            return
        self._stream_buffer += delta
        # Enqueue the very first words ASAP so text appears immediately, then
        # fall back to clause/sentence-sized chunks for the rest.
        if not self._first_chunk_done:
            if self._should_flush_first(self._stream_buffer):
                self._enqueue_chunk()
                self._first_chunk_done = True
        elif self._should_flush(self._stream_buffer):
            self._enqueue_chunk()

    def end_stream(self) -> None:
        """Flush remaining text, wait for all pastes to finish, restore clipboard."""
        self._enqueue_chunk()  # trailing partial, if any
        if self._paste_worker is not None and self._paste_queue is not None:
            self._paste_queue.put(None)  # sentinel: stop once the queue drains
            self._paste_worker.join(timeout=10.0)
        self._paste_worker = None
        self._paste_queue = None

        if not self._config.keep_on_clipboard and self._saved_clipboard is not None:
            time.sleep(0.05)
            try:
                pyperclip.copy(self._saved_clipboard)
            except Exception:
                logger.warning("Could not restore previous clipboard contents")
        self._saved_clipboard = None

    def _enqueue_chunk(self) -> None:
        if not self._stream_buffer:
            return
        chunk = self._stream_buffer
        self._stream_buffer = ""
        if self._paste_queue is not None:
            self._paste_queue.put(chunk)

    def _paste_loop(self) -> None:
        """Drain the queue on a background thread, pasting chunks in order."""
        q = self._paste_queue
        if q is None:
            return
        while True:
            chunk = q.get()
            try:
                if chunk is None:  # sentinel
                    return
                self._paste(chunk)
            except Exception as e:
                logger.warning("Streaming paste failed: %s", e)
            finally:
                q.task_done()

    @staticmethod
    def _should_flush(buf: str) -> bool:
        """Flush on a line break, end of sentence/clause, or a long run with a space."""
        if "\n" in buf:
            return True
        if buf.endswith((". ", "! ", "? ", "; ", ": ", ", ")):
            return True
        return len(buf) >= 60 and buf.endswith(" ")

    @staticmethod
    def _should_flush_first(buf: str) -> bool:
        """Aggressive boundary for the FIRST chunk — get a few words on screen fast."""
        if "\n" in buf:
            return True
        if buf.endswith((". ", "! ", "? ", "; ", ": ", ", ")):
            return True
        return len(buf) >= 14 and buf.endswith(" ")
