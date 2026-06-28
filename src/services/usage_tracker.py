"""Local usage analytics + cost estimation.

Logs each pipeline run to usage_stats.json in the per-user data directory.
Tracks: timestamp, mode, word counts, duration, provider, models, and an
APPROXIMATE per-run cost in USD. No data leaves the machine.

Cost figures are rough estimates from public list prices (which change); they
exist to give a sense of spend, not an exact bill. The authoritative number is
always your provider dashboard.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from src.config import Config

logger = logging.getLogger("speakup")


def _stats_file():
    return Config().data_dir / "usage_stats.json"


# --- Approximate pricing (USD). Update if provider prices change. ---
# Chat models: (input $/1M tokens, output $/1M tokens)
_CHAT_PRICES = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
}
_CHAT_DEFAULT = (0.15, 0.60)
# Speech-to-text: $ per minute of audio
_STT_PRICES = {
    "gpt-4o-transcribe": 0.006,
    "gpt-4o-mini-transcribe": 0.003,
    "whisper-1": 0.006,
    "deepgram": 0.0043,
    "local": 0.0,
}
_STT_DEFAULT = 0.006

_WORDS_PER_MIN = 130    # speaking rate, to estimate audio minutes from words
_TOKENS_PER_WORD = 1.3  # rough token:word ratio
_PROMPT_OVERHEAD_TOKENS = 400  # system prompt + context per rewrite


def _stt_model_for(provider: str) -> str:
    config = Config()
    if provider == "local":
        return "local"
    if config.transcription_realtime and config.deepgram_api_key:
        return "deepgram"
    return config.whisper_model


def _estimate_cost(words_in: int, words_out: int, stt_model: str, gpt_model: str) -> float:
    """Approximate USD cost of one dictation (transcription + rewrite)."""
    audio_min = words_in / _WORDS_PER_MIN
    stt_cost = _STT_PRICES.get(stt_model, _STT_DEFAULT) * audio_min

    in_rate, out_rate = _CHAT_PRICES.get(gpt_model, _CHAT_DEFAULT)
    in_tokens = words_in * _TOKENS_PER_WORD + _PROMPT_OVERHEAD_TOKENS
    out_tokens = words_out * _TOKENS_PER_WORD
    chat_cost = (in_rate * in_tokens + out_rate * out_tokens) / 1_000_000

    return round(stt_cost + chat_cost, 6)


def _load_stats() -> dict:
    path = _stats_file()
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"total_runs": 0, "total_words_in": 0, "total_words_out": 0,
            "total_cost_usd": 0.0, "sessions": []}


def _save_stats(stats: dict) -> None:
    try:
        with open(_stats_file(), "w", encoding="utf-8") as f:
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
    """Append a usage record (with an estimated cost) to usage_stats.json."""
    words_in = len(raw_text.split())
    words_out = len(rewritten_text.split())
    config = Config()
    gpt_model = config.gpt_model
    stt_model = _stt_model_for(provider)
    cost = _estimate_cost(words_in, words_out, stt_model, gpt_model)

    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "mode": mode,
        "provider": provider,
        "stt_model": stt_model,
        "gpt_model": gpt_model,
        "words_in": words_in,
        "words_out": words_out,
        "duration_ms": duration_ms,
        "cost_usd": cost,
    }

    stats = _load_stats()
    stats["total_runs"] = stats.get("total_runs", 0) + 1
    stats["total_words_in"] = stats.get("total_words_in", 0) + words_in
    stats["total_words_out"] = stats.get("total_words_out", 0) + words_out
    stats["total_cost_usd"] = round(stats.get("total_cost_usd", 0.0) + cost, 6)
    stats.setdefault("sessions", []).append(entry)
    if len(stats["sessions"]) > 1000:
        stats["sessions"] = stats["sessions"][-1000:]

    _save_stats(stats)
    logger.debug(
        "Usage recorded: mode=%s stt=%s gpt=%s in=%d out=%d ~$%.4f",
        mode, stt_model, gpt_model, words_in, words_out, cost,
    )


def get_summary() -> dict:
    """Return a summary dict of lifetime usage stats."""
    stats = _load_stats()
    runs = stats.get("total_runs", 0)
    words_in = stats.get("total_words_in", 0)
    words_out = stats.get("total_words_out", 0)
    minutes_saved = words_out / 40 if runs > 0 else 0  # ~40 wpm typing

    return {
        "total_runs": runs,
        "total_words_transcribed": words_in,
        "total_words_generated": words_out,
        "estimated_minutes_saved": round(minutes_saved, 1),
    }


def get_cost_summary() -> dict:
    """Return approximate spend for this month and lifetime."""
    stats = _load_stats()
    sessions = stats.get("sessions", [])
    month_prefix = datetime.now().strftime("%Y-%m")
    config = Config()

    def _entry_cost(s: dict) -> float:
        # Use the stored estimate; for older entries (pre-cost-tracking),
        # estimate from word counts and the current models.
        if s.get("cost_usd") is not None:
            return float(s["cost_usd"])
        return _estimate_cost(
            s.get("words_in", 0), s.get("words_out", 0),
            s.get("stt_model") or config.whisper_model,
            s.get("gpt_model") or config.gpt_model,
        )

    month_runs = 0
    month_cost = 0.0
    total_cost = 0.0
    for s in sessions:
        cost = _entry_cost(s)
        total_cost += cost
        if str(s.get("ts", "")).startswith(month_prefix):
            month_runs += 1
            month_cost += cost

    total_runs = stats.get("total_runs", 0)
    # Lifetime cost is summed from recorded sessions (kept to the last 1000).

    return {
        "month_label": month_prefix,
        "month_runs": month_runs,
        "month_cost": round(month_cost, 4),
        "total_runs": total_runs,
        "total_cost": round(total_cost, 4),
        "avg_cost": round(total_cost / total_runs, 5) if total_runs else 0.0,
    }
