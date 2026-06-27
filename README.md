# SpeakUp

Voice AI productivity tool that converts speech into structured, intelligent text. Speak raw thoughts and get clean emails, PRDs, LinkedIn posts, developer comments, and more.

## Features

- **Push-to-Talk Recording** — Hold `Ctrl+Win` to record, release to process (configurable hotkey)
- **Auto-Stop on Silence** — Optional RMS-based silence detection with configurable threshold and timeout
- **Speech-to-Text** — OpenAI cloud (`gpt-4o-mini-transcribe` by default, `gpt-4o-transcribe` or legacy `whisper-1` selectable) or faster-whisper (local, offline); switchable per-session in Settings
- **Disfluency Cleanup** — Every mode strips filler words ("um", "uh", "like"), false starts, and repetitions, resolves self-corrections ("Tuesday — no, Wednesday" → "Wednesday"), and adds punctuation/paragraphs — turning a raw transcript into the text you *meant* to write, while preserving your wording and tone
- **Inline Voice Commands** — Speak formatting instructions and they're applied, not typed: "new paragraph", "bullet that", "numbered list", "scratch that", "quote that", "in caps"
- **Smart Auto-Format Mode** — Default mode detects the app you're dictating into (chat, email, code editor, document, browser) and matches the right tone and structure automatically — casual in Slack, email shape in Gmail, a code comment in VS Code
- **Personal Dictionary** — Add your names, jargon, and acronyms (e.g. Vestora, WealQuest, Supabase); these bias the speech recogniser and correct phonetic near-misses so proper nouns keep their exact spelling
- **7 Manual Rewrite Modes** — Clean Grammar, Structured Notes, PRD, Professional Email, LinkedIn Post, Developer Comment, Brain Dump (override Smart mode any time)
- **Context Awareness** — Includes clipboard content, selected text, rolling session memory (last 10 interactions), and optionally the active VS Code file
- **VS Code File Context** — Detects the active file in VS Code from the window title, locates it on disk, and includes its content as context (Windows, opt-in)
- **Streaming Output** — In auto-paste mode the rewrite is inserted at the cursor in sentence-sized chunks as it's generated, so text starts appearing almost immediately instead of after the whole response completes — reliable even on long passages (toggle in Settings)
- **Smart Output** — Auto-paste at cursor (default), copy to clipboard, or preview window with Copy/Insert/Close buttons
- **Clipboard-Safe Paste** — Auto-paste restores whatever you had on the clipboard after pasting, so dictation never silently overwrites it; opt in to keep the dictated text on the clipboard via Settings
- **Desktop Overlay** — Minimal floating PyQt5 widget with mic button (3 visual states), mode selector, status indicator, and settings gear; configurable position (bottom-right, bottom-left, bottom-center) and size (compact, normal, large)
- **Compact Mode** — Wispr Flow-style minimal bar that expands on hover to reveal controls; collapses back when mouse leaves
- **Settings Panel** — Configure API keys, GPT model, Whisper model, transcription provider (cloud/local), local model size, hotkey, output mode, widget position/size, auto-start, context toggles, silence timeout; all changes hot-reload immediately
- **Auto-Start with Windows** — Optional registry-based startup entry; toggle in Settings to launch SpeakUp on Windows boot
- **System Tray** — Runs in background with Show/Hide, Settings, Quit menu; programmatic microphone icon
- **First-Run Setup** — GUI prompt for API key if no .env file found; CLI mode prompts via stdin and saves to .env
- **Cancel Pipeline** — Press Escape during recording or processing to abort the current run
- **Live Hotkey Updates** — Changing the hotkey in Settings takes effect immediately (no restart required)
- **Windows Key Support** — Full support for `Ctrl+Win` hotkey with stale-state recovery for missed OS key releases
- **Minimum Recording Guard** — Recordings shorter than 0.3s are silently discarded to prevent API errors
- **Graceful Error Feedback** — GUI shows "Error" state with tooltip describing the failure (API key missing, microphone unavailable, network error, etc.)
- **Microphone Safety** — Missing or unavailable microphone raises a clear error instead of crashing
- **Structured Exceptions** — APIKeyError, RecordingError, TranscriptionError, RewriteError carry user-friendly messages surfaced in the UI
- **Usage Analytics** — Tracks run count, words transcribed, words generated, and estimated typing time saved; stored locally in `usage_stats.json`
- **Desktop Shortcut** — VBS launcher runs SpeakUp without a console window; `create_shortcut.vbs` creates a desktop shortcut
- **Standalone Exe** — PyInstaller build produces a single `SpeakUp.exe` (~85 MB) for easy distribution; no Python installation needed
- **Automated Tests** — pytest suite covering Config, AudioRecorder, Pipeline, and error hierarchy (19 tests)

