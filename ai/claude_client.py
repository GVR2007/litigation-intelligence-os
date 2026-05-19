"""
AI client — Gemini 2.5 Flash only.

All call_claude() / stream_claude() calls are forwarded directly to Gemini.
No Ollama, no Anthropic.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config


def call_claude(system_prompt: str, user_message: str,
                temperature: float = 0.15, max_tokens: int = 4096,
                use_cache: bool = True, redact: bool = True) -> str:
    """
    Call Gemini 2.5 Flash.
    Drop-in replacement — all phases call this function unchanged.
    """
    from ai.gemini_client import call_gemini
    return call_gemini(
        system_prompt, user_message,
        temperature=temperature,
        max_tokens=max_tokens,
        redact=redact,
    )


def stream_claude(system_prompt: str, user_message: str,
                  temperature: float = 0.15, max_tokens: int = 4096):
    """
    Stream Gemini 2.5 Flash tokens.
    Drop-in replacement — all phases that stream call this function unchanged.
    """
    from ai.gemini_client import stream_gemini
    yield from stream_gemini(
        system_prompt, user_message,
        temperature=temperature,
        max_tokens=max_tokens,
    )
