"""
Google Gemini 2.5 Flash — middle-tier AI engine.

Priority in the AI stack:
  1. Ollama mistral:7b  (local, free, private — primary)
  2. Gemini 2.5 Flash   (cloud, fast, cheap — this file)
  3. Claude API         (cloud, best reasoning — complex tasks only)

Gemini 2.5 Flash is a thinking model:
  • Uses internal thought tokens (not billed or visible)
  • Needs maxOutputTokens ≥ 500 to allow reasoning to complete
  • Temperature 0.15 for legal analysis (low hallucination)

Usage:
    from ai.gemini_client import call_gemini, stream_gemini, is_available
"""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

GEMINI_BASE  = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_MODEL = "gemini-2.5-flash"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _key() -> str:
    """Return the Gemini API key from config or env."""
    return (
        getattr(config, "GEMINI_API_KEY", "")
        or os.getenv("GEMINI_API_KEY", "")
    )


def _model() -> str:
    return getattr(config, "GEMINI_MODEL", GEMINI_MODEL)


def is_available() -> bool:
    """Return True if a Gemini API key is configured."""
    return bool(_key())


# ─────────────────────────────────────────────────────────────────────────────
# Non-streaming call
# ─────────────────────────────────────────────────────────────────────────────

def call_gemini(system_prompt: str,
                user_message: str,
                temperature: float = 0.15,
                max_tokens: int = 4096,
                redact: bool = True) -> str:
    """
    Call Gemini 2.5 Flash and return the text response.

    Args:
        system_prompt — system instructions (legal expertise context)
        user_message  — the user query (with RAG context already injected)
        temperature   — 0.15 for legal analysis (low hallucination)
        max_tokens    — output token limit (default 4096; thinking tokens are extra)
        redact        — strip PII before sending (default True)

    Returns:
        str: response text, or "[ERROR] ..." on failure
    """
    import requests as _req

    key = _key()
    if not key:
        return "[ERROR] Gemini API key not set. Go to ⚙️ Settings → paste your Gemini key."

    # ── PII redaction before cloud call ──────────────────────────────────────
    clean_message = user_message
    if redact:
        try:
            from utils.pii_redactor import redact_query
            clean_message, _ = redact_query(user_message)
        except Exception:
            pass

    # Try primary model first, fall back to gemini-2.0-flash on overload
    _FALLBACK_MODEL = "gemini-2.0-flash"
    models_to_try   = [_model(), _FALLBACK_MODEL]
    if models_to_try[0] == models_to_try[1]:
        models_to_try = [_model()]

    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents":           [{"role": "user", "parts": [{"text": clean_message}]}],
        "generationConfig": {
            "temperature":     temperature,
            "maxOutputTokens": max_tokens,
            "topP":            0.95,
        },
    }

    import time
    last_err = ""
    for model_id in models_to_try:
        url = f"{GEMINI_BASE}/{model_id}:generateContent?key={key}"
        for attempt in range(1, 4):          # up to 3 retries per model
            try:
                resp = _req.post(url, json=payload, timeout=180)
                if resp.status_code == 503 or (
                    resp.status_code == 429 and
                    "high demand" in resp.text.lower()
                ):
                    # Temporary overload — wait and retry
                    wait = 8 * attempt
                    time.sleep(wait)
                    last_err = f"overloaded (model={model_id})"
                    continue
                if resp.status_code == 429:
                    # Hard quota — no point retrying same model
                    last_err = "quota exceeded"
                    break
                resp.raise_for_status()
                data = resp.json()
                return _extract_text(data)
            except _req.exceptions.Timeout:
                last_err = "timeout"
                time.sleep(5)
            except _req.exceptions.HTTPError as e:
                try:
                    last_err = resp.json().get("error", {}).get("message", str(e))
                except Exception:
                    last_err = str(e)
                break                        # non-retryable HTTP error
            except Exception as e:
                last_err = str(e)
                break

    return (
        f"[ERROR] Gemini unavailable after retries: {last_err}. "
        "Please wait a minute and try again, or top up Google AI Studio credits."
    )


