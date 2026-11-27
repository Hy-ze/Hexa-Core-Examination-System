"""Candidate result access. A candidate can retrieve only their own published result."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from security import require_roles
from utils import q_all, q_one

router = APIRouter(prefix="/api/results", tags=["results"])
candidate = require_roles("candidate")


@router.get("/mine")
def my_results(user: dict = Depends(candidate), db: Session = Depends(get_db)):
    return q_all(db, """SELECT a.id AS attempt_id, e.id AS exam_id, e.title, a.submitted_at,
                               a.total_score, a.max_score, a.grading_status,
                               CASE WHEN a.max_score>0 THEN ROUND(100*a.total_score/a.max_score,2) ELSE 0 END AS percentage
                        FROM attempts a JOIN exams e ON e.id=a.exam_id
                        WHERE a.candidate_id=:u AND a.is_sandbox=0
                          AND a.status IN ('submitted','expired') AND e.results_published=1
                        ORDER BY a.submitted_at DESC""", u=user["id"])


@router.get("/{attempt_id}")
def my_result(attempt_id: int, user: dict = Depends(candidate), db: Session = Depends(get_db)):
    attempt = q_one(db, """SELECT a.id, a.exam_id, a.candidate_id, a.status, a.submitted_at,
                                  a.total_score, a.max_score, a.grading_status, e.title,
                                  e.results_published
                           FROM attempts a JOIN exams e ON e.id=a.exam_id WHERE a.id=:a""", a=attempt_id)
    # Return 404 for both another candidate's result and an unpublished result.
    if not attempt or attempt["candidate_id"] != user["id"] or not attempt["results_published"] or attempt["status"] == "in_progress":
        raise HTTPException(404, "Published result not found.")
    questions = q_all(db, """SELECT aq.position, aq.question_type, aq.marks, aq.marks_awarded,
                                    aq.is_graded, aq.grader_comment, q.body
                             FROM attempt_questions aq JOIN questions q ON q.id=aq.question_id
                             WHERE aq.attempt_id=:a ORDER BY aq.position""", a=attempt_id)
    return {
        "attempt_id": attempt["id"], "exam_id": attempt["exam_id"], "title": attempt["title"],
        "submitted_at": attempt["submitted_at"], "total_score": attempt["total_score"],
        "max_score": attempt["max_score"],
        "percentage": round(100*float(attempt["total_score"] or 0)/float(attempt["max_score"]), 2)
                      if float(attempt["max_score"] or 0) > 0 else 0,
        "grading_status": attempt["grading_status"],
        "questions": [{
            "position": q["position"], "type": q["question_type"], "body": q["body"],
            "marks": q["marks"], "marks_awarded": q["marks_awarded"],
            "is_graded": bool(q["is_graded"]), "grader_comment": q["grader_comment"] or ""
        } for q in questions],
    }
