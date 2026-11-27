"""Bulk CSV/JSON imports for questions, candidates and exam enrollment."""
import secrets
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session
from access import owned_exam
from database import get_db
from import_core import MAX_CONTENT_CHARS, norm_text, parse_people, parse_questions
from routers.auth import EMAIL_RE
from routers.questions import OptionIn, QuestionIn, validate_question
from security import hash_password, require_roles
from utils import audit, q_all, run

router = APIRouter(prefix="/api/imports", tags=["imports"])
staff = require_roles("examiner", "admin")
admin_only = require_roles("admin")
MAX_QUESTION_ROWS, MAX_CANDIDATE_ROWS, MAX_ENROLL_ROWS, MAX_ERRORS_SHOWN = 500, 120, 1000, 200
PASSWORD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
FIELD_LABEL = {"body": "Question text", "marks": "Marks", "negative_marks": "Negative marks",
               "difficulty": "Difficulty", "question_type": "Type", "multi_scheme": "Scheme",
               "model_answer": "Model answer", "explanation": "Explanation", "options": "Options"}


class ImportIn(BaseModel):
    format: Literal["csv", "json"]
    content: str = Field(min_length=1, max_length=MAX_CONTENT_CHARS)
    commit: bool = False


def _pydantic_message(e: ValidationError) -> str:
    parts = []
    for err in e.errors():
        loc = [str(x) for x in err.get("loc", ())]
        label = FIELD_LABEL.get(loc[0], loc[0]) if loc else "Row"
        parts.append(f"{label}: {err.get('msg', 'invalid value')}")
    return "; ".join(parts)


def _parse_or_422(fn, *args):
    try:
        return fn(*args)
    except ValueError as e:
        raise HTTPException(422, str(e))


def _report(kind: str, total: int, valid_count: int, errors: list, preview: list,
            committed: bool, **extra) -> dict:
    errors = sorted(errors, key=lambda x: (x["row"], x["message"]))
    return {"kind": kind, "total": total, "valid": valid_count, "invalid": len(errors),
            "errors": errors[:MAX_ERRORS_SHOWN], "errors_truncated": len(errors) > MAX_ERRORS_SHOWN,
            "preview": preview[:8], "committed": committed, **extra}


@router.post("/questions")
def import_questions(data: ImportIn, user: dict = Depends(staff), db: Session = Depends(get_db)):
    parsed, errors = _parse_or_422(parse_questions, data.format, data.content)
    total = len(parsed) + len(errors)
    if total > MAX_QUESTION_ROWS:
        raise HTTPException(422, f"This file has {total} rows. Import at most {MAX_QUESTION_ROWS} questions at a time.")
    if total == 0:
        raise HTTPException(422, "The file has a header but no questions.")
    existing = {norm_text(r["body"]): r["id"] for r in q_all(db, "SELECT id, body FROM questions WHERE is_active=1")}
    cats = {r["name"].strip().lower(): r["id"] for r in q_all(db, "SELECT id, name FROM categories")}
    seen, valid, new_cats = {}, [], {}
    for row_no, q in parsed:
        try:
            cat_name = q.pop("category", None)
            if cat_name and len(cat_name) > 100:
                raise ValueError("The category name is longer than 100 characters.")
            model = QuestionIn(category_id=None, options=[OptionIn(**o) for o in q["options"]],
                               **{k: v for k, v in q.items() if k != "options"})
            validate_question(model)
            key = norm_text(model.body)
            if key in existing:
                raise ValueError(f"This question is already in the bank (question #{existing[key]}).")
            if key in seen:
                raise ValueError(f"Same question text as row {seen[key]} of this file.")
        except ValidationError as e:
            errors.append({"row": row_no, "message": _pydantic_message(e)})
            continue
        except HTTPException as e:
            errors.append({"row": row_no, "message": str(e.detail)})
            continue
        except ValueError as e:
            errors.append({"row": row_no, "message": str(e)})
            continue
        seen[key] = row_no
        if cat_name and cat_name.lower() not in cats:
            new_cats.setdefault(cat_name.lower(), cat_name)
        valid.append((row_no, model, cat_name))

    created = 0
    if data.commit and valid:
        try:
            for low, name in new_cats.items():
                cats[low] = run(db, "INSERT INTO categories (name) VALUES (:n)", n=name).lastrowid
            for _row_no, model, cat_name in valid:
                cid = cats.get(cat_name.lower()) if cat_name else None
                res = run(db, """INSERT INTO questions (created_by, category_id, question_type, difficulty, body, marks,
                                 negative_marks, multi_scheme, model_answer, explanation)
                                 VALUES (:u,:c,:t,:d,:b,:m,:nm,:ms,:ma,:ex)""",
                          u=user["id"], c=cid, t=model.question_type, d=model.difficulty, b=model.body.strip(),
                          m=model.marks, nm=model.negative_marks, ms=model.multi_scheme,
                          ma=model.model_answer or None, ex=model.explanation or None)
                for pos, option in enumerate(model.options, start=1):
                    run(db, "INSERT INTO question_options (question_id, option_text, is_correct, position) VALUES (:q,:t,:c,:p)",
                        q=res.lastrowid, t=option.text.strip(), c=int(option.is_correct), p=pos)
                created += 1
            audit(db, "import", user["id"], user["id"], "import_questions", new=created)
            db.commit()
        except Exception:
            db.rollback()
            raise
    preview = [{"row": row, "type": model.question_type, "difficulty": model.difficulty,
                "category": cat, "body": model.body[:110], "marks": model.marks,
                "options": len(model.options)} for row, model, cat in valid]
    return _report("questions", total, len(valid), errors, preview, data.commit and bool(valid),
                   created=created, new_categories=sorted(new_cats.values()))


