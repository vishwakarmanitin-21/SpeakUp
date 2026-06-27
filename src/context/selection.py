from __future__ import annotations

import logging
import time

import pyperclip
from pynput.keyboard import Controller, Key

logger = logging.getLogger("speakup")

# Windows where a simulated Ctrl+C is dangerous: a console interprets it as
# SIGINT and would terminate this application. Skip selection capture there.
_TERMINAL_APPS = {
    "windowsterminal", "wt", "powershell", "pwsh", "cmd", "conhost", "python", "py",
}


def get_selected_text() -> str | None:
    """Attempt to get currently selected text from the active window.

    Strategy: save clipboard, simulate Ctrl+C, read clipboard, restore original.
    Returns None if no text was selected, or if the active window is a terminal
    (a simulated Ctrl+C in a console is read as SIGINT and would kill the app).

    Note: This should be called *before* recording starts, not during.
    The simulated keystrokes could interfere with the user's workflow.
    """
    # Never simulate Ctrl+C into a console window — it becomes SIGINT.
    try:
        from src.context.active_window import _foreground
        exe, _title = _foreground()
        if exe in _TERMINAL_APPS:
            logger.debug("Skipping selection capture in terminal app: %s", exe)
            return None
    except Exception:
        pass

    keyboard = Controller()
    original_clipboard = ""
    try:
        original_clipboard = pyperclip.paste()
    except Exception:
        pass

    try:
        # Clear clipboard
        pyperclip.copy("")

        # Simulate Ctrl+C
        keyboard.press(Key.ctrl)
        keyboard.press("c")
        keyboard.release("c")
        keyboard.release(Key.ctrl)

        # Brief delay for clipboard to update
        time.sleep(0.15)

        selected = pyperclip.paste()

        if selected and selected.strip():
            return selected.strip()
        return None

    except BaseException:
        # BaseException (not just Exception) so a self-inflicted Ctrl+C reaching
        # a console — raised as KeyboardInterrupt — can never crash the app.
        logger.debug("Selection capture aborted", exc_info=True)
        return None
    finally:
        # Restore original clipboard
        try:
            pyperclip.copy(original_clipboard)
        except Exception:
            pass
