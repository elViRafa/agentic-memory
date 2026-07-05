"""Zero-dependency HTTP client for LLM providers (Gemini, OpenAI, Anthropic)."""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from typing import Any


class LLMError(Exception):
    """Raised when an LLM API call fails."""


# Module-level cache: maps (resolved_cwd, mtime_fingerprint) → True.
# Avoids re-reading .env files on every MCP tool call within the same process.
_env_load_cache: dict[tuple[str, float], bool] = {}


def load_env_from_cwd(cwd: str | Any) -> None:
    """Load environment variables from .env files in the workspace directory.

    Checks `.env`, `.env.local`, and `.env.development` (in that order).
    Does not overwrite existing non-empty environment variables.

    Results are cached by (resolved_cwd, max_mtime) so repeated calls during
    the same MCP session do not re-read from disk unless a .env file changes.
    """
    if not cwd:
        return
    from pathlib import Path

    try:
        cwd_path = Path(cwd).resolve()
        env_names = (".env", ".env.local", ".env.development")

        # Build a cheap cache key from the max mtime of all env files present.
        mtime_sum: float = 0.0
        for env_name in env_names:
            dotenv_path = cwd_path / env_name
            if dotenv_path.is_file():
                mtime_sum += dotenv_path.stat().st_mtime

        cache_key = (str(cwd_path), mtime_sum)
        if cache_key in _env_load_cache:
            return  # Already loaded for this cwd + file state
        _env_load_cache[cache_key] = True

        for env_name in env_names:
            dotenv_path = cwd_path / env_name
            if dotenv_path.is_file():
                with open(dotenv_path, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            key, val = line.split("=", 1)
                            key = key.strip()
                            val = val.strip()

                            # Strip quotes if present
                            if (
                                len(val) >= 2
                                and val.startswith(('"', "'"))
                                and val.endswith(val[0])
                            ):
                                val = val[1:-1]

                            if key and not os.environ.get(key):
                                os.environ[key] = val
    except Exception:
        # Graceful fallback: do not crash if file access/parsing fails
        pass


async def call_llm(prompt: str, system_instruction: str = "", context: Any = None) -> str:
    """Execute a text completion request to the configured LLM provider or via MCP Sampling."""
    import asyncio

    # 1. Prefer configured LLM
    provider = (os.environ.get("MEMORY_FABRIC_LLM_PROVIDER") or "").strip().lower()
    if provider:
        if provider == "gemini":
            return await asyncio.to_thread(_call_gemini, prompt, system_instruction)
        elif provider == "openai":
            return await asyncio.to_thread(_call_openai, prompt, system_instruction)
        elif provider == "anthropic":
            return await asyncio.to_thread(_call_anthropic, prompt, system_instruction)
        elif provider == "ollama":
            return await asyncio.to_thread(_call_ollama, prompt, system_instruction)
        else:
            raise LLMError(f"Unsupported LLM provider: {provider}")

    # 2. Fallback to MCP Sampling if context is available
    if context is not None:
        try:
            client_params = getattr(context.session, "client_params", None)
            if (
                client_params is not None
                and getattr(client_params, "capabilities", None) is not None
                and getattr(client_params.capabilities, "sampling", None) is not None
            ):
                from mcp.types import SamplingMessage, TextContent

                messages = [
                    SamplingMessage(role="user", content=TextContent(type="text", text=prompt))
                ]

                # Output preemptive warning to stderr in case of blocking clients
                import sys

                sys.stderr.write(
                    "\n[Memory Fabric] Warning: Fallback to MCP Sampling requested. In sequential client loops "
                    "(like IDE extensions), this may deadlock. If it hangs, please configure a direct LLM provider "
                    "or use the split-tool protocol (prepare_dream_payload_tool / apply_dream_results_tool).\n"
                )
                sys.stderr.flush()

                # Wrap sampling call in a timeout to prevent indefinite hangs
                result = await asyncio.wait_for(
                    context.session.create_message(
                        messages=messages,
                        max_tokens=4000,
                        system_prompt=system_instruction,
                    ),
                    timeout=45.0,
                )
                if hasattr(result, "content"):
                    content = result.content
                    if hasattr(content, "text"):
                        return content.text
                    elif isinstance(content, list):
                        for item in content:
                            if hasattr(item, "text"):
                                return item.text
                raise LLMError(f"Unexpected sampling response format: {result}")
        except asyncio.TimeoutError as exc:
            raise LLMError(
                "MCP Sampling request timed out after 45 seconds. This deadlock is usually caused by "
                "the client/IDE sequential JSON-RPC loop blocking incoming sampling requests while waiting "
                "for the tool execution to complete. To avoid this deadlock, configure a direct LLM "
                "provider (e.g., GEMINI_API_KEY, OPENAI_API_KEY) in a local `.env` file in your project workspace "
                "or in the MCP server configuration."
            ) from exc
        except Exception as exc:
            raise LLMError(f"MCP Sampling failed: {exc}") from exc

    raise LLMError("MEMORY_FABRIC_LLM_PROVIDER is not configured and MCP Sampling is unavailable.")


def _call_gemini(prompt: str, system_instruction: str) -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise LLMError("GEMINI_API_KEY is not set.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    payload: dict[str, Any] = {"contents": [{"parts": [{"text": prompt}]}]}
    if system_instruction:
        payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

    headers = {"Content-Type": "application/json"}
    response_data = _http_post(url, payload, headers)

    try:
        return response_data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"Gemini response parsing failed: {exc}. Response: {response_data}")


def _call_openai(prompt: str, system_instruction: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    base_url = (
        os.environ.get("OPENAI_API_BASE")
        or os.environ.get("OPENAI_BASE_URL")
        or "https://api.openai.com/v1"
    )

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

    payload = {"model": model, "messages": messages}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
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
        "messages": [{"role": "user", "content": prompt}],
    }
    if system_instruction:
        payload["system"] = system_instruction

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
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
        "options": {"num_predict": 8192, "num_ctx": 8192, "temperature": 0.1},
    }
    headers = {"Content-Type": "application/json"}
    response_data = _http_post(url, payload, headers)

    try:
        return response_data["message"]["content"]
    except (KeyError, TypeError) as exc:
        raise LLMError(f"Ollama response parsing failed: {exc}. Response: {response_data}")


