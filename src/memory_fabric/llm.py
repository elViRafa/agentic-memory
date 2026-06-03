"""Zero-dependency HTTP client for LLM providers (Gemini, OpenAI, Anthropic)."""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from typing import Any


class LLMError(Exception):
    """Raised when an LLM API call fails."""


def call_llm(prompt: str, system_instruction: str = "") -> str:
    """Execute a text completion request to the configured LLM provider."""
    provider = (os.environ.get("MEMORY_FABRIC_LLM_PROVIDER") or "").strip().lower()
    if not provider:
        raise LLMError("MEMORY_FABRIC_LLM_PROVIDER is not configured.")

    if provider == "gemini":
        return _call_gemini(prompt, system_instruction)
    elif provider == "openai":
        return _call_openai(prompt, system_instruction)
    elif provider == "anthropic":
        return _call_anthropic(prompt, system_instruction)
    elif provider == "ollama":
        return _call_ollama(prompt, system_instruction)
    else:
        raise LLMError(f"Unsupported LLM provider: {provider}")



def _call_gemini(prompt: str, system_instruction: str) -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise LLMError("GEMINI_API_KEY is not set.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    payload: dict[str, Any] = {
        "contents": [
            {
                "parts": [{"text": prompt}]
            }
        ]
    }
    if system_instruction:
        payload["systemInstruction"] = {
            "parts": [{"text": system_instruction}]
        }

    headers = {"Content-Type": "application/json"}
    response_data = _http_post(url, payload, headers)

    try:
        return response_data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"Gemini response parsing failed: {exc}. Response: {response_data}")


def _call_openai(prompt: str, system_instruction: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("OPENAI_API_BASE") or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1"
    
    if not api_key:
        if "api.openai.com" not in base_url:
            api_key = "dummy"
        else:
            raise LLMError("OPENAI_API_KEY is not set.")

    url = f"{base_url.rstrip('/')}/chat/completions"
    model = os.environ.get("OPENAI_MODEL") or "gpt-4o-mini"

    messages = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model,
        "messages": messages
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    response_data = _http_post(url, payload, headers)

    try:
        return response_data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"OpenAI response parsing failed: {exc}. Response: {response_data}")


def _call_anthropic(prompt: str, system_instruction: str) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise LLMError("ANTHROPIC_API_KEY is not set.")

    url = "https://api.anthropic.com/v1/messages"
    payload: dict[str, Any] = {
        "model": "claude-3-5-haiku-20241022",
        "max_tokens": 4096,
        "messages": [
            {"role": "user", "content": prompt}
        ]
    }
    if system_instruction:
        payload["system"] = system_instruction

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json"
    }
    response_data = _http_post(url, payload, headers)

    try:
        return response_data["content"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"Anthropic response parsing failed: {exc}. Response: {response_data}")


def _call_ollama(prompt: str, system_instruction: str) -> str:
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    model = os.environ.get("OLLAMA_MODEL", "gemma2")
    url = f"{host}/api/chat"
    
    messages = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})
    messages.append({"role": "user", "content": prompt})
    
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {
            "num_predict": 8192,
            "num_ctx": 8192,
            "temperature": 0.1
        }
    }
    headers = {"Content-Type": "application/json"}
    response_data = _http_post(url, payload, headers)
    
    try:
        return response_data["message"]["content"]
    except (KeyError, TypeError) as exc:
        raise LLMError(f"Ollama response parsing failed: {exc}. Response: {response_data}")


def _http_post(url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    import time
    import random

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    
    max_retries = 5
    backoff_factor = 2.0
    initial_delay = 1.0  # seconds
    
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # Retry on rate limit (429) or transient server errors (500, 502, 503, 504)
            if exc.code in {429, 500, 502, 503, 504} and attempt < max_retries - 1:
                delay = initial_delay * (backoff_factor ** attempt) + random.uniform(0, 1.0)
                time.sleep(delay)
                continue
            
            try:
                err_body = exc.read().decode("utf-8")
            except Exception:
                err_body = ""
            raise LLMError(f"HTTP Error {exc.code}: {exc.reason}. Detail: {err_body}") from exc
        except Exception as exc:
            raise LLMError(f"Network request failed: {exc}") from exc

