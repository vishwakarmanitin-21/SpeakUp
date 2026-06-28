"""Auto-learning personal dictionary.

Watches dictations for recurring proper-noun-like words (names, jargon,
acronyms) that aren't already in the user's dictionary, and offers them as
suggestions to add — so the dictionary grows from real use instead of manual
upkeep. Suggestions surface non-intrusively in Settings → Personal Dictionary.

Persistent store (per-user data dir): vocab_suggestions.json
    { "counts": {term: n}, "ignored": [term, ...] }
"""
from __future__ import annotations

import json
import logging
import re

from src.config import Config

logger = logging.getLogger("speakup")

_FILE_NAME = "vocab_suggestions.json"
_THRESHOLD = 2          # times a term must recur before it's suggested
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]{2,}")

# Capitalised-but-common words to never suggest (mostly sentence starters).
_COMMON = {
    "the", "this", "that", "these", "those", "there", "their", "them", "they",
    "and", "but", "for", "with", "from", "your", "you", "yours", "our", "ours",
    "what", "when", "where", "why", "how", "who", "which", "while", "would",
    "could", "should", "will", "shall", "can", "may", "might", "must", "have",
    "has", "had", "was", "were", "are", "been", "being", "its", "his", "her",
    "yes", "okay", "hello", "hey", "please", "thanks", "thank", "also", "just",
    "now", "then", "here", "today", "tomorrow", "yesterday", "let", "lets",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "some", "any", "all", "not",
    "because", "before", "after", "about", "into", "over", "under", "again",
}


class VocabLearner:
    """Learns candidate dictionary terms from dictations."""

    def __init__(self) -> None:
        self._path = Config().data_dir / _FILE_NAME
        self._data = self._load()

    def _load(self) -> dict:
        if self._path.exists():
            try:
                with open(self._path, encoding="utf-8") as f:
                    d = json.load(f)
                d.setdefault("counts", {})
                d.setdefault("ignored", [])
                return d
            except Exception:
                pass
        return {"counts": {}, "ignored": []}

    def _save(self) -> None:
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
        except Exception as e:
            logger.warning("Could not save vocab suggestions: %s", e)

    def _known(self) -> set[str]:
        """Lowercased terms already in the dictionary or ignored."""
        known = {t.lower() for t in Config().custom_vocabulary}
        known.update(t.lower() for t in self._data.get("ignored", []))
        return known

    def observe(self, text: str) -> None:
        """Scan one dictation for candidate terms and bump their counts."""
        if not text:
            return
        try:
            known = self._known()
            counts = self._data["counts"]
            seen_this_run: set[str] = set()
            for word in _WORD_RE.findall(text):
                if not word[0].isupper():
                    continue
                low = word.lower()
                if low in _COMMON or low in known or low in seen_this_run:
                    continue
                seen_this_run.add(low)
                counts[word] = counts.get(word, 0) + 1
            # Bound the store.
            if len(counts) > 200:
                self._data["counts"] = dict(
                    sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:200]
                )
            self._save()
        except Exception as e:
            logger.debug("vocab observe failed: %s", e)

    def pending_suggestions(self) -> list[str]:
        """Terms seen enough times, not yet added or ignored (most frequent first)."""
        known = self._known()
        items = [
            (t, n) for t, n in self._data.get("counts", {}).items()
            if n >= _THRESHOLD and t.lower() not in known
        ]
        items.sort(key=lambda kv: kv[1], reverse=True)
        return [t for t, _ in items]

    def accept(self, term: str) -> None:
        """Add a term to the personal dictionary and drop it from suggestions."""
        config = Config()
        vocab = list(config.custom_vocabulary)
        if term.lower() not in {v.lower() for v in vocab}:
            vocab.append(term)
            config.save_user_overrides({"custom_vocabulary": vocab})
            config.reload()
        self._data.get("counts", {}).pop(term, None)
        self._save()

    def ignore(self, term: str) -> None:
        """Never suggest this term again."""
        if term not in self._data.setdefault("ignored", []):
            self._data["ignored"].append(term)
        self._data.get("counts", {}).pop(term, None)
        self._save()
