"""Exam grading, examiner review and controlled result publication."""
from statistics import mean, median, pstdev
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from access import owned_exam
from attempt_core import staff_attempt
from database import get_db
from scoring import recompute_totals
from security import require_roles
from utils import STATUS_SQL, audit, q_all, q_one, run

router = APIRouter(prefix="/api/grading", tags=["grading"])
staff = require_roles("examiner", "admin")


class WrittenGradeIn(BaseModel):
    marks_awarded: float = Field(ge=0, le=10000)
    grader_comment: Optional[str] = Field(default=None, max_length=3000)


def _finished_attempt_counts(db, exam_id: int) -> dict:
    return q_one(db, """SELECT
        COALESCE(SUM(a.status IN ('submitted','expired')),0) AS submissions,
        COALESCE(SUM(a.status IN ('submitted','expired') AND a.grading_status='graded'),0) AS graded,
        COALESCE(SUM(a.status IN ('submitted','expired') AND a.grading_status<>'graded'),0) AS awaiting,
        COALESCE(SUM(a.status='in_progress'),0) AS in_progress
        FROM attempts a WHERE a.exam_id=:e AND a.is_sandbox=0
          AND a.status IN ('submitted','expired','in_progress')""", e=exam_id)



@router.get("/exams")
def grading_exams(user: dict = Depends(staff), db: Session = Depends(get_db)):
    """List exams the current examiner may grade, with counts from real submissions."""
    sql = f"""SELECT e.id, e.title, e.start_time, e.end_time, e.status,
                     {STATUS_SQL} AS eff_status, e.results_published,
                     (SELECT COUNT(*) FROM attempts a WHERE a.exam_id=e.id AND a.is_sandbox=0
                        AND a.status IN ('submitted','expired')) AS submissions,
                     (SELECT COUNT(*) FROM attempts a WHERE a.exam_id=e.id AND a.is_sandbox=0
                        AND a.status IN ('submitted','expired') AND a.grading_status='graded') AS graded,
                     (SELECT COUNT(*) FROM attempts a WHERE a.exam_id=e.id AND a.is_sandbox=0
                        AND a.status IN ('submitted','expired') AND a.grading_status<>'graded') AS awaiting,
                     (SELECT COUNT(*) FROM attempts a WHERE a.exam_id=e.id AND a.is_sandbox=0
                        AND a.status='in_progress') AS in_progress
              FROM exams e"""
    params = {}
    if user["role"] != "admin":
        sql += " WHERE e.created_by=:u"
        params["u"] = user["id"]
    return q_all(db, sql + " ORDER BY e.start_time DESC", **params)


@router.get("/exams/{exam_id}/attempts")
def exam_attempts(exam_id: int, user: dict = Depends(staff), db: Session = Depends(get_db)):
    exam = owned_exam(db, exam_id, user)
    attempts = q_all(db, """SELECT a.id AS attempt_id, a.candidate_id, u.full_name, u.email, u.roll_no,
                                   a.status, a.grading_status, a.submitted_at, a.total_score, a.max_score,
                                   CASE WHEN a.max_score>0 THEN ROUND(100*a.total_score/a.max_score,2) ELSE 0 END AS percentage
                            FROM attempts a JOIN users u ON u.id=a.candidate_id
                            WHERE a.exam_id=:e AND a.is_sandbox=0 AND a.status IN ('submitted','expired')
                            ORDER BY u.full_name, a.id""", e=exam_id)
    counts = _finished_attempt_counts(db, exam_id)
    return {
        "exam": {"id": exam["id"], "title": exam["title"], "eff_status": exam["eff_status"],
                 "results_published": bool(exam["results_published"])},
        "counts": counts,
        "attempts": attempts,
    }


