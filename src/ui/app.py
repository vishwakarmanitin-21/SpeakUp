from __future__ import annotations

import asyncio
import logging
import os
import sys
import webbrowser
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QInputDialog,
    QLineEdit,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
)
from qasync import QEventLoop

from src.config import Config
from src.hotkeys.listener import HotkeyListener
from src.services.error_handler import setup_logging
from src.services.pipeline import Pipeline
from src.ui.overlay import OverlayWidget

logger = logging.getLogger("speakup")


def _make_tray_pixmap(size: int = 64) -> QPixmap:
    """Draw a simple microphone icon for the system tray."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    accent = QColor("#4FC3F7")
    pen = QPen(accent, max(2, size // 16), Qt.SolidLine, Qt.RoundCap)
    # Mic body (filled rounded rect)
    p.setPen(Qt.NoPen)
    p.setBrush(accent)
    bw, bh = size * 0.35, size * 0.45
    bx = (size - bw) / 2
    p.drawRoundedRect(int(bx), int(size * 0.08), int(bw), int(bh), bw / 2, bw / 2)
    # Arc (half-circle cradle under mic)
    p.setBrush(Qt.NoBrush)
    p.setPen(pen)
    arc_w, arc_h = size * 0.55, size * 0.38
    ax = (size - arc_w) / 2
    ay = size * 0.28
    p.drawArc(int(ax), int(ay), int(arc_w), int(arc_h), 0, -180 * 16)
    # Stand (vertical line + base)
    cx = size / 2
    top_y = ay + arc_h / 2
    base_y = size * 0.82
    p.drawLine(int(cx), int(top_y), int(cx), int(base_y))
    base_half = size * 0.18
    p.drawLine(int(cx - base_half), int(base_y), int(cx + base_half), int(base_y))
    p.end()
    return pm


def _app_icon() -> QIcon:
    """Return the SpeakUp icon from the bundled PNG, falling back to a drawn one."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS"))
    else:
        base = Path(__file__).resolve().parent.parent.parent / "assets"
    png = base / "icon.png"
    if png.exists():
        return QIcon(str(png))
    return QIcon(_make_tray_pixmap())


def _open_user_guide() -> None:
    """Open the bundled HTML user guide in the default browser."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS"))
    else:
        base = Path(__file__).resolve().parent.parent.parent
    guide = base / "user_guide.html"
    try:
        if guide.exists():
            webbrowser.open(guide.as_uri())
        else:
            webbrowser.open(
                "https://github.com/vishwakarmanitin-21/Speak-up/blob/main/USER_GUIDE.md"
            )
    except Exception as e:
        logger.warning("Could not open user guide: %s", e)


def _create_tray_icon(
    app: QApplication,
    overlay: OverlayWidget,
) -> QSystemTrayIcon:
    """Create system tray icon with context menu."""
    tray = QSystemTrayIcon(app)
    tray.setIcon(_app_icon())
    tray.setToolTip("SpeakUp - Voice AI Assistant")

    menu = QMenu()

    show_action = QAction("Show/Hide", menu)
    show_action.triggered.connect(overlay.toggle_visibility)
    menu.addAction(show_action)

    settings_action = QAction("Settings", menu)
    settings_action.triggered.connect(overlay.open_settings)
    menu.addAction(settings_action)

    guide_action = QAction("User Guide", menu)
    guide_action.triggered.connect(_open_user_guide)
    menu.addAction(guide_action)

    menu.addSeparator()

    quit_action = QAction("Quit", menu)
    quit_action.triggered.connect(app.quit)
    menu.addAction(quit_action)

    tray.setContextMenu(menu)
    tray.show()
    return tray


def _ensure_api_key_present() -> bool:
    """Offer first-run key entry. Returns True if a key is set; never blocks launch.

    If the user has no key yet, they can cancel — the app still opens and they
    can add the key any time from the tray menu -> Settings.
    """
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if key and key != "sk-your-key-here":
        return True

    text, ok = QInputDialog.getText(
        None,
        "SpeakUp - Welcome",
        "Enter your OpenAI API key to start dictating.\n"
        "(Stored privately on this PC; never shared.)\n\n"
        "No key yet? Click Cancel — SpeakUp will still open, and you can add it\n"
        "any time from the tray menu → Settings.",
        echo=QLineEdit.Password,
    )

    if ok and text.strip():
        api_key = text.strip()
        os.environ["OPENAI_API_KEY"] = api_key
        try:
            env_path = Config().env_path
            with open(env_path, "w", encoding="utf-8") as f:
                f.write(f"OPENAI_API_KEY={api_key}\n")
            Config().reload()
            logger.info("API key saved")
        except Exception as e:
            logger.error("Could not save API key: %s", e)
        return True
    return False


def run_app() -> None:
    """Main entry point for the GUI application."""
    setup_logging()
    logger.info("SpeakUp starting...")

    app = QApplication(sys.argv)
    app.setApplicationName("SpeakUp")
    app.setWindowIcon(_app_icon())
    app.setQuitOnLastWindowClosed(False)

    # Set up asyncio event loop integrated with Qt
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    # Load config (this loads .env)
    config = Config()

    # First run: offer key entry, but NEVER block launch — the app opens either
    # way and the user can add the key any time from tray → Settings.
    has_key = _ensure_api_key_present()

    # Create pipeline and overlay
    pipeline = Pipeline()
    overlay = OverlayWidget(pipeline=pipeline)
    overlay.show()

    # System tray
    _tray = _create_tray_icon(app, overlay)  # noqa: F841 -- prevent GC
    if not has_key:
        _tray.showMessage(
            "SpeakUp",
            "Add your OpenAI API key in Settings (tray → Settings) to start dictating.",
            QSystemTrayIcon.Information,
            8000,
        )

    # Connect hotkey listener to overlay signals
    hotkey = HotkeyListener(
        hotkey_str=config.hotkey,
        on_activate=overlay.on_hotkey_pressed,
        on_deactivate=overlay.on_hotkey_released,
    )
    hotkey.start()
    # Give overlay a reference so Settings can update the hotkey live
    overlay.set_hotkey_listener(hotkey)


    # Log unhandled exceptions in async tasks so they don't vanish silently
    def _handle_exception(loop_ref, context):
        exc = context.get("exception")
        if exc:
            logger.error("Unhandled async exception: %s", exc, exc_info=exc)
        else:
            logger.error("Unhandled async error: %s", context.get("message"))

    loop.set_exception_handler(_handle_exception)

    logger.info("SpeakUp GUI started. Hotkey: %s", config.hotkey)
    print(f"SpeakUp GUI started. Hotkey: {config.hotkey}")
    print("Use the system tray icon to quit.")

    with loop:
        loop.run_forever()
