"""One small LLM client. The model is a config value, never hardcoded.

Providers:
  - "openai_compatible": any /chat/completions API. Covers Gemini (free tier),
    Ollama (local), Groq, OpenRouter, OpenAI, etc. Just change base_url/model.
  - "mock": no network. Picks actions from the persona's traits, so you can
    test the whole pipeline for free. Its output says nothing about real LLMs.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request

from loader import load_dotenv
from mock_llm import MockModel

RETRY_STATUS = {429, 500, 502, 503, 504}


class LLMError(Exception):
    pass


class QuotaExhausted(LLMError):
    """Retrying won't help (e.g. a daily limit). The run should stop."""


def parse_http_error(body: str):
    """Pull (one-line message, retry delay in seconds or None, is_daily_quota) out of
    an error body. Handles Gemini's shape ([{"error": {..., "details": [...]}}]) and
    OpenAI-style {"error": {"message": ...}}; anything else falls back to raw text."""
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return " ".join(body.split())[:200], None, False
    if isinstance(data, list) and data:
        data = data[0]
    err = data.get("error", data) if isinstance(data, dict) else {}
    if not isinstance(err, dict):
        return str(err)[:200], None, False

    message = " ".join(str(err.get("message", "")).split()) or "no message"
    delay, daily = None, False
    for d in err.get("details") or []:
        if not isinstance(d, dict):
            continue
        if d.get("@type", "").endswith("RetryInfo"):
            m = re.match(r"([\d.]+)s", str(d.get("retryDelay", "")))
            if m:
                delay = float(m.group(1))
        for v in d.get("violations") or []:
            if "PerDay" in str(v.get("quotaId", "")):
                daily = True
    return message[:200], delay, daily


class LLM:
    def __init__(self, cfg: dict, mock_seed: int = 0):
        self.cfg = cfg
        self.provider = cfg["provider"]
        self.calls = 0
        self.usage = {"input_tokens": 0, "output_tokens": 0}  # as reported by the API
        self._last_call = 0.0
        self._lock = threading.Lock()  # calls may run in parallel threads
        if self.provider == "mock":
            self._mock = MockModel(mock_seed)
        elif self.provider == "openai_compatible":
            load_dotenv()
            env = cfg.get("api_key_env") or ""
            self.api_key = os.environ.get(env, "") if env else ""
            if env and not self.api_key:
                raise LLMError(f"{env} is not set: add {env}=... to .env, or run with --mock to test offline")
        else:
            raise LLMError(f"unknown provider {self.provider!r}")

    def complete(self, system: str, user: str, hint: dict | None = None) -> str:
        """hint is only read by the mock provider (it can't read prompts)."""
        with self._lock:
            self.calls += 1
        if self.provider == "mock":
            return self._mock.respond(system, user, hint)
        return self._chat(system, user)

    def _throttle(self):
        """Space call starts at least min_seconds_between_calls apart, across all threads."""
        gap = float(self.cfg.get("min_seconds_between_calls", 0))
        with self._lock:
            start = max(time.time(), self._last_call + gap)
            self._last_call = start
        if start > time.time():
            time.sleep(start - time.time())

    def _chat(self, system: str, user: str) -> str:
        body = {
            "model": self.cfg["model"],
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            # Newer OpenAI models reject "max_tokens" and want "max_completion_tokens":
            # set "token_limit_param" in the llm config. Some also reject a custom temperature:
            # set "temperature": null to leave it out.
            self.cfg.get("token_limit_param", "max_tokens"): self.cfg.get("max_tokens", 1024),
            **self.cfg.get("extra_body", {}),
        }
        if self.cfg.get("temperature", 0.8) is not None:
            body["temperature"] = self.cfg.get("temperature", 0.8)
        url = self.cfg["base_url"].rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        last_err = None
        for attempt in range(6):
            self._throttle()
            req = urllib.request.Request(url, json.dumps(body).encode(), headers)
            try:
                with urllib.request.urlopen(req, timeout=self.cfg.get("timeout_seconds", 60)) as resp:
                    data = json.loads(resp.read())
                usage = data.get("usage") or {}
                with self._lock:
                    self.usage["input_tokens"] += usage.get("prompt_tokens", 0)
                    self.usage["output_tokens"] += usage.get("completion_tokens", 0)
                return data["choices"][0]["message"].get("content") or ""
            except urllib.error.HTTPError as e:
                message, server_delay, daily = parse_http_error(e.read().decode(errors="replace"))
                last_err = f"HTTP {e.code}: {message}"
                if daily:
                    raise QuotaExhausted(f"{last_err} (daily free-tier quota used up; try tomorrow, another model, or another provider)")
                if e.code not in RETRY_STATUS:
                    raise LLMError(last_err)
                retry_after = e.headers.get("Retry-After")
                if server_delay is not None:
                    delay = server_delay + 1
                elif retry_after and retry_after.isdigit():
                    delay = float(retry_after)
                else:
                    delay = min(60, 5 * 2 ** attempt)
            except (urllib.error.URLError, TimeoutError) as e:
                last_err = f"network error: {e}"
                delay = min(60, 5 * 2 ** attempt)
            except (KeyError, IndexError, json.JSONDecodeError) as e:
                raise LLMError(f"unexpected response shape: {e}")
            print(f"   ... LLM call failed ({last_err[:120]}), retry {attempt + 1}/5 in {delay:.0f}s")
            time.sleep(delay)
        raise LLMError(f"gave up after retries: {last_err}")
