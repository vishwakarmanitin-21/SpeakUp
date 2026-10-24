"""Compare clean-up (rewrite) models on speed, cost and term accuracy.

Time-to-first-word is the latency you feel after releasing the hotkey, so it is
the headline number. Each model gets the app's REAL system prompt, dictionary
and request settings (reasoning switched off where the model allows it), and
the same realistic dictations. One warm-up call per model is discarded so a
cold TLS handshake does not count against whoever happens to go first, and
rounds are interleaved so network drift hits every model equally.

Usage
-----
  python scripts/benchmark_rewrite.py
  python scripts/benchmark_rewrite.py --models gpt-6-luna,claude-haiku-5-5 --rounds 5
  python scripts/benchmark_rewrite.py --show      # print every output too

Reads OPENAI_API_KEY / ANTHROPIC_API_KEY the same way the app does. Costs a
fraction of a cent per model per round.
"""
from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import Config  # noqa: E402
from src.rewrite.engine import claude_request_kwargs, completion_kwargs  # noqa: E402
from src.rewrite.modes import RewriteMode  # noqa: E402
from src.rewrite.prompts import SYSTEM_PROMPT, build_user_prompt  # noqa: E402

# Spoken the way people actually dictate: fillers, self-corrections, numbers,
# and the dictionary terms that a wrong model mangles.
SAMPLES = [
    "um so i was thinking we should uh ship the vestora update tomorrow",
    "hey prisha can you send me the kfintech and cams statements by friday "
    "actually no make that thursday thanks",
    "the sebi circular says amfi registered distributors need to uh disclose "
    "commissions so we need to update wealquest before the twenty fifth",
    "okay three things first fix the login bug second deploy to vercel and "
    "third uh update the cloudflare dns records",
    "nitin here just confirming the hdfc and icici folios are linked the total "
    "is about two lakh fifty thousand rupees",
    "can you remind me to call komal at nine thirty am tomorrow about the "
    "wealducate pilot",
]
TERMS = ["Vestora", "Prisha", "KFinTech", "CAMS", "SEBI", "AMFI", "WealQuest",
         "Vercel", "Cloudflare", "Nitin", "HDFC", "ICICI", "Komal", "Wealducate"]

# USD per 1M tokens (input, output). Checked 2026-10-24 against the providers'
# pricing pages; re-check before relying on it.
PRICES = {
    "gpt-5-nano": (0.05, 0.40),       # cheapest OpenAI text model; shuts down 2026-12-11
    "gpt-5-mini": (0.25, 2.00),       # shuts down 2026-12-11
    "gpt-6-luna": (0.10, 0.50),
    "claude-haiku-5-5": (0.10, 0.50),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-5.4-nano": (0.20, 1.25),
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-5.6-luna": (0.20, 1.20),
}
# Every clean-up model at or near the bottom of the price list on the keys
# SpeakUp has (OpenAI pricing page checked 2026-10-24).
DEFAULT_MODELS = ["gpt-5-nano", "gpt-6-luna", "claude-haiku-5-5", "gpt-4o-mini",
                  "gpt-5.6-luna", "gpt-5.4-nano", "gpt-5-mini", "gpt-4.1-mini"]


def _load_installed_app_keys() -> None:
    import os

    from dotenv import load_dotenv

    appdata = os.environ.get("APPDATA")
    if appdata:
        load_dotenv(Path(appdata) / "SpeakUp" / ".env", override=False)


def _prompt(raw: str, vocab: list[str]) -> str:
    return build_user_prompt(RewriteMode.SMART, raw, None,
                             app_hint=("Notepad", "general"), vocabulary=vocab)


async def _run_openai(client, model, user, temperature):
    t0 = time.monotonic()
    first, out, usage = None, [], None
    stream = await client.chat.completions.create(
        model=model, stream=True, stream_options={"include_usage": True},
        messages=[{"role": "system", "content": SYSTEM_PROMPT},
                  {"role": "user", "content": user}],
        **completion_kwargs(model, temperature),
    )
    async for chunk in stream:
        if chunk.usage:
            usage = (chunk.usage.prompt_tokens, chunk.usage.completion_tokens)
        if chunk.choices and chunk.choices[0].delta.content:
            first = first or time.monotonic() - t0
            out.append(chunk.choices[0].delta.content)
    return first, time.monotonic() - t0, "".join(out), usage


