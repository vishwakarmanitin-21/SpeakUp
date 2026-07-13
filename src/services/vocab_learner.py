"""Auto-learning personal dictionary.

Watches dictations for recurring proper-noun-like words (names, jargon,
acronyms) that aren't already in the user's dictionary, and offers them as
suggestions to add — so the dictionary grows from real use instead of manual
upkeep. Suggestions surface non-intrusively in Settings → Personal Dictionary.

Key heuristic: a word is only a candidate if it appears capitalised
MID-SENTENCE. Words capitalised only because they start a sentence
("Additionally", "Sure", "Considering", "Hope") are grammar, not proper nouns,
so they're ignored. Real names/brands ("Vestora", "GitHub") show up capitalised
in the middle of sentences too. A stop-word set and pruning are backups.

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
_THRESHOLD = 3          # times a term must recur mid-sentence before it's suggested
_LEAD_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]{2,}")
_SENTENCE_END = ".!?:;\n"

# Backup stop-word set — common words that must never be suggested even if they
# somehow appear capitalised mid-sentence, plus the ones we've seen leak in.
_COMMON = {
    # articles / pronouns / determiners
    "the", "this", "that", "these", "those", "there", "their", "them", "they",
    "your", "yours", "our", "ours", "his", "her", "its", "you", "yourself",
    "anything", "anyone", "anybody", "everything", "everyone", "everybody",
    "something", "someone", "somebody", "nothing", "nobody", "whatever",
    "whoever", "whichever", "whenever", "wherever", "some", "any", "all",
    "each", "every", "another", "both", "either", "neither", "such",
    # connectives / conjunctions / prepositions
    "and", "but", "for", "nor", "yet", "so", "or", "with", "from", "into",
    "over", "under", "about", "before", "after", "because", "since", "though",
    "although", "unless", "whether", "while", "against", "between", "among",
    # question / relative words
    "what", "when", "where", "why", "how", "who", "which",
    # modals / auxiliaries / common verbs
    "would", "could", "should", "shall", "will", "can", "may", "might", "must",
    "have", "has", "had", "was", "were", "are", "been", "being", "does", "did",
    "hope", "think", "believe", "guess", "suppose", "wonder", "wish", "want",
    "need", "let", "lets", "make", "made", "get", "got", "going", "went",
    "come", "came", "take", "took", "see", "saw", "know", "knew", "say", "said",
    "tell", "told", "ask", "asked", "look", "looking", "try", "trying", "keep",
    "put", "give", "find", "found", "feel", "felt", "work", "working", "start",
    "started", "add", "added", "using", "based", "given", "considering",
    "regarding", "following", "assuming", "doing", "done", "being",
    # sentence-starter adverbs / discourse markers
    "additionally", "also", "however", "therefore", "moreover", "furthermore",
    "meanwhile", "otherwise", "nevertheless", "nonetheless", "consequently",
    "accordingly", "similarly", "likewise", "instead", "besides", "anyway",
    "anyhow", "actually", "basically", "honestly", "frankly", "clearly",
    "obviously", "certainly", "definitely", "probably", "possibly", "perhaps",
    "maybe", "surely", "sure", "indeed", "overall", "generally", "usually",
    "normally", "typically", "currently", "recently", "finally", "eventually",
    "ultimately", "initially", "originally", "essentially", "specifically",
    "particularly", "especially", "importantly", "interestingly",
    "unfortunately", "fortunately", "hopefully",
    # misc common
    "yes", "okay", "well", "hello", "hey", "please", "thanks", "thank",
    "just", "only", "even", "still", "really", "very", "quite", "rather", "too",
    "now", "then", "here", "today", "tomorrow", "yesterday", "once", "first",
    "second", "third", "next", "last", "again", "bank", "not", "than",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
}

# Words the speech model already knows (so a personal-dictionary entry is
# pointless) or that are otherwise common: brands/products, Title-Case business
# words, acronyms, and contractions (I'm/I've are always capitalised).
_COMMON |= {
    # contractions
    "i", "i've", "i'm", "i'll", "i'd", "we're", "we've", "we'll", "we'd",
    "you're", "you've", "you'll", "you'd", "they're", "they've", "they'll",
    "they'd", "it's", "that's", "there's", "here's", "what's", "who's", "let's",
    "don't", "doesn't", "didn't", "won't", "can't", "cannot", "isn't", "aren't",
    "wasn't", "weren't", "haven't", "hasn't", "hadn't", "wouldn't", "shouldn't",
    "couldn't", "mustn't", "we", "he", "she", "it",
    # brands / products / tech the STT model already recognises
    "chrome", "github", "gmail", "google", "windows", "microsoft", "apple",
    "amazon", "aws", "azure", "meta", "facebook", "instagram", "whatsapp",
    "telegram", "slack", "zoom", "teams", "outlook", "excel", "word",
    "powerpoint", "onedrive", "sharepoint", "linkedin", "twitter", "youtube",
    "netflix", "spotify", "notion", "figma", "canva", "jira", "confluence",
    "trello", "asana", "gitlab", "bitbucket", "docker", "kubernetes", "python",
    "java", "javascript", "typescript", "react", "angular", "node", "android",
    "ios", "mac", "macos", "linux", "ubuntu", "safari", "firefox", "edge",
    "bing", "chatgpt", "openai", "deepgram", "claude", "anthropic", "gemini",
    "copilot", "salesforce", "hubspot", "stripe", "paypal", "visa",
    "mastercard", "uber", "swiggy", "zomato", "paytm", "phonepe",
    # common Title-Case business / doc words
    "review", "report", "meeting", "project", "update", "draft", "notes",
    "note", "email", "team", "sprint", "roadmap", "backlog", "design", "sales",
    "marketing", "finance", "admin", "budget", "plan", "agenda", "summary",
    "action", "task", "deadline", "milestone", "feedback", "proposal",
    "contract", "invoice", "dashboard", "analytics", "metrics", "strategy",
    "vision", "mission", "goal", "objective", "quarter", "annual", "monthly",
    "weekly", "daily", "morning", "evening", "afternoon", "night", "week",
    "month", "year", "day", "time",
    # common acronyms
    "etf", "sip", "nav", "ipo", "gst", "roi", "kpi", "api", "url", "pdf",
    "csv", "faq", "ceo", "cfo", "cto", "coo", "hr", "qa", "ux", "ui", "id",
    "ok",
}


class VocabLearner:
    """Learns candidate dictionary terms from dictations."""

    def __init__(self) -> None:
        self._path = Config().data_dir / _FILE_NAME
        self._data = self._load()
        self._prune_common()

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

    def _prune_common(self) -> None:
        """Drop any previously-stored counts that are now stop-words."""
        counts = self._data.get("counts", {})
        stale = [t for t in counts if t.lower() in _COMMON]
        if stale:
            for t in stale:
                counts.pop(t, None)
            self._save()

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
        """Count proper-noun-like words that appear capitalised MID-sentence."""
        if not text or not Config().suggest_dictionary_terms:
            return
        try:
            known = self._known()
            counts = self._data["counts"]
            seen_this_run: set[str] = set()
            at_sentence_start = True
            for token in text.split():
                m = _LEAD_WORD_RE.match(token)
                if m:
                    word = m.group(0)
                    low = word.lower()
                    if (
                        word[0].isupper()
                        and not at_sentence_start      # grammar-capitalised -> skip
                        and low not in _COMMON
                        and low not in known
                        and low not in seen_this_run
                    ):
                        seen_this_run.add(low)
                        counts[word] = counts.get(word, 0) + 1
                # The NEXT token starts a sentence if this one ended one.
                at_sentence_start = bool(token) and token[-1] in _SENTENCE_END

            if len(counts) > 200:
                self._data["counts"] = dict(
                    sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:200]
                )
            self._save()
        except Exception as e:
            logger.debug("vocab observe failed: %s", e)

    def pending_suggestions(self) -> list[str]:
        """Terms seen enough times, not yet added/ignored (most frequent first)."""
        if not Config().suggest_dictionary_terms:
            return []
        known = self._known()
        items = [
            (t, n) for t, n in self._data.get("counts", {}).items()
            if n >= _THRESHOLD and t.lower() not in known and t.lower() not in _COMMON
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
