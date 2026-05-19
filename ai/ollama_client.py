"""Ollama local inference client — primary AI using mistral:7b (or any local model)."""
import json
import requests
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

CHAT_ENDPOINT   = "/api/chat"
HEALTH_ENDPOINT = "/api/tags"


def _base() -> str:
    return config.OLLAMA_BASE_URL.rstrip("/")


def _model() -> str:
    """Return the best available model: primary → fallback → first available."""
    primary  = config.OLLAMA_MODEL
    fallback = getattr(config, "OLLAMA_FALLBACK_MODEL", "mistral:7b")

    if not is_running():
        return primary   # will fail gracefully in call_ollama

    available = list_models()
    if not available:
        return primary

    # Check primary
    if any(m == primary or m.startswith(primary.split(":")[0]) for m in available):
        return primary

    # Check fallback
    if any(m == fallback or m.startswith(fallback.split(":")[0]) for m in available):
        return fallback

    # Use whatever is available
    return available[0]


def is_running() -> bool:
    """Check whether Ollama daemon is reachable."""
    try:
        r = requests.get(f"{_base()}{HEALTH_ENDPOINT}", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def list_models() -> list[str]:
    """Return names of models pulled in Ollama."""
    try:
        r = requests.get(f"{_base()}{HEALTH_ENDPOINT}", timeout=5)
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return []


def model_available(model: str | None = None) -> bool:
    model = model or _model()
    # Strip tag for prefix matching (e.g. "mistral:7b" matches "mistral:7b")
    return any(m == model or m.startswith(model.split(":")[0]) for m in list_models())


def call_ollama(system_prompt: str, user_message: str,
                temperature: float = 0.15, max_tokens: int = 2048) -> str:
    """
    Send a chat completion request to the local Ollama server.
    Returns the assistant's reply as a string.

    mistral:7b defaults:
      temperature=0.15  — low = less hallucination, more factual
      max_tokens=2048   — mistral:7b context window is 4k; keep headroom
    """
    if not is_running():
        m = config.OLLAMA_MODEL
        return (
            f"[ERROR] Ollama is not running.\n\n"
            f"**Fix:** Open a new terminal window and run:\n"
            f"```\nollama serve\n```\n"
            f"Then pull the model if not already downloaded:\n"
            f"```\nollama pull {m}\n```\n\n"
            f"Or go to **⚙️ Settings** and paste your Anthropic API key to use Claude instead."
        )

    model = _model()
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_message},
        ],
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
            "top_p": 0.9,           # nucleus sampling — reduces low-prob hallucinations
            "repeat_penalty": 1.1,  # penalise repetition
            "num_ctx": 4096,        # mistral:7b context window
        },
    }

    try:
        resp = requests.post(
            f"{_base()}{CHAT_ENDPOINT}",
            json=payload,
            timeout=120,          # local models can be slow on CPU
        )
        resp.raise_for_status()
        data = resp.json()
        return data["message"]["content"]
    except requests.exceptions.ConnectionError:
        return "[ERROR] Cannot connect to Ollama. Is 'ollama serve' running?"
    except requests.exceptions.Timeout:
        return "[ERROR] Ollama timed out. Model may be loading — try again in a moment."
    except Exception as e:
        return f"[ERROR] Ollama: {str(e)}"


def stream_ollama(system_prompt: str, user_message: str,
                  temperature: float = 0.3, max_tokens: int = 4096):
    """
    Stream tokens from Ollama. Yields str chunks.
    Falls back to non-streaming if streaming fails.
    """
    if not is_running():
        m = config.OLLAMA_MODEL
        yield (
            f"[ERROR] Ollama is not running. "
            f"Open a terminal and run: `ollama serve`  then: `ollama pull {m}`"
        )
        return

    model = _model()
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_message},
        ],
        "stream": True,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }

    try:
        with requests.post(
            f"{_base()}{CHAT_ENDPOINT}",
            json=payload,
            stream=True,
            timeout=180,
        ) as resp:
            resp.raise_for_status()
            for raw_line in resp.iter_lines():
                if not raw_line:
                    continue
                try:
                    chunk = json.loads(raw_line)
                    token = chunk.get("message", {}).get("content", "")
                    if token:
                        yield token
                    if chunk.get("done"):
                        break
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        yield f"[ERROR] Ollama stream: {str(e)}"


def test_connection() -> tuple[bool, str]:
    """Quick smoke-test. Returns (ok, message)."""
    if not is_running():
        return False, "Ollama daemon not reachable at " + _base()

    models = list_models()
    if not models:
        return False, "Ollama running but no models pulled. Run: ollama pull mistral:7b"

    target = _model()
    if not model_available(target):
        available = ", ".join(models[:5])
        return False, (
            f"Model '{target}' not found. Available: {available}. "
            f"Run: ollama pull {target}"
        )

    # Quick generation test
    result = call_ollama("You are a helpful assistant.", "Reply with exactly: OK", max_tokens=10)
    if result.startswith("[ERROR]"):
        return False, result
    return True, f"Ollama OK — model '{target}' responding"
