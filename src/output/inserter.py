from __future__ import annotations

import logging
import queue
import threading
import time

from pynput.keyboard import Controller, Key

from src.config import Config
from src.output import clipboard_win as clip

logger = logging.getLogger("speakup")

# Ctrl+V is ASYNCHRONOUS: the target app reads the clipboard whenever it gets
# round to processing the keystroke, which can be long after we sent it. So the
# clipboard must not change while a paste we sent might still be pending.
_CHUNK_SETTLE_S = 0.035   # after Ctrl+V, before the next chunk overwrites it
_RESTORE_DELAY_S = 0.6    # after the last paste, before restoring the old value
                          # (runs on a background thread, so it costs no latency)


class OutputMode:
    AUTO_PASTE = "auto_paste"
    CLIPBOARD = "clipboard"
    PREVIEW = "preview"


class OutputInserter:
    """Delivers rewritten text to the user.

    The clipboard goes through clipboard_win, not pyperclip: pyperclip only
    sees plain text, so a copied image or file read back as "" and was then
    "restored" as "" — wiping the user's copy. clipboard_win keeps every
    format, keeps SpeakUp's transient chunks out of Win+V history, and
    retries while another app briefly holds the clipboard.
    """

    def __init__(self) -> None:
        self._config = Config()
        self._keyboard = Controller()
        self._stream_buffer = ""
        self._first_chunk_done = False
        self._saved_clipboard: dict[int, bytes] | None = None
        # Clipboard sequence number after OUR last write — the restore only
        # happens if nothing has written the clipboard since.
        self._last_seq: int | None = None
        self._streamed: list[str] = []
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
            else:
                # Clipboard mode, and preview (shown by the UI layer): the user
                # asked for it on the clipboard, so let history keep it.
                self._copy_to_clipboard(text)
        except Exception as e:
            logger.error("Output delivery failed: %s", e, exc_info=True)

        return mode

    def _auto_paste(self, text: str) -> None:
        """Paste at the cursor, then put the user's clipboard back.

        Unless the user opted to keep the text (keep_on_clipboard), every
        format they had copied is snapshotted and restored afterwards.
        """
        keep = self._config.keep_on_clipboard
        saved = None if keep else clip.snapshot()
        if not self._paste(text, private=not keep):
            return  # typed instead — the clipboard was never touched
        if not keep and saved is not None:
            self._restore_clipboard_later(saved, self._last_seq)

    def _restore_clipboard_later(self, saved: dict[int, bytes], our_seq: int | None) -> None:
        """Put the user's clipboard back, once pending pastes have certainly landed.

        Restoring too early is what made dictation paste the user's OLD clipboard
        content instead of the transcript: Ctrl+V is asynchronous, so a paste we
        had already sent could read the clipboard AFTER we restored it. Two guards:

        1. Wait a generous delay (on a background thread, so no added latency).
        2. Only restore if nothing has written the clipboard since OUR last
           write (sequence number) — if something else has taken it over,
           leave it alone.
        """
        if our_seq is None:
            # Nothing was ever put on the clipboard, so it was never clobbered —
            # restoring would blindly overwrite whatever the user has since copied.
            return

        def _worker() -> None:
            time.sleep(_RESTORE_DELAY_S)
            try:
                if clip.sequence() != our_seq:
                    return  # another app owns the clipboard now — don't fight it
                clip.restore(saved)
            except Exception as e:
                logger.warning("Could not restore previous clipboard contents: %s", e)

        threading.Thread(target=_worker, daemon=True).start()

    def _copy_to_clipboard(self, text: str) -> None:
        """Just copy to clipboard."""
        clip.set_text(text, private=False)

    def _paste(self, text: str, private: bool = True) -> bool:
        """Put text on the clipboard and send Ctrl+V. Never drops the text.

        Returns True if it went through the clipboard, False if the clipboard
        stayed busy through every retry and the text was typed instead (a
        failed chunk used to be logged and skipped, losing those words).
        The two short sleeps guard against the clipboard not being set before
        Ctrl+V (would paste stale text) and the next chunk overwriting before
        this paste is consumed.
        """
        try:
            self._last_seq = clip.set_text(text, private=private)
        except clip.ClipboardBusy as e:
            logger.warning("Clipboard busy (%s); typing %d chars instead", e, len(text))
            self._type_text(text)
            return False
        time.sleep(0.025)
        self._keyboard.press(Key.ctrl)
        self._keyboard.press("v")
        self._keyboard.release("v")
        self._keyboard.release(Key.ctrl)
        # Give the target app time to CONSUME this paste before the next chunk
        # overwrites the clipboard, or it would insert the wrong chunk.
        time.sleep(_CHUNK_SETTLE_S)
        return True

    def _type_text(self, text: str) -> None:
        """Type text as Unicode key events — the no-clipboard fallback.

        Line breaks go in as Shift+Enter: a bare Enter would SEND the message
        in chat apps.
        """
        for i, line in enumerate(text.split("\n")):
            if i:
                with self._keyboard.pressed(Key.shift):
                    self._keyboard.press(Key.enter)
                    self._keyboard.release(Key.enter)
            if line:
                self._keyboard.type(line)

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
        self._last_seq = None
        self._streamed = []
        self._saved_clipboard = None
        if not self._config.keep_on_clipboard:
            self._saved_clipboard = clip.snapshot()
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

        if self._config.keep_on_clipboard:
            # The user wants the dictation kept: the WHOLE text, not just the
            # last chunk, and visible in clipboard history.
            if self._streamed:
                time.sleep(_CHUNK_SETTLE_S)
                try:
                    clip.set_text("".join(self._streamed), private=False)
                except Exception as e:
                    logger.warning("Could not leave the dictation on the clipboard: %s", e)
        elif self._saved_clipboard is not None:
            # Delayed + guarded: the final Ctrl+V may still be pending, and
            # restoring underneath it would paste the OLD clipboard instead.
            self._restore_clipboard_later(self._saved_clipboard, self._last_seq)
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
                self._streamed.append(chunk)
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
