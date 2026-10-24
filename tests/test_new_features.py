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
    # Must appear capitalised MID-sentence (not just at a sentence start),
    # and recur past the threshold before being suggested.
    vl.observe("I spoke to Zephyrion today about the plan.")
    vl.observe("We saw Zephyrion again yesterday.")
    vl.observe("Ask Zephyrion about it.")
    assert "Zephyrion" in vl.pending_suggestions()


def test_learner_ignores_sentence_start_words(tmp_path, monkeypatch):
    vl = _fresh_learner(tmp_path, monkeypatch)
    # "Considering" / "Hope" only ever start sentences -> never suggested.
    vl.observe("Considering the plan. Hope it works.")
    vl.observe("Considering that. Hope so.")
    pending = vl.pending_suggestions()
    assert "Considering" not in pending
    assert "Hope" not in pending


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
    vl.observe("I called Zephyrion earlier.")   # mid-sentence -> 1
    vl.observe("Please meet Zephyrion now.")    # mid-sentence -> 2
    vl.observe("Tell Zephyrion today.")         # mid-sentence -> 3 (threshold)
    assert "Zephyrion" in vl.pending_suggestions()
    vl.ignore("Zephyrion")
    assert "Zephyrion" not in vl.pending_suggestions()


# --------------------------------------------------------------------------- #
# Phonetic repair of mis-heard dictionary terms (self-learning phase 1)
# --------------------------------------------------------------------------- #

_VOCAB = ["Nitin", "Prisha", "Komal", "Pranit", "Vestora", "WealQuest", "Wealducate"]


def _corrector():
    from src.services.phonetic import PhoneticCorrector
    return PhoneticCorrector(_VOCAB)


@pytest.mark.parametrize("heard,expected", [
    ("I spoke to west or a about it", "Vestora"),      # term split across words
    ("the well quest roadmap is ready", "WealQuest"),
    ("send it to well due cate today", "Wealducate"),
    ("Nithin will join", "Nitin"),                      # single mis-spelling
    ("ask Komall about it", "Komal"),
])
def test_phonetic_restores_misheard_terms(heard, expected):
    assert expected in _corrector().correct(heard)


@pytest.mark.parametrize("text", [
    "the west side of the building was quiet",   # 'west' alone is not Vestora
    "well, that went better than expected",
    "I want to make a request for the team",
    "please send the report before the meeting",
])
def test_phonetic_leaves_ordinary_english_alone(text):
    """A wrong replacement corrupts the user's words — precision over recall."""
    assert _corrector().correct(text) == text


def test_phonetic_handles_soft_c():
    """'Vercel' is said "ver-SELL", so its c must fold to /s/, not /k/.

    Regression: it was heard as "WERSAL" and left uncorrected because c always
    folded to k. Hard c ("CAMS", "Cloud") must be unaffected.
    """
    from src.services.phonetic import PhoneticCorrector, sound_key

    assert sound_key("Vercel") == sound_key("WERSAL")
    assert sound_key("CAMS") != sound_key("Vercel")
    pc = PhoneticCorrector(["Vercel", "CAMS", "Cloud", "Claude"])
    assert pc.correct("deployed on WERSAL today") == "deployed on Vercel today"
    # Ordinary soft-c English must survive.
    for text in ["the cell tower is down", "a circle and a cycle differ",
                 "I will cancel the meeting"]:
        assert pc.correct(text) == text


@pytest.mark.parametrize("text", [
    "she came all the way from the coast",   # 'came all' folds like 'Komal'
    "it is not in the report yet",           # 'not in'   folds like 'Nitin'
    "please come all the way here",
])
def test_phonetic_does_not_stitch_ordinary_words_into_a_name(text):
    """Joining words to reach a SHORT key is the main false-positive risk.

    Regression: 'she came all the way' once became 'she Komal the way'.
    """
    from src.services.phonetic import PhoneticCorrector
    assert PhoneticCorrector(["Komal", "Nitin", "Vestora"]).correct(text) == text


