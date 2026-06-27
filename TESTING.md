# Testing FlowAI (Speak-up) — Plain-Language Guide

Windows / PowerShell. Run commands **one line at a time** (don't chain with `&&`).

> **Python:** use **3.13** (`py -3.13`). The app needs Python ≥ 3.11. Avoid 3.14 —
> some packages (e.g. PyQt5) don't have ready wheels for it yet.

---

## Part A — One-time setup (~5 min)

**1. Go to the project**
```powershell
cd D:\Dev\Speak-up
```

**2. Create a private Python 3.13 environment** (a sandbox for this app's packages)
```powershell
py -3.13 -m venv .venv
```

**3. Turn it on**
```powershell
.\.venv\Scripts\Activate.ps1
```
You should see `(.venv)` at the start of your prompt. *If PowerShell blocks it with a
security error,* run this once and repeat step 3:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

**4. Install the app + dependencies (including test tools)**
```powershell
pip install -e ".[dev]"
```

**5. Confirm your OpenAI key is present** (the app will prompt you on launch if not)
```powershell
Test-Path .env
```
`True` = good. `False` = just paste the key when the app asks on first launch.

---

## Part B — Quickest smoke test (CLI, no overlay)

Checks the core engine (record → transcribe → clean up) in isolation.

```powershell
python -m src.main --cli
```
- Hold **`Ctrl` + `Windows`** together, speak a deliberately messy sentence
  (*"um so like I was thinking we could move the deadline, no wait, keep the
  deadline but cut scope"*), then release.
- **Good result:** it prints the raw transcription, then a cleaned version with the
  fillers and false start gone and the self-correction resolved.
- Press `Ctrl+C` to exit.

---

## Part C — The full desktop app

```powershell
python -m src.main
```
A small floating bar appears (bottom-right) plus a tray mic icon. If asked, paste your
OpenAI key.

**Test 1 — Streaming output (the "no lag" feel)**
1. Open Notepad, click inside it.
2. Hold `Ctrl+Win`, speak, release.
3. **Look for:** text types itself in word-by-word, starting almost immediately.

**Test 2 — Smart mode adapts to the app**
1. Say the same thing into Notepad (document) and into a chat app (Slack/Teams/etc.).
2. **Look for:** document version = fuller prose; chat version = shorter, casual.
   The bar dropdown reads "Smart (auto-format)".

**Test 3 — Personal dictionary**
1. Gear icon (or tray → Settings) → Personal Dictionary.
2. Add terms, e.g. `Vestora, WealQuest, Supabase`. Save.
3. Dictate using one. **Look for:** it's spelled exactly as entered.

**Test 4 — Clipboard is protected**
1. Copy any text with `Ctrl+C`.
2. Dictate into Notepad.
3. Paste (`Ctrl+V`) somewhere. **Look for:** your original copied text pastes,
   not the dictation.

**Test 5 — Cancel (optional)**
- Start dictating, press `Esc` mid-way → aborts cleanly.

---

## Part C2 — (Optional) Experimental live transcription

This streams your voice to OpenAI *while you speak*, for the lowest possible lag.
It's experimental and off by default. To try it:

**1. Install the extra dependency (one time)**
```powershell
pip install -e ".[realtime]"
```

**2. Turn it on:** Settings → Transcription → tick **"Live transcription —
transcribe while speaking (experimental)"** → Save.

**3. Test it:** dictate as usual.
- **Good result:** after you release the hotkey, the cleaned text appears almost
  immediately (little or no "transcribing" pause).
- **If it fails:** you'll see a clear message telling you to turn it off in
  Settings; the normal mode keeps working. Please send me the last ~30 lines of
  `flowai.log` (especially any lines starting `Realtime`) so I can finalise it:
```powershell
Get-Content flowai.log -Tail 30
```

---

## Part D — Automated tests (19 built-in checks)

```powershell
python -m pytest -q
```
**Good result:** all tests pass.

---

## Part E — If something misbehaves

- **Logs:**
```powershell
Get-Content flowai.log -Tail 40
```
- **Hotkey clashes?** Settings → change Hotkey (e.g. `ctrl+shift+space`), Save.
- **API key error?** Settings → API Settings → re-enter the key.
- **Nothing types in?** Make sure the target app's cursor is focused before releasing
  the hotkey.

---

*This guide reflects the build with: balanced disfluency cleanup, Smart auto-format
mode, personal dictionary, clipboard-safe paste, and streaming word-by-word output.*
