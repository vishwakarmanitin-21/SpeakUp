from __future__ import annotations

import os
import sys

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.config import Config
from src.output.inserter import OutputMode
from src.rewrite.modes import RewriteMode


class SettingsDialog(QDialog):
    """Application settings dialog."""

    def __init__(self, parent=None, hotkey_listener=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("SpeakUp Settings")
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.setMinimumWidth(450)
        self._config = Config()
        self._hotkey_listener = hotkey_listener
        try:
            from src.services.vocab_learner import VocabLearner
            self._vocab_learner = VocabLearner()
        except Exception:
            self._vocab_learner = None
        self._setup_ui()
        self._load_current_settings()

    def _setup_ui(self) -> None:
        # Scrollable content so the dialog never overflows small screens;
        # the Save/Cancel row stays fixed at the bottom.
        outer = QVBoxLayout(self)
        content = QWidget()
        content.setObjectName("settingsContent")  # so it picks up the dark theme
        layout = QVBoxLayout(content)

        # --- API Settings ---
        api_group = QGroupBox("API Settings")
        api_layout = QFormLayout()

        self._api_key_input = QLineEdit()
        self._api_key_input.setEchoMode(QLineEdit.Password)
        self._api_key_input.setPlaceholderText("sk-...")
        self._show_key_btn = QPushButton("Show")
        self._show_key_btn.setObjectName("compact")
        self._test_key_btn = QPushButton("Test")
        self._test_key_btn.setObjectName("compact")
        self._test_key_btn.setToolTip("Check the key against OpenAI without saving.")
        key_row = QHBoxLayout()
        key_row.addWidget(self._api_key_input)
        key_row.addWidget(self._show_key_btn)
        key_row.addWidget(self._test_key_btn)
        api_layout.addRow("OpenAI API Key:", key_row)

        self._model_combo = QComboBox()
        self._model_combo.setEditable(True)  # type any current OpenAI model id
        self._model_combo.addItems(
            ["gpt-4.1-nano", "gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1"]
        )
        self._model_combo.setToolTip(
            "The model that cleans up & formats your speech.\n"
            "gpt-4.1-nano: fastest, lowest lag — but weaker on complex formatting.\n"
            "gpt-4o-mini: fast + cheap, great default (recommended).\n"
            "gpt-4o / larger: higher quality on complex formatting, but SLOWER.\n"
            "You can type any current OpenAI model id and hit Test."
        )
        api_layout.addRow("GPT Model:", self._model_combo)

        self._whisper_model_combo = QComboBox()
        self._whisper_model_combo.addItems(
            ["gpt-4o-transcribe", "gpt-4o-mini-transcribe", "whisper-1"]
        )
        api_layout.addRow("Speech Model (cloud):", self._whisper_model_combo)

        self._temperature_spin = QDoubleSpinBox()
        self._temperature_spin.setRange(0.0, 2.0)
        self._temperature_spin.setSingleStep(0.1)
        self._temperature_spin.setDecimals(1)
        api_layout.addRow("Temperature:", self._temperature_spin)

        api_group.setLayout(api_layout)
        layout.addWidget(api_group)

        # --- Behavior Settings ---
        behavior_group = QGroupBox("Behavior")
        behavior_layout = QFormLayout()

        self._hotkey_input = QLineEdit()
        self._hotkey_input.setPlaceholderText("e.g. ctrl+shift+space")
        behavior_layout.addRow("Hotkey:", self._hotkey_input)

        self._default_mode_combo = QComboBox()
        for mode in RewriteMode:
            self._default_mode_combo.addItem(mode.display_name, mode.value)
        behavior_layout.addRow("Default Mode:", self._default_mode_combo)

        self._output_mode_combo = QComboBox()
        self._output_mode_combo.addItem("Auto-paste", OutputMode.AUTO_PASTE)
        self._output_mode_combo.addItem("Clipboard", OutputMode.CLIPBOARD)
        self._output_mode_combo.addItem("Preview", OutputMode.PREVIEW)
        behavior_layout.addRow("Output Mode:", self._output_mode_combo)

        self._auto_stop_check = QCheckBox("Auto-stop on silence")
        behavior_layout.addRow(self._auto_stop_check)

        self._keep_clipboard_check = QCheckBox(
            "Keep dictated text on clipboard after pasting"
        )
        behavior_layout.addRow(self._keep_clipboard_check)

        self._stream_output_check = QCheckBox(
            "Stream output (insert text as it's written)"
        )
        behavior_layout.addRow(self._stream_output_check)

        self._auto_start_check = QCheckBox("Start SpeakUp with Windows")
        behavior_layout.addRow(self._auto_start_check)

        self._silence_timeout_spin = QSpinBox()
        self._silence_timeout_spin.setRange(500, 10000)
        self._silence_timeout_spin.setSuffix(" ms")
        self._silence_timeout_spin.setSingleStep(500)
        behavior_layout.addRow("Silence Timeout:", self._silence_timeout_spin)

        behavior_group.setLayout(behavior_layout)
        layout.addWidget(behavior_group)

        # --- Transcription Settings ---
        transcription_group = QGroupBox("Transcription")
        transcription_layout = QFormLayout()

        self._transcription_provider_combo = QComboBox()
        self._transcription_provider_combo.addItem("Cloud (OpenAI Whisper API)", "cloud")
        # The local engine (faster-whisper) isn't bundled in the packaged exe, so
        # only offer it when running from source — no dead-end option for exe users.
        self._is_frozen = getattr(sys, "frozen", False)
        if not self._is_frozen:
            self._transcription_provider_combo.addItem(
                "Local (faster-whisper, offline)", "local"
            )
        transcription_layout.addRow("Provider:", self._transcription_provider_combo)

        self._local_model_combo = QComboBox()
        self._local_model_combo.addItems(["tiny", "base", "small", "medium", "large"])
        if not self._is_frozen:
            transcription_layout.addRow("Local Model Size:", self._local_model_combo)

        self._realtime_check = QCheckBox(
            "Live transcription — transcribe while speaking (experimental)"
        )
        self._realtime_check.setObjectName("experimental")  # amber-tinted label
        transcription_layout.addRow(self._realtime_check)

        self._deepgram_key_input = QLineEdit()
        self._deepgram_key_input.setEchoMode(QLineEdit.Password)
        self._deepgram_key_input.setPlaceholderText(
            "optional — for smooth word-by-word live captions"
        )
        self._deepgram_key_input.setToolTip(
            "Optional. With Live transcription on, a Deepgram key streams "
            "word-by-word captions as you speak. Without it, OpenAI is used."
        )
        transcription_layout.addRow("Deepgram API Key:", self._deepgram_key_input)

        transcription_group.setLayout(transcription_layout)
        layout.addWidget(transcription_group)

        # --- Widget Appearance ---
        appearance_group = QGroupBox("Widget Appearance")
        appearance_layout = QFormLayout()

        self._position_combo = QComboBox()
        self._position_combo.addItem("Bottom Right", "bottom_right")
        self._position_combo.addItem("Bottom Left", "bottom_left")
        self._position_combo.addItem("Bottom Center", "bottom_center")
        appearance_layout.addRow("Position:", self._position_combo)

        self._scale_combo = QComboBox()
        self._scale_combo.addItem("Compact (minimal bar, expands on hover)", "compact")
        self._scale_combo.addItem("Normal", "normal")
        self._scale_combo.addItem("Large (2x)", "large")
        appearance_layout.addRow("Size:", self._scale_combo)

        # Transparency (30%–100%)
        self._opacity_slider = QSlider(Qt.Horizontal)
        self._opacity_slider.setRange(30, 100)
        self._opacity_slider.setValue(100)
        self._opacity_value = QLabel("100%")
        self._opacity_value.setMinimumWidth(38)
        self._opacity_slider.valueChanged.connect(
            lambda v: self._opacity_value.setText(f"{v}%")
        )
        opacity_row = QHBoxLayout()
        opacity_row.addWidget(self._opacity_slider)
        opacity_row.addWidget(self._opacity_value)
        appearance_layout.addRow("Opacity:", opacity_row)

        appearance_group.setLayout(appearance_layout)
        layout.addWidget(appearance_group)

        # --- Context Settings ---
        context_group = QGroupBox("Context Sources")
        context_layout = QVBoxLayout()

        self._include_clipboard_check = QCheckBox("Include clipboard content")
        self._include_selection_check = QCheckBox("Include selected text")
        self._include_memory_check = QCheckBox("Include session memory")
        self._include_vscode_check = QCheckBox(
            "Include VS Code active file (Windows only)"
        )

        context_layout.addWidget(self._include_clipboard_check)
        context_layout.addWidget(self._include_selection_check)
        context_layout.addWidget(self._include_memory_check)
        context_layout.addWidget(self._include_vscode_check)

        context_group.setLayout(context_layout)
        layout.addWidget(context_group)

        # --- Personal Dictionary ---
        vocab_group = QGroupBox("Personal Dictionary")
        vocab_layout = QVBoxLayout()
        self._vocab_edit = QPlainTextEdit()
        self._vocab_edit.setPlaceholderText(
            "Names, jargon, acronyms — comma or newline separated "
            "(e.g. Vestora, WealQuest, Supabase, Nitin)"
        )
        self._vocab_edit.setFixedHeight(70)
        vocab_layout.addWidget(self._vocab_edit)

        self._suggest_check = QCheckBox("Suggest new terms from my dictations")
        self._suggest_check.setToolTip(
            "Auto-suggest uncommon names/jargon from your speech. Uncheck to stop "
            "all suggestions."
        )
        self._suggest_check.toggled.connect(self._on_suggest_toggle)
        vocab_layout.addWidget(self._suggest_check)

        # Auto-learned suggestions (recurring proper nouns from your dictations)
        self._suggest_label = QLabel("Suggested from your dictations:")
        self._suggest_label.setStyleSheet("color:#9aa4b0; margin-top:4px;")
        vocab_layout.addWidget(self._suggest_label)
        self._suggest_box = QVBoxLayout()
        self._suggest_box.setSpacing(4)
        suggest_container = QWidget()
        suggest_container.setLayout(self._suggest_box)
        vocab_layout.addWidget(suggest_container)

        vocab_group.setLayout(vocab_layout)
        layout.addWidget(vocab_group)

        layout.addStretch()

        # Authorship / version footer
        from src.version import AUTHOR, __version__
        footer = QLabel(f"SpeakUp v{__version__}  ·  Created by {AUTHOR}")
        footer.setObjectName("footer")
        footer.setAlignment(Qt.AlignCenter)
        footer.setStyleSheet("color:#8a94a0; font-size:11px; margin-top:6px;")
        layout.addWidget(footer)

        # Put all the groups above inside a scroll area. Never show a horizontal
        # scrollbar — content should wrap/fit the width, only scroll vertically.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        # --- Buttons (fixed below the scroll area) ---
        btn_layout = QHBoxLayout()
        self._save_btn = QPushButton("Save")
        self._save_btn.setObjectName("primary")  # accent-filled primary action
        self._cancel_btn = QPushButton("Cancel")
        btn_layout.addStretch()
        btn_layout.addWidget(self._save_btn)
        btn_layout.addWidget(self._cancel_btn)
        outer.addLayout(btn_layout)

        self._save_btn.clicked.connect(self._save)
        self._cancel_btn.clicked.connect(self.reject)
        self._show_key_btn.clicked.connect(self._toggle_key_visibility)
        self._test_key_btn.clicked.connect(self._test_api_key)

        # Tooltips for the non-obvious settings
        self._whisper_model_combo.setToolTip(
            "gpt-4o-transcribe is the most accurate; gpt-4o-mini-transcribe is "
            "faster; whisper-1 is the legacy model.")
        self._temperature_spin.setToolTip(
            "Lower = more faithful to your words; higher = more creative. "
            "0.2 recommended.")
        self._default_mode_combo.setToolTip(
            "Smart auto-detects the app you're typing into (chat, email, editor, "
            "document) and formats to match.")
        self._output_mode_combo.setToolTip(
            "Auto-paste inserts at your cursor. Clipboard copies only. "
            "Preview shows a window first.")
        self._keep_clipboard_check.setToolTip(
            "Off (recommended): your previous clipboard is restored after pasting. "
            "On: the dictated text stays on the clipboard.")
        self._stream_output_check.setToolTip(
            "Insert the result as it's written instead of all at once at the end "
            "(auto-paste only).")
        self._realtime_check.setToolTip(
            "Experimental: transcribe while you speak via the OpenAI Realtime API "
            "for the lowest latency. Needs the 'realtime' add-on; falls back to "
            "standard transcription if unavailable.")
        self._include_selection_check.setToolTip(
            "Use your currently selected text as context (captured via Ctrl+C). "
            "Skipped automatically in terminals.")

        # Grey out settings that don't apply to the current choices
        self._transcription_provider_combo.currentIndexChanged.connect(
            self._update_dependent_states)
        self._auto_stop_check.toggled.connect(self._update_dependent_states)

        # Style — dark theme with readable labels and a single accent (mic blue)
        self.setStyleSheet("""
            QDialog { background-color: #262626; }
            QScrollArea { border: none; background-color: #262626; }
            QWidget#settingsContent { background-color: #262626; }
            QLabel { color: #e8e8e8; }
            QLabel:disabled { color: #777; }
            QGroupBox {
                color: #4FC3F7; font-weight: bold;
                border: 1px solid #4a4a4a; border-radius: 6px;
                margin-top: 14px; padding: 12px 10px 6px 10px; }
            QGroupBox::title {
                subcontrol-origin: margin; subcontrol-position: top left;
                left: 10px; padding: 0 4px; }
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit {
                background-color: #3a3a3a; color: #ffffff;
                border: 1px solid #5a5a5a; padding: 5px; border-radius: 4px;
                selection-background-color: #4FC3F7; selection-color: #062430; }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus,
            QDoubleSpinBox:focus, QPlainTextEdit:focus { border: 1px solid #4FC3F7; }
            QComboBox QAbstractItemView {
                background-color: #3a3a3a; color: #ffffff;
                selection-background-color: #4FC3F7; selection-color: #062430; }
            QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled,
            QDoubleSpinBox:disabled { color: #777; background-color: #333; }
            QCheckBox { color: #e8e8e8; spacing: 8px; }
            QCheckBox:disabled { color: #777; }
            QCheckBox::indicator {
                width: 16px; height: 16px; border-radius: 3px;
                border: 1px solid #6a6a6a; background-color: #3a3a3a; }
            QCheckBox::indicator:checked {
                background-color: #4FC3F7; border-color: #4FC3F7; }
            QCheckBox::indicator:hover { border-color: #4FC3F7; }
            QCheckBox#experimental { color: #e0a030; }
            QPushButton {
                background-color: #3d3d3d; color: #ffffff;
                border: 1px solid #5a5a5a; padding: 7px 22px; border-radius: 5px; }
            QPushButton:hover { background-color: #4a4a4a; }
            QPushButton#compact { padding: 5px 12px; }
            QPushButton#primary {
                background-color: #4FC3F7; color: #062430;
                font-weight: bold; border: none; }
            QPushButton#primary:hover { background-color: #6fd0fb; }
        """)

        # Open tall enough to show all content; the scroll bar only appears if
        # that would exceed the available screen height.
        screen = QApplication.primaryScreen().availableGeometry()
        wanted_h = content.sizeHint().height() + 90  # + buttons row & margins
        self.resize(480, min(wanted_h, screen.height() - 80))

    def _update_dependent_states(self) -> None:
        """Enable only the settings relevant to the current selections."""
        is_local = self._transcription_provider_combo.currentData() == "local"
        self._local_model_combo.setEnabled(is_local)
        # Cloud speech model and live transcription apply only to the cloud provider.
        self._whisper_model_combo.setEnabled(not is_local)
        self._realtime_check.setEnabled(not is_local)
        # Silence timeout only matters when auto-stop is on.
        self._silence_timeout_spin.setEnabled(self._auto_stop_check.isChecked())

    def _toggle_key_visibility(self) -> None:
        """Show/hide the API key text."""
        if self._api_key_input.echoMode() == QLineEdit.Password:
            self._api_key_input.setEchoMode(QLineEdit.Normal)
            self._show_key_btn.setText("Hide")
        else:
            self._api_key_input.setEchoMode(QLineEdit.Password)
            self._show_key_btn.setText("Show")

    def _test_api_key(self) -> None:
        """Validate the entered key against OpenAI without saving it."""
        key = self._api_key_input.text().strip()
        if not key:
            QMessageBox.warning(self, "Test API Key", "Enter an API key first.")
            return
        self._test_key_btn.setEnabled(False)
        self._test_key_btn.setText("Testing…")
        QApplication.processEvents()
        try:
            from openai import OpenAI
            OpenAI(api_key=key, timeout=8.0, max_retries=0).models.list()
            QMessageBox.information(self, "Test API Key", "The key works.")
        except Exception as e:
            QMessageBox.warning(self, "Test API Key", f"Key test failed:\n{e}")
        finally:
            self._test_key_btn.setEnabled(True)
            self._test_key_btn.setText("Test")

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._apply_dark_titlebar()

    def _apply_dark_titlebar(self) -> None:
        """Darken the native Windows title bar to match the dark theme."""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            from ctypes import wintypes
            set_attr = ctypes.windll.dwmapi.DwmSetWindowAttribute
            # Explicit argtypes so the 64-bit window handle isn't truncated.
            set_attr.argtypes = [
                wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD
            ]
            hwnd = int(self.winId())
            value = ctypes.c_int(1)
            # DWMWA_USE_IMMERSIVE_DARK_MODE = 20 (19 on older Windows 10 builds)
            for attr in (20, 19):
                set_attr(hwnd, attr, ctypes.byref(value), ctypes.sizeof(value))
        except Exception:
            pass

    def _load_current_settings(self) -> None:
        """Populate fields from current config."""
        # API keys from environment
        self._api_key_input.setText(os.getenv("OPENAI_API_KEY", ""))
        self._deepgram_key_input.setText(os.getenv("DEEPGRAM_API_KEY", ""))

        # Model (editable — accept a value that isn't in the preset list)
        idx = self._model_combo.findText(self._config.gpt_model)
        if idx >= 0:
            self._model_combo.setCurrentIndex(idx)
        else:
            self._model_combo.setCurrentText(self._config.gpt_model)

        # Whisper model
        idx = self._whisper_model_combo.findText(self._config.whisper_model)
        if idx >= 0:
            self._whisper_model_combo.setCurrentIndex(idx)

        # Temperature
        self._temperature_spin.setValue(self._config.temperature)

        # Default mode
        for i in range(self._default_mode_combo.count()):
            if self._default_mode_combo.itemData(i) == self._config.default_rewrite_mode:
                self._default_mode_combo.setCurrentIndex(i)
                break

        # Output mode
        for i in range(self._output_mode_combo.count()):
            if self._output_mode_combo.itemData(i) == self._config.output_mode:
                self._output_mode_combo.setCurrentIndex(i)
                break

        # Hotkey
        self._hotkey_input.setText(self._config.hotkey)

        # Behavior
        self._auto_stop_check.setChecked(self._config.auto_stop_on_silence)
        self._keep_clipboard_check.setChecked(self._config.keep_on_clipboard)
        self._stream_output_check.setChecked(self._config.stream_output)
        self._silence_timeout_spin.setValue(self._config.silence_timeout_ms)

        # Auto-start (read actual registry state)
        from src.services.autostart import is_autostart_enabled

        self._auto_start_check.setChecked(is_autostart_enabled())

        # Transcription provider
        for i in range(self._transcription_provider_combo.count()):
            if self._transcription_provider_combo.itemData(i) == self._config.transcription_provider:
                self._transcription_provider_combo.setCurrentIndex(i)
                break

        idx = self._local_model_combo.findText(self._config.whisper_local_model_size)
        if idx >= 0:
            self._local_model_combo.setCurrentIndex(idx)

        self._realtime_check.setChecked(self._config.transcription_realtime)

        # Widget appearance
        for i in range(self._position_combo.count()):
            if self._position_combo.itemData(i) == self._config.widget_position:
                self._position_combo.setCurrentIndex(i)
                break
        for i in range(self._scale_combo.count()):
            if self._scale_combo.itemData(i) == self._config.widget_scale:
                self._scale_combo.setCurrentIndex(i)
                break
        self._opacity_slider.setValue(int(round(self._config.widget_opacity * 100)))

        # Context
        self._include_clipboard_check.setChecked(self._config.include_clipboard)
        self._include_selection_check.setChecked(self._config.include_selection)
        self._include_memory_check.setChecked(self._config.include_session_memory)
        self._include_vscode_check.setChecked(self._config.include_vscode_file)

        # Personal dictionary
        self._vocab_edit.setPlainText(", ".join(self._config.custom_vocabulary))
        self._suggest_check.setChecked(self._config.suggest_dictionary_terms)
        self._refresh_suggestions()

        # Reflect dependent enable/disable state for the loaded values
        self._update_dependent_states()

    def _on_suggest_toggle(self, on: bool) -> None:
        if on:
            self._refresh_suggestions()
        else:
            self._suggest_label.setVisible(False)
            while self._suggest_box.count():
                item = self._suggest_box.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.deleteLater()

    def _refresh_suggestions(self) -> None:
        """Rebuild the auto-learned dictionary suggestion rows."""
        while self._suggest_box.count():
            item = self._suggest_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        terms = []
        if self._vocab_learner is not None:
            try:
                terms = self._vocab_learner.pending_suggestions()
            except Exception:
                terms = []

        self._suggest_label.setVisible(bool(terms))
        for term in terms[:12]:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            lbl = QLabel(term)
            lbl.setStyleSheet("font-weight:600;")
            add_btn = QPushButton("Add")
            add_btn.setObjectName("compact")
            ignore_btn = QPushButton("Ignore")
            ignore_btn.setObjectName("compact")
            add_btn.clicked.connect(lambda _checked=False, t=term: self._accept_suggestion(t))
            ignore_btn.clicked.connect(lambda _checked=False, t=term: self._ignore_suggestion(t))
            h.addWidget(lbl)
            h.addStretch()
            h.addWidget(add_btn)
            h.addWidget(ignore_btn)
            self._suggest_box.addWidget(row)

    def _accept_suggestion(self, term: str) -> None:
        if self._vocab_learner is not None:
            try:
                self._vocab_learner.accept(term)
            except Exception:
                pass
        # Reflect the newly-added term in the editable box and refresh the list.
        self._config.reload()
        self._vocab_edit.setPlainText(", ".join(self._config.custom_vocabulary))
        self._refresh_suggestions()

    def _ignore_suggestion(self, term: str) -> None:
        if self._vocab_learner is not None:
            try:
                self._vocab_learner.ignore(term)
            except Exception:
                pass
        self._refresh_suggestions()

    def _save(self) -> None:
        """Validate and save settings."""
        new_hotkey = self._hotkey_input.text().strip() or self._config.hotkey

        # Parse the personal dictionary (comma- or newline-separated, deduped).
        raw_vocab = self._vocab_edit.toPlainText().replace("\n", ",")
        vocab: list[str] = []
        for term in raw_vocab.split(","):
            term = term.strip()
            if term and term not in vocab:
                vocab.append(term)

        overrides = {
            "gpt_model": self._model_combo.currentText(),
            "whisper_model": self._whisper_model_combo.currentText(),
            "temperature": self._temperature_spin.value(),
            "hotkey": new_hotkey,
            "default_rewrite_mode": self._default_mode_combo.currentData(),
            "output_mode": self._output_mode_combo.currentData(),
            "auto_stop_on_silence": self._auto_stop_check.isChecked(),
            "keep_on_clipboard": self._keep_clipboard_check.isChecked(),
            "stream_output": self._stream_output_check.isChecked(),
            "silence_timeout_ms": self._silence_timeout_spin.value(),
            "transcription_provider": self._transcription_provider_combo.currentData(),
            "transcription_realtime": self._realtime_check.isChecked(),
            "whisper_local_model_size": self._local_model_combo.currentText(),
            "include_clipboard": self._include_clipboard_check.isChecked(),
            "include_selection": self._include_selection_check.isChecked(),
            "include_session_memory": self._include_memory_check.isChecked(),
            "include_vscode_file": self._include_vscode_check.isChecked(),
            "custom_vocabulary": vocab,
            "suggest_dictionary_terms": self._suggest_check.isChecked(),
            "auto_start": self._auto_start_check.isChecked(),
            "widget_position": self._position_combo.currentData(),
            "widget_scale": self._scale_combo.currentData(),
            "widget_opacity": self._opacity_slider.value() / 100.0,
        }

        try:
            self._config.save_user_overrides(overrides)
            # Hot-reload config so all components pick up new values immediately
            self._config.reload()

            # Update Windows startup registry
            from src.services.autostart import set_autostart

            set_autostart(self._auto_start_check.isChecked())

            # Update hotkey listener live if one is available
            if self._hotkey_listener is not None:
                self._hotkey_listener.update_hotkey(new_hotkey)

            # Save API keys to .env if changed
            new_key = self._api_key_input.text().strip()
            if new_key and new_key != os.getenv("OPENAI_API_KEY", ""):
                self._set_env_var("OPENAI_API_KEY", new_key)

            new_dg = self._deepgram_key_input.text().strip()
            if new_dg != os.getenv("DEEPGRAM_API_KEY", ""):
                self._set_env_var("DEEPGRAM_API_KEY", new_dg)

            self.accept()
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to save settings: {e}")

    def _set_env_var(self, name: str, value: str) -> None:
        """Upsert a KEY=value line in the .env file and the live environment."""
        # Use the config's resolved path so this works in the packaged .exe
        # (next to the exe) as well as from source.
        env_path = self._config.env_path
        lines = []
        found = False
        prefix = f"{name}="

        if env_path.exists():
            with open(env_path, encoding="utf-8") as f:
                for line in f:
                    if line.startswith(prefix):
                        lines.append(f"{name}={value}\n")
                        found = True
                    else:
                        lines.append(line)

        if not found:
            lines.append(f"{name}={value}\n")

        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

        os.environ[name] = value
