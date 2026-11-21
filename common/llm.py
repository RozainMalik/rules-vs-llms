"""
One Gemini client for the whole repo.

Why a wrapper instead of calling the SDK directly?
  1. DISK CACHE  — every response is stored in llm_cache/ (committed to git).
     Re-running the benchmarks replays the cache, so "one command reproduces
     every number" works without an API key and without burning free-tier quota.
     The cache stores the ORIGINAL latency and token counts, so replayed runs
     still report real latency and cost.
  2. RATE LIMIT  — free tier allows only a few requests/minute. A cross-process
     file lock spaces calls out; 429/503 errors are retried with backoff.
  3. ACCOUNTING  — token counts -> USD at paid-tier prices, so we can report
     "cost per 1,000 requests" even though the free tier costs $0.

Env vars:
  GEMINI_API_KEY        required for cache misses
  LLM_OFFLINE=1         never call the API; a cache miss raises CacheMiss
  LLM_MIN_INTERVAL=4.5  seconds between real calls (all processes combined)
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "llm_cache"
LOCK_FILE = CACHE_DIR / ".ratelimit.lock"

DEFAULT_MODEL = os.environ.get("LLM_MODEL", "gemini-3.5-flash-lite")

# USD per 1M tokens (input, output). Thinking tokens bill as output.
# Paid-tier list prices — the free tier is $0, these give the cost at scale.
# SOURCE: ai.google.dev/gemini-api/docs/pricing  (re-check before submitting)
PRICING = {
    "gemini-3.5-flash-lite": (0.30, 2.50),   # Standard tier, checked 2026-11-21
}


def _load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


class CacheMiss(RuntimeError):
    pass


@dataclass
class LLMResponse:
    text: str
    model: str
    input_tokens: int
    output_tokens: int          # includes thinking tokens
    latency_s: float            # latency of the ORIGINAL call
    cached: bool = False

    @property
    def cost_usd(self) -> float:
        pin, pout = PRICING.get(self.model, (0.0, 0.0))
        return (self.input_tokens * pin + self.output_tokens * pout) / 1e6


def _key(model: str, system: str, prompt: str, json_mode: bool, sample: int) -> str:
    raw = json.dumps([model, system, prompt, json_mode, sample])
    return hashlib.sha256(raw.encode()).hexdigest()


def _wait_turn(min_interval: float) -> None:
    """Cross-process rate limiter: one file holds the time of the last call."""
    CACHE_DIR.mkdir(exist_ok=True)
    with open(LOCK_FILE, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        last = float(f.read().strip() or 0)
        wait = last + min_interval - time.time()
        if wait > 0:
            time.sleep(wait)
        f.seek(0)
        f.truncate()
        f.write(str(time.time()))
        fcntl.flock(f, fcntl.LOCK_UN)


class LLM:
    def __init__(self, model: str = DEFAULT_MODEL):
        self.model = model
        self._client = None

    def _sdk(self):
        if self._client is None:
            _load_env()
            from google import genai
            self._client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        return self._client

    def generate(self, prompt: str, system: str = "", json_mode: bool = False,
                 sample: int = 0, max_retries: int = 12) -> LLMResponse:
        """`sample` lets us ask the SAME prompt N times (determinism test)
        while still caching each answer separately."""
        key = _key(self.model, system, prompt, json_mode, sample)
        path = CACHE_DIR / key[:2] / f"{key}.json"
        if path.exists():
            data = json.loads(path.read_text())
            return LLMResponse(**{**data, "cached": True})

        if os.environ.get("LLM_OFFLINE") == "1":
            raise CacheMiss(f"no cached response for {key[:12]}")

        from google.genai import types
        config = types.GenerateContentConfig(
            system_instruction=system or None,
            response_mime_type="application/json" if json_mode else None,
        )
        min_interval = float(os.environ.get("LLM_MIN_INTERVAL", "4.5"))
        delay = 10.0
        for attempt in range(max_retries):
            _wait_turn(min_interval)
            t0 = time.time()
            try:
                r = self._sdk().models.generate_content(model=self.model, contents=prompt, config=config)
                latency = time.time() - t0
                u = r.usage_metadata
                resp = LLMResponse(
                    text=r.text or "",
                    model=self.model,
                    input_tokens=u.prompt_token_count or 0,
                    output_tokens=(u.candidates_token_count or 0) + (u.thoughts_token_count or 0),
                    latency_s=round(latency, 3),
                )
                path.parent.mkdir(parents=True, exist_ok=True)
                d = asdict(resp)
                d.pop("cached")
                path.write_text(json.dumps(d))
                return resp
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                retriable = any(c in msg for c in ("429", "503", "500", "RESOURCE_EXHAUSTED", "UNAVAILABLE", "timed out"))
                if not retriable or attempt == max_retries - 1:
                    raise
                time.sleep(delay)
                delay = min(delay * 2, 120)
        raise RuntimeError("unreachable")


def parse_json(text: str):
    """Tolerant JSON parse: strips ``` fences that models sometimes add."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(t)
