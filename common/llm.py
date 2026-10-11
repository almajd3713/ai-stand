"""A tiny client for whichever local LLM server is running on the stand.

Speaks the OpenAI-style /v1/chat/completions API, which Ollama, llama.cpp's
llama-server and LM Studio all serve, so the games don't care which one the
Mac runs. Settings come from the environment or the repo's .env file:

    LLM_URL    base URL of the server      (default http://localhost:11434, Ollama)
    LLM_MODEL  model name on that server   (default qwen3.5:9b)
"""

import os
import pathlib

import httpx

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_env(path=ROOT / ".env"):
    """Read KEY=value lines from .env into os.environ (real env vars win)."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


load_env()
LLM_URL = os.environ.get("LLM_URL", "http://localhost:11434").rstrip("/")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen3.5:9b")

_client = httpx.AsyncClient(timeout=httpx.Timeout(90, connect=5))


async def chat(messages, max_tokens=300, temperature=0.7):
    """Send a conversation, get the reply text back."""
    res = await _client.post(f"{LLM_URL}/v1/chat/completions", json={
        "model": LLM_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        # Qwen3.5 and friends "think" before answering by default, which is
        # slow and pointless here. Each server spells "don't" differently:
        "chat_template_kwargs": {"enable_thinking": False},  # llama.cpp
        "think": False,                                      # Ollama
        "reasoning_effort": "none",                          # Ollama, newer
    })
    res.raise_for_status()
    text = res.json()["choices"][0]["message"].get("content") or ""
    if "</think>" in text:  # a server that ignored all three still thinks out loud
        text = text.split("</think>", 1)[1]
    return text.strip()


async def health():
    """True when the LLM server answers. Used for the games' status lights."""
    try:
        res = await _client.get(f"{LLM_URL}/v1/models", timeout=3)
        return res.status_code == 200
    except httpx.HTTPError:
        return False
