from __future__ import annotations

import pyperclip
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.output.inserter import OutputInserter, OutputMode


class PreviewWindow(QWidget):
    """Shows rewritten text with action buttons."""

    closed = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setWindowTitle("SpeakUp - Preview")
        self.setMinimumSize(450, 300)
        self._inserter = OutputInserter()
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        self._text_edit = QTextEdit()
        self._text_edit.setReadOnly(True)
        self._text_edit.setStyleSheet(
            "QTextEdit { background-color: #1e1e1e; color: #ddd; "
            "font-size: 13px; padding: 8px; border: 1px solid #444; }"
        )
        layout.addWidget(self._text_edit)

        btn_layout = QHBoxLayout()
        self._copy_btn = QPushButton("Copy to Clipboard")
        self._insert_btn = QPushButton("Insert at Cursor")
        self._close_btn = QPushButton("Close")

        for btn in (self._copy_btn, self._insert_btn, self._close_btn):
            btn.setStyleSheet(
                "QPushButton { background-color: #3d3d3d; color: white; "
                "border: 1px solid #555; padding: 6px 16px; border-radius: 4px; }"
                "QPushButton:hover { background-color: #555; }"
            )

        btn_layout.addWidget(self._copy_btn)
        btn_layout.addWidget(self._insert_btn)
        btn_layout.addWidget(self._close_btn)
        layout.addLayout(btn_layout)

        self._copy_btn.clicked.connect(self._on_copy)
        self._insert_btn.clicked.connect(self._on_insert)
        self._close_btn.clicked.connect(self._on_close)

    def show_result(self, text: str) -> None:
        self._text_edit.setPlainText(text)
        self.show()
        self.raise_()

    def _on_copy(self) -> None:
        text = self._text_edit.toPlainText()
        pyperclip.copy(text)

    def _on_insert(self) -> None:
        text = self._text_edit.toPlainText()
        self._inserter.deliver(text, OutputMode.AUTO_PASTE)
        self._on_close()

    def _on_close(self) -> None:
        self.hide()
        self.closed.emit()
