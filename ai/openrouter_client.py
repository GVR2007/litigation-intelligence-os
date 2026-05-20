"""
OpenRouter LLM client — drop-in replacement for call_gemini in synthesis pipeline.

Uses OpenRouter chat completions API (OpenAI-compatible endpoint).
Default model: google/gemini-2.0-flash-001  (fast, cheap, strong JSON)
No daily quota — pay-per-use via OpenRouter.

Retry strategy:
  - 429 / 503 / 504 / 502 → transient, retried with exponential backoff
  - All retries exhausted on primary model → automatic fallback to FALLBACK_MODEL
  - Network exceptions → retried with backoff
"""

from __future__ import annotations
import os
import sys
import json
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

_BASE_URL      = "https://openrouter.ai/api/v1/chat/completions"
_DEFAULT_MODEL = "google/gemini-2.0-flash-001"
_FALLBACK_MODEL = "google/gemini-2.5-flash-preview"   # used when primary times out
_MAX_RETRIES   = 4
_RETRY_BASE    = 2   # exponential backoff: 2, 4, 8, 16 seconds

# HTTP status codes that are transient and worth retrying
_RETRYABLE = {429, 502, 503, 504, 524}


def _or_key() -> str:
    return getattr(config, "OPENROUTER_API_KEY", "") or os.getenv("OPENROUTER_API_KEY", "")


def _do_call(headers: dict, payload: dict, max_retries: int) -> tuple[bool, str]:
    """
    Internal: attempt one model with retry loop.
    Returns (success: bool, text: str).
    """
    import requests

    last_error = ""
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(_BASE_URL, headers=headers,
                                 json=payload, timeout=120)

            if resp.status_code in _RETRYABLE:
                wait = _RETRY_BASE ** attempt
                last_error = f"HTTP {resp.status_code} (attempt {attempt}/{max_retries})"
                if attempt < max_retries:
                    time.sleep(wait)
                continue

            if resp.status_code != 200:
                # Non-retryable error (4xx except 429) — fail immediately
                return False, f"[ERROR] OpenRouter HTTP {resp.status_code}: {resp.text[:300]}"

            data = resp.json()
            choices = data.get("choices", [])
            if not choices:
                return False, "[ERROR] OpenRouter returned empty choices"

            content = choices[0].get("message", {}).get("content", "")
            if content:
                return True, content
            return False, "[ERROR] OpenRouter returned empty content"

        except Exception as e:
            last_error = str(e)
            if attempt < max_retries:
                time.sleep(_RETRY_BASE ** attempt)

    return False, f"[ERROR] OpenRouter failed after {max_retries} attempts: {last_error}"


def call_openrouter(
    system_prompt: str,
    user_message:  str,
    model:         str   = _DEFAULT_MODEL,
    temperature:   float = 0.1,
    max_tokens:    int   = 2048,
    redact:        bool  = True,
) -> str:
    """
    Call OpenRouter chat completions API with automatic retry + model fallback.

    Args:
        system_prompt — role=system content
        user_message  — role=user content
        model         — OpenRouter model ID (default: google/gemini-2.0-flash-001)
        temperature   — 0.0–1.0
        max_tokens    — max output tokens
        redact        — unused (kept for compatibility with call_gemini signature)

    Returns:
        str — model output text, or "[ERROR] ..." on failure
    """
    api_key = _or_key()
    if not api_key:
        return "[ERROR] OPENROUTER_API_KEY not set"

    import requests

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
        "HTTP-Referer":  "https://litigation-os.local",
        "X-Title":       "Litigation OS",
    }

    def _payload(m: str) -> dict:
        return {
            "model":       m,
            "temperature": temperature,
            "max_tokens":  max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_message},
            ],
        }

    # ── Primary model ──────────────────────────────────────────────────────────
    ok, result = _do_call(headers, _payload(model), _MAX_RETRIES)
    if ok:
        return result

    # ── Fallback model (only if primary is not already the fallback) ───────────
    if model != _FALLBACK_MODEL:
        ok2, result2 = _do_call(headers, _payload(_FALLBACK_MODEL), 2)
        if ok2:
            return result2
        # Return the original primary error (more informative)
        return result

    return result
