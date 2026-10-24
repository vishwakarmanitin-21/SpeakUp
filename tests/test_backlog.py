"""Checks for backlog.html — SpeakUp's single backlog and status tracker.

Ported from Vestora's two backlog gates (excel-vestor/scripts/check-backlog.mjs
and check-backlog-ids.mjs), 2026-10-24.

WHY THESE EXIST. backlog.html embeds the whole backlog as a `const ITEMS = [...]`
JavaScript array inside a <script> tag. Nothing else validates it: it is not part
of the app, the build or any other test. A stray syntax error (most often an
unescaped apostrophe inside a single-quoted string) silently blanks the page and
ships unnoticed — that happened on Vestora's copy across several commits.

The id check enforces the backlog's one structural rule: ids are PERMANENT. An
item is re-statused (shipped / withdrawn), never deleted or renumbered, because
commits, notes and other items cite ids — a vanished id turns every citation
into a pointer at nothing. backlog-id-baseline.json (repo root) lists every id
that has existed; none may disappear.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKLOG = ROOT / "backlog.html"
BASELINE = ROOT / "backlog-id-baseline.json"

REQUIRED_FIELDS = ("id", "title", "status", "priority", "kind", "category", "pillars", "summary")
KNOWN_STATUSES = {"open", "in-progress", "blocked", "parked", "shipped", "withdrawn"}
KNOWN_PRIORITIES = {"P1", "P2", "P3"}
KNOWN_KINDS = {"bug", "feature", "chore", "test"}
KNOWN_PILLARS = {"speed", "accuracy", "reliability", "effortless"}


# ── Extraction ───────────────────────────────────────────────────────────────

def _script_block() -> str:
    """The REAL <script> block: a line that is exactly "<script>", not the
    literal "<script>" that appears in the page's own prose."""
    lines = BACKLOG.read_text(encoding="utf-8").split("\n")
    start = end = -1
    for i, line in enumerate(lines):
        t = line.strip()
        if start < 0 and t == "<script>":
            start = i
        elif start >= 0 and t == "</script>":
            end = i
            break
    assert start >= 0 and end > start, "could not locate the <script> block in backlog.html"
    return "\n".join(lines[start + 1:end])


class _JsLiteralParser:
    """Reads a JavaScript array/object LITERAL (unquoted keys, single- or
    double-quoted strings, trailing commas, // and /* */ comments).

    Pure Python on purpose, so the field and id checks run even on a machine
    without node. It refuses anything that is not a plain literal rather than
    guessing — a check that cannot see must fail, never report clean.
    """

    _ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}

    def __init__(self, text: str) -> None:
        self.s = text
        self.i = 0

    def _skip(self) -> None:
        s = self.s
        while self.i < len(s):
            c = s[self.i]
            if c.isspace():
                self.i += 1
            elif s.startswith("//", self.i):
                nl = s.find("\n", self.i)
                self.i = len(s) if nl < 0 else nl + 1
            elif s.startswith("/*", self.i):
                close = s.find("*/", self.i + 2)
                if close < 0:
                    raise ValueError("unterminated comment")
                self.i = close + 2
            else:
                return

    def _peek(self) -> str:
        self._skip()
        if self.i >= len(self.s):
            raise ValueError("unexpected end of literal")
        return self.s[self.i]

    def value(self):
        c = self._peek()
        if c == "[":
            return self._array()
        if c == "{":
            return self._object()
        if c in "'\"`":
            return self._string()
        m = re.compile(r"-?\d+(\.\d+)?|true|false|null").match(self.s, self.i)
        if not m:
            raise ValueError(f"unsupported token at offset {self.i}: {self.s[self.i:self.i + 30]!r}")
        self.i = m.end()
        tok = m.group(0)
        if tok in ("true", "false", "null"):
            return {"true": True, "false": False, "null": None}[tok]
        return float(tok)

    def _array(self) -> list:
        self.i += 1
        out = []
        while True:
            if self._peek() == "]":
                self.i += 1
                return out
            out.append(self.value())
            if self._peek() == ",":
                self.i += 1

    def _object(self) -> dict:
        self.i += 1
        out = {}
        while True:
            c = self._peek()
            if c == "}":
                self.i += 1
                return out
            if c in "'\"":
                key = self._string()
            else:
                m = re.compile(r"[A-Za-z_$][\w$]*").match(self.s, self.i)
                if not m:
                    raise ValueError(f"bad object key at offset {self.i}")
                key = m.group(0)
                self.i = m.end()
            if self._peek() != ":":
                raise ValueError(f"expected ':' after key {key!r}")
            self.i += 1
            out[key] = self.value()
            if self._peek() == ",":
                self.i += 1

    def _string(self) -> str:
        s = self.s
        quote = s[self.i]
        if quote == "`":
            raise ValueError("template literals are not supported in ITEMS — use '...' or \"...\"")
        self.i += 1
        buf = []
        while True:
            if self.i >= len(s):
                raise ValueError("unterminated string")
            c = s[self.i]
            if c == quote:
                self.i += 1
                return "".join(buf)
            if c == "\n":
                raise ValueError("raw newline inside a string")
            if c == "\\":
                e = s[self.i + 1]
                if e == "u":
                    if s[self.i + 2] == "{":
                        close = s.index("}", self.i)
                        buf.append(chr(int(s[self.i + 3:close], 16)))
                        self.i = close + 1
                    else:
                        buf.append(chr(int(s[self.i + 2:self.i + 6], 16)))
                        self.i += 6
                    continue
                if e == "x":
                    buf.append(chr(int(s[self.i + 2:self.i + 4], 16)))
                    self.i += 4
                    continue
                if e == "\n":  # line continuation
                    self.i += 2
                    continue
                buf.append(self._ESCAPES.get(e, e))
                self.i += 2
                continue
            buf.append(c)
            self.i += 1


