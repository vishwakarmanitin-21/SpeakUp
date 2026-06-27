from __future__ import annotations

import asyncio
import os
import sys
import time

from src.audio.recorder import AudioRecorder
from src.audio.silence_detector import SilenceDetector
from src.config import Config
from src.hotkeys.listener import HotkeyListener
from src.rewrite.engine import RewriteEngine
from src.rewrite.modes import RewriteMode
from src.services.error_handler import setup_logging
from src.transcription.whisper_client import WhisperClient


# Current mode — changed via number keys 1-7 in the CLI
_current_mode: RewriteMode = RewriteMode.CLEAN_GRAMMAR


def _ensure_api_key() -> bool:
    """Check for OpenAI API key; prompt via stdin if missing. Returns True if key is set."""
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if key and key != "sk-your-key-here":
        return True

    print("\n[Setup] OpenAI API key not found.")
    print("Enter your OpenAI API key (or press Enter to exit):")
    try:
        key = input("API Key: ").strip()
    except (EOFError, KeyboardInterrupt):
        return False

    if not key:
        print("[Error] No API key provided. Exiting.")
        return False

    os.environ["OPENAI_API_KEY"] = key
    env_path = Config().env_path
    # Append or create .env with the key
    with open(env_path, "a", encoding="utf-8") as f:
        f.write(f"\nOPENAI_API_KEY={key}\n")
    print(f"[Setup] API key saved to {env_path}\n")
    return True


def _print_modes() -> None:
    """Print available rewrite modes."""
    print("\nRewrite Modes:")
    for i, mode in enumerate(RewriteMode, 1):
        marker = " *" if mode == _current_mode else ""
        print(f"  {i}. {mode.display_name}{marker}")
    print(f"\nCurrent: {_current_mode.display_name}")
    print("Type a number (1-7) + Enter to switch modes.\n")


def main() -> None:
    """CLI entry point: hotkey -> record -> transcribe -> rewrite -> print."""
    global _current_mode

    setup_logging()

    try:
        config = Config()
    except Exception as e:
        print(f"[Error] Failed to load config: {e}")
        sys.exit(1)

    if not _ensure_api_key():
        sys.exit(1)

    # Set initial mode from config
    for mode in RewriteMode:
        if mode.value == config.default_rewrite_mode:
            _current_mode = mode
            break

    recorder = AudioRecorder(sample_rate=config.sample_rate)
    silence_detector = SilenceDetector(
        silence_duration_ms=config.silence_timeout_ms,
    )

    # Wire silence detection into the recorder callback
    _original_callback = recorder._audio_callback

    def _callback_with_silence(indata, frames, time_info, status):
        _original_callback(indata, frames, time_info, status)
        if config.auto_stop_on_silence and recorder.is_recording:
            if silence_detector.feed(indata):
                print("\n[Auto-stop] Silence detected.")
                recorder.stop()
                _on_recording_done()

    recorder._audio_callback = _callback_with_silence

    loop = asyncio.new_event_loop()

    def _on_recording_done() -> None:
        """Transcribe the recorded audio, then rewrite with current mode."""
        start = time.monotonic()
        try:
            # Step 1: Transcribe
            print("[Processing...] Transcribing audio...")
            client = WhisperClient()
            wav_bytes = recorder.get_wav_bytes()
            raw_text = loop.run_until_complete(client.transcribe(wav_bytes))
            t_transcribe = time.monotonic() - start

            print(f"\n--- Raw Transcription ({t_transcribe:.1f}s) ---")
            print(raw_text)
            print()

            # Step 2: Rewrite
            print(f"[Rewriting...] Mode: {_current_mode.display_name}")
            rewriter = RewriteEngine()
            rewritten = loop.run_until_complete(
                rewriter.rewrite(raw_text, _current_mode)
            )
            t_total = time.monotonic() - start

            print(f"\n--- Rewritten ({t_total:.1f}s total) ---")
            print(rewritten)
            print("-----------------------------------\n")

        except ValueError as e:
            print(f"[Warning] {e}")
        except Exception as e:
            print(f"[Error] Processing failed: {e}")

    def on_activate() -> None:
        silence_detector.reset()
        recorder.start()
        print("[Recording...] Hold hotkey to continue, release to stop.")

    def on_deactivate() -> None:
        if recorder.is_recording:
            recorder.stop()
            _on_recording_done()

    listener = HotkeyListener(
        hotkey_str=config.hotkey,
        on_activate=on_activate,
        on_deactivate=on_deactivate,
    )
    listener.start()

    print("=" * 50)
    print("  FlowAI — Voice AI Productivity Tool (CLI)")
    print("=" * 50)
    print(f"  Hotkey:     {config.hotkey}")
    print(f"  Whisper:    {config.whisper_model}")
    print(f"  GPT Model:  {config.gpt_model}")
    print(f"  Rate:       {config.sample_rate} Hz")
    print("=" * 50)
    _print_modes()
    print("Hold the hotkey to record. Release to transcribe & rewrite.")
    print("Press Ctrl+C to exit.\n")

    try:
        import threading

        def _input_loop():
            """Background thread to handle mode switching via stdin."""
            global _current_mode
            modes = list(RewriteMode)
            while True:
                try:
                    line = input().strip()
                    if line.isdigit():
                        idx = int(line) - 1
                        if 0 <= idx < len(modes):
                            _current_mode = modes[idx]
                            print(f"[Mode] Switched to: {_current_mode.display_name}\n")
                        else:
                            print(f"[Mode] Invalid. Enter 1-{len(modes)}.")
                except EOFError:
                    break

        input_thread = threading.Thread(target=_input_loop, daemon=True)
        input_thread.start()

        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        listener.stop()
        loop.close()
        print("\nExiting FlowAI. Goodbye!")


def gui() -> None:
    """Launch the PyQt5 GUI overlay."""
    from src.ui.app import run_app
    run_app()


if __name__ == "__main__":
    if "--cli" in sys.argv:
        main()
    else:
        gui()
