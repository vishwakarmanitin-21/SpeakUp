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
                "https://github.com/vishwakarmanitin-21/SpeakUp/blob/main/USER_GUIDE.md"
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

    usage_action = QAction("Usage && cost…", menu)
    usage_action.triggered.connect(_show_usage)
    menu.addAction(usage_action)

    setup_action = QAction("Run setup again", menu)
    setup_action.triggered.connect(_run_onboarding_again)
    menu.addAction(setup_action)

    about_action = QAction("About SpeakUp", menu)
    about_action.triggered.connect(_show_about)
    menu.addAction(about_action)

    menu.addSeparator()

    quit_action = QAction("Quit", menu)
    quit_action.triggered.connect(app.quit)
    menu.addAction(quit_action)

    tray.setContextMenu(menu)
    tray.show()
    return tray


def _run_first_run_if_needed() -> bool:
    """Show the onboarding wizard on first run. Returns True if a key is set.

    Never blocks launch — onboarding is skippable and the key can be added later
    from tray → Settings. Marks itself complete so it won't reappear.
    """
    from src.ui.components.onboarding_dialog import OnboardingDialog

    if not Config().onboarding_complete:
        try:
            OnboardingDialog().exec_()
        except Exception as e:
            logger.warning("Onboarding failed: %s", e)
    return OnboardingDialog.has_api_key()


def _show_about() -> None:
    """Open the About dialog (version + authorship + links)."""
    try:
        from src.ui.components.about_dialog import AboutDialog
        AboutDialog().exec_()
    except Exception as e:
        logger.warning("Could not open About: %s", e)


def _run_onboarding_again() -> None:
    """Re-open the setup wizard from the tray."""
    try:
        from src.ui.components.onboarding_dialog import OnboardingDialog
        OnboardingDialog().exec_()
    except Exception as e:
        logger.warning("Could not open setup: %s", e)


def _show_usage() -> None:
    """Show a usage + approximate-cost summary."""
    try:
        from src.services.usage_tracker import get_cost_summary, get_summary
        s = get_summary()
        c = get_cost_summary()
        msg = (
            f"This month ({c['month_label']}):\n"
            f"   • {c['month_runs']} dictations\n"
            f"   • ~${c['month_cost']:.2f} estimated\n\n"
            f"Lifetime:\n"
            f"   • {s['total_runs']} dictations\n"
            f"   • {s['total_words_generated']:,} words written\n"
            f"   • ~${c['total_cost']:.2f} estimated total"
            f" (~${c['avg_cost']:.4f} per dictation)\n"
            f"   • ~{s['estimated_minutes_saved']:.0f} minutes of typing saved\n\n"
            "Costs are rough estimates from public list prices — check your "
            "OpenAI / Deepgram dashboard for exact billing."
        )
        QMessageBox.information(None, "SpeakUp — Usage & cost", msg)
    except Exception as e:
        QMessageBox.warning(None, "SpeakUp — Usage & cost", f"Couldn't load usage: {e}")


def run_app() -> None:
    """Main entry point for the GUI application."""
    setup_logging()
    logger.info("SpeakUp starting...")

    # Resolve hosts via public DNS if the system resolver fails (some routers
    # refuse api.deepgram.com) so live transcription keeps working.
    try:
        from src.services.dns_resilience import install as install_dns_resilience
        install_dns_resilience()
    except Exception as e:
        logger.debug("DNS resilience unavailable: %s", e)

    app = QApplication(sys.argv)
    app.setApplicationName("SpeakUp")
    app.setWindowIcon(_app_icon())
    app.setQuitOnLastWindowClosed(False)

    # Set up asyncio event loop integrated with Qt
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    # Load config (this loads .env)
    config = Config()

    # First run: show the onboarding wizard (skippable), but NEVER block launch —
    # the app opens either way and the user can add the key later via Settings.
    has_key = _run_first_run_if_needed()

    # Create pipeline and overlay
    pipeline = Pipeline()
    overlay = OverlayWidget(pipeline=pipeline)
    overlay.show()

    # System tray
    _tray = _create_tray_icon(app, overlay)  # noqa: F841 -- prevent GC

    # Quiet hints (e.g. live transcription fell back to standard mode) → tray
    # balloon, debounced so it can't spam (at most once per 60s).
    import time as _time
    _last_notice = {"t": 0.0}

    def _show_notice(msg: str) -> None:
        now = _time.monotonic()
        if now - _last_notice["t"] < 60.0:
            return
        _last_notice["t"] = now
        _tray.showMessage("SpeakUp", msg, QSystemTrayIcon.Information, 4000)

    overlay.notice_updated.connect(_show_notice)
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
