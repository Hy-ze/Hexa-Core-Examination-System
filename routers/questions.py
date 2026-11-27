"""Question bank: categories, questions, options."""
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from security import require_roles
from utils import audit, q_all, q_one, run

router = APIRouter(prefix="/api", tags=["questions"])
staff = require_roles("examiner", "admin")


class OptionIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    is_correct: bool = False


class QuestionIn(BaseModel):
    category_id: Optional[int] = None
    question_type: Literal["mcq", "multi", "written"]
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    body: str = Field(min_length=5, max_length=5000)
    marks: float = Field(gt=0, le=100)
    negative_marks: float = Field(default=0, ge=0, le=100)
    multi_scheme: Literal["all_or_nothing", "partial"] = "partial"
    model_answer: Optional[str] = Field(default=None, max_length=5000)
    explanation: Optional[str] = Field(default=None, max_length=2000)
    options: List[OptionIn] = []


class CategoryIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)


def validate_question(d: QuestionIn):
    if d.negative_marks > d.marks:
        raise HTTPException(422, "Negative marks cannot be larger than the question's marks.")
    if d.question_type == "written":
        return
    texts = [o.text.strip().lower() for o in d.options]
    correct = sum(1 for o in d.options if o.is_correct)
    if len(d.options) < 2:
        raise HTTPException(422, "Add at least two answer options.")
    if len(d.options) > 8:
        raise HTTPException(422, "Use at most eight answer options.")
    if len(set(texts)) != len(texts):
        raise HTTPException(422, "Answer options must be different from each other.")
    if d.question_type == "mcq" and correct != 1:
        raise HTTPException(422, "A single-answer question needs exactly one correct option.")
    if d.question_type == "multi" and not (1 <= correct < len(d.options)):
        raise HTTPException(422, "A multiple-select question needs at least one correct option, and at least one wrong one.")


def _used_in_attempts(db, qid: int) -> bool:
    return q_one(db, "SELECT COUNT(*) AS n FROM attempt_questions WHERE question_id=:i", i=qid)["n"] > 0


def _own_or_admin(q: dict, user: dict):
    if user["role"] != "admin" and q["created_by"] != user["id"]:
        raise HTTPException(403, "Only the question's author or an administrator can change it.")


def _check_category(db, cid):
    if cid is not None and not q_one(db, "SELECT id FROM categories WHERE id=:i", i=cid):
        raise HTTPException(422, "That category does not exist.")


# ------------------------------------------------------------ categories
@router.get("/categories")
def categories(_: dict = Depends(staff), db: Session = Depends(get_db)):
    return q_all(db, """SELECT c.id, c.name, COUNT(q.id) AS question_count
                        FROM categories c LEFT JOIN questions q ON q.category_id=c.id AND q.is_active=1
                        GROUP BY c.id, c.name ORDER BY c.name""")


@router.post("/categories", status_code=201)
def add_category(data: CategoryIn, _: dict = Depends(staff), db: Session = Depends(get_db)):
    name = data.name.strip()
    if q_one(db, "SELECT id FROM categories WHERE name=:n", n=name):
        raise HTTPException(409, "This category already exists.")
    res = run(db, "INSERT INTO categories (name) VALUES (:n)", n=name)
    db.commit()
    return {"id": res.lastrowid, "name": name}


# ------------------------------------------------------------ questions
@router.get("/questions")
def list_questions(category_id: Optional[int] = None, difficulty: Optional[str] = None,
                   question_type: Optional[str] = None, q: Optional[str] = None,
                   _: dict = Depends(staff), db: Session = Depends(get_db)):
    sql = """SELECT q.id, q.body, q.question_type, q.difficulty, q.marks, q.negative_marks, q.category_id,
                    c.name AS category, q.created_by, u.full_name AS author,
                    q.times_presented, q.times_correct,
                    (SELECT COUNT(*) FROM exam_questions eq WHERE eq.question_id=q.id) AS exam_count
             FROM questions q
             LEFT JOIN categories c ON c.id=q.category_id
             JOIN users u ON u.id=q.created_by
             WHERE q.is_active=1"""
    p = {}
    if category_id:
        sql += " AND q.category_id=:c"; p["c"] = category_id
    if difficulty in ("easy", "medium", "hard"):
        sql += " AND q.difficulty=:d"; p["d"] = difficulty
    if question_type in ("mcq", "multi", "written"):
        sql += " AND q.question_type=:t"; p["t"] = question_type
    if q:
        sql += " AND q.body LIKE :q"; p["q"] = f"%{q.strip()}%"
    return q_all(db, sql + " ORDER BY q.id DESC", **p)


