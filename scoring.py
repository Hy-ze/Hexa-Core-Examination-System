"""Automatic grading of objective questions and consistent total calculation."""
import json

from utils import q_all, q_one, run


def _ids(raw) -> set:
    try:
        return {int(x) for x in json.loads(raw or "[]")}
    except (ValueError, TypeError):
        return set()


def score_objective(qtype: str, marks: float, negative: float, scheme: str, correct: set, selected: set) -> float:
    """Single answer: all or nothing. Multiple select: all_or_nothing, or proportional credit
    where every wrong pick cancels one right pick. A wrong answer costs `negative` marks."""
    if not selected or not correct:
        return 0.0
    if qtype == "mcq" or scheme == "all_or_nothing":
        return marks if selected == correct else -negative
    fraction = (len(selected & correct) - len(selected - correct)) / len(correct)
    return round(marks * fraction, 2) if fraction > 0 else -negative


def autograde_attempt(db, attempt_id: int):
    """Grade every ungraded objective answer. Blank written answers get 0; other written
    answers stay pending for the examiner. Already graded rows are never touched."""
    rows = q_all(db, """SELECT id, question_id, question_type, marks, negative_marks, multi_scheme,
                               selected_options, written_answer
                        FROM attempt_questions WHERE attempt_id=:a AND is_graded=0""", a=attempt_id)
    correct: dict = {}
    for o in q_all(db, """SELECT question_id, id, is_correct FROM question_options
                          WHERE question_id IN (SELECT question_id FROM attempt_questions WHERE attempt_id=:a)""", a=attempt_id):
        if o["is_correct"]:
            correct.setdefault(o["question_id"], set()).add(o["id"])
    for r in rows:
        if r["question_type"] == "written":
            if (r["written_answer"] or "").strip():
                continue
            award = 0.0
        else:
            award = score_objective(r["question_type"], float(r["marks"]), float(r["negative_marks"]),
                                    r["multi_scheme"], correct.get(r["question_id"], set()), _ids(r["selected_options"]))
        run(db, "UPDATE attempt_questions SET marks_awarded=:m, is_graded=1, graded_by=NULL WHERE id=:i", m=award, i=r["id"])
    recompute_totals(db, attempt_id)


def recompute_totals(db, attempt_id: int):
    """One place that decides an attempt's score and grading state (never below zero)."""
    t = q_one(db, """SELECT COALESCE(SUM(CASE WHEN is_graded=1 THEN marks_awarded ELSE 0 END),0) AS s,
                            COALESCE(SUM(marks),0) AS m, COUNT(*) AS n, COALESCE(SUM(is_graded),0) AS g
                     FROM attempt_questions WHERE attempt_id=:a""", a=attempt_id)
    state = "graded" if t["n"] and t["g"] == t["n"] else ("partial" if t["g"] else "pending")
    run(db, "UPDATE attempts SET total_score=:s, max_score=:m, grading_status=:g WHERE id=:a",
        s=max(0, round(t["s"], 2)), m=t["m"], g=state, a=attempt_id)
