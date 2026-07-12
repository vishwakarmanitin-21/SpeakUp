"""DNS resilience: fall back to public DNS when the system resolver fails.

Some routers/ISPs intermittently refuse to resolve certain hosts (we've seen
`api.deepgram.com` fail while `api.openai.com` resolves). That silently kills
live transcription. This installs a wrapper around `socket.getaddrinfo` that,
on a resolution failure, resolves the host via Cloudflare DNS-over-HTTPS
(1.1.1.1 — an IP, so it needs no DNS itself) and retries with the resulting IP.

Because only the *address* is overridden (the connection still uses the original
hostname for TLS SNI / cert validation), certificates keep validating normally.
It only ever engages when the system resolver has already failed, so normal
resolution is untouched.
"""
from __future__ import annotations

import logging
import socket

logger = logging.getLogger("speakup")

_orig_getaddrinfo = socket.getaddrinfo
_ip_cache: dict[str, str] = {}


def _doh_resolve(host: str) -> str | None:
    """Resolve a hostname's A record via Cloudflare DoH (no system DNS needed)."""
    try:
        import httpx

        resp = httpx.get(
            "https://1.1.1.1/dns-query",
            params={"name": host, "type": "A"},
            headers={"accept": "application/dns-json"},
            timeout=5.0,
        )
        for ans in resp.json().get("Answer", []):
            if ans.get("type") == 1 and ans.get("data"):  # 1 == A record
                return ans["data"]
    except Exception as e:
        logger.debug("DoH resolve failed for %s: %s", host, e)
    return None


def _resilient_getaddrinfo(host, *args, **kwargs):
    try:
        return _orig_getaddrinfo(host, *args, **kwargs)
    except socket.gaierror:
        if not isinstance(host, str):
            raise
        ip = _ip_cache.get(host) or _doh_resolve(host)
        if ip:
            _ip_cache[host] = ip
            logger.info("DNS fallback: resolved %s -> %s via public DNS", host, ip)
            return _orig_getaddrinfo(ip, *args, **kwargs)
        raise


def install() -> None:
    """Install the resilient resolver once (idempotent)."""
    if getattr(socket, "_speakup_dns_patched", False):
        return
    socket.getaddrinfo = _resilient_getaddrinfo
    socket._speakup_dns_patched = True  # type: ignore[attr-defined]
    logger.debug("DNS resilience installed")