@router.post("/candidates")
def import_candidates(data: ImportIn, admin: dict = Depends(admin_only), db: Session = Depends(get_db)):
    parsed, errors = _parse_or_422(parse_people, data.format, data.content, ("full_name", "email"))
    total = len(parsed) + len(errors)
    if total > MAX_CANDIDATE_ROWS:
        raise HTTPException(422, f"This file has {total} rows. Import at most {MAX_CANDIDATE_ROWS} candidates at a time.")
    if total == 0:
        raise HTTPException(422, "The file has a header but no candidates.")
    emails = {r["email"].strip().lower() for r in q_all(db, "SELECT email FROM users")}
    rolls = {r["roll_no"].strip().lower(): r["full_name"] for r in
             q_all(db, "SELECT roll_no, full_name FROM users WHERE roll_no IS NOT NULL AND roll_no<>''")}
    seen_email, seen_roll, valid = {}, {}, []
    for row_no, rec in parsed:
        name, email = (rec.get("full_name") or "").strip(), (rec.get("email") or "").strip().lower()
        roll, pw = (rec.get("roll_no") or "").strip(), (rec.get("password") or "")
        problem = None
        if len(name) < 2 or len(name) > 120:
            problem = "The name must be 2 to 120 characters."
        elif not email or not EMAIL_RE.match(email) or len(email) > 190:
            problem = "The email address is missing or not valid."
        elif email in emails:
            problem = "An account with this email already exists."
        elif email in seen_email:
            problem = f"Same email as row {seen_email[email]} of this file."
        elif len(roll) > 40:
            problem = "The roll number is longer than 40 characters."
        elif roll and roll.lower() in rolls:
            problem = f"This roll number already belongs to {rolls[roll.lower()]}."
        elif roll and roll.lower() in seen_roll:
            problem = f"Same roll number as row {seen_roll[roll.lower()]} of this file."
        elif pw and not (8 <= len(pw) <= 100):
            problem = "A password must be 8 to 100 characters (or leave it blank to generate one)."
        if problem:
            errors.append({"row": row_no, "message": problem})
            continue
        seen_email[email] = row_no
        if roll:
            seen_roll[roll.lower()] = row_no
        valid.append((row_no, name, email, roll or None, pw or None))

    created, credentials = 0, []
    if data.commit and valid:
        try:
            for _row_no, name, email, roll, pw in valid:
                generated = pw is None
                password = pw or "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(10))
                res = run(db, """INSERT INTO users (full_name, email, password_hash, role, roll_no, is_active)
                                 VALUES (:n,:e,:h,'candidate',:r,1)""",
                          n=name, e=email, h=hash_password(password), r=roll)
                audit(db, "user", res.lastrowid, admin["id"], "create", new="candidate (import)")
                if generated:
                    credentials.append({"full_name": name, "email": email, "roll_no": roll or "", "password": password})
                created += 1
            db.commit()
        except Exception:
            db.rollback()
            raise
    preview = [{"row": row, "full_name": name, "email": email, "roll_no": roll,
                "password": "provided" if pw else "will be generated"}
               for row, name, email, roll, pw in valid]
    return _report("candidates", total, len(valid), errors, preview, data.commit and bool(valid),
                   created=created, credentials=credentials)