@router.get("/attempts/{attempt_id}")
def attempt_for_grading(attempt_id: int, user: dict = Depends(staff), db: Session = Depends(get_db)):
    a = staff_attempt(db, attempt_id, user)
    if a["is_sandbox"]:
        raise HTTPException(404, "Sandbox attempts are not part of official grading.")
    candidate = q_one(db, "SELECT full_name, email, roll_no FROM users WHERE id=:u", u=a["candidate_id"])
    if a["status"] == "in_progress":
        raise HTTPException(409, "This candidate has not submitted the attempt yet.")

    rows = q_all(db, """SELECT aq.id AS aq_id, aq.question_id, aq.position, aq.question_type,
                               aq.marks, aq.negative_marks, aq.multi_scheme, aq.selected_options,
                               aq.written_answer, aq.is_answered, aq.marks_awarded, aq.is_graded,
                               aq.graded_by, aq.grader_comment, q.body, q.model_answer
                        FROM attempt_questions aq JOIN questions q ON q.id=aq.question_id
                        WHERE aq.attempt_id=:a ORDER BY aq.position""", a=attempt_id)
    opts = q_all(db, """SELECT o.id, o.question_id, o.option_text, o.is_correct, o.position
                        FROM question_options o
                        WHERE o.question_id IN (SELECT question_id FROM attempt_questions WHERE attempt_id=:a)
                        ORDER BY o.question_id, o.position, o.id""", a=attempt_id)
    by_question = {}
    for option in opts:
        by_question.setdefault(option["question_id"], []).append(option)

    import json
    questions = []
    for row in rows:
        selected = []
        try:
            selected = [int(x) for x in json.loads(row["selected_options"] or "[]")]
        except (ValueError, TypeError):
            pass
        questions.append({
            "aq_id": row["aq_id"], "question_id": row["question_id"], "position": row["position"],
            "type": row["question_type"], "body": row["body"], "marks": row["marks"],
            "negative_marks": row["negative_marks"], "multi_scheme": row["multi_scheme"],
            "selected": selected, "written_answer": row["written_answer"] or "",
            "is_answered": bool(row["is_answered"]), "marks_awarded": row["marks_awarded"],
            "is_graded": bool(row["is_graded"]), "graded_by": row["graded_by"],
            "grader_comment": row["grader_comment"] or "", "model_answer": row["model_answer"] or "",
            "options": [{"id": o["id"], "text": o["option_text"],
                         "is_correct": bool(o["is_correct"]),
                         "selected": o["id"] in selected}
                        for o in by_question.get(row["question_id"], [])],
        })

    return {
        "attempt_id": a["id"], "exam_id": a["exam_id"], "exam_title": a["title"],
        "candidate_id": a["candidate_id"], "candidate_name": candidate["full_name"],
        "candidate_email": candidate["email"], "candidate_roll_no": candidate["roll_no"],
        "status": a["status"], "grading_status": a["grading_status"],
        "results_published": bool(a.get("results_published")),
        "submitted_at": a["submitted_at"], "total_score": a["total_score"],
        "max_score": a["max_score"], "questions": questions,
    }


@router.put("/attempts/{attempt_id}/questions/{aq_id}")
def grade_written_response(attempt_id: int, aq_id: int, data: WrittenGradeIn,
                           user: dict = Depends(staff), db: Session = Depends(get_db)):
    """Save an examiner's written grade; objective questions are auto-graded and read-only."""
    a = staff_attempt(db, attempt_id, user)
    if a["is_sandbox"]:
        raise HTTPException(404, "Sandbox attempts cannot be graded.")
    publication = q_one(db, "SELECT results_published FROM exams WHERE id=:e FOR UPDATE", e=a["exam_id"])
    if publication and publication["results_published"]:
        raise HTTPException(409, "Published results are locked. Unpublishing is not supported.")
    if a["status"] == "in_progress":
        raise HTTPException(409, "You can grade an answer only after submission.")

    row = q_one(db, """SELECT aq.id, aq.question_type, aq.marks, aq.marks_awarded, aq.is_graded
                       FROM attempt_questions aq WHERE aq.id=:q AND aq.attempt_id=:a""",
                q=aq_id, a=attempt_id)
    if not row:
        raise HTTPException(404, "Question response not found.")
    if row["question_type"] != "written":
        raise HTTPException(409, "Objective responses are graded automatically and cannot be changed here.")
    if float(data.marks_awarded) > float(row["marks"]):
        raise HTTPException(422, f"Marks awarded cannot exceed the assigned {row['marks']} marks.")

    old = row["marks_awarded"] if row["is_graded"] else "pending"
    run(db, """UPDATE attempt_questions
               SET marks_awarded=:m, is_graded=1, graded_by=:u, grader_comment=:c
               WHERE id=:q AND attempt_id=:a""",
        m=round(float(data.marks_awarded), 2), u=user["id"],
        c=(data.grader_comment or "").strip() or None, q=aq_id, a=attempt_id)
    recompute_totals(db, attempt_id)
    audit(db, "attempt_question", aq_id, user["id"], "grade_written",
          old=old, new=round(float(data.marks_awarded), 2), note=data.grader_comment)
    db.commit()
    fresh = q_one(db, "SELECT total_score, max_score, grading_status FROM attempts WHERE id=:a", a=attempt_id)
    return {"ok": True, **fresh}


