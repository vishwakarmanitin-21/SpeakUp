"""About dialog — version, authorship, and links.

Gives users of the exe / repo a clear record of who created SpeakUp.
"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout

from src.version import APP_NAME, AUTHOR, GITHUB_URL, TAGLINE, __version__

_STYLE = """
    QDialog { background-color: #262626; }
    QLabel { color: #e8e8e8; }
    QLabel#title { color: #4FC3F7; font-size: 20px; font-weight: bold; }
    QLabel#muted { color: #9aa4b0; font-size: 12px; }
    QLabel a { color: #4FC3F7; }
    QPushButton {
        background-color: #4FC3F7; color: #062430; border: none;
        border-radius: 7px; padding: 8px 18px; font-weight: bold;
    }
    QPushButton:hover { background-color: #6fd0fb; }
"""


class AboutDialog(QDialog):
    """Small, themed About box."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"About {APP_NAME}")
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.setMinimumWidth(380)
        self.setStyleSheet(_STYLE)

        lay = QVBoxLayout(self)

        title = QLabel(f"{APP_NAME}  v{__version__}")
        title.setObjectName("title")
        lay.addWidget(title)

        tagline = QLabel(TAGLINE)
        tagline.setWordWrap(True)
        lay.addWidget(tagline)
        lay.addSpacing(8)

        created = QLabel(f"Created by <b>{AUTHOR}</b>")
        created.setTextFormat(Qt.RichText)
        lay.addWidget(created)

        link = QLabel(f'<a href="{GITHUB_URL}">{GITHUB_URL}</a>')
        link.setTextFormat(Qt.RichText)
        link.setOpenExternalLinks(True)
        link.setWordWrap(True)
        lay.addWidget(link)

        note = QLabel("Free & open-source (MIT). Built by orchestrating AI.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        lay.addSpacing(6)
        lay.addWidget(note)

        lay.addSpacing(10)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        lay.addWidget(close_btn, alignment=Qt.AlignRight)