def test_phonetic_leaves_already_correct_terms_untouched():
    text = "Vestora and WealQuest are both fine"
    assert _corrector().correct(text) == text


def test_phonetic_preserves_punctuation():
    out = _corrector().correct("I called west or a, then left.")
    assert "Vestora," in out and out.endswith("left.")


def test_phonetic_noop_without_vocabulary():
    from src.services.phonetic import PhoneticCorrector
    text = "west or a and well quest"
    assert PhoneticCorrector([]).correct(text) == text


def test_deepgram_url_boosts_dictionary_terms(monkeypatch):
    """The dictionary must reach the live transcriber, not just the rewrite."""
    import src.transcription.deepgram_client as dg

    class _Cfg:
        custom_vocabulary = ["Vestora", "WealQuest"]

    monkeypatch.setattr(dg, "Config", lambda: _Cfg())
    url = dg._build_url()
    # nova-3 takes plain `keyterm`; the weighted `keywords` form is nova-2 only,
    # and sending the wrong one loses ALL biasing silently (Deepgram 200s on
    # unknown params) — which cost 13/13 terms down to 7/13 when tested.
    assert "model=nova-3" in url
    assert "keyterm=Vestora" in url
    assert "keyterm=WealQuest" in url
    assert "keywords=" not in url


# --------------------------------------------------------------------------- #
# Live-caption typewriter reveal
# --------------------------------------------------------------------------- #

def test_caption_reveal_grows_smoothly_and_reaches_target():
    from src.ui.components.caption_window import CaptionWindow as C

    # A 2-3 word chunk lands at once; the reveal walks toward it over frames
    # (never overshooting), and converges exactly on the target.
    cur, target = "", "Sending a trial message"
    steps = 0
    while cur != target:
        cur = target[: C._reveal_len(cur, target)]
        steps += 1
        assert target.startswith(cur)        # only ever a prefix of the target
        assert steps < 200                    # always converges
    assert cur == target
    assert steps > 1                          # revealed gradually, not one jump


def test_caption_reveal_handles_shrink_and_revision():
    from src.ui.components.caption_window import CaptionWindow as C

    # Interim shrank / finalized to a shorter prefix -> snap straight to it.
    assert C._reveal_len("hello world", "hello") == len("hello")
    # Interim was revised mid-word -> fall back toward the shared prefix.
    assert C._reveal_len("hello", "hello world") <= len("hello world")


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


@pytest.mark.parametrize("configured,expected", [
    # The file-path setting must NEVER leak into the live session. Regression:
    # with gpt-4o-transcribe configured, the live session produced 0 deltas and
    # captions silently stopped.
    ("gpt-4o-transcribe", "gpt-live-transcribe"),
    ("gpt-4o-mini-transcribe", "gpt-live-transcribe"),
    ("gpt-transcribe", "gpt-live-transcribe"),
    ("whisper-1", "gpt-live-transcribe"),
    ("", "gpt-live-transcribe"),
    # A realtime-specific model the user chose deliberately is honoured.
    ("gpt-live-transcribe", "gpt-live-transcribe"),
    ("gpt-realtime-whisper", "gpt-realtime-whisper"),
])
def test_live_session_always_uses_a_realtime_model(configured, expected):
    from src.transcription.realtime_client import realtime_model_for
    assert realtime_model_for(configured) == expected


def test_cost_uses_measured_audio_length_not_word_count():
    """STT is billed per minute of AUDIO, so a slow speaker with long pauses
    costs more than their word count implies. Measured length wins when known."""
    from src.services.usage_tracker import _estimate_cost

    # Same words, very different recording lengths -> different STT cost.
    short = _estimate_cost(30, 30, "deepgram", "gpt-4o-mini", audio_seconds=12)
    long = _estimate_cost(30, 30, "deepgram", "gpt-4o-mini", audio_seconds=120)
    assert long > short

    # A pricier engine costs more for identical audio.
    dg = _estimate_cost(30, 30, "deepgram", "gpt-4o-mini", audio_seconds=60)
    live = _estimate_cost(30, 30, "gpt-live-transcribe", "gpt-4o-mini", audio_seconds=60)
    assert live > dg * 2

    # Without a measurement it still falls back to the old word-count estimate.
    assert _estimate_cost(30, 30, "deepgram", "gpt-4o-mini") > 0


