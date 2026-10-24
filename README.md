# SpeakUp

Voice AI productivity tool that converts speech into structured, intelligent text. Speak raw thoughts and get clean emails, PRDs, LinkedIn posts, developer comments, and more.

## Features

- **Push-to-Talk Recording** — Hold `Ctrl+Win` to record, release to process (configurable hotkey)
- **Auto-Stop on Silence** — Optional RMS-based silence detection with configurable threshold and timeout
- **Speech-to-Text** — OpenAI cloud (`gpt-4o-transcribe` by default — most accurate; `gpt-4o-mini-transcribe` for speed, or legacy `whisper-1`) or faster-whisper (local, offline); switchable in Settings
- **Live Captions** — With live transcription on, words appear in a floating caption as you speak. OpenAI gives per-pause (segment) captions; an optional **Deepgram** key (`DEEPGRAM_API_KEY`) upgrades this to smooth word-by-word streaming. OpenAI still does the rewrite, and the live path falls back to OpenAI batch on any failure
- **Clean-up model, with a backup** — `gpt-6-luna` by default (cheapest, no announced retirement); any OpenAI or Claude model id works. An optional **Anthropic** key (`ANTHROPIC_API_KEY`, Settings → Anthropic API Key) lets **Claude Haiku 5.5** step in automatically when the main model fails, so an outage or a retired model never costs formatting. `scripts/benchmark_rewrite.py` compares models on SpeakUp's real prompt
- **Never loses a dictation** — if clean-up fails the words are pasted unformatted; a silent recording pastes nothing (no invented text); pressing the hotkey again while the previous dictation is still processing is safe — each dictation keeps its own audio and they paste in order
- **Disfluency Cleanup** — Every mode strips filler words ("um", "uh", "like"), false starts, and repetitions, resolves self-corrections ("Tuesday — no, Wednesday" → "Wednesday"), and adds punctuation/paragraphs — turning a raw transcript into the text you *meant* to write, while preserving your wording and tone
- **Inline Voice Commands** — Speak formatting instructions and they're applied, not typed: "new paragraph", "bullet that", "numbered list", "scratch that", "quote that", "in caps"
- **Smart Auto-Format Mode** — Default mode detects the app you're dictating into (chat, email, code editor, document, browser) and matches the right tone and structure automatically — casual in Slack, email shape in Gmail, a code comment in VS Code
- **Personal Dictionary** — Add your names, jargon, and acronyms (e.g. Vestora, WealQuest, Supabase); these bias the speech recogniser and correct phonetic near-misses so proper nouns keep their exact spelling
- **7 Manual Rewrite Modes** — Clean Grammar, Structured Notes, PRD, Professional Email, LinkedIn Post, Developer Comment, Brain Dump (override Smart mode any time)
- **Context Awareness** — Optionally includes clipboard content and selected text (both **off by default**), rolling session memory (last 10 interactions, on by default), and the active VS Code file — each toggled in Settings
- **VS Code File Context** — Detects the active file in VS Code from the window title, locates it on disk, and includes its content as context (Windows, opt-in)
- **Streaming Output** — In auto-paste mode the rewrite is inserted at the cursor in sentence-sized chunks as it's generated, so text starts appearing almost immediately instead of after the whole response completes — reliable even on long passages (toggle in Settings)
- **Low-Latency Pipeline** — The first words flush to the cursor immediately (rather than after a whole clause) and pasting runs on a background thread that overlaps with generation, so output starts appearing fast and streams smoothly
- **Smart Output** — Auto-paste at cursor (default), copy to clipboard, or preview window with Copy/Insert/Close buttons
- **Clipboard-Safe Paste** — Auto-paste restores whatever you had on the clipboard after pasting, so dictation never silently overwrites it; opt in to keep the dictated text on the clipboard via Settings
- **Desktop Overlay** — Minimal floating PyQt5 widget with mic button (3 visual states), mode selector, status indicator, and settings gear; configurable position (bottom-right, bottom-left, bottom-center) and size (compact, normal, large)
- **Compact Mode** — Wispr Flow-style minimal bar that expands on hover to reveal controls; collapses back when mouse leaves
- **Settings Panel** — Configure OpenAI & Deepgram API keys, GPT model (editable), speech model, transcription provider (cloud/local) and live transcription, local model size, hotkey, output mode, widget position/size/**opacity**, auto-start, context toggles, personal dictionary (with auto-learned suggestions), and silence timeout; all changes hot-reload immediately
- **Auto-Start with Windows** — Registry-based startup entry, **on by default**; toggle off in Settings to stop launching SpeakUp on Windows boot
- **Adjustable Opacity** — Set the overlay/caption transparency (30–100%) from Settings to suit your taste
- **System Tray** — Runs in background with Show/Hide, Settings, User Guide, Usage & cost, Run setup again, and Quit; programmatic microphone icon
- **First-Run Onboarding** — A skippable 3-step wizard on first launch: API key entry, a microphone test with a live level meter, and a 30-second tutorial; tracked by `onboarding_complete` and re-runnable from the tray. (CLI mode still prompts via stdin.)
- **Auto-Learning Dictionary** — Watches your dictations for recurring proper-noun-like words not already in your dictionary and offers them as Add/Ignore suggestions in Settings → Personal Dictionary (so the dictionary grows from real use)
- **Cost Visibility** — Estimates approximate per-dictation, this-month, and lifetime API spend from usage stats (STT per-minute + GPT token list prices); view via tray → Usage & cost
- **Cancel Pipeline** — Press Escape during recording or processing to abort the current run
- **Live Hotkey Updates** — Changing the hotkey in Settings takes effect immediately (no restart required)
- **Windows Key Support** — Full support for `Ctrl+Win` hotkey with stale-state recovery for missed OS key releases
- **Minimum Recording Guard** — Recordings shorter than 0.3s are silently discarded to prevent API errors
- **Graceful Error Feedback** — GUI shows "Error" state with tooltip describing the failure (API key missing, microphone unavailable, network error, etc.)
- **Microphone Safety** — Missing or unavailable microphone raises a clear error instead of crashing
- **Structured Exceptions** — APIKeyError, RecordingError, TranscriptionError, RewriteError carry user-friendly messages surfaced in the UI
- **Usage Analytics** — Tracks run count, words transcribed, words generated, estimated typing time saved, and approximate cost; stored locally in `usage_stats.json`
- **Desktop Shortcut** — VBS launcher runs SpeakUp without a console window; `create_shortcut.vbs` creates a desktop shortcut
- **Standalone Exe** — PyInstaller build produces a single `SpeakUp.exe` (~93 MB, bundles websockets for live transcription) for easy distribution; no Python installation needed
- **Automated Tests** — pytest suite covering Config, AudioRecorder, Pipeline, and error hierarchy (19 tests)

## Tech Stack

| Layer | Choice |
|-------|--------|
| Desktop UI | Python 3.11+ + PyQt5 |
| Speech-to-Text | OpenAI cloud (`gpt-4o-transcribe` default / `gpt-4o-mini-transcribe` / `whisper-1`), Deepgram streaming (optional, live captions), or faster-whisper (local/offline) |
| AI Rewriting | OpenAI GPT-4o-mini (default) / GPT-4o |
| Global Hotkeys | pynput (press/release detection, Windows key support) |
| Audio Recording | sounddevice (16kHz mono, in-memory BytesIO) |
| Clipboard | pyperclip |
| Async Bridge | qasync (asyncio + PyQt5 event loop) |
| Packaging | PyInstaller (standalone .exe build) |

## Quick Start

### Option A: Standalone Exe (easiest)

1. Download `SpeakUp.exe` (from the dist folder or a teammate)
2. Double-click to run — a skippable first-run wizard walks you through entering your OpenAI API key, testing your microphone, and a quick tutorial
3. Your key and settings are stored privately in `%APPDATA%\SpeakUp` — never next to the exe

### Option B: From Source

#### 1. Clone and install

```bash
git clone https://github.com/vishwakarmanitin-21/SpeakUp.git
cd SpeakUp
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -e .
```

#### 2. Configure API key

```bash
cp .env.example .env
# Edit .env and add your OpenAI API key
# (optional) add DEEPGRAM_API_KEY for word-by-word live captions
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

### Choosing a live engine

Two engines can transcribe while you speak, and they trade off differently:

- **Deepgram** — chosen originally for snappy word-by-word captions.
- **OpenAI** (`gpt-live-transcribe`) — markedly more accurate on names and
  acronyms in testing.

Pick one in **Settings → Transcription → Live engine**; it applies from your next
dictation. `auto` (the default) keeps the historical behaviour: Deepgram when a
Deepgram key is set, OpenAI otherwise. Each dictation logs which engine ran
(`Live engine: …` in `speakup.log`), so an A/B is easy to confirm.

Don't take the defaults on faith — measure both on your own voice:

```bash
python scripts/benchmark_transcription.py --record 35 --lead-in 10
```

It scores every engine on how many of *your* dictionary terms survive, plus word
error rate. On the author's voice the ranking was gpt-4o-transcribe 12/13 →
gpt-live-transcribe 11/13 → nova-3 9/13 → nova-2 8/13, but accuracy is
voice-dependent — and the benchmark does not measure latency, which is the other
half of the decision.

### Releasing (one command)

`release.ps1` does the whole release in one step so it can't be half-done —
build, GitHub release, and the locally installed copy always end up in sync:

```powershell
.\release.ps1
```

Each run **bumps the version automatically** — fixes and small enhancements
bump the third place (1.2.0 → 1.2.1 → 1.2.2), so every exe has its own version
and you can always tell which build is running (tray → About) and whether a
machine has the latest. It then runs the tests,
rebuilds `dist\SpeakUp.exe`, commits and pushes the version bump, creates the
GitHub release for the new version and uploads the exe, then closes the running
app, overwrites the installed copy at
`%LOCALAPPDATA%\Programs\SpeakUp\SpeakUp.exe`, and relaunches it. It warns first
if you have other uncommitted or unpushed changes (so the exe can't silently
ship code that isn't on GitHub).

`src\version.py` is the single source of truth for the app, the exe and the tag.

| Flag | Effect |
|------|--------|
| `-Minor` | Mark a feature release (1.2.5 → 1.3.0) |
| `-Major` | Start a new series (1.3.7 → 2.0.0) |
| `-NoBump` | Reuse the current version (for iterating without burning versions) |
| `-SkipTests` | Skip the test run |
| `-NoRelease` | Don't touch GitHub |
| `-NoInstall` | Don't update the installed copy |
| `-Relaunch` | Relaunch the app even if it wasn't running |

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
Record (sounddevice) -> Transcribe (Whisper API batch, or live via OpenAI Realtime / Deepgram streaming) -> Rewrite (GPT API, streamed) -> Output (paste/clipboard/preview)
```

Live transcription (when enabled) runs the WebSocket on its own thread/loop with a live caption overlay, and always falls back to batch transcription so a dictation is never lost.

If the clean-up (rewrite) step fails before any text is typed, the `backup_model` is tried (when its provider's key is set); if that fails too, the transcript is still pasted at the cursor, unformatted, with a tray notice saying why - the words were already transcribed, so they are never thrown away. If the configured model has been retired (as happened to `gpt-4.1-nano` on 2026-10-23), SpeakUp switches `gpt_model` back to the shipped default (`gpt-6-luna`) so the next dictation is formatted again; ids already known to be retired are swapped on load.

Request settings follow the model family (`completion_kwargs` in `src/rewrite/engine.py`): GPT-5 onwards and the o-series get `max_completion_tokens` with reasoning switched off, because they reject `max_tokens`/`temperature` and default reasoning roughly triples time-to-first-word; Claude gets thinking disabled and no temperature.

Each key release snapshots its own live session and audio, and rewrite+paste is serialised, so an overlapping dictation can neither steal the previous one's audio nor interleave its paste.

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
  main.py                # Entry point (CLI + GUI, first-run onboarding)
  audio/
    recorder.py          # Push-to-talk audio capture
    silence_detector.py  # Auto-stop on silence
  hotkeys/
    listener.py          # Global hotkey (Ctrl+Win, with Windows key support)
  transcription/
    whisper_client.py    # OpenAI Whisper API (cloud, batch)
    local_whisper_client.py  # faster-whisper (local/offline)
    realtime_client.py   # OpenAI Realtime API live transcription (per-pause captions)
    deepgram_client.py   # Deepgram streaming live transcription (word-by-word captions)
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
    usage_tracker.py     # Local usage analytics + cost estimation (usage_stats.json)
    vocab_learner.py     # Auto-learning dictionary suggestions (vocab_suggestions.json)
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
      caption_window.py  # Floating live-caption overlay (blinking caret)
      onboarding_dialog.py # First-run setup wizard (key + mic test + tutorial)
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
| `gpt_model` | `gpt-6-luna` | Clean-up (rewrite) model — any OpenAI id, or a `claude-*` id with an Anthropic key. Measured 2026-10-24: gpt-6-luna ~0.83 s to first word, $0.12/1000 dictations; gpt-4.1-mini ~0.61 s, $0.45 (shuts down 2027-01-14) |
| `backup_model` | `claude-haiku-5-5` | Tried when the clean-up model fails before any text is typed; ignored unless its provider's key is set. `""` disables |
| `max_recording_seconds` | `300` | A recording is stopped and processed at this length (0 = no cap). Also, while you hold the hotkey, SpeakUp checks every 150 ms that the keys are really down, so a release Windows swallowed (lock screen, sleep) can't leave the mic on |

`ANTHROPIC_WORKSPACE_ID` (in `.env`, or Settings → Anthropic workspace ID) is only needed for an Anthropic key created at the organisation level rather than inside a workspace — Anthropic refuses such a key unless each request names the workspace.

Live captions connect to whichever Deepgram endpoint (US or EU) answers faster from your machine, measured once at startup; from India the EU endpoint opens the connection ~0.4 s sooner with the same transcript and billing. After each dictation a connection is kept warm for 5 minutes (0.1 s of silence, then keep-alive pings — Deepgram bills audio, so ~2 s a day), so the next dictation's captions start in ~30 ms instead of ~1 s. If a connection still isn't up 1.5 s after release, the recorded audio goes straight to standard transcription instead of waiting.

Pasting goes through the Windows clipboard API directly (`src/output/clipboard_win.py`): everything you had copied — text, images, files, rich text — is put back afterwards; SpeakUp's own chunks are kept out of Win+V history and cloud clipboard sync; and if another app is holding the clipboard, the words are typed instead of dropped.

## What it costs

Each dictation is billed in two parts, and **length matters — mostly through the first one**:

| Part | Billed by | Typical dictation (7 s, 14 words) | Long dictation (60 s, ~150 words) |
|---|---|---|---|
| Speech-to-text (Deepgram nova-3 live, ~$0.0048/min) | **seconds of audio**, pauses included | ~$0.0005 | ~$0.0048 |
| Clean-up (gpt-6-luna, $0.10 / $0.50 per 1M tokens) | **tokens**: a fixed ~1,000-token instruction + dictionary, plus ~1 token per word in and out | ~$0.0001 | ~$0.0002 |
| **Total** | | **~$0.0006** | **~$0.005** |

So a long dictation costs roughly in proportion to its length, while a short one never drops below the clean-up's fixed ~$0.0001. Measured 2026-10-24: the clean-up's input was 1,014 tokens for 10 words and 1,261 for 250 words. On the author's real usage (20 dictations a day, median 7 s, ~5 minutes of speech a day) that is about **$0.75 a month**, ~90% of it speech-to-text — the clean-up model choice moves the total by cents. The app's own running estimate is under tray → **Usage & cost…**.
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
| `transcription_realtime` | `false` | **Experimental.** Transcribe *while you speak* (lowest latency, live captions). Uses Deepgram streaming if `DEEPGRAM_API_KEY` is set (word-by-word), else the OpenAI Realtime API (per-pause). Requires `pip install -e ".[realtime]"`; falls back to standard transcription on any failure |
| `realtime_vad_silence_ms` | `250` | OpenAI live mode only: silence (ms) before a caption segment closes. Lower = more frequent captions, but can split words |
| `whisper_local_model_size` | `base` | Local model: `tiny`, `base`, `small`, `medium`, `large` |
| `include_clipboard` | `false` | Include clipboard contents as rewrite context |
| `include_selection` | `false` | Include selected text as rewrite context |
| `include_session_memory` | `true` | Include recent dictations (rolling history) as context |
| `include_vscode_file` | `false` | Include active VS Code file content as context (Windows) |
| `widget_position` | `bottom_center` | Widget position: `bottom_right`, `bottom_left`, or `bottom_center` |
| `widget_scale` | `compact` | Widget size: `compact` (hover-expand), `normal`, or `large` (2x) |
| `widget_opacity` | `1.0` | Overlay/caption opacity, `0.3`–`1.0` (Settings → Opacity slider) |
| `caption_max_lines` | `6` | Lines the live caption grows to before older words scroll off, `2`–`12` (Settings → Caption height) |
| `phonetic_correction` | `true` | Repair dictionary terms the transcriber mis-heard or split up, e.g. "west or a" → "Vestora" (Settings → Personal Dictionary) |
| `live_engine` | `auto` | Which engine transcribes while you speak: `auto` (Deepgram if a key is set), `deepgram`, or `openai` (gpt-live-transcribe). See "Choosing a live engine" below |
| `auto_start` | `true` | Start SpeakUp automatically with Windows (default on; toggle off in Settings) |
| `track_usage` | `true` | Log usage stats (incl. estimated cost) to `usage_stats.json` |
| `log_transcripts` | `false` | **Debug.** Log the raw transcript to `speakup.log` (may contain sensitive text) |
| `onboarding_complete` | `false` | Set true once the first-run setup wizard has been completed/dismissed |

## Privacy & Security

- No audio stored — held in memory only, never written to disk
- Audio is sent to OpenAI for transcription (and to Deepgram only if you enable live word-by-word captions); nothing else leaves your machine
- Encrypted API calls — HTTPS via the provider SDKs
- API keys live in `.env` (git-ignored); in the packaged app that's `%APPDATA%\SpeakUp\.env` — never bundled into the exe
- Auto-paste restores your previous clipboard by default, so dictation doesn't silently overwrite what you copied

## License

MIT — free to use, modify, and distribute. See [LICENSE](LICENSE).

## Author

Created by **Nitin Vishwakarma** — built by orchestrating AI coding agents, as a
hands-on exercise in leading AI to ship real, useful software.

- GitHub: https://github.com/vishwakarmanitin-21/SpeakUp

If SpeakUp saves you some typing, that's the point. Issues and ideas welcome.
