"""
AI client — routes all call_claude() / stream_claude() calls to Gemini.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def call_claude(system_prompt: str, user_message: str,
                temperature: float = 0.15, max_tokens: int = 4096,
                use_cache: bool = True, redact: bool = True) -> str:
    from ai.gemini_client import call_gemini
    return call_gemini(system_prompt, user_message,
                       temperature=temperature, max_tokens=max_tokens)


def stream_claude(system_prompt: str, user_message: str,
                  temperature: float = 0.15, max_tokens: int = 4096):
    """Yields full response as single chunk (Gemini non-streaming)."""
    from ai.gemini_client import call_gemini
    yield call_gemini(system_prompt, user_message,
                      temperature=temperature, max_tokens=max_tokens)
