from __future__ import annotations

import logging
from typing import Callable

from pynput import keyboard

logger = logging.getLogger("speakup")


# Map string names to pynput key objects
_KEY_MAP: dict[str, keyboard.Key | str] = {
    "ctrl": keyboard.Key.ctrl_l,
    "shift": keyboard.Key.shift,
    "alt": keyboard.Key.alt_l,
    "cmd": keyboard.Key.cmd,
    "win": keyboard.Key.cmd,
    "windows": keyboard.Key.cmd,
    "space": keyboard.Key.space,
    "tab": keyboard.Key.tab,
    "enter": keyboard.Key.enter,
}


def _parse_hotkey(hotkey_str: str) -> set:
    """Parse a hotkey string like 'ctrl+shift+space' into a set of pynput keys."""
    keys = set()
    for part in hotkey_str.lower().split("+"):
        part = part.strip()
        if part in _KEY_MAP:
            keys.add(_KEY_MAP[part])
        else:
            # Single character key
            keys.add(keyboard.KeyCode.from_char(part))
    return keys


def _normalize_key(key: keyboard.Key | keyboard.KeyCode) -> keyboard.Key | keyboard.KeyCode:
    """Normalize a key so left/right modifier variants match."""
    if isinstance(key, keyboard.Key):
        # Map right-side modifiers to their left-side equivalents
        mapping = {
            keyboard.Key.ctrl_r: keyboard.Key.ctrl_l,
            keyboard.Key.shift_r: keyboard.Key.shift,
            keyboard.Key.alt_r: keyboard.Key.alt_l,
            keyboard.Key.alt_gr: keyboard.Key.alt_l,
            keyboard.Key.cmd_r: keyboard.Key.cmd,
        }
        return mapping.get(key, key)
    return key


class HotkeyListener:
    """Listens for a global push-to-talk hotkey.

    Runs a pynput keyboard listener in a daemon thread. Fires
    on_activate when all hotkey keys are pressed, and on_deactivate
    when any hotkey key is released.
    """

    def __init__(
        self,
        hotkey_str: str,
        on_activate: Callable[[], None],
        on_deactivate: Callable[[], None],
    ) -> None:
        self._hotkey_keys = _parse_hotkey(hotkey_str)
        self._pressed_keys: set = set()
        self._is_active = False
        self._on_activate = on_activate
        self._on_deactivate = on_deactivate
        self._listener: keyboard.Listener | None = None

    def _on_press(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        try:
            normalized = _normalize_key(key)
            was_in_set = normalized in self._pressed_keys
            self._pressed_keys.add(normalized)

            if self._hotkey_keys.issubset(self._pressed_keys):
                if not self._is_active:
                    self._is_active = True
                    logger.info("Hotkey activated (all keys pressed)")
                    self._on_activate()
                elif normalized in self._hotkey_keys and not was_in_set:
                    # Key was missing from pressed set but we're still "active" —
                    # means we missed its release event (common with Windows key).
                    # Force deactivate then reactivate.
                    logger.info("Hotkey stale-state recovery: deactivate+reactivate")
                    self._is_active = False
                    self._on_deactivate()
                    self._is_active = True
                    self._on_activate()
        except Exception as e:
            logger.error("Hotkey _on_press error: %s", e, exc_info=True)

    def _on_release(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        try:
            normalized = _normalize_key(key)

            # If we were active and a hotkey key was released, deactivate
            if self._is_active and normalized in self._hotkey_keys:
                self._is_active = False
                logger.info("Hotkey deactivated (key released)")
                self._on_deactivate()

            self._pressed_keys.discard(normalized)
        except Exception as e:
            logger.error("Hotkey _on_release error: %s", e, exc_info=True)

    def start(self) -> None:
        """Start the hotkey listener (non-blocking, runs in a daemon thread)."""
        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._listener.daemon = True
        self._listener.start()
        logger.info("Hotkey listener started (keys: %s)", self._hotkey_keys)

    def stop(self) -> None:
        """Stop the hotkey listener."""
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    def reset_state(self) -> None:
        """Reset pressed keys and active flag.

        Call after pipeline completes to ensure the listener is ready
        for the next activation, even if a key release was missed by the OS.
        """
        self._is_active = False
        self._pressed_keys.clear()

    def update_hotkey(self, hotkey_str: str) -> None:
        """Update the hotkey combination (e.g. from settings)."""
        self._hotkey_keys = _parse_hotkey(hotkey_str)
        self.reset_state()
