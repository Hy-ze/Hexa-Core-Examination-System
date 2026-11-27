"""5.2 Fairness of randomized papers: shows examiners how balanced the papers really are."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from access import owned_exam
from database import get_db
from paper_builder import MIN_OBSERVATIONS, effective_difficulty, simulate
from security import require_roles
from utils import q_all

router = APIRouter(prefix="/api/exams/{exam_id}/fairness", tags=["fairness"])
staff = require_roles("examiner", "admin")


def _pool(db, exam_id: int):
    return q_all(db, """SELECT eq.question_id, eq.marks, eq.position, q.body, q.question_type, q.difficulty,
                               q.times_presented, q.times_correct
                        FROM exam_questions eq JOIN questions q ON q.id=eq.question_id
                        WHERE eq.exam_id=:e ORDER BY eq.position, eq.question_id""", e=exam_id)


@router.get("")
def fairness(exam_id: int, user: dict = Depends(staff), db: Session = Depends(get_db)):
    exam = owned_exam(db, exam_id, user)
    pool = _pool(db, exam_id)
    questions = []
    for q in pool:
        shown = q["times_presented"] or 0
        questions.append({"question_id": q["question_id"], "body": q["body"][:110], "type": q["question_type"],
                          "label": q["difficulty"], "marks": q["marks"], "presented": shown,
                          "correct_rate": round(q["times_correct"] / shown, 2) if shown and q["question_type"] != "written" else None,
                          "effective": effective_difficulty(q), "uses_observed": shown >= MIN_OBSERVATIONS and q["question_type"] != "written"})
    papers = q_all(db, """SELECT a.id AS attempt_id, u.full_name, a.paper_difficulty, a.max_score, a.status
                          FROM attempts a JOIN users u ON u.id=a.candidate_id
                          WHERE a.exam_id=:e AND a.is_sandbox=0 ORDER BY a.id""", e=exam_id)
    return {"randomized": bool(exam["paper_size"]), "paper_size": exam["paper_size"], "pool_size": len(pool),
            "target_marks": exam["total_marks"], "balance_on": bool(exam["balance_difficulty"]),
            "questions": questions, "papers": papers}


@router.get("/simulate")
def simulate_papers(exam_id: int, count: int = Query(30, ge=5, le=100), user: dict = Depends(staff), db: Session = Depends(get_db)):
    exam = owned_exam(db, exam_id, user)
    pool = _pool(db, exam_id)
    n = exam["paper_size"]
    if not n or len(pool) <= n:
        raise HTTPException(409, "Papers only differ when each candidate gets fewer questions than the pool holds.")
    return {"count": count, "balanced": simulate(pool, n, float(exam["total_marks"]), count, True),
            "random": simulate(pool, n, float(exam["total_marks"]), count, False)}
