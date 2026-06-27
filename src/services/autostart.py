"""Manage SpeakUp auto-start with Windows startup via the registry."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

logger = logging.getLogger("speakup")

_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_APP_NAME = "SpeakUp"


def _get_launch_command() -> str:
    """Return the command that Windows should execute at startup.

    When running from a PyInstaller bundle, use the .exe path directly.
    Otherwise, use the VBS launcher (no console window) if it exists,
    falling back to pythonw.exe -m src.main.
    """
    # PyInstaller frozen exe
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'

    # Development mode — prefer the VBS launcher
    project_root = Path(__file__).resolve().parent.parent.parent
    vbs_path = project_root / "SpeakUp.vbs"
    if vbs_path.exists():
        return f'wscript.exe "{vbs_path}"'

    # Fallback: pythonw.exe in the venv
    pythonw = project_root / ".venv" / "Scripts" / "pythonw.exe"
    if pythonw.exists():
        return f'"{pythonw}" -m src.main'

    # Last resort
    return f'"{sys.executable}" -m src.main'


def is_autostart_enabled() -> bool:
    """Check whether SpeakUp is registered in Windows startup."""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_KEY, 0, winreg.KEY_READ)
        try:
            winreg.QueryValueEx(key, _APP_NAME)
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except OSError:
        return False


def set_autostart(enable: bool) -> None:
    """Enable or disable SpeakUp auto-start with Windows."""
    if sys.platform != "win32":
        logger.warning("Auto-start is only supported on Windows")
        return

    import winreg

    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _REG_KEY, 0, winreg.KEY_SET_VALUE
        )
        try:
            if enable:
                cmd = _get_launch_command()
                winreg.SetValueEx(key, _APP_NAME, 0, winreg.REG_SZ, cmd)
                logger.info("Auto-start enabled: %s", cmd)
            else:
                try:
                    winreg.DeleteValue(key, _APP_NAME)
                    logger.info("Auto-start disabled")
                except FileNotFoundError:
                    pass  # Already removed
        finally:
            winreg.CloseKey(key)
    except OSError as e:
        logger.error("Failed to update auto-start registry: %s", e)
        raise
