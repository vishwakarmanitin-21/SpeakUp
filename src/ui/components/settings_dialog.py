from __future__ import annotations

import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from src.config import Config
from src.output.inserter import OutputMode
from src.rewrite.modes import RewriteMode


class SettingsDialog(QDialog):
    """Application settings dialog."""

    def __init__(self, parent=None, hotkey_listener=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("FlowAI Settings")
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.setMinimumWidth(450)
        self._config = Config()
        self._hotkey_listener = hotkey_listener
        self._setup_ui()
        self._load_current_settings()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # --- API Settings ---
        api_group = QGroupBox("API Settings")
        api_layout = QFormLayout()

        self._api_key_input = QLineEdit()
        self._api_key_input.setEchoMode(QLineEdit.Password)
        self._api_key_input.setPlaceholderText("sk-...")
        api_layout.addRow("OpenAI API Key:", self._api_key_input)

        self._model_combo = QComboBox()
        self._model_combo.addItems(["gpt-4o", "gpt-4o-mini"])
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

        self._auto_start_check = QCheckBox("Start FlowAI with Windows")
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
        self._transcription_provider_combo.addItem("Local (faster-whisper, offline)", "local")
        transcription_layout.addRow("Provider:", self._transcription_provider_combo)

        self._local_model_combo = QComboBox()
        self._local_model_combo.addItems(["tiny", "base", "small", "medium", "large"])
        transcription_layout.addRow("Local Model Size:", self._local_model_combo)

        self._realtime_check = QCheckBox(
            "Live transcription — transcribe while speaking (experimental)"
        )
        transcription_layout.addRow(self._realtime_check)

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
        vocab_group.setLayout(vocab_layout)
        layout.addWidget(vocab_group)

        # --- Buttons ---
        btn_layout = QHBoxLayout()
        self._save_btn = QPushButton("Save")
        self._save_btn.setObjectName("primary")  # accent-filled primary action
        self._cancel_btn = QPushButton("Cancel")
        btn_layout.addStretch()
        btn_layout.addWidget(self._save_btn)
        btn_layout.addWidget(self._cancel_btn)
        layout.addLayout(btn_layout)

        self._save_btn.clicked.connect(self._save)
        self._cancel_btn.clicked.connect(self.reject)

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
            QPushButton {
                background-color: #3d3d3d; color: #ffffff;
                border: 1px solid #5a5a5a; padding: 7px 22px; border-radius: 5px; }
            QPushButton:hover { background-color: #4a4a4a; }
            QPushButton#primary {
                background-color: #4FC3F7; color: #062430;
                font-weight: bold; border: none; }
            QPushButton#primary:hover { background-color: #6fd0fb; }
        """)

    def _update_dependent_states(self) -> None:
        """Enable only the settings relevant to the current selections."""
        is_local = self._transcription_provider_combo.currentData() == "local"
        self._local_model_combo.setEnabled(is_local)
        # Cloud speech model and live transcription apply only to the cloud provider.
        self._whisper_model_combo.setEnabled(not is_local)
        self._realtime_check.setEnabled(not is_local)
        # Silence timeout only matters when auto-stop is on.
        self._silence_timeout_spin.setEnabled(self._auto_stop_check.isChecked())

    def _load_current_settings(self) -> None:
        """Populate fields from current config."""
        # API key from environment
        api_key = os.getenv("OPENAI_API_KEY", "")
        self._api_key_input.setText(api_key)

        # Model
        idx = self._model_combo.findText(self._config.gpt_model)
        if idx >= 0:
            self._model_combo.setCurrentIndex(idx)

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

        # Context
        self._include_clipboard_check.setChecked(self._config.include_clipboard)
        self._include_selection_check.setChecked(self._config.include_selection)
        self._include_memory_check.setChecked(self._config.include_session_memory)
        self._include_vscode_check.setChecked(self._config.include_vscode_file)

        # Personal dictionary
        self._vocab_edit.setPlainText(", ".join(self._config.custom_vocabulary))

        # Reflect dependent enable/disable state for the loaded values
        self._update_dependent_states()

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
            "auto_start": self._auto_start_check.isChecked(),
            "widget_position": self._position_combo.currentData(),
            "widget_scale": self._scale_combo.currentData(),
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

            # Save API key to .env if changed
            new_key = self._api_key_input.text().strip()
            if new_key and new_key != os.getenv("OPENAI_API_KEY", ""):
                self._save_api_key(new_key)

            self.accept()
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to save settings: {e}")

    def _save_api_key(self, key: str) -> None:
        """Update the API key in the .env file."""
        # Use the config's resolved path so this works in the packaged .exe
        # (next to the exe) as well as from source.
        env_path = self._config.env_path
        lines = []
        key_found = False

        if env_path.exists():
            with open(env_path, encoding="utf-8") as f:
                for line in f:
                    if line.startswith("OPENAI_API_KEY="):
                        lines.append(f"OPENAI_API_KEY={key}\n")
                        key_found = True
                    else:
                        lines.append(line)

        if not key_found:
            lines.append(f"OPENAI_API_KEY={key}\n")

        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

        os.environ["OPENAI_API_KEY"] = key
