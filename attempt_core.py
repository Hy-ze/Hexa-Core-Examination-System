"""Shared exam-engine logic: attempt lookup, server-side timing, finalisation, background sweep.

Timing rule: every time comparison is done by the DATABASE clock in UTC. The browser's clock
is never sent or trusted. GRACE_SECONDS only covers requests that were already in flight when
the deadline passed.
"""
import logging

from fastapi import HTTPException
from sqlalchemy import text

from database import SessionLocal
from scoring import autograde_attempt
from utils import q_all, q_one, run

log = logging.getLogger("exam")
GRACE_SECONDS = 5


def get_attempt(db, attempt_id: int, user: dict) -> dict:
    """Return the attempt (with exam info and server-computed seconds remaining) if it is the user's own."""
    a = q_one(db, """SELECT a.*, e.title, e.instructions, e.integrity_monitoring, e.ai_review_written,
                            e.duration_minutes, e.results_published,
                            TIMESTAMPDIFF(SECOND, UTC_TIMESTAMP(), a.deadline_at) AS remaining
                     FROM attempts a JOIN exams e ON e.id=a.exam_id WHERE a.id=:i""", i=attempt_id)
    if not a or a["candidate_id"] != user["id"]:
        raise HTTPException(404, "Attempt not found.")
    return a


def staff_attempt(db, attempt_id: int, user: dict) -> dict:
    """Attempt lookup for examiners/admins: only attempts of exams they own."""
    a = q_one(db, """SELECT a.*, e.created_by, e.title, e.integrity_monitoring, e.ai_review_written,
                            e.results_published
                     FROM attempts a JOIN exams e ON e.id=a.exam_id WHERE a.id=:i""", i=attempt_id)
    if not a:
        raise HTTPException(404, "Attempt not found.")
    if user["role"] != "admin" and a["created_by"] != user["id"]:
        raise HTTPException(403, "This attempt belongs to another examiner's exam.")
    return a


def finalize_attempt(db, attempt_id: int, expired: bool) -> bool:
    """Close an attempt exactly once. Returns True only for the call that actually closed it,
    so repeated submits, double clicks and the background sweeper can never double-finalise."""
    res = run(db, """UPDATE attempts SET status=:s,
                       submitted_at=IF(:ex, LEAST(deadline_at, UTC_TIMESTAMP()), UTC_TIMESTAMP())
                     WHERE id=:i AND status='in_progress'""",
              s="expired" if expired else "submitted", ex=1 if expired else 0, i=attempt_id)
    if res.rowcount == 0:
        db.commit()
        return False
    autograde_attempt(db, attempt_id)
    meta = q_one(db, "SELECT is_sandbox FROM attempts WHERE id=:i", i=attempt_id)
    if not meta["is_sandbox"]:
        # statistics feed Question Analytics (4.5) and the fairness balancing (5.2); sandbox never counts
        run(db, """UPDATE questions q JOIN attempt_questions aq ON aq.question_id=q.id AND aq.attempt_id=:a
                   SET q.times_presented=q.times_presented+1,
                       q.times_skipped=q.times_skipped+IF(aq.is_answered=0,1,0),
                       q.times_correct=q.times_correct+IF(aq.question_type<>'written' AND aq.marks_awarded>=aq.marks,1,0)""",
            a=attempt_id)
    db.commit()
    return True


def finalize_overdue(db, exam_id: int | None = None) -> list[int]:
    """Close every attempt whose deadline (plus grace) has passed. Returns the ids it closed."""
    sql = """SELECT id FROM attempts WHERE status='in_progress'
             AND deadline_at < DATE_SUB(UTC_TIMESTAMP(), INTERVAL :g SECOND)"""
    params = {"g": GRACE_SECONDS}
    if exam_id:
        sql += " AND exam_id=:e"
        params["e"] = exam_id
    closed = []
    for row in q_all(db, sql, **params):
        if finalize_attempt(db, row["id"], expired=True):
            closed.append(row["id"])
    return closed


def sweep_once():
    """Run by app.py every 30 seconds: expire overdue attempts even if the candidate's browser is gone."""
    from integrity_rules import post_process
    db = SessionLocal()
    try:
        ids = finalize_overdue(db)
    finally:
        db.close()
    for i in ids:
        post_process(i)
    if ids:
        log.info("Sweeper finalised %d expired attempt(s): %s", len(ids), ids)
