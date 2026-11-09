"""Optional LLM second pass over the shortlist.

Design constraints, straight from the brief:

* the model must be easy to swap -- so the only coupling is "OpenAI-compatible
  JSON chat" or "Anthropic messages", both plain ``urllib``;
* it must be cheap enough to run at volume -- so the model only ever sees the
  handful of clips the rules already liked, never the full pack;
* it must be safe to run offline -- so every verdict is cached to disk and a
  missing key or network failure degrades to the heuristic score instead of
  crashing.

A strong model is better than the lexicons at exactly one judgement: whether a
clip makes sense to someone who has never seen the show. It is *not* trusted on
timestamps -- those come from the parser.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .candidates import Candidate
from .prompting import render_clip

SYSTEM_PROMPT = (
    "You are a short-form promo editor for vertical microdramas. You cut 20-60 "
    "second clips for Instagram, TikTok and YouTube Shorts. You are ruthless: "
    "most clips are not postable."
)

USER_TEMPLATE = """Judge this candidate promo clip.

Rules a good promo must satisfy:
1. HOOK: something in the first 3 seconds that makes a scrolling viewer stop \
(a slap, a reveal, a shocking line).
2. CLIFFHANGER: it cuts at an unresolved moment, so the viewer needs to know \
what happens next.
3. STANDS ALONE: someone who has never seen the show understands what is \
happening. Judge this as a first-time viewer, not someone who knows the series.

CLIP
{clip}

