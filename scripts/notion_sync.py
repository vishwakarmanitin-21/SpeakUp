"""Initial sync of project documentation to Notion pages."""

import json
import os
import urllib.request
from datetime import date

TOKEN = os.getenv("NOTION_API_TOKEN", "")
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}
TODAY = date.today().isoformat()

PAGE_IDS = {
    "overview": "312c6ee7-d563-8150-a407-e049138f505f",
    "features": "312c6ee7-d563-8130-b924-fa6817f4aed8",
    "architecture": "312c6ee7-d563-81ce-b84c-fcf30ad8beac",
    "requirements": "312c6ee7-d563-813a-9c0b-e6d2c573f70a",
    "memory": "312c6ee7-d563-8142-a70d-ca651001c385",
}


def notion_request(method, url, body=None):
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=HEADERS, method=method)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def clear_page(page_id):
    url = f"https://api.notion.com/v1/blocks/{page_id}/children?page_size=100"
    data = notion_request("GET", url)
    for block in data.get("results", []):
        try:
            notion_request("DELETE", f"https://api.notion.com/v1/blocks/{block['id']}")
        except Exception:
            pass


def append_blocks(page_id, blocks):
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    for i in range(0, len(blocks), 100):
        notion_request("PATCH", url, {"children": blocks[i:i + 100]})


def text_block(text, btype="paragraph"):
    return {
        "object": "block",
        "type": btype,
        btype: {"rich_text": [{"type": "text", "text": {"content": text}}]},
    }


def heading2(text):
    return text_block(text, "heading_2")


def heading3(text):
    return text_block(text, "heading_3")


def bullet(text):
    return text_block(text, "bulleted_list_item")


def divider():
    return {"object": "block", "type": "divider", "divider": {}}


def code_block(text, lang="plain text"):
    return {
        "object": "block",
        "type": "code",
        "code": {
            "rich_text": [{"type": "text", "text": {"content": text}}],
            "language": lang,
        },
    }


def sync_overview():
    print("Syncing Overview...")
    pid = PAGE_IDS["overview"]
    clear_page(pid)
    append_blocks(pid, [
        heading2("SpeakUp (Speak-up)"),
        text_block(
            "Voice AI productivity tool that converts speech into structured, "
            "intelligent text. Speak raw thoughts and get clean emails, PRDs, "
            "LinkedIn posts, developer comments, and more."
        ),
        divider(),
        heading3("Quick Start"),
        bullet("Clone the repo and create a venv with Python 3.12"),
        bullet("Copy .env.example to .env and add your OpenAI API key"),
        bullet("pip install -e . to install dependencies"),
        bullet("python -m src.main to launch GUI (or --cli for CLI mode)"),
        divider(),
        heading3("How It Works"),
        bullet("Hold Ctrl+Shift+Space to record your voice"),
        bullet("Release to transcribe (Whisper API) and rewrite (GPT-4o)"),
        bullet("Output is auto-pasted, copied to clipboard, or shown in preview"),
        bullet("Select from 7 rewrite modes: Grammar, Notes, PRD, Email, LinkedIn, Dev Comment, Brain Dump"),
        divider(),
        heading3("Tech Stack"),
        bullet("Python 3.12 + PyQt5 desktop overlay"),
        bullet("OpenAI Whisper API (speech-to-text)"),
        bullet("OpenAI GPT-4o (AI rewriting)"),
        bullet("pynput (global hotkeys), sounddevice (audio), pyperclip (clipboard)"),
        bullet("qasync (asyncio + PyQt5 bridge)"),
        divider(),
        text_block(f"Last synced from README.md: {TODAY}"),
    ])
    print("  Done.")


