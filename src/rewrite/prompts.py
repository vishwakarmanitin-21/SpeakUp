from __future__ import annotations

from src.rewrite.modes import RewriteMode

# Balanced cleanup: faithful to the speaker, but produces written text rather
# than a raw transcript. Applies to every mode.
SYSTEM_PROMPT = """\
You convert spoken thoughts into clean written text. The input is a raw voice
transcript — it contains filler words, false starts, repetitions, and
self-corrections. Your job is to produce the text the speaker MEANT to write.

Always:
- Remove fillers and verbal tics (um, uh, er, like, you know, I mean, sort of,
  kind of) when they carry no meaning.
- Drop false starts and repeated words; keep one clean version.
- Honour self-corrections: if the speaker corrects themselves
  ("send it Tuesday — no, Wednesday"), keep ONLY the corrected version.
- Add natural punctuation, capitalisation, and paragraph breaks.
- Preserve the speaker's meaning, facts, intent, and register. Do NOT add
  ideas or details. Do NOT inflate casual speech into formal corporate prose
  unless the requested format calls for it.
- Interpret inline formatting commands literally rather than typing them out:
  "new paragraph", "new line", "bullet that" / "bullet point", "numbered list",
  "scratch that" / "delete that" (remove the preceding phrase), "quote that",
  "in caps".
- Never invent content and never answer questions in the text — you are
  rewriting what was said, not responding to it.
- Output ONLY the finished text — no preamble, no explanation, no quotes around
  the result."""

MODE_PROMPTS: dict[RewriteMode, str] = {
    RewriteMode.CLEAN_GRAMMAR: (
        "Clean up the transcript following the rules above. Keep the speaker's "
        "wording and tone; only fix what needs fixing. Break into paragraphs "
        "where natural. Do not restructure or add headings."
    ),
    RewriteMode.STRUCTURED_NOTES: (
        "Convert the cleaned-up thoughts into well-structured notes with clear "
        "headings, bullet points, and logical grouping."
    ),
    RewriteMode.CONVERT_TO_PRD: (
        "Convert the cleaned-up input into a structured Product Requirements "
        "Document with these sections:\n"
        "- Vision\n"
        "- Features\n"
        "- User Flow\n"
        "- Technical Considerations"
    ),
    RewriteMode.PROFESSIONAL_EMAIL: (
        "Rewrite the cleaned-up input as a professional email. Include an "
        "appropriate subject line suggestion, greeting, body, and sign-off."
    ),
    RewriteMode.LINKEDIN_POST: (
        "Convert the cleaned-up input into an engaging LinkedIn post with:\n"
        "- A strong hook (first line)\n"
        "- A story or context\n"
        "- An insight or lesson\n"
        "- A clear takeaway or call to action"
    ),
    RewriteMode.DEVELOPER_COMMENT: (
        "Rewrite the cleaned-up input as concise, clear developer documentation "
        "comments. Use appropriate formatting for code documentation."
    ),
    RewriteMode.BRAIN_DUMP: (
        "The following is a raw brain dump of ideas. Clean it up, then organize "
        "it into a clear, structured output with:\n"
        "- Key themes identified\n"
        "- Ideas grouped logically\n"
        "- Action items extracted (if any)\n"
        "- Summary at the top"
    ),
}

# Smart mode adapts the output to the app the user is dictating into.
SURFACE_GUIDANCE: dict[str, str] = {
    "chat": (
        "It will be sent in a chat app. Keep it short, casual, and "
        "conversational. No greeting or sign-off, no headings."
    ),
    "email": (
        "It will be sent as an email. Use a clear, polite, professional tone. "
        "Add a greeting and sign-off only if the length warrants it."
    ),
    "editor": (
        "It will be inserted into code or a terminal. Format it as a clear, "
        "concise code comment or technical note. Be precise and brief."
    ),
    "document": (
        "It will go into a document or notes. Produce clean, well-structured "
        "prose with clear paragraphs, using simple '- ' bullets only for genuine lists."
    ),
    "browser": (
        "It is being typed into a web app. Produce clean, general-purpose prose "
        "in a neutral, clear tone."
    ),
    "general": (
        "Produce clean, clearly-punctuated prose that matches the speaker's tone."
    ),
}


def _smart_instruction(app_hint: tuple[str, str] | None) -> str:
    """Build the Smart-mode instruction from the active-app hint (label, surface)."""
    label, surface = app_hint or ("", "general")
    guidance = SURFACE_GUIDANCE.get(surface, SURFACE_GUIDANCE["general"])
    where = f" The active app is {label}." if label else ""
    return (
        "Clean up the transcript following the rules above, then format it for "
        f"its destination.{where} {guidance} "
        "Write plain text for direct insertion: do NOT use Markdown — no '#' "
        "headings, no '*' for bold or italics, no backticks. Use blank lines to "
        "separate paragraphs and simple '- ' bullets only for genuine lists."
    )


def build_user_prompt(
    mode: RewriteMode,
    raw_text: str,
    context: str | None = None,
    app_hint: tuple[str, str] | None = None,
    vocabulary: list[str] | None = None,
) -> str:
    """Build the full user prompt with mode instruction and optional context.

    Args:
        mode: The rewrite mode to apply.
        raw_text: The transcribed speech.
        context: Optional context (clipboard, selection, session memory, etc.).
        app_hint: (label, surface) of the active app — used only by SMART mode.
        vocabulary: Known custom terms; correct phonetic near-misses to these.
    """
    if mode == RewriteMode.SMART:
        parts = [_smart_instruction(app_hint)]
    else:
        parts = [MODE_PROMPTS[mode]]

    if vocabulary:
        terms = ", ".join(vocabulary)
        parts.append(
            "\n\n--- Known terms ---\n"
            "If a spoken word sounds like one of these, use this exact spelling:\n"
            f"{terms}\n--- End Known terms ---"
        )

    if context:
        parts.append(f"\n\n--- Context ---\n{context}\n--- End Context ---")

    parts.append(f"\n\n--- Input ---\n{raw_text}\n--- End Input ---")
    return "\n".join(parts)