## Tech Stack

| Layer | Choice |
|-------|--------|
| Desktop UI | Python 3.12 + PyQt5 |
| Speech-to-Text | OpenAI cloud (`gpt-4o-mini-transcribe` / `gpt-4o-transcribe` / `whisper-1`) or faster-whisper (local/offline) |
| AI Rewriting | OpenAI GPT-4o-mini (default) / GPT-4o |
| Global Hotkeys | pynput (press/release detection, Windows key support) |
| Audio Recording | sounddevice (16kHz mono, in-memory BytesIO) |
| Clipboard | pyperclip |
| Async Bridge | qasync (asyncio + PyQt5 event loop) |
| Packaging | PyInstaller (standalone .exe build) |

## Quick Start

### Option A: Standalone Exe (easiest)

1. Download `SpeakUp.exe` from the dist folder (or get it from a teammate)
2. Double-click to run — enter your OpenAI API key when prompted on first launch
3. That's it! Config files are created next to the exe automatically

### Option B: From Source

#### 1. Clone and install

```bash
git clone https://github.com/your-username/Speak-up.git
cd Speak-up
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -e .
```

#### 2. Configure API key

```bash
cp .env.example .env
# Edit .env and add your OpenAI API key
```

#### 3. Run

**GUI mode (default):**
```bash
python -m src.main
```

**CLI mode:**
```bash
python -m src.main --cli
```

**Desktop shortcut (no terminal):**
```bash
wscript create_shortcut.vbs
```
This creates a "SpeakUp" shortcut on your Desktop that launches the app without a console window.

### Building the Exe

```bash
pip install pyinstaller
python scripts/build.py
# Output: dist/SpeakUp.exe
```

## Usage

1. The overlay widget appears at the bottom of your screen (position configurable in Settings)
2. Select a rewrite mode from the dropdown (hover to expand in compact mode)
3. Hold `Ctrl+Win` and speak your thoughts
4. Release the hotkey — your speech is transcribed and rewritten
5. Output is auto-pasted at your cursor (or copied to clipboard / shown in preview, based on settings)

## Rewrite Modes

| Mode | Description |
|------|-------------|
| Smart (auto-format) | **Default.** Cleans up speech, then formats it for the active app's surface (chat / email / editor / document) |
| Clean & Fix Grammar | Fix grammar and punctuation, preserve meaning |
| Structured Notes | Convert to headings and bullet points |
| Convert to PRD | Generate Vision / Features / User Flow / Tech sections |
| Professional Email | Subject line + greeting + body + sign-off |
| LinkedIn Post | Hook + story + insight + takeaway format |
| Developer Comment | Code documentation style |
| Brain Dump -> Organized | Group themes, extract action items, add summary |

Each mode has a dedicated system prompt engineered in `src/rewrite/prompts.py`.

## AI Prompt Design

- **System prompt**: Balanced cleanup engine — removes disfluencies and resolves self-corrections while preserving the speaker's meaning, voice, and register (never invents content or over-formalises)
- **Mode-specific prompts**: Smart mode plus 7 manually-selectable modes, each carefully tuned
- **Surface adaptation**: Smart mode injects the active app's surface (chat / email / editor / document / browser) so tone and format match the destination
- **Personal dictionary**: Known terms are passed to the transcription model as a recognition hint and listed in the rewrite prompt for spelling correction
- **Context injection**: Clipboard, selected text, session history, and the active VS Code file are included when available
- Built with `build_user_prompt()` helper that assembles transcription + mode + app hint + vocabulary + context

## Architecture

### Pipeline Flow

```
Record (sounddevice) -> Transcribe (Whisper API) -> Rewrite (GPT API) -> Output (paste/clipboard/preview)
```

### Threading Model

- **Qt main thread**: All UI + asyncio coroutines (via qasync)
- **pynput thread**: Keyboard callbacks -> `pyqtSignal.emit()` only
- Never call widget methods from pynput thread

### Configuration Layers

- `.env` — API keys only (git-ignored)
- `config_defaults.json` — Committed defaults
- `config.json` — User overrides (git-ignored)
- `Config` singleton in `src/config.py` merges all three

### Key Design Decisions

- Single-process: no separate backend server for MVP
- Audio in-memory only: BytesIO, never written to disk
- Async from day 1: AsyncOpenAI client for qasync compatibility
- Push-to-talk: custom pynput Listener for press + release detection

## Project Structure

