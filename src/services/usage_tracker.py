"""Local usage analytics tracker.

Logs each pipeline run to usage_stats.json in the project root.
Tracks: timestamp, rewrite mode, word counts, duration, and provider.
No data leaves the machine.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("speakup")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_STATS_FILE = _PROJECT_ROOT / "usage_stats.json"


def _load_stats() -> dict:
    if _STATS_FILE.exists():
        try:
            with open(_STATS_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"total_runs": 0, "total_words_in": 0, "total_words_out": 0, "sessions": []}


def _save_stats(stats: dict) -> None:
    try:
        with open(_STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2)
    except Exception as e:
        logger.warning("Could not save usage stats: %s", e)


def record_run(
    *,
    raw_text: str,
    rewritten_text: str,
    mode: str,
    provider: str,
    duration_ms: int,
) -> None:
    """Append a usage record to usage_stats.json.

    Args:
        raw_text: Original transcription.
        rewritten_text: GPT-rewritten output.
        mode: RewriteMode value string.
        provider: 'cloud' or 'local'.
        duration_ms: Total pipeline duration in milliseconds.
    """
    words_in = len(raw_text.split())
    words_out = len(rewritten_text.split())

    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "mode": mode,
        "provider": provider,
        "words_in": words_in,
        "words_out": words_out,
        "duration_ms": duration_ms,
    }

    stats = _load_stats()
    stats["total_runs"] += 1
    stats["total_words_in"] += words_in
    stats["total_words_out"] += words_out
    # Keep only the last 1000 sessions to bound file size
    stats["sessions"].append(entry)
    if len(stats["sessions"]) > 1000:
        stats["sessions"] = stats["sessions"][-1000:]

    _save_stats(stats)
    logger.debug(
        "Usage recorded: mode=%s provider=%s words_in=%d words_out=%d duration=%dms",
        mode, provider, words_in, words_out, duration_ms,
    )


def get_summary() -> dict:
    """Return a summary dict of lifetime usage stats."""
    stats = _load_stats()
    runs = stats.get("total_runs", 0)
    words_in = stats.get("total_words_in", 0)
    words_out = stats.get("total_words_out", 0)

    # Rough estimate: average typing speed ~40 wpm, speaking ~130 wpm
    # Words typed saved = words_out (would have typed those), at 40 wpm
    minutes_saved = words_out / 40 if runs > 0 else 0

    return {
        "total_runs": runs,
        "total_words_transcribed": words_in,
        "total_words_generated": words_out,
        "estimated_minutes_saved": round(minutes_saved, 1),
    }