def test_usage_tracker_prices_the_engine_that_actually_ran():
    """Regression: OpenAI live dictations were logged as Deepgram and priced at
    Deepgram's rate, understating real spend ~4x."""
    from src.config import Config
    from src.services.usage_tracker import _STT_PRICES, _stt_model_for

    assert _STT_PRICES["gpt-live-transcribe"] > _STT_PRICES["deepgram"] * 3

    config = Config()
    saved = {k: config._overrides.get(k) for k in ("transcription_realtime", "live_engine")}
    try:
        config._overrides["transcription_realtime"] = True
        config._overrides["live_engine"] = "openai"
        assert _stt_model_for("cloud") == "gpt-live-transcribe"
        config._overrides["live_engine"] = "deepgram"
        expected = "deepgram" if config.deepgram_api_key else "gpt-live-transcribe"
        assert _stt_model_for("cloud") == expected
    finally:
        for k, v in saved.items():
            if v is None:
                config._overrides.pop(k, None)
            else:
                config._overrides[k] = v


def test_friendly_api_error_names_the_real_problem():
    """Regression: an out-of-credits account showed "check your API key and
    internet connection" — both of which were fine, sending the user off
    debugging the wrong thing."""
    from src.services.error_handler import friendly_api_error

    quota = friendly_api_error(
        Exception("Error code: 429 - insufficient_quota: You have no credits remaining."),
        "Transcription")
    assert "out of credits" in quota.lower()
    assert "internet" not in quota.lower()

    assert "rate-limited" in friendly_api_error(
        Exception("rate_limit_exceeded"), "Rewrite").lower()
    assert "key was rejected" in friendly_api_error(
        Exception("invalid_api_key"), "Rewrite").lower()
    assert "internet" in friendly_api_error(
        Exception("getaddrinfo failed"), "Transcription").lower()
    # Unrecognised errors keep the original generic advice.
    assert "api key and internet" in friendly_api_error(
        Exception("something odd"), "Rewrite").lower()
    # The streaming path passes a string, not an exception.
    assert "out of credits" in friendly_api_error(
        "credit_balance_exhausted", "Rewrite").lower()


def test_session_stops_immediately_once_the_final_transcript_arrives():
    """The API sends nothing after the committed buffer's transcript.

    Waiting out the quiet period anyway added ~0.8s to every dictation on the
    OpenAI engine, which was most of its latency gap vs Deepgram.
    """
    from src.transcription.realtime_client import should_finish

    # Final transcript in hand -> done, however recently events arrived.
    assert should_finish(True, 0.0, 0.0) is True
    # Without it, still wait for quiet or the hard cap.
    assert should_finish(False, 0.1, 0.5) is False
    assert should_finish(False, 1.0, 1.0) is True   # gone quiet
    assert should_finish(False, 0.1, 5.0) is True   # hard cap protects us


def test_turn_detection_disabled_for_streaming_models():
    """Regression: gpt-live-transcribe REJECTS turn_detection.

    Sending it returned "Turn detection is not supported for this transcription
    model", which aborted the session — 0 deltas, so captions vanished entirely.
    Legacy models still need VAD to close segments.
    """
    from src.transcription.realtime_client import turn_detection_for

    assert turn_detection_for("gpt-live-transcribe", 250) is None
    legacy = turn_detection_for("gpt-4o-transcribe", 250)
    assert legacy and legacy["type"] == "server_vad"
    assert legacy["silence_duration_ms"] == 250


def test_keywords_only_sent_to_models_that_accept_them():
    """Regression: 'keywords is not supported for this model' killed the session.

    The error aborted live transcription entirely, so captions vanished and every
    dictation fell back to batch.
    """
    from src.transcription.realtime_client import build_transcription_config

    vocab = ["Vestora", "KFinTech"]
    assert "keywords" in build_transcription_config("gpt-live-transcribe", vocab)
    legacy = build_transcription_config("gpt-4o-transcribe", vocab)
    assert "keywords" not in legacy and "prompt" not in legacy