```
tests/
  test_config.py         # Config singleton and reload tests
  test_recorder.py       # AudioRecorder + mic error tests
  test_pipeline.py       # Pipeline state machine + cancel tests
  test_error_handler.py  # Exception hierarchy tests
src/
  config.py              # Configuration singleton (with reload())
  main.py                # Entry point (CLI + GUI, API key prompt)
  audio/
    recorder.py          # Push-to-talk audio capture
    silence_detector.py  # Auto-stop on silence
  hotkeys/
    listener.py          # Global hotkey (Ctrl+Win, with Windows key support)
  transcription/
    whisper_client.py    # OpenAI Whisper API (cloud)
    local_whisper_client.py  # faster-whisper (local/offline)
    factory.py           # Returns cloud or local client based on config
  rewrite/
    modes.py             # 7 rewrite modes enum
    prompts.py           # AI prompt templates
    engine.py            # GPT rewrite client
  context/
    clipboard.py         # Clipboard reading
    selection.py         # Active window text selection
    session_memory.py    # Rolling session history
    context_builder.py   # Context assembly
    vscode_context.py    # VS Code active file reader (Windows)
  output/
    inserter.py          # Auto-paste / clipboard / preview output
  services/
    pipeline.py          # Orchestrator: record -> transcribe -> rewrite -> output
    error_handler.py     # Error types + logging
    usage_tracker.py     # Local usage analytics (usage_stats.json)
    autostart.py         # Windows startup registry management
  ui/
    app.py               # QApplication + system tray
    overlay.py           # Floating overlay widget (position, scale, compact mode)
    styles.py            # Dark theme styles
    components/
      mic_button.py      # Animated mic button
      mode_selector.py   # Rewrite mode dropdown
      status_indicator.py # Status display
      preview_window.py  # Result preview popup
      settings_dialog.py # Settings panel
scripts/
  build.py               # PyInstaller build script
SpeakUp.vbs               # VBS launcher (no console window)
create_shortcut.vbs       # Creates desktop shortcut
SpeakUp.spec               # PyInstaller spec file
```

## Configuration

Settings can be changed via the gear icon on the overlay or by editing `config.json`:

| Setting | Default | Description |
|---------|---------|-------------|
| `gpt_model` | `gpt-4o-mini` | GPT model for rewriting |
| `whisper_model` | `gpt-4o-transcribe` | Cloud speech model (used when provider=cloud): `gpt-4o-transcribe` (most accurate), `gpt-4o-mini-transcribe` (faster), or legacy `whisper-1` |
| `temperature` | `0.2` | AI creativity level (0-2); low favours faithful cleanup |
| `default_rewrite_mode` | `smart` | Mode selected on launch (`smart` auto-formats per active app) |
| `custom_vocabulary` | `[]` | Personal dictionary of names/jargon/acronyms; biases transcription and corrects spelling |
| `hotkey` | `ctrl+cmd` | Push-to-talk hotkey (Ctrl+Win) |
| `output_mode` | `auto_paste` | Output: `auto_paste`, `clipboard`, or `preview` |
| `stream_output` | `true` | Type the rewrite word-by-word at the cursor as it streams (auto-paste mode only) |
| `keep_on_clipboard` | `false` | Keep dictated text on the clipboard after auto-paste; when `false`, the previous clipboard contents are restored |
| `auto_stop_on_silence` | `false` | Stop recording after silence |
| `silence_timeout_ms` | `2000` | Silence duration before auto-stop |
| `transcription_provider` | `cloud` | `cloud` (OpenAI Whisper API) or `local` (faster-whisper) |
| `transcription_realtime` | `false` | **Experimental.** Stream audio over the OpenAI Realtime API to transcribe *while you speak* (lowest latency). Requires `pip install -e ".[realtime]"`; falls back to standard transcription on any failure |
| `whisper_local_model_size` | `base` | Local model: `tiny`, `base`, `small`, `medium`, `large` |
| `include_vscode_file` | `false` | Include active VS Code file content as context (Windows) |
| `widget_position` | `bottom_center` | Widget position: `bottom_right`, `bottom_left`, or `bottom_center` |
| `widget_scale` | `compact` | Widget size: `compact` (hover-expand), `normal`, or `large` (2x) |
| `auto_start` | `false` | Start SpeakUp automatically with Windows |
| `track_usage` | `true` | Log usage stats to `usage_stats.json` |

## Privacy & Security

- No audio stored — BytesIO only, garbage collected after use
- Encrypted API calls — HTTPS via OpenAI SDK
- API keys stored in `.env` file (git-ignored)
