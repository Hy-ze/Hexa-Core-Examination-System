"""Enroll candidates in exams."""
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from access import owned_exam
from database import get_db
from security import require_roles
from utils import audit, q_all, q_one, run

router = APIRouter(prefix="/api/exams/{exam_id}/enrollments", tags=["enrollments"])
staff = require_roles("examiner", "admin")


class EnrollIn(BaseModel):
    candidate_ids: List[int] = Field(min_length=1, max_length=1000)


@router.get("")
def list_enrollments(exam_id: int, user: dict = Depends(staff), db: Session = Depends(get_db)):
    owned_exam(db, exam_id, user)
    return q_all(db, """SELECT u.id, u.full_name, u.email, u.roll_no, en.enrolled_at,
                        (SELECT a.status FROM attempts a WHERE a.exam_id=en.exam_id AND a.candidate_id=u.id
                         AND a.is_sandbox=0 LIMIT 1) AS attempt_status
                        FROM exam_enrollments en JOIN users u ON u.id=en.candidate_id
                        WHERE en.exam_id=:e ORDER BY u.full_name""", e=exam_id)


@router.post("")
def enroll(exam_id: int, data: EnrollIn, user: dict = Depends(staff), db: Session = Depends(get_db)):
    exam = owned_exam(db, exam_id, user)
    if exam["eff_status"] == "completed":
        raise HTTPException(409, "This exam has finished; enrollment is closed.")
    added = 0
    for cid in dict.fromkeys(data.candidate_ids):
        if not q_one(db, "SELECT id FROM users WHERE id=:i AND role='candidate' AND is_active=1", i=cid):
            continue
        if q_one(db, "SELECT id FROM exam_enrollments WHERE exam_id=:e AND candidate_id=:c", e=exam_id, c=cid):
            continue
        run(db, "INSERT INTO exam_enrollments (exam_id, candidate_id) VALUES (:e,:c)", e=exam_id, c=cid)
        added += 1
    audit(db, "exam", exam_id, user["id"], "enroll", new=added)
    db.commit()
    return {"added": added}


@router.delete("/{candidate_id}")
def unenroll(exam_id: int, candidate_id: int, user: dict = Depends(staff), db: Session = Depends(get_db)):
    owned_exam(db, exam_id, user)
    if q_one(db, "SELECT id FROM attempts WHERE exam_id=:e AND candidate_id=:c AND is_sandbox=0", e=exam_id, c=candidate_id):
        raise HTTPException(409, "This candidate has already started the exam and cannot be removed.")
    run(db, "DELETE FROM exam_enrollments WHERE exam_id=:e AND candidate_id=:c", e=exam_id, c=candidate_id)
    audit(db, "exam", exam_id, user["id"], "unenroll", old=candidate_id)
    db.commit()
    return {"ok": True}
