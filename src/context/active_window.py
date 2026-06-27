"""Foreground application detection for the Smart (context-aware) rewrite mode.

Windows-only. Identifies which app the user is dictating into so the rewrite
can match the right tone and format (chat vs email vs editor vs document).
Falls back to a neutral 'general' surface on any failure or non-Windows OS.
"""
from __future__ import annotations

import ctypes
import logging
import sys

logger = logging.getLogger("flowai")

# Process exe name (lowercased, without .exe) -> (friendly label, surface)
_APP_MAP: dict[str, tuple[str, str]] = {
    "slack": ("Slack", "chat"),
    "teams": ("Microsoft Teams", "chat"),
    "ms-teams": ("Microsoft Teams", "chat"),
    "discord": ("Discord", "chat"),
    "telegram": ("Telegram", "chat"),
    "whatsapp": ("WhatsApp", "chat"),
    "outlook": ("Outlook", "email"),
    "hxoutlook": ("Outlook", "email"),
    "thunderbird": ("Thunderbird", "email"),
    "code": ("VS Code", "editor"),
    "code - insiders": ("VS Code", "editor"),
    "cursor": ("Cursor", "editor"),
    "devenv": ("Visual Studio", "editor"),
    "idea64": ("IntelliJ IDEA", "editor"),
    "pycharm64": ("PyCharm", "editor"),
    "sublime_text": ("Sublime Text", "editor"),
    "windowsterminal": ("Terminal", "editor"),
    "wt": ("Terminal", "editor"),
    "powershell": ("PowerShell", "editor"),
    "pwsh": ("PowerShell", "editor"),
    "cmd": ("Command Prompt", "editor"),
    "winword": ("Word", "document"),
    "notion": ("Notion", "document"),
    "obsidian": ("Obsidian", "document"),
    "onenote": ("OneNote", "document"),
    "notepad": ("Notepad", "document"),
}

_BROWSERS = {"chrome", "msedge", "firefox", "brave", "opera", "arc", "vivaldi"}


def _foreground() -> tuple[str, str]:
    """Return (exe_name_without_ext_lower, window_title) for the foreground window."""
    if sys.platform != "win32":
        return ("", "")
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ("", "")

        # Window title
        length = user32.GetWindowTextLengthW(hwnd)
        title = ""
        if length:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value

        # Owning process id
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        # Process executable name
        exe = ""
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if handle:
            try:
                size = ctypes.c_ulong(260)
                name_buf = ctypes.create_unicode_buffer(size.value)
                if kernel32.QueryFullProcessImageNameW(
                    handle, 0, name_buf, ctypes.byref(size)
                ):
                    exe = name_buf.value.rsplit("\\", 1)[-1]
            finally:
                kernel32.CloseHandle(handle)

        exe = exe.lower()
        if exe.endswith(".exe"):
            exe = exe[:-4]
        return (exe, title)
    except Exception as e:  # pragma: no cover - platform/edge dependent
        logger.debug("Active window detection failed: %s", e)
        return ("", "")


def detect_active_app() -> tuple[str, str]:
    """Return (friendly_label, surface) for the foreground app.

    surface is one of: chat | email | editor | document | browser | general.
    Returns ("", "general") when the app is unknown or detection fails.
    """
    exe, title = _foreground()
    if not exe:
        return ("", "general")

    if exe in _APP_MAP:
        return _APP_MAP[exe]

    if exe in _BROWSERS:
        # Refine the browser surface from the tab title where possible.
        t = title.lower()
        if "gmail" in t or "outlook" in t or "proton mail" in t or " - mail" in t:
            return ("Webmail", "email")
        if "slack" in t or "discord" in t or "teams" in t or "messenger" in t:
            return ("Web chat", "chat")
        if "google docs" in t or "docs.google" in t or "notion" in t or "confluence" in t:
            return ("Web doc", "document")
        return ("Browser", "browser")

    return (exe, "general")