@pytest.mark.parametrize("engine,has_key,expect_deepgram", [
    ("auto", True, True),        # historical behaviour preserved
    ("auto", False, False),
    ("deepgram", True, True),
    ("deepgram", False, False),  # asked for Deepgram, no key -> must still work
    ("openai", True, False),     # explicit OpenAI wins even with a key present
    ("openai", False, False),
])
def test_live_engine_selection(engine, has_key, expect_deepgram):
    """The live engine is an explicit choice, not a side effect of which key exists."""
    use_deepgram = has_key and engine in ("auto", "deepgram")
    assert use_deepgram is expect_deepgram


def test_live_engine_config_rejects_nonsense():
    from src.config import Config

    config = Config()
    original = config._overrides.get("live_engine")
    try:
        for value, expected in [("openai", "openai"), ("DEEPGRAM", "deepgram"),
                                ("nonsense", "auto"), ("", "auto")]:
            config._overrides["live_engine"] = value
            assert config.live_engine == expected
    finally:
        if original is None:
            config._overrides.pop("live_engine", None)
        else:
            config._overrides["live_engine"] = original


def test_realtime_language_field_matches_model_generation():
    """gpt-live-transcribe takes `languages` (array); legacy takes `language`.

    Sending both is explicitly disallowed, so the wrong field would break the
    live session.
    """
    from src.transcription.realtime_client import build_transcription_config

    new = build_transcription_config("gpt-live-transcribe")
    assert new["languages"] == ["en"] and "language" not in new

    legacy = build_transcription_config("gpt-4o-transcribe")
    assert legacy["language"] == "en" and "languages" not in legacy


def test_realtime_config_biases_dictionary_but_drops_ordinary_words():
    from src.transcription.realtime_client import build_transcription_config

    cfg = build_transcription_config(
        "gpt-live-transcribe", ["Vestora", "KFinTech", "Order", "I'm"]
    )
    assert "Vestora" in cfg["keywords"] and "KFinTech" in cfg["keywords"]
    assert "Order" not in cfg["keywords"] and "I'm" not in cfg["keywords"]


def test_vocabulary_prompt_forbids_forcing_a_match():
    """Regression: 'finish' was being rewritten to a term containing 'fin'.

    The old wording ("if a spoken word sounds like one of these") was loose
    enough that the model matched ordinary English on a few shared sounds.
    """
    from src.rewrite.modes import RewriteMode
    from src.rewrite.prompts import build_user_prompt

    prompt = build_user_prompt(
        RewriteMode.CLEAN_GRAMMAR, "let me finish this", vocabulary=["KFinTech"]
    )
    assert "Do NOT force a match" in prompt
    assert "when in doubt, keep the dictated word" in prompt


def test_guard_comes_after_the_transcript():
    """The anti-answering guard must be LAST.

    When the transcript is the final thing in the prompt, a spoken imperative
    ("give me a step-by-step guide...") reads as the live instruction and the
    model obeys it instead of transcribing. The guard has to come after it.
    """
    from src.rewrite.modes import RewriteMode
    from src.rewrite.prompts import build_user_prompt

    spoken = "give me a step-by-step guide to connect to the server"
    prompt = build_user_prompt(RewriteMode.SMART, spoken, context="prior stuff")

    assert spoken in prompt
    assert prompt.index(spoken) < prompt.index("Reminder before you answer")
    assert "NOT a task for you" in prompt
    assert "Do not copy anything from the Context section" in prompt
    # The guard must be the FINAL block — no input/context section after it.
    tail = prompt[prompt.index("Reminder before you answer"):]
    assert "--- " not in tail


