"""5.1 Integrity in the AI era: turns raw observations into INDICATORS for human review.

Principles (shown to examiners in the UI and in the README):
  * Indicators, not proof. Every flag starts 'open' and only a person can dismiss or note it.
  * Privacy-light: no camera, no screen capture, no keystroke logging. Only page visibility,
    focus changes and the SIZE of pasted text are recorded (never its content).
  * Nothing changes a candidate's marks automatically.
"""
import logging
import re

from database import SessionLocal
from utils import q_all, q_one, run

log = logging.getLogger("exam")

TAB_SWITCH_MIN = 3        # times the page was hidden before it is worth a look
BLUR_MIN = 5              # times the window lost focus
BIG_PASTE_CHARS = 150     # one paste at least this long
MANY_PASTES = 3
AI_FLAG_THRESHOLD = 0.6
MAX_AI_REVIEWS = 6        # per attempt, keeps the free tier safe


def _num(detail: str | None, key: str) -> int:
    m = re.search(rf"{key}=(\d+)", detail or "")
    return int(m.group(1)) if m else 0


def rule_flags(events: list[dict]) -> list[dict]:
    """Pure function: events in, flag dicts out (easy to test and to explain)."""
    flags = []
    hidden = [e for e in events if e["event_type"] == "tab_hidden"]
    away = sum(_num(e["detail"], "away") for e in events if e["event_type"] == "tab_visible")
    if len(hidden) >= TAB_SWITCH_MIN:
        flags.append({"signal": "tab_switching", "score": round(min(1.0, len(hidden) / 10), 2),
                      "reason": f"The exam page was hidden {len(hidden)} times (about {away}s away in total). "
                                "Notifications, other windows and assistive tools can cause this too."})
    pastes = [_num(e["detail"], "len") for e in events if e["event_type"] == "paste"]
    if pastes and (max(pastes) >= BIG_PASTE_CHARS or len(pastes) >= MANY_PASTES):
        flags.append({"signal": "paste_activity", "score": round(min(1.0, 0.4 + 0.15 * len(pastes)), 2),
                      "reason": f"Text was pasted {len(pastes)} time(s); the largest paste was {max(pastes)} characters. "
                                "Pasting can be legitimate (for example, the candidate's own rough work)."})
    blurs = [e for e in events if e["event_type"] == "window_blur"]
    if len(blurs) >= BLUR_MIN:
        flags.append({"signal": "focus_loss", "score": round(min(1.0, len(blurs) / 15), 2),
                      "reason": f"The exam window lost focus {len(blurs)} times for several seconds each."})
    return flags


def analyze_rules(db, attempt_id: int) -> int:
    run(db, "DELETE FROM integrity_flags WHERE attempt_id=:a AND source='rule' AND review_status='open' AND attempt_question_id IS NULL", a=attempt_id)
    events = q_all(db, "SELECT event_type, detail FROM attempt_events WHERE attempt_id=:a", a=attempt_id)
    flags = rule_flags(events)
    for f in flags:
        run(db, """INSERT INTO integrity_flags (attempt_id, source, signal, score, reason)
                   VALUES (:a,'rule',:s,:c,:r)""", a=attempt_id, s=f["signal"], c=f["score"], r=f["reason"])
    return len(flags)


def analyze_ai(db, attempt_id: int) -> int:
    """Review written answers (Groq if available, otherwise the offline heuristic)."""
    from ai_service import review_written
    run(db, "DELETE FROM integrity_flags WHERE attempt_id=:a AND attempt_question_id IS NOT NULL AND review_status='open'", a=attempt_id)
    rows = q_all(db, """SELECT aq.id, aq.written_answer, q.body FROM attempt_questions aq
                        JOIN questions q ON q.id=aq.question_id
                        WHERE aq.attempt_id=:a AND aq.question_type='written'
                          AND CHAR_LENGTH(COALESCE(aq.written_answer,''))>=60
                        ORDER BY aq.position LIMIT :n""", a=attempt_id, n=MAX_AI_REVIEWS)
    made = 0
    for r in rows:
        res = review_written(r["body"], r["written_answer"])
        if res["score"] >= AI_FLAG_THRESHOLD:
            run(db, """INSERT INTO integrity_flags (attempt_id, attempt_question_id, source, signal, score, reason)
                       VALUES (:a,:q,:src,:sig,:sc,:re)""",
                a=attempt_id, q=r["id"], src=res["source"],
                sig="ai_style_text" if res["source"] == "ai" else "text_style_heuristic", sc=res["score"], re=res["reason"])
            made += 1
    return made


def post_process(attempt_id: int):
    """Run after an attempt is finalised (background). Real attempts only. Never raises."""
    db = SessionLocal()
    try:
        a = q_one(db, """SELECT a.is_sandbox, e.integrity_monitoring, e.ai_review_written
                         FROM attempts a JOIN exams e ON e.id=a.exam_id WHERE a.id=:i""", i=attempt_id)
        if not a or a["is_sandbox"]:
            return
        if a["integrity_monitoring"]:
            analyze_rules(db, attempt_id)
        if a["ai_review_written"]:
            analyze_ai(db, attempt_id)
        db.commit()
    except Exception:
        log.exception("Integrity post-processing failed for attempt %s", attempt_id)
        db.rollback()
    finally:
        db.close()