@router.get("/exams/{exam_id}/summary")
def exam_grading_summary(exam_id: int, user: dict = Depends(staff), db: Session = Depends(get_db)):
    """Exam-level performance summary calculated only from real submitted attempts."""
    exam = owned_exam(db, exam_id, user)
    rows = q_all(db, """SELECT a.id, a.total_score, a.max_score, a.grading_status,
                               CASE WHEN a.max_score>0 THEN 100*a.total_score/a.max_score ELSE 0 END AS pct
                        FROM attempts a WHERE a.exam_id=:e AND a.is_sandbox=0
                          AND a.status IN ('submitted','expired')""", e=exam_id)
    graded = [float(r["pct"]) for r in rows if r["grading_status"] == "graded"]
    return {
        "exam_id": exam_id, "title": exam["title"], "results_published": bool(exam["results_published"]),
        "submissions": len(rows), "graded": len(graded), "awaiting_grading": len(rows)-len(graded),
        "average_percentage": round(mean(graded), 2) if graded else None,
        "median_percentage": round(median(graded), 2) if graded else None,
        "standard_deviation": round(pstdev(graded), 2) if len(graded) > 1 else (0 if graded else None),
        "highest_percentage": round(max(graded), 2) if graded else None,
        "lowest_percentage": round(min(graded), 2) if graded else None,
        "candidate_scores": [
            {"attempt_id": r["id"], "score": r["total_score"], "out_of": r["max_score"],
             "percentage": round(float(r["pct"]), 2), "grading_status": r["grading_status"]}
            for r in rows
        ],
    }


@router.post("/exams/{exam_id}/publish-results")
def publish_results(exam_id: int, user: dict = Depends(staff), db: Session = Depends(get_db)):
    """Publish only after the exam window closes and every submitted attempt is fully graded."""
    exam = owned_exam(db, exam_id, user)
    if exam["results_published"]:
        raise HTTPException(409, "Results have already been published.")
    if exam["eff_status"] != "completed":
        raise HTTPException(409, "Results can be published only after the examination window has closed.")
    # Lock the exam and its real attempts so publication cannot race with a manual grade or finalisation.
    publication = q_one(db, "SELECT id, results_published FROM exams WHERE id=:e FOR UPDATE", e=exam_id)
    if not publication or publication["results_published"]:
        raise HTTPException(409, "Results have already been published.")
    locked_attempts = q_all(db, """SELECT id, status, grading_status FROM attempts
                                  WHERE exam_id=:e AND is_sandbox=0
                                    AND status IN ('submitted','expired','in_progress')
                                  FOR UPDATE""", e=exam_id)
    finished = [a for a in locked_attempts if a["status"] in ("submitted", "expired")]
    in_progress = sum(1 for a in locked_attempts if a["status"] == "in_progress")
    awaiting = sum(1 for a in finished if a["grading_status"] != "graded")
    if in_progress:
        raise HTTPException(409, "Some attempts are still in progress or awaiting automatic finalisation.")
    if not finished:
        raise HTTPException(409, "There are no submitted attempts to publish.")
    if awaiting:
        raise HTTPException(409, f"{awaiting} submitted attempt(s) still need written-response grading.")
    run(db, "UPDATE exams SET results_published=1 WHERE id=:e AND results_published=0", e=exam_id)
    audit(db, "exam", exam_id, user["id"], "publish_results",
          old="unpublished", new="published", note=f"{len(finished)} fully graded attempts")
    db.commit()
    return {"ok": True, "published": True, "submissions": len(finished)}
