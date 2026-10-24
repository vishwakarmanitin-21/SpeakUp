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


# Windows virtual-key codes per hotkey key. Generic codes (either side) for
# modifiers, because _normalize_key folds left and right together.
_VK_ANY_SIDE: dict = {
    keyboard.Key.ctrl_l: (0x11,),          # VK_CONTROL
    keyboard.Key.shift: (0x10,),           # VK_SHIFT
    keyboard.Key.alt_l: (0x12,),           # VK_MENU
    keyboard.Key.cmd: (0x5B, 0x5C),        # VK_LWIN, VK_RWIN
    keyboard.Key.space: (0x20,),
    keyboard.Key.tab: (0x09,),
    keyboard.Key.enter: (0x0D,),
}


def _vk_codes(key) -> tuple[int, ...]:
    if key in _VK_ANY_SIDE:
        return _VK_ANY_SIDE[key]
    vk = getattr(key, "vk", None)
    if vk is None and getattr(key, "char", None):
        import ctypes
        fn = ctypes.windll.user32.VkKeyScanW
        fn.restype = ctypes.c_short  # -1 = no key produces this character
        scan = fn(key.char)
        vk = scan & 0xFF if scan != -1 else None
    return (vk,) if vk else ()


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

    def keys_physically_down(self) -> bool | None:
        """Ask Windows whether every hotkey key is held RIGHT NOW.

        The press/release events can be lost (lock screen, desktop switch,
        sleep, the Windows key's own shortcuts); the async key state can't.
        Returns None when it can't be determined (not Windows / no code).
        """
        try:
            import ctypes
            get = ctypes.windll.user32.GetAsyncKeyState
        except Exception:
            return None
        for key in self._hotkey_keys:
            codes = _vk_codes(key)
            if not codes:
                return None
            if not any(get(vk) & 0x8000 for vk in codes):
                return False
        return True

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