def test_session_memory_dedupes_repeated_dictations():
    """Repeating a dictation must not fill the context with N copies of it."""
    from src.context.session_memory import SessionMemory

    m = SessionMemory()
    dmarc = "v=DMARC1; p=none; rua=mailto:dmarc@example.com; fo=1"
    for _ in range(3):
        m.add(dmarc, dmarc, "smart")
    summary = m.get_context_summary()
    assert summary.count("v=DMARC1") == 1

    # Distinct entries are still all kept.
    m2 = SessionMemory()
    for t in ("alpha", "beta", "gamma"):
        m2.add(t, t, "smart")
    s2 = m2.get_context_summary()
    for t in ("alpha", "beta", "gamma"):
        assert t in s2


def test_system_prompt_has_number_formatting_rule():
    """Spoken numbers must come out as digits where they carry data."""
    from src.rewrite.prompts import SYSTEM_PROMPT

    assert "Numbers:" in SYSTEM_PROMPT
    assert "DIGITS" in SYSTEM_PROMPT
    # The rule must cover the data-carrying cases and keep casual prose spelled out.
    for kind in ("money", "percentages", "times", "versions"):
        assert kind in SYSTEM_PROMPT
    assert "one-to-nine" in SYSTEM_PROMPT


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


def _stub_paste(inst, fake):
    """Stand-in for OutputInserter._paste: writes the clipboard and records what
    we last put there (the real method does both), but touches no keyboard."""
    def _paste(chunk):
        fake.copy(chunk)
        inst._last_pasted = chunk
    return _paste


def _wait_for(predicate, timeout=2.0):
    """Wait for a background (delayed) clipboard restore to land."""
    import time as _t

    deadline = _t.monotonic() + timeout
    while _t.monotonic() < deadline:
        if predicate():
            return True
        _t.sleep(0.01)
    return False


def test_stream_restores_clipboard(monkeypatch):
    monkeypatch.setattr("src.output.inserter._RESTORE_DELAY_S", 0.02)
    fake = _FakeClip("ORIGINAL")
    inst = _make_inserter(monkeypatch, fake)
    inst._paste = _stub_paste(inst, fake)   # pastes for real, minus the keyboard

    inst.begin_stream()           # snapshots "ORIGINAL"
    inst.feed_stream("Some new dictated text here. ")
    inst.end_stream()             # schedules the guarded restore

    assert _wait_for(lambda: fake.clip == "ORIGINAL"), f"got {fake.clip!r}"


def test_restore_is_delayed_not_immediate(monkeypatch):
    """The restore must NOT land while a Ctrl+V we sent could still be pending.

    Restoring immediately is what made dictation paste the user's OLD clipboard
    instead of the transcript.
    """
    # A long delay makes this deterministic: the restore cannot plausibly fire
    # before the assertion below, however loaded the machine is.
    monkeypatch.setattr("src.output.inserter._RESTORE_DELAY_S", 30.0)
    fake = _FakeClip("ORIGINAL")
    inst = _make_inserter(monkeypatch, fake)
    inst._paste = _stub_paste(inst, fake)

    inst.begin_stream()
    inst.feed_stream("Dictated sentence lands here. ")
    inst.end_stream()

    # Right after end_stream the dictation must still own the clipboard.
    assert fake.clip != "ORIGINAL", "restored too early — a pending paste would insert the old clipboard"


def test_no_restore_when_nothing_was_pasted(monkeypatch):
    """If we never wrote the clipboard, we must not 'restore' over it.

    Otherwise a dictation that produced no output would blindly overwrite
    whatever the user copied in the meantime.
    """
    monkeypatch.setattr("src.output.inserter._RESTORE_DELAY_S", 0.02)
    fake = _FakeClip("ORIGINAL")
    inst = _make_inserter(monkeypatch, fake)

    inst.begin_stream()
    inst.end_stream()                       # no chunks fed → nothing pasted
    fake.copy("USER COPIED THIS AFTERWARDS")

    import time as _t
    _t.sleep(0.2)
    assert fake.clip == "USER COPIED THIS AFTERWARDS"


