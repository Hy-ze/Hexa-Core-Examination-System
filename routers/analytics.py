"""Question analytics for one exam, excluding sandbox previews."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from access import owned_exam
from analytics_core import compute
from database import get_db
from security import require_roles
from utils import q_all

router = APIRouter(prefix="/api/exams/{exam_id}/analytics", tags=["analytics"])
staff = require_roles("examiner", "admin")
FINISHED_REAL = "a.exam_id=:e AND a.is_sandbox=0 AND a.status<>'in_progress'"


def question_analytics(db, exam_id: int) -> dict:
    """Shared with the PDF exam report so screen and PDF always agree."""
    rows = q_all(db, f"""SELECT aq.attempt_id, aq.question_id, aq.question_type, aq.marks,
                                aq.marks_awarded, aq.is_graded, aq.is_answered,
                                aq.selected_options, a.total_score, a.max_score
                         FROM attempt_questions aq JOIN attempts a ON a.id=aq.attempt_id
                         WHERE {FINISHED_REAL}""", e=exam_id)
    questions = q_all(db, """SELECT q.id, q.body, q.question_type, q.difficulty, c.name AS category
                             FROM questions q LEFT JOIN categories c ON c.id=q.category_id
                             WHERE q.id IN (SELECT question_id FROM exam_questions WHERE exam_id=:e)
                                OR q.id IN (SELECT aq.question_id FROM attempt_questions aq
                                            JOIN attempts a ON a.id=aq.attempt_id WHERE a.exam_id=:e)""", e=exam_id)
    options = q_all(db, """SELECT o.question_id, o.id, o.option_text, o.is_correct, o.position
                           FROM question_options o
                           WHERE o.question_id IN (SELECT question_id FROM exam_questions WHERE exam_id=:e)
                              OR o.question_id IN (SELECT aq.question_id FROM attempt_questions aq
                                                   JOIN attempts a ON a.id=aq.attempt_id WHERE a.exam_id=:e)""", e=exam_id)
    order = [r["question_id"] for r in q_all(
        db, "SELECT question_id FROM exam_questions WHERE exam_id=:e ORDER BY position, question_id", e=exam_id
    )]
    result = compute(rows, questions, options, order)
    result["attempts_counted"] = q_all(
        db, f"SELECT COUNT(*) AS n FROM attempts a WHERE {FINISHED_REAL}", e=exam_id
    )[0]["n"]
    return result


@router.get("/questions")
def exam_question_analytics(exam_id: int, user: dict = Depends(staff), db: Session = Depends(get_db)):
    exam = owned_exam(db, exam_id, user)
    result = question_analytics(db, exam_id)
    result["exam"] = {"id": exam["id"], "title": exam["title"], "randomized": bool(exam["paper_size"])}
    return result