async def _run_claude(client, model, user):
    t0 = time.monotonic()
    first, out = None, []
    async with client.messages.stream(
        model=model, system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user}],
        **claude_request_kwargs(),
    ) as stream:
        async for text in stream.text_stream:
            first = first or time.monotonic() - t0
            out.append(text)
        msg = await stream.get_final_message()
    usage = (msg.usage.input_tokens, msg.usage.output_tokens)
    return first, time.monotonic() - t0, "".join(out), usage


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default=",".join(DEFAULT_MODELS))
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args()
    # Outputs contain symbols like the rupee sign; the Windows console codepage
    # can't encode them.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    # Keys typed into the installed app's Settings live in %APPDATA%\SpeakUp\.env,
    # not the repo's .env — read both (the repo's wins).
    _load_installed_app_keys()
    config = Config()
    vocab = config.custom_vocabulary or TERMS
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    clients: dict[str, object] = {}
    for m in models:
        if m.startswith("claude-"):
            if not config.anthropic_api_key:
                print(f"skip {m}: ANTHROPIC_API_KEY not set")
                continue
            import os

            from anthropic import AsyncAnthropic
            ws = os.getenv("ANTHROPIC_WORKSPACE_ID", "").strip()
            clients[m] = AsyncAnthropic(
                api_key=config.anthropic_api_key, max_retries=0,
                default_headers={"anthropic-workspace-id": ws} if ws else None,
            )
        else:
            from openai import AsyncOpenAI
            clients[m] = AsyncOpenAI(api_key=config.openai_api_key, max_retries=0)

    async def call(m, raw):
        user = _prompt(raw, vocab)
        if m.startswith("claude-"):
            return await _run_claude(clients[m], m, user)
        return await _run_openai(clients[m], m, user, config.temperature)

    results: dict[str, list] = {m: [] for m in clients}
    errors: dict[str, str] = {}
    for m in list(clients):  # warm-up, discarded
        try:
            await call(m, SAMPLES[0])
        except Exception as e:
            errors[m] = str(e)[:160]
            del clients[m]
    for _ in range(args.rounds):
        for raw in SAMPLES:
            for m in clients:
                results[m].append((raw, *await call(m, raw)))

    print(f"\n{len(SAMPLES)} dictations x {args.rounds} rounds per model "
          f"(+1 warm-up discarded)\n")
    print(f"{'model':18} {'first word':>11} {'p90':>7} {'total':>7} "
          f"{'terms':>7} {'$/1000 dictations':>18}")
    for m, rows in results.items():
        if not rows:
            continue
        firsts = sorted(r[1] for r in rows if r[1] is not None)
        totals = [r[2] for r in rows]
        # Exact spelling and capitalisation — "Kfintech" is a miss.
        hits = sum(t in r[3] for r in rows for t in TERMS if t.lower() in r[0].lower())
        wanted = sum(t.lower() in r[0].lower() for r in rows for t in TERMS)
        price = PRICES.get(m)
        cost = "?"
        if price and all(r[4] for r in rows):
            per = statistics.mean(r[4][0] * price[0] + r[4][1] * price[1]
                                  for r in rows) / 1e6
            cost = f"${per * 1000:.3f}"
        p90 = firsts[int(0.9 * (len(firsts) - 1))]
        print(f"{m:18} {statistics.median(firsts) * 1000:9.0f}ms {p90 * 1000:5.0f}ms "
              f"{statistics.median(totals) * 1000:5.0f}ms {hits:>3}/{wanted:<3} {cost:>18}")
        if args.show:
            for raw, *_, out, _u in rows[: len(SAMPLES)]:
                print(f"    {out!r}")
    for m, err in errors.items():
        print(f"{m:18} FAILED: {err}")


if __name__ == "__main__":
    asyncio.run(main())
