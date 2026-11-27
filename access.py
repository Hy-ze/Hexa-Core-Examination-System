"""Object-level access checks shared by routers."""
from fastapi import HTTPException

from utils import STATUS_SQL, q_one


def owned_exam(db, exam_id: int, user: dict) -> dict:
    """Return the exam if the user is its examiner (or an admin); otherwise 404/403."""
    exam = q_one(db, f"SELECT e.*, {STATUS_SQL} AS eff_status FROM exams e WHERE e.id=:i", i=exam_id)
    if not exam:
        raise HTTPException(404, "Exam not found.")
    if user["role"] != "admin" and exam["created_by"] != user["id"]:
        raise HTTPException(403, "This exam belongs to another examiner.")
    return exam


def has_real_attempts(db, exam_id: int) -> bool:
    row = q_one(db, "SELECT COUNT(*) AS n FROM attempts WHERE exam_id=:i AND is_sandbox=0", i=exam_id)
    return row["n"] > 0


def check_editable(db, exam: dict):
    """An exam can change only while nobody has started it."""
    if exam["eff_status"] in ("ongoing", "completed") or has_real_attempts(db, exam["id"]):
        raise HTTPException(409, "This exam has started, so its setup is locked.")