def sync_features():
    print("Syncing Features...")
    pid = PAGE_IDS["features"]
    clear_page(pid)
    append_blocks(pid, [
        heading2("Features"),
        divider(),
        heading3("Push-to-Talk Recording"),
        bullet("Hold Ctrl+Shift+Space to record, release to process"),
        bullet("Optional auto-stop on silence (configurable timeout)"),
        bullet("Audio stays in-memory (BytesIO), never written to disk"),
        divider(),
        heading3("Speech-to-Text"),
        bullet("OpenAI Whisper API with English/India accent support"),
        bullet("16kHz mono recording optimized for Whisper"),
        divider(),
        heading3("7 AI Rewrite Modes"),
        bullet("Clean & Fix Grammar - fix grammar, preserve meaning"),
        bullet("Structured Notes - headings and bullet points"),
        bullet("Convert to PRD - Vision / Features / User Flow / Tech sections"),
        bullet("Professional Email - subject + greeting + body + sign-off"),
        bullet("LinkedIn Post - hook + story + insight + takeaway"),
        bullet("Developer Comment - code documentation style"),
        bullet("Brain Dump -> Organized - group themes, extract actions, add summary"),
        divider(),
        heading3("Context Awareness"),
        bullet("Includes clipboard content as context"),
        bullet("Captures selected text from active window"),
        bullet("Rolling session memory (last 10 interactions)"),
        divider(),
        heading3("Smart Output"),
        bullet("Auto-paste at cursor position"),
        bullet("Copy to clipboard"),
        bullet("Preview window with Copy/Insert buttons"),
        divider(),
        heading3("Desktop Overlay UI"),
        bullet("Minimal floating PyQt5 widget, always on top"),
        bullet("Mic button, mode selector dropdown, status indicator"),
        bullet("Settings gear icon for configuration"),
        bullet("Draggable, frameless, dark theme"),
        divider(),
        heading3("Settings Panel"),
        bullet("API key, GPT model, Whisper model, temperature"),
        bullet("Default rewrite mode, output mode"),
        bullet("Context source toggles (clipboard, selection, memory)"),
        bullet("Auto-stop on silence with configurable timeout"),
        divider(),
        heading3("System Tray"),
        bullet("Runs in background with tray icon"),
        bullet("Show/Hide, Settings, Quit menu"),
        divider(),
        text_block(f"Last synced from README.md: {TODAY}"),
    ])
    print("  Done.")


def sync_architecture():
    print("Syncing Architecture...")
    pid = PAGE_IDS["architecture"]
    clear_page(pid)
    structure = """src/
  config.py              # Configuration singleton
  main.py                # Entry point (CLI + GUI)
  audio/
    recorder.py          # Push-to-talk audio capture
    silence_detector.py  # Auto-stop on silence
  hotkeys/
    listener.py          # Global hotkey (Ctrl+Shift+Space)
  transcription/
    whisper_client.py    # OpenAI Whisper API
  rewrite/
    modes.py             # 7 rewrite modes enum
    prompts.py           # AI prompt templates
    engine.py            # GPT rewrite client
  context/
    clipboard.py         # Clipboard reading
    selection.py         # Active window text selection
    session_memory.py    # Rolling session history
    context_builder.py   # Context assembly
  output/
    inserter.py          # Auto-paste / clipboard / preview
  services/
    pipeline.py          # Orchestrator
    error_handler.py     # Error types + logging
  ui/
    app.py               # QApplication + system tray
    overlay.py           # Floating overlay widget
    styles.py            # Dark theme QSS
    components/          # UI components"""
    append_blocks(pid, [
        heading2("Architecture"),
        divider(),
        heading3("Project Structure"),
        code_block(structure),
        divider(),
        heading3("Threading Model"),
        bullet("Qt main thread: all UI + asyncio coroutines (via qasync)"),
        bullet("pynput thread: keyboard callbacks -> pyqtSignal.emit() only"),
        bullet("Never call widget methods from pynput thread"),
        divider(),
        heading3("Pipeline Flow"),
        text_block("Record (sounddevice) -> Transcribe (Whisper API) -> Rewrite (GPT API) -> Output (paste/clipboard/preview)"),
        divider(),
        heading3("Configuration Layers"),
        bullet(".env file - API keys only (git-ignored)"),
        bullet("config_defaults.json - committed defaults"),
        bullet("config.json - user overrides (git-ignored)"),
        bullet("Config singleton in src/config.py merges all three"),
        divider(),
        heading3("Key Design Decisions"),
        bullet("Single-process: no separate backend server for MVP"),
        bullet("Audio in-memory only: BytesIO, never written to disk"),
        bullet("Async from day 1: AsyncOpenAI client for qasync compatibility"),
        bullet("Push-to-talk: custom pynput Listener for press + release detection"),
        divider(),
        text_block(f"Last synced from README.md: {TODAY}"),
    ])
    print("  Done.")