@router.post("/exams/{exam_id}/candidates")
def import_enrollments(exam_id: int, data: ImportIn, user: dict = Depends(staff), db: Session = Depends(get_db)):
    exam = owned_exam(db, exam_id, user)
    if exam["eff_status"] == "completed":
        raise HTTPException(409, "This exam has finished; enrollment is closed.")
    parsed, errors = _parse_or_422(parse_people, data.format, data.content, ("email", "roll_no"))
    total = len(parsed) + len(errors)
    if total > MAX_ENROLL_ROWS:
        raise HTTPException(422, f"This file has {total} rows. Import at most {MAX_ENROLL_ROWS} at a time.")
    if total == 0:
        raise HTTPException(422, "The file has a header but no rows.")
    by_email, by_roll = {}, {}
    for candidate in q_all(db, "SELECT id, full_name, email, roll_no FROM users WHERE role='candidate' AND is_active=1"):
        by_email[candidate["email"].strip().lower()] = candidate
        if candidate["roll_no"]:
            by_roll.setdefault(candidate["roll_no"].strip().lower(), []).append(candidate)
    enrolled = {r["candidate_id"] for r in q_all(db, "SELECT candidate_id FROM exam_enrollments WHERE exam_id=:e", e=exam_id)}
    picked, valid, already = {}, [], 0
    for row_no, rec in parsed:
        email, roll = (rec.get("email") or "").strip().lower(), (rec.get("roll_no") or "").strip().lower()
        if not email and not roll:
            errors.append({"row": row_no, "message": "Give an email or a roll number for this candidate."})
            continue
        cand = by_email.get(email) if email else None
        if email and not cand:
            errors.append({"row": row_no, "message": f"No active candidate account has the email '{email}'. Ask an administrator to add the account first."})
            continue
        if not cand:
            matches = by_roll.get(roll, [])
            if not matches:
                errors.append({"row": row_no, "message": f"No active candidate has the roll number '{rec.get('roll_no')}'."})
                continue
            if len(matches) > 1:
                errors.append({"row": row_no, "message": "More than one candidate has this roll number. Use the email address instead."})
                continue
            cand = matches[0]
        elif roll and (cand["roll_no"] or "").strip().lower() != roll:
            errors.append({"row": row_no, "message": "The email and the roll number belong to different candidates."})
            continue
        if cand["id"] in enrolled:
            already += 1
            continue
        if cand["id"] in picked:
            errors.append({"row": row_no, "message": f"{cand['full_name']} is already listed in row {picked[cand['id']]}."})
            continue
        picked[cand["id"]] = row_no
        valid.append((row_no, cand))

    created = 0
    if data.commit and valid:
        try:
            for _row_no, cand in valid:
                run(db, "INSERT INTO exam_enrollments (exam_id, candidate_id) VALUES (:e,:c)", e=exam_id, c=cand["id"])
                created += 1
            audit(db, "exam", exam_id, user["id"], "enroll", new=created, note="bulk import")
            db.commit()
        except Exception:
            db.rollback()
            raise
    preview = [{"row": row, "full_name": cand["full_name"], "email": cand["email"], "roll_no": cand["roll_no"]}
               for row, cand in valid]
    return _report("enrollments", total, len(valid), errors, preview, data.commit and bool(valid),
                   created=created, already_enrolled=already)
