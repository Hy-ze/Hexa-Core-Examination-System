"""3.6 Examination monitoring: live attempts, progress, connection state, indicators, announcements."""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from access import owned_exam
from attempt_core import finalize_overdue
from database import get_db
from integrity_rules import post_process
from security import require_roles
from utils import audit, q_all, q_one, run

router = APIRouter(prefix="/api/exams/{exam_id}", tags=["monitoring"])
staff = require_roles("examiner", "admin")


class AnnounceIn(BaseModel):
    message: str = Field(min_length=2, max_length=1000)


@router.get("/monitor")
def monitor(exam_id: int, bg: BackgroundTasks, user: dict = Depends(staff), db: Session = Depends(get_db)):
    exam = owned_exam(db, exam_id, user)
    for att_id in finalize_overdue(db, exam_id):          # close anything past its deadline before showing it
        bg.add_task(post_process, att_id)
    ev = lambda t: f"(SELECT COUNT(*) FROM attempt_events v WHERE v.attempt_id=a.id AND v.event_type='{t}')"
    attempts = q_all(db, f"""SELECT a.id AS attempt_id, u.id AS candidate_id, u.full_name, u.roll_no, a.status, a.grading_status,
                      a.started_at, a.submitted_at, a.paper_difficulty,
                      TIMESTAMPDIFF(SECOND, UTC_TIMESTAMP(), a.deadline_at) AS remaining,
                      TIMESTAMPDIFF(SECOND, a.last_heartbeat_at, UTC_TIMESTAMP()) AS hb_age,
                      (SELECT COUNT(*) FROM attempt_questions x WHERE x.attempt_id=a.id) AS total_q,
                      (SELECT COALESCE(SUM(x.is_answered),0) FROM attempt_questions x WHERE x.attempt_id=a.id) AS answered_q,
                      (SELECT COALESCE(SUM(x.marked_for_review),0) FROM attempt_questions x WHERE x.attempt_id=a.id) AS marked_q,
                      {ev('tab_hidden')} AS n_tab, {ev('paste')} AS n_paste, {ev('window_blur')} AS n_blur, {ev('offline')} AS n_offline,
                      (SELECT COUNT(*) FROM integrity_flags f WHERE f.attempt_id=a.id AND f.review_status='open') AS open_flags
               FROM attempts a JOIN users u ON u.id=a.candidate_id
               WHERE a.exam_id=:e AND a.is_sandbox=0 ORDER BY (a.status='in_progress') DESC, a.started_at DESC""", e=exam_id)
    waiting = q_all(db, """SELECT u.id, u.full_name, u.roll_no FROM exam_enrollments en JOIN users u ON u.id=en.candidate_id
                           WHERE en.exam_id=:e AND NOT EXISTS (SELECT 1 FROM attempts a WHERE a.exam_id=en.exam_id
                           AND a.candidate_id=en.candidate_id AND a.is_sandbox=0) ORDER BY u.full_name""", e=exam_id)
    count = lambda s: sum(1 for a in attempts if a["status"] == s)
    return {"exam_status": exam["eff_status"], "integrity_monitoring": bool(exam["integrity_monitoring"]),
            "summary": {"enrolled": len(waiting) + len(attempts), "not_started": len(waiting), "in_progress": count("in_progress"),
                        "submitted": count("submitted"), "expired": count("expired"),
                        "open_flags": sum(int(a["open_flags"]) for a in attempts)},
            "attempts": attempts, "not_started": waiting}


@router.get("/announcements")
def list_announcements(exam_id: int, user: dict = Depends(staff), db: Session = Depends(get_db)):
    owned_exam(db, exam_id, user)
    return q_all(db, """SELECT n.id, n.message, n.created_at, u.full_name AS author FROM announcements n
                        JOIN users u ON u.id=n.author_id WHERE n.exam_id=:e ORDER BY n.id DESC LIMIT 30""", e=exam_id)


@router.post("/announcements", status_code=201)
def announce(exam_id: int, data: AnnounceIn, user: dict = Depends(staff), db: Session = Depends(get_db)):
    exam = owned_exam(db, exam_id, user)
    if exam["eff_status"] == "draft":
        raise HTTPException(409, "Publish the exam before sending announcements.")
    res = run(db, "INSERT INTO announcements (exam_id, author_id, message) VALUES (:e,:u,:m)", e=exam_id, u=user["id"], m=data.message.strip())
    audit(db, "exam", exam_id, user["id"], "announce", new=data.message[:200])
    db.commit()
    return {"id": res.lastrowid}
