"""5.1 Integrity indicators: the per-attempt timeline and the human review of flags.
Flags are signals for a person to look at. Dismissing or noting one never changes marks."""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import ai_service
from attempt_core import staff_attempt
from database import get_db
from integrity_rules import analyze_ai, analyze_rules
from security import require_roles
from utils import audit, q_all, q_one, run

router = APIRouter(prefix="/api/integrity", tags=["integrity"])
staff = require_roles("examiner", "admin")

NOTICE = ("These are indicators, not proof. Page switches, focus changes and pastes also happen for innocent reasons "
          "(notifications, accessibility tools, rough work, unstable networks). Only a person reviewing the full context can judge.")


class FlagReview(BaseModel):
    review_status: Literal["open", "dismissed", "noted"]
    note: Optional[str] = Field(default=None, max_length=1000)


@router.get("/attempts/{attempt_id}")
def attempt_timeline(attempt_id: int, user: dict = Depends(staff), db: Session = Depends(get_db)):
    a = staff_attempt(db, attempt_id, user)
    who = q_one(db, "SELECT full_name, roll_no FROM users WHERE id=:i", i=a["candidate_id"])
    events = q_all(db, """SELECT v.id, v.event_type, v.detail, v.created_at,
                          TIMESTAMPDIFF(SECOND, (SELECT started_at FROM attempts WHERE id=:a), v.created_at) AS offset_s
                          FROM attempt_events v WHERE v.attempt_id=:a ORDER BY v.id""", a=attempt_id)
    flags = q_all(db, """SELECT f.id, f.source, f.signal, f.score, f.reason, f.review_status, f.review_note, f.created_at,
                                f.attempt_question_id, aq.position AS question_no, r.full_name AS reviewer
                         FROM integrity_flags f LEFT JOIN attempt_questions aq ON aq.id=f.attempt_question_id
                         LEFT JOIN users r ON r.id=f.reviewed_by WHERE f.attempt_id=:a ORDER BY f.score DESC, f.id""", a=attempt_id)
    return {"candidate": who, "status": a["status"], "title": a["title"], "events": events, "flags": flags,
            "notice": NOTICE, "monitoring_enabled": bool(a["integrity_monitoring"]), "ai_provider": "Groq" if ai_service.groq_enabled() else "offline heuristic"}


@router.put("/flags/{flag_id}")
def review_flag(flag_id: int, data: FlagReview, user: dict = Depends(staff), db: Session = Depends(get_db)):
    f = q_one(db, "SELECT id, attempt_id, review_status FROM integrity_flags WHERE id=:i", i=flag_id)
    if not f:
        raise HTTPException(404, "Flag not found.")
    staff_attempt(db, f["attempt_id"], user)               # ownership check
    if data.review_status != "open" and not (data.note or "").strip():
        raise HTTPException(422, "Add a short note explaining your decision.")
    run(db, "UPDATE integrity_flags SET review_status=:s, review_note=:n, reviewed_by=:u WHERE id=:i",
        s=data.review_status, n=(data.note or "").strip() or None, u=user["id"], i=flag_id)
    audit(db, "integrity_flag", flag_id, user["id"], "review", old=f["review_status"], new=data.review_status, note=data.note)
    db.commit()
    return {"ok": True}


@router.post("/attempts/{attempt_id}/rescan")
def rescan(attempt_id: int, user: dict = Depends(staff), db: Session = Depends(get_db)):
    """Re-run the rule checks and the written-answer review now (for example after adding a Groq key)."""
    a = staff_attempt(db, attempt_id, user)
    if a["is_sandbox"] or a["status"] == "in_progress":
        raise HTTPException(409, "Only finished, real attempts can be scanned.")
    made = analyze_rules(db, attempt_id) if a["integrity_monitoring"] else 0
    if a["ai_review_written"]:
        made += analyze_ai(db, attempt_id)
    audit(db, "attempt", attempt_id, user["id"], "integrity_rescan", new=made)
    db.commit()
    return {"flags_created": made, "provider": "Groq" if ai_service.groq_enabled() else "offline heuristic"}
