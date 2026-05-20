"""
AI client — OpenRouter (google/gemini-2.0-flash-001).

All call_claude() / stream_claude() calls route through OpenRouter.
No daily quota — pay-per-use.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config


def call_claude(system_prompt: str, user_message: str,
                temperature: float = 0.15, max_tokens: int = 4096,
                use_cache: bool = True, redact: bool = True) -> str:
    """Route to OpenRouter. Drop-in replacement for all phases."""
    from ai.openrouter_client import call_openrouter
    return call_openrouter(
        system_prompt, user_message,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def stream_claude(system_prompt: str, user_message: str,
                  temperature: float = 0.15, max_tokens: int = 4096):
    """Non-streaming fallback via OpenRouter (no streaming wrapper yet)."""
    from ai.openrouter_client import call_openrouter
    yield call_openrouter(
        system_prompt, user_message,
        temperature=temperature,
        max_tokens=max_tokens,
    )