def _log_debug(message: str) -> None:
    debug_val = (os.environ.get("MEMORY_FABRIC_LLM_DEBUG") or "").strip()
    if not debug_val:
        return

    import sys
    from pathlib import Path

    write_to_stderr = False
    log_file_path: Path | None = None

    if debug_val.lower() in ("1", "true"):
        write_to_stderr = True
        if Path(".ai-memory").is_dir():
            log_file_path = Path(".ai-memory") / "llm_debug.log"
        else:
            log_file_path = Path("llm_debug.log")
    elif debug_val.lower() == "stderr":
        write_to_stderr = True
    else:
        log_file_path = Path(debug_val)

    if write_to_stderr:
        sys.stderr.write(message + "\n")
        sys.stderr.flush()

    if log_file_path:
        try:
            log_file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_file_path, "a", encoding="utf-8") as f:
                f.write(message + "\n")
        except Exception as exc:
            sys.stderr.write(f"Failed to write to LLM debug log file: {exc}\n")
            sys.stderr.flush()


def _sanitize_headers(headers: dict[str, str]) -> dict[str, str]:
    sanitized = {}
    for k, v in headers.items():
        k_lower = k.lower()
        if "auth" in k_lower or "key" in k_lower or "api" in k_lower or "token" in k_lower:
            sanitized[k] = "[REDACTED]"
        else:
            sanitized[k] = v
    return sanitized


def _http_post(url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    import time
    import random

    # Log the request
    sanitized_headers = _sanitize_headers(headers)
    _log_debug(
        f"--- LLM REQUEST ---\n"
        f"URL: {url}\n"
        f"Headers: {json.dumps(sanitized_headers)}\n"
        f"Payload:\n{json.dumps(payload, indent=2, ensure_ascii=False)}\n"
        f"-------------------"
    )

    headers_copy = dict(headers)
    headers_copy.setdefault(
        "User-Agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    )
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers_copy, method="POST")

    max_retries = 5
    backoff_factor = 2.0
    initial_delay = 1.0  # seconds

    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                resp_bytes = resp.read()
                resp_str = resp_bytes.decode("utf-8")
                response_data = json.loads(resp_str)
                # Log the response
                _log_debug(
                    f"--- LLM RESPONSE ---\n"
                    f"URL: {url}\n"
                    f"Response:\n{json.dumps(response_data, indent=2, ensure_ascii=False)}\n"
                    f"--------------------"
                )
                return response_data
        except urllib.error.HTTPError as exc:
            try:
                err_body = exc.read().decode("utf-8")
            except Exception:
                err_body = ""

            # Log the HTTP error
            _log_debug(
                f"--- LLM HTTP ERROR ---\n"
                f"URL: {url}\n"
                f"Code: {exc.code}\n"
                f"Reason: {exc.reason}\n"
                f"Detail: {err_body}\n"
                f"----------------------"
            )

            # Retry on rate limit (429) or transient server errors (500, 502, 503, 504)
            if exc.code in {429, 500, 502, 503, 504} and attempt < max_retries - 1:
                delay = initial_delay * (backoff_factor**attempt) + random.uniform(0, 1.0)
                time.sleep(delay)
                continue

            raise LLMError(f"HTTP Error {exc.code}: {exc.reason}. Detail: {err_body}") from exc
        except Exception as exc:
            # Log network or parsing errors
            _log_debug(f"--- LLM ERROR ---\nURL: {url}\nError: {exc}\n-----------------")
            raise LLMError(f"Network request failed: {exc}") from exc

    raise LLMError(f"Failed to get a response from {url} after {max_retries} attempts.")
