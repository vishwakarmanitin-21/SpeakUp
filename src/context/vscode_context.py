"""VS Code active-file context reader for Windows.

Detects whether VS Code is the foreground window, extracts the active
filename and workspace from the title bar, then attempts to locate and
read the file so its content can be injected as context.
"""
from __future__ import annotations

import ctypes
import json
import logging
import os
import re
import sys
from pathlib import Path

logger = logging.getLogger("speakup")

# VS Code title patterns (Windows uses " - ", some builds use " — ")
# Pattern: "[● ]filename.ext - [subfolder - ]WorkspaceName - Visual Studio Code"
_VSCODE_TITLE_RE = re.compile(
    r"^[●•\u25cf]?\s*(.+?)\s*[-\u2014]\s*(.+?)\s*[-\u2014]\s*Visual Studio Code",
    re.IGNORECASE,
)

# Max chars of file content to include in context
_MAX_FILE_CHARS = 3000


def _get_foreground_window_title() -> str:
    """Return the title of the currently focused window (Windows only)."""
    if sys.platform != "win32":
        return ""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value
    except Exception:
        return ""


def _get_vscode_workspaces() -> list[Path]:
    """Read VS Code's recently opened workspace folders from its storage."""
    appdata = os.environ.get("APPDATA", "")
    if not appdata:
        return []

    storage_path = Path(appdata) / "Code" / "User" / "globalStorage" / "storage.json"
    if not storage_path.exists():
        return []

    try:
        with open(storage_path, encoding="utf-8") as f:
            data = json.load(f)

        workspaces: list[Path] = []
        # VS Code stores recent folders under openedPathsList
        for key in ("openedPathsList.workspaces3", "openedPathsList.folders"):
            for entry in data.get(key, []):
                # entries are like {"folderUri": "file:///C:/Users/..."}
                uri = entry if isinstance(entry, str) else entry.get("folderUri", "")
                if uri.startswith("file:///"):
                    folder = Path(uri[8:].replace("/", "\\"))
                    if folder.exists():
                        workspaces.append(folder)
        return workspaces
    except Exception:
        return []


def _find_file(filename: str, workspace_name: str) -> Path | None:
    """Try to locate the file by searching VS Code workspace folders."""
    search_roots: list[Path] = []

    # 1. Known VS Code workspaces from storage
    search_roots.extend(_get_vscode_workspaces())

    # 2. Common dev locations as fallback
    home = Path.home()
    for candidate in [
        home / "OneDrive" / "Documents" / "GitHub",
        home / "Documents" / "GitHub",
        home / "Projects",
        home / "Dev",
        home / "Desktop",
        home / "Documents",
        home,
    ]:
        if candidate.exists():
            search_roots.append(candidate)

    seen: set[Path] = set()
    for root in search_roots:
        if root in seen:
            continue
        seen.add(root)
        # Search up to 4 levels deep to avoid huge trees
        try:
            for match in root.rglob(filename):
                if match.is_file():
                    return match
        except PermissionError:
            pass

    return None


def get_vscode_file_context() -> str | None:
    """Return active VS Code file content as a context string, or None.

    Only runs on Windows. Returns None when:
    - VS Code is not the foreground window
    - The active filename can't be parsed from the title
    - The file can't be located on disk
    """
    if sys.platform != "win32":
        return None

    title = _get_foreground_window_title()
    if "Visual Studio Code" not in title:
        return None

    match = _VSCODE_TITLE_RE.match(title)
    if not match:
        return None

    filename = match.group(1).strip()
    workspace_name = match.group(2).strip()

    # Strip leading ● or modification marker
    filename = filename.lstrip("●•\u25cf").strip()

    logger.debug("VS Code active file: %s (workspace: %s)", filename, workspace_name)

    file_path = _find_file(filename, workspace_name)
    if file_path is None:
        # Still provide minimal context if we know the filename
        return f"[VS Code: {filename} in {workspace_name}]"

    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        if len(content) > _MAX_FILE_CHARS:
            content = content[:_MAX_FILE_CHARS] + "\n… (truncated)"
        return f"[VS Code — {filename}]\n{content}"
    except Exception as e:
        logger.warning("Could not read VS Code file %s: %s", file_path, e)
        return f"[VS Code: {filename} in {workspace_name}]"
