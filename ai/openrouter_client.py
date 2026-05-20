"""
OpenRouter LLM client — drop-in replacement for call_gemini in synthesis pipeline.

Uses OpenRouter chat completions API (OpenAI-compatible endpoint).
Model: openrouter/auto — OpenRouter picks the best available model automatically.
No hardcoded model names. No provider lock-in. No daily quota.

Retry strategy:
  - 429 / 502 / 503 / 504 / 524 → transient, retried with exponential backoff
  - Network exceptions → retried with backoff
"""

from __future__ import annotations
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

_BASE_URL      = "https://openrouter.ai/api/v1/chat/completions"
_DEFAULT_MODEL = "openrouter/auto"   # OpenRouter picks the best model automatically
_MAX_RETRIES   = 4
_RETRY_BASE    = 2   # exponential backoff: 2, 4, 8, 16 seconds

# HTTP status codes that are transient and worth retrying
_RETRYABLE = {429, 502, 503, 504, 524}


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
        model         — OpenRouter model ID (default: openrouter/auto)
        temperature   — 0.0–1.0
        max_tokens    — max output tokens
        redact        — unused (kept for compatibility)

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

    last_error = ""
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            resp = requests.post(_BASE_URL, headers=headers,
                                 json=payload, timeout=120)

            if resp.status_code in _RETRYABLE:
                last_error = f"HTTP {resp.status_code}"
                if attempt < _MAX_RETRIES:
                    time.sleep(_RETRY_BASE ** attempt)
                continue

            if resp.status_code != 200:
                return f"[ERROR] OpenRouter HTTP {resp.status_code}: {resp.text[:300]}"

            data     = resp.json()
            choices  = data.get("choices", [])
            if not choices:
                return "[ERROR] OpenRouter returned empty choices"

            content = choices[0].get("message", {}).get("content", "")
            return content if content else "[ERROR] OpenRouter returned empty content"

        except Exception as e:
            last_error = str(e)
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_BASE ** attempt)

    return f"[ERROR] OpenRouter failed after {_MAX_RETRIES} attempts: {last_error}"