def _extract_text(data: dict) -> str:
    """
    Extract text from Gemini API response.
    Handles:
      - Normal responses: candidates[0].content.parts[0].text
      - Thinking model responses: may have thought parts + text parts
      - Empty parts (cut off by token limit)
    """
    try:
        candidates = data.get("candidates", [])
        if not candidates:
            err = data.get("error", {}).get("message", "No candidates returned")
            return f"[ERROR] Gemini: {err}"

        candidate = candidates[0]
        finish    = candidate.get("finishReason", "")

        content = candidate.get("content", {})
        parts   = content.get("parts", [])

        # Filter to only text parts (skip thought parts which have no "text" key sometimes)
        text_parts = [p.get("text", "") for p in parts if "text" in p]
        text = " ".join(text_parts).strip()

        if not text:
            if finish == "MAX_TOKENS":
                return "[ERROR] Gemini response was cut off. Increase max_tokens or shorten the prompt."
            if finish == "SAFETY":
                return "[ERROR] Gemini blocked this response due to safety filters."
            return f"[ERROR] Gemini returned empty response (finish: {finish})"

        return text

    except Exception as e:
        return f"[ERROR] Parsing Gemini response: {str(e)}"


# ─────────────────────────────────────────────────────────────────────────────
# Streaming call (for phases 7, 9, 10, 3 — long-form live output)
# ─────────────────────────────────────────────────────────────────────────────

def stream_gemini(system_prompt: str,
                  user_message: str,
                  temperature: float = 0.15,
                  max_tokens: int = 4096):
    """
    Stream Gemini 2.5 Flash tokens. Yields str chunks.

    Uses Server-Sent Events via :streamGenerateContent endpoint.
    Falls back to non-streaming if stream fails.
    """
    import requests as _req

    key = _key()
    if not key:
        yield "[ERROR] Gemini API key not set. Go to ⚙️ Settings."
        return

    # PII redaction
    clean_message = user_message
    try:
        from utils.pii_redactor import redact_query
        clean_message, _ = redact_query(user_message)
    except Exception:
        pass

    url = f"{GEMINI_BASE}/{_model()}:streamGenerateContent?key={key}&alt=sse"

    payload = {
        "system_instruction": {
            "parts": [{"text": system_prompt}]
        },
        "contents": [
            {"role": "user", "parts": [{"text": clean_message}]}
        ],
        "generationConfig": {
            "temperature":     temperature,
            "maxOutputTokens": max_tokens,
            "topP":            0.95,
        },
    }

    try:
        with _req.post(url, json=payload, stream=True, timeout=180) as resp:
            resp.raise_for_status()

            for raw_line in resp.iter_lines(decode_unicode=True):
                if not raw_line or not raw_line.startswith("data: "):
                    continue

                json_str = raw_line[6:].strip()  # strip "data: " prefix
                if json_str == "[DONE]":
                    break

                try:
                    chunk = json.loads(json_str)
                    candidates = chunk.get("candidates", [])
                    if not candidates:
                        continue
                    parts = candidates[0].get("content", {}).get("parts", [])
                    for part in parts:
                        text = part.get("text", "")
                        if text:
                            yield text
                except json.JSONDecodeError:
                    continue

    except _req.exceptions.Timeout:
        yield "\n\n[ERROR] Gemini stream timed out."
    except _req.exceptions.HTTPError as e:
        try:
            err_msg = resp.json().get("error", {}).get("message", str(e))
        except Exception:
            err_msg = str(e)
        # Fallback to non-streaming
        yield call_gemini(system_prompt, user_message, temperature, max_tokens)
    except Exception as e:
        yield f"\n\n[ERROR] Gemini stream: {str(e)}"


# ─────────────────────────────────────────────────────────────────────────────
# Connection test
# ─────────────────────────────────────────────────────────────────────────────

def test_connection() -> tuple[bool, str]:
    """
    Quick smoke-test. Returns (ok, message).
    Used by Settings page "Test Gemini" button.
    """
    if not _key():
        return False, "Gemini API key not configured."

    result = call_gemini(
        "You are a helpful assistant.",
        "Reply with exactly the word: READY",
        max_tokens=50,
        redact=False,
    )

    if result.startswith("[ERROR]"):
        return False, result

    return True, f"Gemini 2.5 Flash OK — model responding ✓  (response: '{result.strip()[:30]}')"


# ─────────────────────────────────────────────────────────────────────────────
# Model info
# ─────────────────────────────────────────────────────────────────────────────

def get_model_info() -> dict:
    """Return info about the Gemini model being used."""
    return {
        "model":       _model(),
        "provider":    "Google DeepMind",
        "type":        "Thinking model (internal chain-of-thought)",
        "context":     "1M tokens input",
        "temperature": 0.15,
        "cost":        "~₹0.05–₹0.20 per 1000 tokens (standard tier)",
        "strengths":   ["Long context", "Fast", "Cheap", "Thinking model", "Good legal reasoning"],
    }