def _items() -> list[dict]:
    code = _script_block()
    tok = "const ITEMS = ["
    start = code.find(tok)
    assert start >= 0, 'backlog.html <script> block has no "const ITEMS = [" array'
    end = code.find("\n];", start)
    assert end >= 0, "could not find the end of the ITEMS array (a line starting with '];')"
    literal = code[start + len(tok) - 1:end + 2]
    items = _JsLiteralParser(literal).value()
    assert isinstance(items, list) and items, "ITEMS parsed to nothing — refusing to report clean"
    return items


# ── Checks ───────────────────────────────────────────────────────────────────

def test_script_block_parses_with_node(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not on PATH — the syntax gate needs it")
    script = tmp_path / "backlog_script.js"
    script.write_text(_script_block(), encoding="utf-8")
    result = subprocess.run([node, "--check", str(script)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, (
        "backlog.html <script> block has a SYNTAX ERROR — the page would render empty.\n"
        "Most likely an unescaped apostrophe inside a single-quoted string (write \\' ).\n"
        + result.stderr
    )


def test_no_python_style_unicode_escapes() -> None:
    # JavaScript has no 8-digit \UXXXXXXXX escape: it renders as the literal text
    # "U0001f7e2". Valid JS, so node --check cannot see it (found on Vestora's copy).
    bad = re.findall(r"\\U[0-9a-fA-F]{8}", _script_block())
    assert not bad, f"{len(bad)} Python-style \\U escape(s), e.g. {bad[0]} — write the character itself"


def test_every_item_has_required_fields_and_known_values() -> None:
    problems = []
    for it in _items():
        iid = it.get("id")
        if not isinstance(iid, str) or not iid or len(iid) > 60 or re.search(r"\s", iid):
            problems.append(f"id is not a well-formed id: {str(iid)[:80]!r}")
            continue
        for field in REQUIRED_FIELDS:
            v = it.get(field)
            if v is None or (isinstance(v, (str, list)) and not v):
                problems.append(f"{iid}: missing {field}")
        if it.get("status") not in KNOWN_STATUSES:
            problems.append(f"{iid}: unknown status {it.get('status')!r} (use one of {sorted(KNOWN_STATUSES)})")
        if it.get("priority") not in KNOWN_PRIORITIES:
            problems.append(f"{iid}: unknown priority {it.get('priority')!r}")
        if it.get("kind") not in KNOWN_KINDS:
            problems.append(f"{iid}: unknown kind {it.get('kind')!r}")
        pillars = it.get("pillars")
        if not isinstance(pillars, list) or not pillars or not set(pillars) <= KNOWN_PILLARS:
            problems.append(f"{iid}: pillars must be a non-empty list from {sorted(KNOWN_PILLARS)}, got {pillars!r}")
    assert not problems, f"{len(problems)} backlog item problem(s):\n  " + "\n  ".join(problems)


def test_ids_are_unique() -> None:
    ids = [it.get("id") for it in _items()]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    assert not dupes, f"duplicate backlog ids: {dupes}"


def test_no_baselined_id_disappears() -> None:
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    known = baseline.get("ids") or []
    assert known, "backlog-id-baseline.json lists no ids — refusing to report clean"
    current = {it["id"] for it in _items()}
    missing = [i for i in known if i not in current]
    assert not missing, (
        f"{len(missing)} backlog id(s) disappeared from backlog.html: {missing}\n"
        "Ids are permanent. Restore the item and mark it 'shipped' or 'withdrawn' instead of deleting it."
    )


def test_every_item_is_in_the_baseline() -> None:
    # Keeps the guard above covering NEW items too: without this, an item added
    # after the baseline was written could be deleted again without any test failing.
    known = set(json.loads(BASELINE.read_text(encoding="utf-8")).get("ids") or [])
    unlisted = [it["id"] for it in _items() if it["id"] not in known]
    assert not unlisted, (
        f"new backlog id(s) not yet in backlog-id-baseline.json: {unlisted}\n"
        "Append them to its \"ids\" list (never remove one)."
    )
