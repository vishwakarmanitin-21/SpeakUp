"""Which microphone SpeakUp records from.

Until 2026-11-05 every capture path used whatever Windows called the default
input, with no way to choose. That day the default was a USB mic delivering
digital silence (-84 dBFS) while the built-in mic worked, and every dictation
failed. The choice is now a setting (`input_device`), stored by NAME: device
indexes change whenever something is plugged in or out.
"""
from __future__ import annotations

import logging
import re

import sounddevice as sd

logger = logging.getLogger("speakup")

# Windows renames a re-plugged USB device "Microphone (2- Usb Audio Device)";
# MME also cuts names at 31 characters. Compare names without either quirk.
_NUMBER_PREFIX = re.compile(r"\b\d+- ")


def _normalise(name: str) -> str:
    return _NUMBER_PREFIX.sub("", name).strip(" )").lower()


def _default_hostapi() -> int | None:
    try:
        return sd.query_devices(sd.default.device[0])["hostapi"]
    except Exception:
        return None


def list_input_devices() -> list[str]:
    """Input device names, one per physical mic (the default host API only —
    the same mic otherwise appears once per Windows audio API)."""
    hostapi = _default_hostapi()
    names: list[str] = []
    try:
        for dev in sd.query_devices():
            if dev.get("max_input_channels", 0) <= 0:
                continue
            if hostapi is not None and dev.get("hostapi") != hostapi:
                continue
            name = str(dev.get("name", ""))
            if name and name not in names and "sound mapper" not in name.lower():
                names.append(name)
    except Exception as e:
        logger.debug("Could not list input devices: %s", e)
    return names


def default_input_name() -> str:
    try:
        return str(sd.query_devices(kind="input")["name"])
    except Exception:
        return "unknown"


def resolve_input_device(name: str | None = None) -> int | None:
    """sounddevice index for the chosen mic, or None for the Windows default.

    Exact name first, then the same name ignoring a "2- " re-plug prefix and
    MME's truncation. An unplugged mic falls back to the default (logged).
    """
    if name is None:
        try:
            from src.config import Config
            name = Config().input_device
        except Exception:
            name = ""
    if not name:
        return None
    hostapi = _default_hostapi()
    candidates = []
    try:
        for idx, dev in enumerate(sd.query_devices()):
            if dev.get("max_input_channels", 0) > 0:
                candidates.append((idx, str(dev.get("name", "")), dev.get("hostapi")))
    except Exception:
        return None
    # Search the default host API (MME on Windows) completely — exact, then
    # ignoring the re-plug prefix — before any other: the same mic also exists
    # under WDM-KS, which often can't open at SpeakUp's 16 kHz.
    want = _normalise(name)
    groups = [[c for c in candidates if c[2] == hostapi],
              [c for c in candidates if c[2] != hostapi]]
    for group in groups:
        for idx, dev_name, _ in group:
            if dev_name == name:
                return idx
        for idx, dev_name, _ in group:
            have = _normalise(dev_name)
            if have == want or have.startswith(want) or want.startswith(have):
                return idx
    logger.warning("Chosen microphone %r not found; using the Windows default", name)
    return None


def active_input_name() -> str:
    """Name of the mic a recording will actually use right now."""
    idx = resolve_input_device()
    if idx is None:
        return default_input_name()
    try:
        return str(sd.query_devices(idx)["name"])
    except Exception:
        return "unknown"