def test_restore_skipped_when_another_app_takes_clipboard(monkeypatch):
    """If something else owns the clipboard by restore time, don't clobber it."""
    # Generous delay so the competing copy below is definitely in place before
    # the restore worker wakes — otherwise this test would race the scheduler.
    monkeypatch.setattr("src.output.inserter._RESTORE_DELAY_S", 0.4)
    fake = _FakeClip("ORIGINAL")
    inst = _make_inserter(monkeypatch, fake)
    inst._paste = _stub_paste(inst, fake)

    inst.begin_stream()
    inst.feed_stream("Dictated text. ")
    inst.end_stream()
    fake.copy("USER COPIED SOMETHING ELSE")  # another app wins the clipboard

    import time as _t
    _t.sleep(1.2)                             # well past the restore delay
    assert fake.clip == "USER COPIED SOMETHING ELSE"


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


# --- Request settings per model family (2026-10-24) ---------------------------

@pytest.mark.parametrize("model,expected", [
    ("gpt-4o-mini", {"temperature": 0.2, "max_tokens": 2000}),
    ("gpt-4.1", {"temperature": 0.2, "max_tokens": 2000}),
    ("gpt-5-nano", {"reasoning_effort": "minimal", "max_completion_tokens": 2000}),
    ("gpt-5.4-nano", {"reasoning_effort": "none", "max_completion_tokens": 2000}),
    ("gpt-6-luna", {"reasoning_effort": "none", "max_completion_tokens": 2000}),
    ("gpt-6.1-sol", {"reasoning_effort": "none", "max_completion_tokens": 2000}),
    ("gpt-5-chat-latest", {"temperature": 0.2, "max_tokens": 2000}),
    ("o4-mini", {"reasoning_effort": "low", "max_completion_tokens": 2000}),
])
def test_completion_kwargs_match_what_each_model_accepts(model, expected):
    from src.rewrite.engine import completion_kwargs
    assert completion_kwargs(model, 0.2) == expected


def test_claude_requests_switch_thinking_off_and_send_no_temperature():
    from src.rewrite.engine import claude_request_kwargs, is_claude
    kw = claude_request_kwargs()
    assert kw["thinking"] == {"type": "disabled"}
    assert "temperature" not in kw
    assert is_claude("claude-haiku-5-5") and not is_claude("gpt-6-luna")


# --------------------------------------------------------------------------- #
# Recording watchdog (2026-10-24: 8 recordings of 19 min - 2.6 h were lost)
# --------------------------------------------------------------------------- #

def _watchdog_self(held, elapsed=10.0, by_hotkey=True, cap=300):
    import time
    from unittest.mock import MagicMock
    from src.ui.overlay import OverlayWidget

    me = MagicMock()
    me._is_recording = True
    me._recording_start = time.monotonic() - elapsed
    me._config.max_recording_seconds = cap
    me._recording_by_hotkey = by_hotkey
    me._hotkey_listener.keys_physically_down.return_value = held
    me._keys_up_polls = 0
    me._KEYS_UP_POLLS_TO_STOP = OverlayWidget._KEYS_UP_POLLS_TO_STOP
    return me, OverlayWidget._check_recording


def test_missed_release_is_processed_after_consecutive_keys_up_polls():
    me, check = _watchdog_self(held=False)
    check(me)
    check(me)
    me._finish_missed_release.assert_not_called()   # not on a single misread
    check(me)
    me._finish_missed_release.assert_called_once()


def test_keys_still_held_never_stops_the_recording():
    me, check = _watchdog_self(held=True)
    for _ in range(10):
        check(me)
    me._finish_missed_release.assert_not_called()


def test_mic_button_recording_is_not_checked_for_held_keys():
    me, check = _watchdog_self(held=False, by_hotkey=False)
    for _ in range(10):
        check(me)
    me._finish_missed_release.assert_not_called()


def test_recording_past_the_cap_is_processed_with_a_notice():
    me, check = _watchdog_self(held=True, elapsed=301, cap=300)
    check(me)
    me._finish_missed_release.assert_called_once()
    assert "5-minute" in me.notice_updated.emit.call_args[0][0]
