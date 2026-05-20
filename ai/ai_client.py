"""
Central AI client — single entry point for all LLM calls.

Tiers:
  FAST    → openrouter/auto   OpenRouter picks best available model automatically
  QUALITY → openrouter/auto   same — OpenRouter handles provider routing

Only one API key needed: OPENROUTER_API_KEY.
OpenRouter handles model selection, provider failover, and load balancing.

Switching model = change FAST/QUALITY constants here. No other file changes.
All synthesis code should call AIClient.call() / AIClient.call_json().
"""

from __future__ import annotations
import json
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class AIClient:

    FAST    = "openrouter/auto"
    QUALITY = "openrouter/auto"

    # ── Public API ─────────────────────────────────────────────────────────────

    @classmethod
    def call(
        cls,
        system:      str,
        user:        str,
        tier:        str   = FAST,
        temperature: float = 0.1,
        max_tokens:  int   = 2048,
    ) -> str:
        """
        Make a single LLM call. Returns raw string response.
        On error returns "[ERROR] ..." string — callers must check.
        """
        from ai.gemini_client import call_gemini
        return call_gemini(
            system_prompt = system,
            user_message  = user,
            temperature   = temperature,
            max_tokens    = max_tokens,
        )

    @classmethod
    def call_json(
        cls,
        system:      str,
        user:        str,
        tier:        str   = FAST,
        temperature: float = 0.0,
        max_tokens:  int   = 1024,
    ) -> dict | list | None:
        """
        LLM call that expects JSON back. Parses and returns Python object.
        Returns None if response is not valid JSON.
        """
        raw = cls.call(system, user, tier=tier,
                       temperature=temperature, max_tokens=max_tokens)
        return cls.parse_json(raw)

    @staticmethod
    def parse_json(raw: str) -> dict | list | None:
        """
        Parse JSON from LLM output. Handles markdown code fences.
        Returns None on failure.
        """
        try:
            clean = raw.strip()
            if "```" in clean:
                clean = re.sub(r"```(?:json)?", "", clean).strip().rstrip("`").strip()
            # Try array first, then object
            for start_ch, end_ch in [("[", "]"), ("{", "}")]:
                start = clean.find(start_ch)
                end   = clean.rfind(end_ch) + 1
                if start >= 0 and end > start:
                    return json.loads(clean[start:end])
        except Exception:
            pass
        return None

    @classmethod
    def is_error(cls, response: str) -> bool:
        return not response or response.startswith("[ERROR]")
