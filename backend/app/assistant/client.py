"""Minimal client for an OpenAI-compatible chat-completions API (Qwen on Model Studio by default)."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from ..api import ApiError
from ..config import settings


def chat(messages: list[dict], tools: list[dict] | None = None, max_tokens: int = 1200) -> dict:
    """One completion. Returns {"message": {...}, "usage": {...}}. Raises ApiError with a readable message."""
    if not settings.ai_api_key:
        raise ApiError(503, "ai_not_configured", "The assistant is not set up on this server yet (AI_API_KEY is missing).")
    body = {"model": settings.ai_model, "messages": messages, "temperature": 0.2, "max_tokens": max_tokens}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    req = urllib.request.Request(settings.ai_base_url + "/chat/completions", data=json.dumps(body).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {settings.ai_api_key}")
    try:
        with urllib.request.urlopen(req, timeout=settings.ai_timeout_s) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            err = json.loads(e.read() or b"{}")
            detail = (err.get("error") or {}).get("message") or err.get("message") or ""
        except Exception:
            pass
        if e.code in (401, 403):
            raise ApiError(502, "ai_auth", "The AI service refused the key. Check AI_API_KEY, and that AI_BASE_URL is the "
                                           "address of the region or workspace where the key was created." + (f" ({detail})" if detail else ""))
        if e.code == 404:
            raise ApiError(502, "ai_model", f"The AI service does not know the model or address. Check AI_MODEL "
                                            f"({settings.ai_model}) and AI_BASE_URL." + (f" ({detail})" if detail else ""))
        if e.code == 429:
            raise ApiError(429, "ai_busy", "The AI service is busy or the account's quota is used up. Try again shortly.")
        raise ApiError(502, "ai_error", "The AI service returned an error." + (f" ({detail[:200]})" if detail else ""))
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ApiError(504, "ai_unreachable", "The AI service could not be reached. Try again; if it repeats, check AI_BASE_URL.")
    try:
        msg = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        raise ApiError(502, "ai_error", "The AI service returned an answer in an unexpected format.")
    return {"message": msg, "usage": data.get("usage") or {}}
