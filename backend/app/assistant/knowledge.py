"""Searchable help text: the Complanning User Manual, split into sections."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

MANUAL = Path(__file__).with_name("manual.md")
WORD = re.compile(r"[\w؀-ۿ]+", re.UNICODE)
STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are", "be", "how", "what", "do", "i", "it",
        "my", "with", "can", "does", "this", "that", "when", "where", "why", "which", "at", "by", "from", "as", "you"}


@lru_cache(maxsize=1)
def sections() -> list[tuple[str, str]]:
    text = MANUAL.read_text(encoding="utf-8")
    out, title, buf = [], "Complanning User Manual", []
    for line in text.splitlines():
        if line.startswith("## ") or line.startswith("### "):
            if buf:
                out.append((title, "\n".join(buf).strip()))
            title, buf = line.lstrip("# ").strip(), []
        else:
            buf.append(line)
    if buf:
        out.append((title, "\n".join(buf).strip()))
    return [s for s in out if s[1]]


def search(query: str, limit: int = 3, max_chars: int = 2500) -> list[dict]:
    words = [w.lower() for w in WORD.findall(query) if w.lower() not in STOP and len(w) > 1]
    if not words:
        return []
    scored = []
    for title, body in sections():
        hay, head = body.lower(), title.lower()
        score = sum(hay.count(w) + 5 * head.count(w) for w in words)
        if score:
            scored.append((score, title, body))
    scored.sort(key=lambda x: -x[0])
    return [{"section": t, "text": b[:max_chars]} for _s, t, b in scored[:limit]]
