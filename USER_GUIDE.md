# SpeakUp — User Guide

SpeakUp turns your speech into clean, structured text anywhere you type. Hold a
hotkey, talk, release — and polished text appears at your cursor.

This guide is for someone installing SpeakUp for the first time. No coding needed.

---

## 1. What you need

- A Windows PC.
- An **OpenAI API key** (instructions below). This is what powers the speech-to-text
  and the cleanup. You pay OpenAI directly for what you use — typically a few cents
  for a long session of dictation.

> **Note:** an OpenAI *API key* is different from a ChatGPT Plus subscription.
> ChatGPT Plus does **not** include API access — you need an API key from the
> developer platform below.

---

## 2. Get your OpenAI API key (5 minutes)

1. Go to **https://platform.openai.com** and sign in (or create a free account).
2. Add a payment method and a little credit: **Settings → Billing → Add payment
   method**, then add a small amount (e.g. $5). API usage is pay-as-you-go.
3. Open **https://platform.openai.com/api-keys**.
4. Click **Create new secret key**, give it a name (e.g. "SpeakUp"), and **Create**.
5. **Copy the key** (it starts with `sk-...`). You can only see it once — keep it
   somewhere safe. If you lose it, just create a new one.

---

## 3. Install and first run

1. Put **`SpeakUp.exe`** anywhere you like (e.g. your Desktop) and double-click it.
2. On first launch it asks for your OpenAI API key — **paste it** and click OK.
3. A small floating bar appears at the bottom of your screen, plus a microphone
   icon in your system tray (bottom-right of the taskbar).

That's it — you're ready.

---

## 4. How to use it

1. Click into any text field (an email, chat box, document…).
2. **Hold `Ctrl` + `Windows` key together and speak.**
3. **Release** — your words are cleaned up and typed in at your cursor.

It removes "um/uh/like", fixes grammar, honours corrections ("Tuesday — no,
Wednesday"), and formats to suit the app you're in (short and casual in chat,
fuller in a document).

**Pick a style** from the dropdown on the bar — Smart (automatic) is the default;
you can also choose Email, LinkedIn Post, PRD, Structured Notes, and more.

---

## 5. Settings (the gear icon, or tray → Settings)

| Setting | What it does |
|---|---|
| **OpenAI API Key** | Your key. Use **Show** to reveal it, **Test** to check it works. |
| **GPT Model** | The model that cleans up your text. `gpt-4o-mini` (fast) is a good default. |
| **Speech Model** | `gpt-4o-transcribe` (most accurate) / `gpt-4o-mini-transcribe` (faster). |
| **Default Mode** | Which rewrite style is selected on launch (Smart recommended). |
| **Output Mode** | Auto-paste at cursor (default), Clipboard, or Preview window. |
| **Hotkey** | The push-to-talk keys. Change if `Ctrl+Win` clashes with something. |
| **Personal Dictionary** | Add your names/jargon so they're always spelled right. |
| **Live transcription (experimental)** | Transcribe while you speak for lower lag. |
| **Start with Windows** | Launch SpeakUp automatically when you log in. |

---

## 6. Which AI models give the best results?

SpeakUp uses OpenAI for both steps. Recommended:

- **Speech-to-text:** `gpt-4o-transcribe` — the most accurate, best for long or
  technical speech. Switch to `gpt-4o-mini-transcribe` if you prefer speed/lower cost.
- **Cleanup/formatting:** `gpt-4o-mini` — fast, cheap, and high quality for this task.
  Use `gpt-4o` if you want maximum polish on important writing (a little slower).
- **Lowest lag:** turn on **Live transcription** (experimental) to transcribe while
  you talk. If it ever can't connect, SpeakUp automatically falls back to the standard
  mode, so you never lose a dictation.

---

## 7. Your privacy & where things are stored

- Your API key is stored **only on your own PC**, privately under your user profile
  (`%APPDATA%\SpeakUp`). It is never bundled into the app and never shared.
- Audio is processed in memory and sent to OpenAI for transcription — it is **not
  saved to disk**.
- Settings and your personal dictionary stay on your PC.

---

## 8. Troubleshooting

| Problem | Fix |
|---|---|
| "API key" error / nothing happens | Open Settings → paste your key → click **Test** to confirm it works. |
| The hotkey doesn't trigger | Settings → change the **Hotkey** to something else (e.g. `ctrl+shift+space`). |
| No text appears | Make sure your cursor is in a text field before you release the keys. |
| Microphone error | Check your mic is connected and not in use by another app. |
| Want to start fresh | Delete the `%APPDATA%\SpeakUp` folder; the app will prompt for your key again. |

---

*SpeakUp is a personal productivity tool. You are billed by OpenAI for your own API
usage; keep an eye on your usage at platform.openai.com.*
