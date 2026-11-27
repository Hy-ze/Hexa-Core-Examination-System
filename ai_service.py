"""Groq integration (optional). Every function has a rule-based fallback, so the system works
fully with no key, no internet, or if the Groq API fails (competition rule: no required
feature may depend on a paid or external service)."""
import json
import logging
import re
from statistics import mean, pstdev

import httpx

from config import GROQ_API_KEY, GROQ_MODEL

log = logging.getLogger("exam")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def groq_enabled() -> bool:
    return bool(GROQ_API_KEY)


def _chat_json(system: str, user: str, max_tokens: int = 300):
    """Call Groq and return the parsed JSON object, or None on any problem."""
    if not groq_enabled():
        return None
    try:
        r = httpx.post(GROQ_URL, timeout=15,
                       headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                       json={"model": GROQ_MODEL, "temperature": 0.1, "max_tokens": max_tokens,
                             "response_format": {"type": "json_object"},
                             "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
        r.raise_for_status()
        return json.loads(r.json()["choices"][0]["message"]["content"])
    except Exception as e:                      # never let an AI failure break an exam workflow
        log.warning("Groq call failed, using rule-based fallback: %r", e)
        return None


# ------------------------------------------------------------------ 5.1 written-answer review
_SYSTEM_REVIEW = (
    "You help an examiner by looking at ONE written exam answer for wording patterns that are common in "
    "AI-generated text (generic structure, stock transition phrases, unusually polished uniform prose, "
    "no personal or course-specific detail). You cannot know who wrote it. Many honest students write "
    "formally, so be conservative. Your output is only a hint for a human reviewer, never a verdict. "
    'Reply with JSON only: {"score": number from 0 to 1, "reason": "one or two sentences naming the '
    'observable features, and say that this is only an indicator"}.')

_STOCK = ["in conclusion", "furthermore", "moreover", "it is important to note", "it is worth noting",
          "delve", "multifaceted", "plays a crucial role", "in today's", "additionally", "in summary",
          "key takeaway", "tapestry", "landscape of", "leverage", "it is essential to", "overall,"]


def heuristic_review(answer: str) -> dict:
    """Offline fallback: counts a few stylistic signals. Deliberately weak and labelled as such."""
    low = answer.lower()
    hits = [p for p in _STOCK if p in low]
    score, notes = min(0.45, 0.15 * len(hits)), []
    if hits:
        notes.append("stock phrases (" + ", ".join(hits[:4]) + ")")
    sentences = [s for s in re.split(r"[.!?]+\s", answer.strip()) if len(s.split()) > 3]
    if len(sentences) >= 4:
        lens = [len(s.split()) for s in sentences]
        if pstdev(lens) / max(mean(lens), 1) < 0.3:
            score += 0.2
            notes.append("very uniform sentence length")
    if re.search(r"(^|\n)\s*(\d+[.)]|[-*•])\s", answer) or "**" in answer:
        score += 0.15
        notes.append("list or markdown-style formatting inside a prose answer")
    if len(answer) > 700:
        score += 0.1
        notes.append("long, fully polished answer")
    score = round(min(score, 0.95), 2)
    reason = ("Style indicators: " + "; ".join(notes) + ". " if notes else "No strong style indicators. ") + \
             "This is a simple offline heuristic, not evidence of misconduct."
    return {"score": score, "reason": reason, "source": "rule"}


def review_written(question: str, answer: str) -> dict:
    """Return {score 0..1, reason, source 'ai'|'rule'}. Only the question and answer text are
    sent to Groq: no name, email or roll number."""
    data = _chat_json(_SYSTEM_REVIEW, f"Question:\n{question[:1500]}\n\nStudent answer:\n{answer[:4000]}")
    if data and "score" in data:
        try:
            return {"score": round(max(0.0, min(1.0, float(data["score"]))), 2),
                    "reason": str(data.get("reason", ""))[:900] or "No reason given.", "source": "ai"}
        except (TypeError, ValueError):
            pass
    return heuristic_review(answer)