Return ONLY minified JSON, no prose, with exactly these keys:
{{"hook":1-5,"cliffhanger":1-5,"standalone":1-5,"spoiler_risk":1-5,\
"postable":true|false,"reason":"one sentence","fix":"one sentence on the single \
biggest improvement"}}
"""


@dataclass
class Verdict:
    hook: float
    cliffhanger: float
    standalone: float
    spoiler_risk: float
    postable: bool
    reason: str
    fix: str
    model: str
    cached: bool = False

    @property
    def norm(self) -> float:
        """Mean of the three positive 1-5 scores, mapped to 0-1."""
        return (self.hook + self.cliffhanger + self.standalone - 3.0) / 12.0

    def to_dict(self) -> dict:
        return {
            "hook": self.hook, "cliffhanger": self.cliffhanger, "standalone": self.standalone,
            "spoiler_risk": self.spoiler_risk, "postable": self.postable,
            "reason": self.reason, "fix": self.fix, "model": self.model, "cached": self.cached,
        }


@dataclass
class JudgeConfig:
    provider: str = "none"          # none | openai | anthropic
    model: str = ""
    api_key: str = ""
    base_url: str = ""
    timeout: float = 60.0

    @classmethod
    def from_env(cls) -> "JudgeConfig":
        provider = os.environ.get("PROMO_LLM_PROVIDER", "").strip().lower()
        base = os.environ.get("PROMO_LLM_BASE_URL", "").strip()
        key = (
            os.environ.get("PROMO_LLM_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("ANTHROPIC_API_KEY")
            or os.environ.get("GROQ_API_KEY")
            or ""
        )
        if not provider and base:
            provider = "openai"
        if not provider and key:
            provider = "openai"
        model = os.environ.get("PROMO_LLM_MODEL", "")
        if not model:
            model = "claude-sonnet-4-20250514" if provider == "anthropic" else "gpt-4o-mini"
        if not base:
            base = (
                "https://api.anthropic.com/v1" if provider == "anthropic"
                else "https://api.openai.com/v1"
            )
        return cls(provider=provider, model=model, api_key=key, base_url=base)

    @property
    def enabled(self) -> bool:
        return self.provider in ("openai", "anthropic") and bool(self.api_key)


class LLMJudge:
    def __init__(self, config: JudgeConfig, cache_path: str | Path = "outputs/llm_cache.json"):
        self.config = config
        self.cache_path = Path(cache_path)
        self.last_error = ""
        self.failures = 0
        self.retryable = False
        self.retry_after = 0.0
        self._cache: dict[str, dict] = {}
        if self.cache_path.exists():
            try:
                self._cache = json.loads(self.cache_path.read_text())
            except json.JSONDecodeError:
                self._cache = {}

    def _save_cache(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self._cache, indent=1, sort_keys=True))

    def _key(self, clip: str) -> str:
        raw = f"{self.config.provider}|{self.config.model}|{SYSTEM_PROMPT}|{clip}"
        return hashlib.sha1(raw.encode()).hexdigest()

    def judge(self, cand: Candidate) -> Verdict | None:
        if not self.config.enabled:
            return None
        clip = render_clip(cand)
        key = self._key(clip)
        if key in self._cache:
            v = self._cache[key]
            return Verdict(**v, model=self.config.model, cached=True)
        raw = self._call(USER_TEMPLATE.format(clip=clip))
        if raw is None:
            self.failures += 1
            return None
        parsed = parse_verdict(raw)
        if parsed is None:
            self.failures += 1
            self.last_error = "model did not return JSON"
            return None
        self._cache[key] = parsed
        self._save_cache()
        return Verdict(**parsed, model=self.config.model)

    def _call(self, user: str) -> str | None:
        self.last_error = ""
        payload = None
        for attempt in range(6):
            payload = self._post(user)
            if payload is not None:
                break
            if not self.retryable:
                return None
            time.sleep(min(self.retry_after or 2.0 * (attempt + 1), 25.0))
        if payload is None:
            return None

        try:
            if self.config.provider == "anthropic":
                return payload["content"][0]["text"]
            return payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            self.last_error = "unexpected response shape"
            return None

    def _post(self, user: str) -> dict | None:
        self.retryable = False
        try:
            if self.config.provider == "anthropic":
                url = f"{self.config.base_url.rstrip('/')}/messages"
                body = {
                    "model": self.config.model,
                    "max_tokens": 900,  # reasoning models spend budget before the JSON
                    "temperature": 0,
                    "system": SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": user}],
                }
                headers = {
                    "x-api-key": self.config.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                    "user-agent": "promo-finder/1.0",
                }
            else:
                url = f"{self.config.base_url.rstrip('/')}/chat/completions"
                body = {
                    "model": self.config.model,
                    "temperature": 0,
                    "max_tokens": 900,  # reasoning models spend budget before the JSON
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user},
                    ],
                }
                headers = {
                    "authorization": f"Bearer {self.config.api_key}",
                    "content-type": "application/json",
                    # Cloudflare-fronted gateways (Groq among them) reject
                    # requests with Python's default User-Agent outright.
                    "user-agent": "promo-finder/1.0",
                }
            req = urllib.request.Request(
                url, data=json.dumps(body).encode(), headers=headers, method="POST"
            )
            with urllib.request.urlopen(req, timeout=self.config.timeout) as resp:
                payload = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode(errors="replace")[:300]
            except OSError:
                detail = ""
            self.last_error = f"HTTP {e.code}: {detail}".strip()
            # Free tiers throttle hard; retrying briefly is worth it, but one
            # clip must never stall the run.
            self.retryable = e.code in (429, 500, 502, 503, 504)
            try:
                self.retry_after = float(e.headers.get("retry-after", ""))
            except (TypeError, ValueError):
                self.retry_after = 0.0
            return None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
            self.last_error = f"{type(e).__name__}: {e}"
            return None
        return payload


def _extract_json(text: str) -> dict | None:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def _score(value, default: float = 3.0) -> float:
    try:
        return max(1.0, min(5.0, float(value)))
    except (TypeError, ValueError):
        return default


def parse_verdict(text: str) -> dict | None:
    data = _extract_json(text)
    if not data:
        return None
    return {
        "hook": _score(data.get("hook")),
        "cliffhanger": _score(data.get("cliffhanger")),
        "standalone": _score(data.get("standalone")),
        "spoiler_risk": _score(data.get("spoiler_risk")),
        "postable": bool(data.get("postable", True)),
        "reason": str(data.get("reason", "")).strip()[:400],
        "fix": str(data.get("fix", "")).strip()[:400],
    }
