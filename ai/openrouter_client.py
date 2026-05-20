"""
OpenRouter LLM client — free-tier models, no credits required.

Free model chain (tried in order until one succeeds):
  1. nvidia/nemotron-3-super-120b-a12b:free  — 120B, best quality
  2. google/gemma-4-31b-it:free             — 31B, fast fallback
  3. meta-llama/llama-3.3-70b-instruct:free — 70B, reliable fallback

Retry strategy:
  - 429 provider overload → try next model in chain
  - 502 / 503 / 504 / 524 → retry same model with backoff
"""

from __future__ import annotations
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"

# Free models tried in order — all work with a free-tier key
# openrouter/free = OpenRouter picks best available free model automatically
_FREE_MODELS = [
    "openrouter/free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "google/gemma-4-31b-it:free",
    "meta-llama/llama-3.3-70b-instruct:free",
]

_DEFAULT_MODEL = _FREE_MODELS[0]
_MAX_RETRIES   = 3
_RETRYABLE     = {502, 503, 504, 524}


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
    Call OpenRouter using free models. Walks _FREE_MODELS chain on 429.

    Returns str response, or "[ERROR] ..." on failure.
    """
    api_key = _or_key()
    if not api_key:
        return "[ERROR] OPENROUTER_API_KEY not set in config"

    import requests

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
        "HTTP-Referer":  "https://litigation-os.local",
        "X-Title":       "Litigation OS",
    }

    # Build model list: requested model first, then rest of free chain
    model_chain = [model] + [m for m in _FREE_MODELS if m != model]

    last_error = ""
    for current_model in model_chain:
        payload = {
            "model":       current_model,
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
                                     json=payload, timeout=180)

                if resp.status_code == 429:
                    # Provider overloaded — try next model
                    last_error = f"{current_model} rate-limited (429)"
                    break

                if resp.status_code in _RETRYABLE:
                    last_error = f"HTTP {resp.status_code}"
                    if attempt < _MAX_RETRIES:
                        time.sleep(5 * attempt)
                    continue

                if resp.status_code != 200:
                    last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    break

                data    = resp.json()
                choices = data.get("choices", [])
                if not choices:
                    last_error = "empty choices"
                    break

                content = choices[0].get("message", {}).get("content", "")
                if content:
                    return content
                last_error = "empty content"
                break

            except Exception as e:
                last_error = str(e)
                if attempt < _MAX_RETRIES:
                    time.sleep(5)

    return f"[ERROR] All models unavailable: {last_error}"
