"""
OpenRouter LLM client — drop-in replacement for call_gemini in synthesis pipeline.

Uses OpenRouter chat completions API (OpenAI-compatible endpoint).
Default model: google/gemini-2.0-flash-001  (fast, cheap, strong JSON)
No daily quota — pay-per-use via OpenRouter.
"""

from __future__ import annotations
import os
import sys
import json
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

_BASE_URL   = "https://openrouter.ai/api/v1/chat/completions"
_DEFAULT_MODEL = "google/gemini-2.0-flash-001"
_MAX_RETRIES   = 3
_RETRY_WAIT    = 5   # seconds on 429/503


def _or_key() -> str:
    return getattr(config, "OPENROUTER_API_KEY", "") or os.getenv("OPENROUTER_API_KEY", "")


def call_openrouter(
    system_prompt: str,
    user_message:  str,
    model:         str   = _DEFAULT_MODEL,
    temperature:   float = 0.1,
    max_tokens:    int   = 2048,
    redact:        bool  = True,
) -> str:
    """
    Call OpenRouter chat completions API.

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
    payload = {
        "model":       model,
        "temperature": temperature,
        "max_tokens":  max_tokens,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_message},
        ],
    }

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            resp = requests.post(_BASE_URL, headers=headers,
                                 json=payload, timeout=90)

            if resp.status_code == 429 or resp.status_code == 503:
                wait = _RETRY_WAIT * attempt
                time.sleep(wait)
                continue

            if resp.status_code != 200:
                return f"[ERROR] OpenRouter HTTP {resp.status_code}: {resp.text[:200]}"

            data = resp.json()
            choices = data.get("choices", [])
            if not choices:
                return "[ERROR] OpenRouter returned empty choices"

            content = choices[0].get("message", {}).get("content", "")
            return content if content else "[ERROR] OpenRouter returned empty content"

        except Exception as e:
            if attempt == _MAX_RETRIES:
                return f"[ERROR] OpenRouter exception: {e}"
            time.sleep(_RETRY_WAIT)

    return "[ERROR] OpenRouter max retries exceeded"
