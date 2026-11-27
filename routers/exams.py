"""Exam setup, question pool, lifecycle (draft -> published -> ongoing -> completed)."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from access import check_editable, has_real_attempts, owned_exam
from database import get_db
from security import current_user, require_roles
from utils import ACCESS_SQL, STATUS_SQL, audit, now_utc, parse_client_dt, q_all, q_one, run

router = APIRouter(prefix="/api/exams", tags=["exams"])
staff = require_roles("examiner", "admin")


class ExamIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    instructions: str = Field(default="", max_length=5000)
    start_time: str
    end_time: str
    duration_minutes: int = Field(ge=1, le=600)
    total_marks: float = Field(default=0, ge=0, le=10000)
    randomize_questions: bool = True
    randomize_options: bool = True
    paper_size: Optional[int] = Field(default=None, ge=1, le=500)
    balance_difficulty: bool = True
    integrity_monitoring: bool = True
    ai_review_written: bool = True


class PoolAdd(BaseModel):
    question_ids: List[int] = Field(min_length=1, max_length=200)


class MarksIn(BaseModel):
    marks: float = Field(gt=0, le=100)


def _times(data: ExamIn):
    try:
        start, end = parse_client_dt(data.start_time), parse_client_dt(data.end_time)
    except ValueError:
        raise HTTPException(422, "Enter valid start and end times.")
    if end <= start:
        raise HTTPException(422, "The end time must be after the start time.")
    if (end - start).total_seconds() / 60 < data.duration_minutes:
        raise HTTPException(422, "The availability window is shorter than the exam duration.")
    return start, end


def recalc_total(db, exam_id: int):
    """With no paper_size every candidate sees the whole pool, so total = sum of pool marks."""
    run(db, """UPDATE exams SET total_marks=(SELECT COALESCE(SUM(marks),0) FROM exam_questions WHERE exam_id=:i)
               WHERE id=:i AND paper_size IS NULL""", i=exam_id)


def pool_of(db, exam_id: int):
    return q_all(db, """SELECT eq.question_id, eq.marks, eq.position, q.body, q.question_type, q.difficulty,
                               c.name AS category
                        FROM exam_questions eq JOIN questions q ON q.id=eq.question_id
                        LEFT JOIN categories c ON c.id=q.category_id
                        WHERE eq.exam_id=:i ORDER BY eq.position, eq.question_id""", i=exam_id)


def review(db, exam: dict) -> dict:
    """Pre-publication checklist: 'issues' block publishing, 'warnings' are advice."""
    pool = pool_of(db, exam["id"])
    issues, warnings = [], []
    if not pool:
        issues.append("Add at least one question to the exam.")
    n = exam["paper_size"]
    if n and len(pool) < n:
        issues.append(f"Each paper needs {n} questions but the pool only has {len(pool)}.")
    if n and pool and len(pool) >= n:
        marks = sorted(float(p["marks"]) for p in pool)
        lo, hi = sum(marks[:n]), sum(marks[-n:])
        if exam["total_marks"] <= 0:
            issues.append("Set the target total marks for each paper.")
        elif not (lo <= exam["total_marks"] <= hi):
            issues.append(f"A paper of {n} questions can total between {lo:g} and {hi:g} marks; "
                          f"the target is {exam['total_marks']:g}.")
    elif not n and exam["total_marks"] <= 0 and pool:
        issues.append("Total marks must be above zero.")
    if exam["end_time"] <= now_utc().isoformat() + "Z":
        issues.append("The end time has already passed.")
    if any(p["question_type"] == "written" for p in pool):
        warnings.append("Written answers need manual grading before results can be published.")
    enrolled = q_one(db, "SELECT COUNT(*) AS n FROM exam_enrollments WHERE exam_id=:i", i=exam["id"])["n"]
    if enrolled == 0:
        warnings.append("No candidates are enrolled yet. Only enrolled candidates can enter.")
    return {"issues": issues, "warnings": warnings, "pool_size": len(pool), "enrolled": enrolled}


# ------------------------------------------------------------ lists
@router.get("")
def list_exams(user: dict = Depends(staff), db: Session = Depends(get_db)):
    sql = f"""SELECT e.id, e.title, e.start_time, e.end_time, e.duration_minutes, e.total_marks, e.paper_size,
                     e.results_published, {STATUS_SQL} AS eff_status, e.created_by, u.full_name AS examiner,
                     (SELECT COUNT(*) FROM exam_questions x WHERE x.exam_id=e.id) AS pool_count,
                     (SELECT COUNT(*) FROM exam_enrollments n WHERE n.exam_id=e.id) AS enrolled_count
              FROM exams e JOIN users u ON u.id=e.created_by"""
    p = {}
    if user["role"] != "admin":
        sql += " WHERE e.created_by=:u"; p["u"] = user["id"]
    return q_all(db, sql + " ORDER BY e.start_time DESC", **p)


@router.get("/mine")
def my_exams(user: dict = Depends(require_roles("candidate")), db: Session = Depends(get_db)):
    """Candidate view: only enrolled, non-draft exams."""
    return q_all(db, f"""SELECT e.id, e.title, e.instructions, e.start_time, e.end_time, e.duration_minutes,
                  e.total_marks, e.results_published, {ACCESS_SQL} AS access_status,
                  (SELECT a.status FROM attempts a WHERE a.exam_id=e.id AND a.candidate_id=:u AND a.is_sandbox=0 LIMIT 1) AS attempt_status,
                  (SELECT a.id FROM attempts a WHERE a.exam_id=e.id AND a.candidate_id=:u AND a.is_sandbox=0 LIMIT 1) AS attempt_id
           FROM exams e JOIN exam_enrollments en ON en.exam_id=e.id AND en.candidate_id=:u
           WHERE e.status<>'draft' ORDER BY e.start_time DESC""", u=user["id"])


# ------------------------------------------------------------ create / read / update
@router.post("", status_code=201)
def create_exam(data: ExamIn, user: dict = Depends(staff), db: Session = Depends(get_db)):
    start, end = _times(data)
    res = run(db, """INSERT INTO exams (created_by, title, instructions, start_time, end_time, duration_minutes,
             total_marks, status, randomize_questions, randomize_options, paper_size, balance_difficulty,
             integrity_monitoring, ai_review_written)
             VALUES (:u,:t,:ins,:s,:e,:d,:tm,'draft',:rq,:ro,:ps,:bd,:im,:ai)""",
              u=user["id"], t=data.title.strip(), ins=data.instructions.strip(), s=start, e=end,
              d=data.duration_minutes, tm=data.total_marks, rq=int(data.randomize_questions),
              ro=int(data.randomize_options), ps=data.paper_size, bd=int(data.balance_difficulty),
              im=int(data.integrity_monitoring), ai=int(data.ai_review_written))
    audit(db, "exam", res.lastrowid, user["id"], "create")
    db.commit()
    return {"id": res.lastrowid}


@router.get("/{exam_id}")
def exam_detail(exam_id: int, user: dict = Depends(staff), db: Session = Depends(get_db)):
    exam = owned_exam(db, exam_id, user)
    exam["questions"] = pool_of(db, exam_id)
    exam["review"] = review(db, exam)
    exam["locked"] = exam["eff_status"] in ("ongoing", "completed") or has_real_attempts(db, exam_id)
    return exam


@router.put("/{exam_id}")
def update_exam(exam_id: int, data: ExamIn, user: dict = Depends(staff), db: Session = Depends(get_db)):
    exam = owned_exam(db, exam_id, user)
    check_editable(db, exam)
    start, end = _times(data)
    run(db, """UPDATE exams SET title=:t, instructions=:ins, start_time=:s, end_time=:e, duration_minutes=:d,
               total_marks=:tm, randomize_questions=:rq, randomize_options=:ro, paper_size=:ps,
               balance_difficulty=:bd, integrity_monitoring=:im, ai_review_written=:ai WHERE id=:i""",
        t=data.title.strip(), ins=data.instructions.strip(), s=start, e=end, d=data.duration_minutes,
        tm=data.total_marks, rq=int(data.randomize_questions), ro=int(data.randomize_options),
        ps=data.paper_size, bd=int(data.balance_difficulty), im=int(data.integrity_monitoring),
        ai=int(data.ai_review_written), i=exam_id)
    recalc_total(db, exam_id)
    audit(db, "exam", exam_id, user["id"], "edit")
    db.commit()
    return {"ok": True}


@router.delete("/{exam_id}")
def delete_exam(exam_id: int, user: dict = Depends(staff), db: Session = Depends(get_db)):
    exam = owned_exam(db, exam_id, user)
    if exam["status"] != "draft" or has_real_attempts(db, exam_id):
        raise HTTPException(409, "Only draft exams without attempts can be deleted.")
    run(db, "DELETE FROM exams WHERE id=:i", i=exam_id)
    audit(db, "exam", exam_id, user["id"], "delete", old=exam["title"])
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------ question pool
@router.post("/{exam_id}/questions")
def add_questions(exam_id: int, data: PoolAdd, user: dict = Depends(staff), db: Session = Depends(get_db)):
    exam = owned_exam(db, exam_id, user)
    check_editable(db, exam)
    pos = q_one(db, "SELECT COALESCE(MAX(position),0) AS m FROM exam_questions WHERE exam_id=:i", i=exam_id)["m"]
    added = 0
    for qid in dict.fromkeys(data.question_ids):
        q = q_one(db, "SELECT id, marks FROM questions WHERE id=:i AND is_active=1", i=qid)
        if not q or q_one(db, "SELECT id FROM exam_questions WHERE exam_id=:e AND question_id=:q", e=exam_id, q=qid):
            continue
        pos += 1
        run(db, "INSERT INTO exam_questions (exam_id, question_id, marks, position) VALUES (:e,:q,:m,:p)",
            e=exam_id, q=qid, m=q["marks"], p=pos)
        added += 1
    recalc_total(db, exam_id)
    db.commit()
    return {"added": added}


@router.put("/{exam_id}/questions/{qid}")
def set_question_marks(exam_id: int, qid: int, data: MarksIn, user: dict = Depends(staff), db: Session = Depends(get_db)):
    exam = owned_exam(db, exam_id, user)
    check_editable(db, exam)
    res = run(db, "UPDATE exam_questions SET marks=:m WHERE exam_id=:e AND question_id=:q", m=data.marks, e=exam_id, q=qid)
    if res.rowcount == 0 and not q_one(db, "SELECT id FROM exam_questions WHERE exam_id=:e AND question_id=:q", e=exam_id, q=qid):
        raise HTTPException(404, "That question is not in this exam.")
    recalc_total(db, exam_id)
    db.commit()
    return {"ok": True}


@router.delete("/{exam_id}/questions/{qid}")
def remove_question(exam_id: int, qid: int, user: dict = Depends(staff), db: Session = Depends(get_db)):
    exam = owned_exam(db, exam_id, user)
    check_editable(db, exam)
    run(db, "DELETE FROM exam_questions WHERE exam_id=:e AND question_id=:q", e=exam_id, q=qid)
    recalc_total(db, exam_id)
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------ lifecycle
@router.post("/{exam_id}/publish")
def publish(exam_id: int, user: dict = Depends(staff), db: Session = Depends(get_db)):
    exam = owned_exam(db, exam_id, user)
    if exam["status"] != "draft":
        raise HTTPException(409, "This exam is already published.")
    check = review(db, exam)
    if check["issues"]:
        raise HTTPException(409, "Fix these first: " + " ".join(check["issues"]))
    run(db, "UPDATE exams SET status='published' WHERE id=:i", i=exam_id)
    audit(db, "exam", exam_id, user["id"], "publish")
    db.commit()
    return {"ok": True}


@router.post("/{exam_id}/unpublish")
def unpublish(exam_id: int, user: dict = Depends(staff), db: Session = Depends(get_db)):
    exam = owned_exam(db, exam_id, user)
    if exam["eff_status"] != "published" or has_real_attempts(db, exam_id):
        raise HTTPException(409, "Only published exams that have not started can go back to draft.")
    run(db, "UPDATE exams SET status='draft' WHERE id=:i", i=exam_id)
    audit(db, "exam", exam_id, user["id"], "unpublish")
    db.commit()
    return {"ok": True}
