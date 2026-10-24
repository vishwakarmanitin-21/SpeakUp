"""Windows clipboard access that keeps everything the user had copied.

pyperclip only speaks plain text: with an image, a file or anything else on the
clipboard it read back "" and SpeakUp later "restored" that "" — destroying
what the user had copied. Every streamed chunk also landed in Win+V history
(and cloud clipboard sync). This module, via the Win32 API directly:

  * snapshots and restores ALL memory-backed formats (text, rich text, HTML,
    images as DIB, copied files as HDROP, app-private formats);
  * marks SpeakUp's own temporary writes so clipboard history, cloud sync and
    clipboard managers skip them;
  * retries OpenClipboard, which fails while another app briefly holds it
    (seen in the log as "Error calling OpenClipboard").
"""
from __future__ import annotations

import ctypes
import logging
import time
from ctypes import wintypes

logger = logging.getLogger("speakup")

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_user32.OpenClipboard.argtypes = [wintypes.HWND]
_user32.OpenClipboard.restype = wintypes.BOOL
_user32.CloseClipboard.restype = wintypes.BOOL
_user32.EmptyClipboard.restype = wintypes.BOOL
_user32.EnumClipboardFormats.argtypes = [wintypes.UINT]
_user32.EnumClipboardFormats.restype = wintypes.UINT
_user32.GetClipboardData.argtypes = [wintypes.UINT]
_user32.GetClipboardData.restype = wintypes.HANDLE
_user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
_user32.SetClipboardData.restype = wintypes.HANDLE
_user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
_user32.RegisterClipboardFormatW.restype = wintypes.UINT
_user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
_kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
_kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
_kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
_kernel32.GlobalLock.restype = wintypes.LPVOID
_kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
_kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
_kernel32.GlobalSize.restype = ctypes.c_size_t
_kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]

_GMEM_MOVEABLE = 0x0002
CF_UNICODETEXT = 13
# GDI-handle formats are not memory blocks and can't be copied byte-for-byte.
# Windows re-synthesises the bitmap ones from CF_DIB / CF_DIBV5, which we keep.
_HANDLE_FORMATS = {2, 3, 9, 14, 0x80, 0x82, 0x83, 0x8E}  # BITMAP, METAFILEPICT,
# PALETTE, ENHMETAFILE, OWNERDISPLAY, DSPBITMAP, DSPMETAFILEPICT, DSPENHMETAFILE
_MAX_SNAPSHOT_BYTES = 64 * 1024 * 1024

_OPEN_TRIES = 10
_OPEN_BACKOFF_S = 0.02


class ClipboardBusy(RuntimeError):
    """Another app kept the clipboard open through every retry."""


def _fmt(name: str) -> int:
    return _user32.RegisterClipboardFormatW(name)


# Documented by Microsoft for apps that put transient data on the clipboard.
_EXCLUDE_FROM_MONITORS = _fmt("ExcludeClipboardContentFromMonitorProcessing")
_CAN_INCLUDE_IN_HISTORY = _fmt("CanIncludeInClipboardHistory")
_CAN_UPLOAD_TO_CLOUD = _fmt("CanUploadToCloudClipboard")


class _Open:
    """Context manager: OpenClipboard with retries, always closed afterwards."""

    def __enter__(self):
        for attempt in range(_OPEN_TRIES):
            if _user32.OpenClipboard(None):
                return self
            time.sleep(_OPEN_BACKOFF_S * (attempt + 1))
        raise ClipboardBusy(f"clipboard busy (error {ctypes.get_last_error()})")

    def __exit__(self, *exc):
        _user32.CloseClipboard()
        return False


def sequence() -> int:
    """Changes every time anything writes the clipboard."""
    return _user32.GetClipboardSequenceNumber()


def _alloc(data: bytes) -> int:
    h = _kernel32.GlobalAlloc(_GMEM_MOVEABLE, max(len(data), 1))
    if not h:
        raise MemoryError("GlobalAlloc failed")
    p = _kernel32.GlobalLock(h)
    ctypes.memmove(p, data, len(data))
    _kernel32.GlobalUnlock(h)
    return h


def _put(fmt: int, data: bytes) -> None:
    h = _alloc(data)
    if not _user32.SetClipboardData(fmt, h):
        _kernel32.GlobalFree(h)  # ownership only passes on success


def _mark_private() -> None:
    _put(_EXCLUDE_FROM_MONITORS, b"\x00")
    _put(_CAN_INCLUDE_IN_HISTORY, (0).to_bytes(4, "little"))
    _put(_CAN_UPLOAD_TO_CLOUD, (0).to_bytes(4, "little"))


def snapshot() -> dict[int, bytes] | None:
    """Every copyable format currently on the clipboard ({} if empty).

    None when it can't be captured (busy, or absurdly large) — the caller
    must then NOT restore, rather than overwrite the user's copy with nothing.
    """
    try:
        with _Open():
            out: dict[int, bytes] = {}
            total = 0
            fmt = _user32.EnumClipboardFormats(0)
            while fmt:
                if fmt not in _HANDLE_FORMATS:
                    h = _user32.GetClipboardData(fmt)
                    if h:
                        size = _kernel32.GlobalSize(h)
                        p = _kernel32.GlobalLock(h) if size else None
                        if p:
                            try:
                                out[fmt] = ctypes.string_at(p, size)
                            finally:
                                _kernel32.GlobalUnlock(h)
                            total += size
                            if total > _MAX_SNAPSHOT_BYTES:
                                logger.info("Clipboard too large to snapshot; won't restore")
                                return None
                fmt = _user32.EnumClipboardFormats(fmt)
            return out
    except Exception as e:
        logger.warning("Clipboard snapshot failed: %s", e)
        return None


def restore(saved: dict[int, bytes]) -> None:
    """Put a snapshot back (an empty one empties the clipboard).

    Marked so clipboard history doesn't record the user's own item twice.
    """
    with _Open():
        _user32.EmptyClipboard()
        for fmt, data in saved.items():
            if fmt in (_EXCLUDE_FROM_MONITORS, _CAN_INCLUDE_IN_HISTORY, _CAN_UPLOAD_TO_CLOUD):
                continue
            _put(fmt, data)
        if saved:
            _mark_private()


def set_text(text: str, private: bool = True) -> int:
    """Replace the clipboard with `text`; returns the new sequence number.

    private=True keeps it out of Win+V history, cloud sync and clipboard
    managers — right for SpeakUp's transient paste chunks.
    """
    with _Open():
        _user32.EmptyClipboard()
        _put(CF_UNICODETEXT, (text + "\0").encode("utf-16-le"))
        if private:
            _mark_private()
    return sequence()


def get_text() -> str:
    with _Open():
        h = _user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return ""
        p = _kernel32.GlobalLock(h)
        try:
            return ctypes.wstring_at(p) if p else ""
        finally:
            _kernel32.GlobalUnlock(h)