@router.get("/questions/{qid}")
def get_question(qid: int, _: dict = Depends(staff), db: Session = Depends(get_db)):
    q = q_one(db, "SELECT * FROM questions WHERE id=:i AND is_active=1", i=qid)
    if not q:
        raise HTTPException(404, "Question not found.")
    q["options"] = q_all(db, "SELECT id, option_text AS text, is_correct FROM question_options "
                             "WHERE question_id=:i ORDER BY position, id", i=qid)
    q["locked"] = _used_in_attempts(db, qid)
    return q


def _insert_options(db, qid: int, options: List[OptionIn]):
    for pos, o in enumerate(options, start=1):
        run(db, "INSERT INTO question_options (question_id, option_text, is_correct, position) "
                "VALUES (:q, :t, :c, :p)", q=qid, t=o.text.strip(), c=int(o.is_correct), p=pos)


@router.post("/questions", status_code=201)
def create_question(data: QuestionIn, user: dict = Depends(staff), db: Session = Depends(get_db)):
    validate_question(data)
    _check_category(db, data.category_id)
    res = run(db, """INSERT INTO questions (created_by, category_id, question_type, difficulty, body, marks,
                     negative_marks, multi_scheme, model_answer, explanation)
                     VALUES (:u, :c, :t, :d, :b, :m, :nm, :ms, :ma, :ex)""",
              u=user["id"], c=data.category_id, t=data.question_type, d=data.difficulty, b=data.body.strip(),
              m=data.marks, nm=data.negative_marks, ms=data.multi_scheme,
              ma=(data.model_answer or None), ex=(data.explanation or None))
    qid = res.lastrowid
    if data.question_type != "written":
        _insert_options(db, qid, data.options)
    db.commit()
    return {"id": qid}


@router.put("/questions/{qid}")
def update_question(qid: int, data: QuestionIn, user: dict = Depends(staff), db: Session = Depends(get_db)):
    existing = q_one(db, "SELECT * FROM questions WHERE id=:i AND is_active=1", i=qid)
    if not existing:
        raise HTTPException(404, "Question not found.")
    _own_or_admin(existing, user)
    validate_question(data)
    _check_category(db, data.category_id)

    old_opts = q_all(db, "SELECT option_text, is_correct FROM question_options WHERE question_id=:i ORDER BY position, id", i=qid)
    new_opts = [{"option_text": o.text.strip(), "is_correct": int(o.is_correct)} for o in data.options] \
        if data.question_type != "written" else []
    structure_changed = (data.question_type != existing["question_type"] or
                         [(o["option_text"], int(o["is_correct"])) for o in old_opts] !=
                         [(o["option_text"], o["is_correct"]) for o in new_opts] or
                         data.multi_scheme != existing["multi_scheme"])
    if structure_changed and _used_in_attempts(db, qid):
        raise HTTPException(409, "This question has already been attempted, so its type, options and "
                                 "marking scheme are locked to keep past results valid. Create a new question instead.")

    run(db, """UPDATE questions SET category_id=:c, question_type=:t, difficulty=:d, body=:b, marks=:m,
               negative_marks=:nm, multi_scheme=:ms, model_answer=:ma, explanation=:ex WHERE id=:i""",
        c=data.category_id, t=data.question_type, d=data.difficulty, b=data.body.strip(), m=data.marks,
        nm=data.negative_marks, ms=data.multi_scheme, ma=(data.model_answer or None),
        ex=(data.explanation or None), i=qid)
    if structure_changed:
        run(db, "DELETE FROM question_options WHERE question_id=:i", i=qid)
        if data.question_type != "written":
            _insert_options(db, qid, data.options)
    audit(db, "question", qid, user["id"], "edit")
    db.commit()
    return {"ok": True}


@router.delete("/questions/{qid}")
def delete_question(qid: int, user: dict = Depends(staff), db: Session = Depends(get_db)):
    existing = q_one(db, "SELECT * FROM questions WHERE id=:i AND is_active=1", i=qid)
    if not existing:
        raise HTTPException(404, "Question not found.")
    _own_or_admin(existing, user)
    if q_one(db, "SELECT COUNT(*) AS n FROM exam_questions WHERE question_id=:i", i=qid)["n"] > 0:
        raise HTTPException(409, "This question is part of an exam. Remove it from those exams first.")
    if _used_in_attempts(db, qid):
        run(db, "UPDATE questions SET is_active=0 WHERE id=:i", i=qid)   # keep history intact
    else:
        run(db, "DELETE FROM questions WHERE id=:i", i=qid)
    audit(db, "question", qid, user["id"], "delete")
    db.commit()
    return {"ok": True}