def sync_requirements():
    print("Syncing Requirements...")
    pid = PAGE_IDS["requirements"]
    clear_page(pid)
    append_blocks(pid, [
        heading2("Requirements (PRD)"),
        text_block("Product Name: SpeakUp (Working Name)"),
        divider(),
        heading3("Product Vision"),
        text_block(
            "Build a cross-platform AI voice-to-text assistant that captures live voice input, "
            "converts to high-quality text, rewrites intelligently based on intent, inserts text "
            "into active applications, supports context-aware rewriting modes, and works locally "
            "with minimal latency."
        ),
        divider(),
        heading3("Target User"),
        bullet("Senior delivery leader"),
        bullet("AI builder"),
        bullet("Knowledge worker"),
        bullet("Developer using VS Code"),
        bullet("Heavy thinker, high idea volume"),
        divider(),
        heading3("Core Value Proposition"),
        text_block(
            "Traditional dictation converts speech to literal text. "
            "SpeakUp converts thinking to structured, clean, contextual output."
        ),
        divider(),
        heading3("MVP Features (Phase 1)"),
        bullet("Voice Capture: Push-to-talk hotkey, auto-stop on silence"),
        bullet("Speech-to-Text: OpenAI Whisper API, English (India accent tolerant)"),
        bullet("AI Rewrite: 7 modes (Grammar, Notes, PRD, Email, LinkedIn, Dev Comment, Brain Dump)"),
        bullet("Context Awareness: clipboard, selected text, session memory"),
        bullet("Smart Output: auto-paste, preview window, clipboard"),
        bullet("Desktop Overlay: floating widget with mic, mode selector, status, settings"),
        divider(),
        heading3("Phase 2 (Advanced)"),
        bullet("Real-time streaming transcription"),
        bullet("Multi-language support"),
        bullet("Speaker diarization"),
        bullet("Custom tone training"),
        bullet("Persistent memory profile"),
        bullet("WhatsApp integration, Notion direct posting"),
        bullet("VS Code extension"),
        divider(),
        heading3("Success Metrics"),
        bullet("Latency < 3 seconds"),
        bullet("Rewrite accuracy satisfaction"),
        bullet("Daily usage count"),
        bullet("Reduced typing time"),
        divider(),
        text_block(f"Last synced from Requirements.md: {TODAY}"),
    ])
    print("  Done.")


def sync_memory():
    print("Syncing Memory...")
    pid = PAGE_IDS["memory"]
    clear_page(pid)
    append_blocks(pid, [
        heading2("Project Memory"),
        divider(),
        heading3("Tech Stack"),
        bullet("Python 3.12 (venv at .venv/)"),
        bullet("PyQt5 for desktop overlay UI"),
        bullet("OpenAI Whisper API for STT, GPT-4o for rewriting"),
        bullet("pynput for global hotkeys, sounddevice for audio, pyperclip for clipboard"),
        bullet("qasync bridges asyncio + PyQt5 event loop"),
        divider(),
        heading3("Key Architecture"),
        bullet("Single-process app: PyQt5 main thread + qasync for async OpenAI calls"),
        bullet("pynput listener runs in daemon thread, communicates via pyqtSignal"),
        bullet("Audio kept entirely in-memory (BytesIO), never written to disk"),
        bullet("Config: .env (API keys) + config_defaults.json (defaults) + config.json (user overrides)"),
        bullet("Pipeline: record -> transcribe -> rewrite -> output"),
        divider(),
        heading3("Key Files"),
        bullet("Entry point: src/main.py (--cli for CLI, default is GUI)"),
        bullet("Config: src/config.py (singleton pattern)"),
        bullet("Pipeline: src/services/pipeline.py (orchestrator)"),
        bullet("Overlay: src/ui/overlay.py (main floating widget)"),
        bullet("Prompts: src/rewrite/prompts.py (all 7 mode prompts)"),
        divider(),
        heading3("Known Issues"),
        bullet("Unicode arrow char causes cp1252 encoding issues on Windows terminal (use -> instead)"),
        bullet("Python 3.14 is on PATH but bleeding edge; using 3.12"),
        divider(),
        text_block(f"Last synced from MEMORY.md: {TODAY}"),
    ])
    print("  Done.")


if __name__ == "__main__":
    sync_overview()
    sync_features()
    sync_architecture()
    sync_requirements()
    sync_memory()
    print("\n=== ALL 5 NOTION PAGES SYNCED SUCCESSFULLY ===")
