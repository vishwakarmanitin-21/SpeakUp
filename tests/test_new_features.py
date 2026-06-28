"""Tests for recently-added features.

Covers: cost estimation, auto-learning dictionary (VocabLearner), prompt
assembly, the streaming inserter (chunk boundaries, ordering, clipboard
restore), and the live→batch fallback notice.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# --------------------------------------------------------------------------- #
# Cost estimation (usage_tracker)
# --------------------------------------------------------------------------- #

def test_estimate_cost_positive_and_model_sensitive():
    from src.services.usage_tracker import _estimate_cost

    mini = _estimate_cost(100, 100, "gpt-4o-transcribe", "gpt-4o-mini")
    big = _estimate_cost(100, 100, "gpt-4o-transcribe", "gpt-4o")
    assert mini > 0
    assert big > mini  # gpt-4o is pricier than gpt-4o-mini


def test_estimate_cost_local_stt_is_cheaper():
    from src.services.usage_tracker import _estimate_cost

    cloud = _estimate_cost(200, 50, "gpt-4o-transcribe", "gpt-4o-mini")
    local = _estimate_cost(200, 50, "local", "gpt-4o-mini")
    assert local < cloud  # local transcription has no per-minute charge


def test_cost_summary_shape():
    from src.services.usage_tracker import get_cost_summary

    c = get_cost_summary()
    for key in ("month_label", "month_runs", "month_cost", "total_runs",
                "total_cost", "avg_cost"):
        assert key in c


# --------------------------------------------------------------------------- #
# Auto-learning dictionary (VocabLearner)
# --------------------------------------------------------------------------- #

def _fresh_learner(tmp_path, monkeypatch):
    from src.config import Config
    from src.services.vocab_learner import VocabLearner

    # Pretend the dictionary is empty so nothing is pre-filtered as "known".
    monkeypatch.setattr(Config, "custom_vocabulary", property(lambda self: []))
    vl = VocabLearner()
    vl._path = tmp_path / "vocab_suggestions.json"
    vl._data = {"counts": {}, "ignored": []}
    return vl


def test_learner_suggests_recurring_proper_noun(tmp_path, monkeypatch):
    vl = _fresh_learner(tmp_path, monkeypatch)
    vl.observe("I spoke to Zephyrion today about the plan.")
    vl.observe("Zephyrion agreed with the plan.")
    assert "Zephyrion" in vl.pending_suggestions()


def test_learner_ignores_common_and_single_words(tmp_path, monkeypatch):
    vl = _fresh_learner(tmp_path, monkeypatch)
    vl.observe("Today The Plan is good. Monday works.")
    vl.observe("The Plan continues.")
    pending = vl.pending_suggestions()
    # Common capitalised words (sentence starters / days) are never suggested.
    for word in ("Today", "The", "Monday"):
        assert word not in pending


def test_learner_ignore_removes_suggestion(tmp_path, monkeypatch):
    vl = _fresh_learner(tmp_path, monkeypatch)
    vl.observe("Zephyrion and Zephyrion.")  # dedup per run -> count 1
    vl.observe("Zephyrion again.")          # count 2 -> eligible
    assert "Zephyrion" in vl.pending_suggestions()
    vl.ignore("Zephyrion")
    assert "Zephyrion" not in vl.pending_suggestions()


# --------------------------------------------------------------------------- #
# Prompt assembly
# --------------------------------------------------------------------------- #

def test_build_user_prompt_includes_text_and_vocab():
    from src.rewrite.modes import RewriteMode
    from src.rewrite.prompts import build_user_prompt

    prompt = build_user_prompt(
        RewriteMode.CLEAN_GRAMMAR,
        "hello there world",
        context="prior note",
        vocabulary=["Vestora"],
    )
    assert "hello there world" in prompt
    assert "Vestora" in prompt


# --------------------------------------------------------------------------- #
# Streaming inserter: boundaries, ordering, clipboard restore
# --------------------------------------------------------------------------- #

def test_flush_boundaries():
    from src.output.inserter import OutputInserter as O

    # First chunk flushes after a few words; body waits for a clause/sentence.
    assert O._should_flush_first("Before we rebuild ") is True
    assert O._should_flush_first("Hi ") is False
    assert O._should_flush("a short run ") is False
    assert O._should_flush("a full clause, ") is True


class _FakeClip:
    def __init__(self, val=""):
        self.clip = val
        self.copies = []

    def paste(self):
        return self.clip

    def copy(self, v):
        self.clip = v
        self.copies.append(v)


def _make_inserter(monkeypatch, fake_clip):
    monkeypatch.setattr("src.output.inserter.pyperclip", fake_clip)
    from src.output.inserter import OutputInserter
    return OutputInserter()


def test_stream_preserves_order(monkeypatch):
    fake = _FakeClip("ORIGINAL")
    inst = _make_inserter(monkeypatch, fake)
    recorded: list[str] = []
    inst._paste = lambda chunk: recorded.append(chunk)  # don't touch real keyboard

    inst.begin_stream()
    for ch in "Before we rebuild, we can address this. Second sentence here now. ":
        inst.feed_stream(ch)
    inst.end_stream()  # drains + joins the worker

    assert "".join(recorded).strip() == (
        "Before we rebuild, we can address this. Second sentence here now."
    )


def test_stream_restores_clipboard(monkeypatch):
    fake = _FakeClip("ORIGINAL")
    inst = _make_inserter(monkeypatch, fake)
    inst._paste = lambda chunk: None  # stub the actual paste

    inst.begin_stream()           # snapshots "ORIGINAL"
    inst.feed_stream("Some new dictated text here. ")
    inst.end_stream()             # restores the snapshot

    assert fake.clip == "ORIGINAL"


# --------------------------------------------------------------------------- #
# Live → batch fallback notice (pipeline)
# --------------------------------------------------------------------------- #

def _make_pipeline():
    with (
        patch("src.services.pipeline.AudioRecorder"),
        patch("src.services.pipeline.SilenceDetector"),
        patch("src.services.pipeline.RewriteEngine"),
        patch("src.services.pipeline.SessionMemory"),
        patch("src.services.pipeline.ContextBuilder"),
        patch("src.services.pipeline.OutputInserter"),
    ):
        from src.services.pipeline import Pipeline
        return Pipeline()


@pytest.mark.asyncio
async def test_realtime_fallback_emits_notice():
    from src.rewrite.modes import RewriteMode

    pipeline = _make_pipeline()
    notices: list[str] = []
    pipeline.set_notice_callback(notices.append)

    realtime = MagicMock()
    realtime.used_fallback = True
    realtime.stop_and_transcribe = AsyncMock(return_value="hello world")
    pipeline._use_realtime = True
    pipeline._realtime = realtime
    pipeline._rewriter.rewrite = AsyncMock(return_value="Hello world.")
    pipeline._context_builder.build.return_value = None

    with (
        patch("src.services.usage_tracker.record_run"),
        patch("src.services.vocab_learner.VocabLearner"),
    ):
        # clipboard output -> non-streaming path (uses rewriter.rewrite)
        await pipeline.process(RewriteMode.CLEAN_GRAMMAR, output_mode="clipboard")

    assert any("standard mode" in n for n in notices)
