from __future__ import annotations

import asyncio
import logging
import os
import sys

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QInputDialog,
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

logger = logging.getLogger("flowai")


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


def _create_tray_icon(
    app: QApplication,
    overlay: OverlayWidget,
) -> QSystemTrayIcon:
    """Create system tray icon with context menu."""
    tray = QSystemTrayIcon(app)
    tray.setIcon(QIcon(_make_tray_pixmap()))
    tray.setToolTip("FlowAI - Voice AI Assistant")

    menu = QMenu()

    show_action = QAction("Show/Hide", menu)
    show_action.triggered.connect(overlay.toggle_visibility)
    menu.addAction(show_action)

    settings_action = QAction("Settings", menu)
    settings_action.triggered.connect(overlay.open_settings)
    menu.addAction(settings_action)

    menu.addSeparator()

    quit_action = QAction("Quit", menu)
    quit_action.triggered.connect(app.quit)
    menu.addAction(quit_action)

    tray.setContextMenu(menu)
    tray.show()
    return tray


def _check_api_key() -> bool:
    """Check if the OpenAI API key is set. Prompt the user if not."""
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if key and key != "sk-your-key-here":
        return True

    # Show first-run dialog
    text, ok = QInputDialog.getText(
        None,
        "FlowAI - First Run Setup",
        "Enter your OpenAI API key to get started:\n"
        "(This will be saved to .env in the project root)",
    )

    if ok and text.strip():
        api_key = text.strip()
        os.environ["OPENAI_API_KEY"] = api_key

        # Write to .env file (use the config-resolved path so it lands next to
        # the exe when frozen, not in the temporary PyInstaller extract dir).
        env_path = Config().env_path
        with open(env_path, "w", encoding="utf-8") as f:
            f.write(f"OPENAI_API_KEY={api_key}\n")

        logger.info("API key saved to .env")
        return True
    else:
        QMessageBox.warning(
            None,
            "FlowAI",
            "An OpenAI API key is required.\n"
            "Copy .env.example to .env and add your key,\n"
            "or restart FlowAI and enter it when prompted.",
        )
        return False


def run_app() -> None:
    """Main entry point for the GUI application."""
    setup_logging()
    logger.info("FlowAI starting...")

    app = QApplication(sys.argv)
    app.setApplicationName("FlowAI")
    app.setQuitOnLastWindowClosed(False)

    # Set up asyncio event loop integrated with Qt
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    # Load config (this loads .env)
    config = Config()

    # Check API key (first-run experience)
    if not _check_api_key():
        sys.exit(1)

    # Create pipeline and overlay
    pipeline = Pipeline()
    overlay = OverlayWidget(pipeline=pipeline)
    overlay.show()

    # System tray
    _tray = _create_tray_icon(app, overlay)  # noqa: F841 -- prevent GC

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

    logger.info("FlowAI GUI started. Hotkey: %s", config.hotkey)
    print(f"FlowAI GUI started. Hotkey: {config.hotkey}")
    print("Use the system tray icon to quit.")

    with loop:
        loop.run_forever()
