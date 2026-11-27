"""The exam room API: start/resume, load state, autosave, heartbeat, submit, scratchpad, events.

Everything about time is decided here on the server (see attempt_core). The browser only displays
the seconds-remaining value it is given."""
import json
import random
import time
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from access import owned_exam
from attempt_core import GRACE_SECONDS, finalize_attempt, get_attempt
from database import get_db
from integrity_rules import post_process
from paper_builder import build_paper
from scoring import recompute_totals
from security import current_user
from utils import ACCESS_SQL, STATUS_SQL, parse_client_dt, q_all, q_one, run

router = APIRouter(prefix="/api/attempts", tags=["attempts"])

EVENT_TYPES = {"tab_hidden", "tab_visible", "window_blur", "paste", "copy", "offline", "online"}
ALWAYS_RECORDED = {"offline", "online"}          # technical incidents help candidates in disputes
MAX_EVENTS_PER_ATTEMPT = 400


class StartIn(BaseModel):
    exam_id: int
    sandbox: bool = False


class SaveItem(BaseModel):
    aq_id: int
    version: int = Field(ge=1, le=10_000_000)
    selected: List[int] = Field(default=[], max_length=10)
    written: str = Field(default="", max_length=20000)
    marked: bool = False


class SaveIn(BaseModel):
    items: List[SaveItem] = Field(default=[], max_length=60)


class PadIn(BaseModel):
    content: str = Field(max_length=30000)


class EventIn(BaseModel):
    type: str
    detail: Optional[str] = Field(default=None, max_length=300)


class EventsIn(BaseModel):
    events: List[EventIn] = Field(max_length=50)


# ---------------------------------------------------------------- helpers
def _remaining(db, attempt_id: int) -> int:
    return q_one(db, "SELECT TIMESTAMPDIFF(SECOND, UTC_TIMESTAMP(), deadline_at) AS r FROM attempts WHERE id=:i", i=attempt_id)["r"]


def _close_if_overdue(db, a: dict, bg: BackgroundTasks) -> dict:
    """If the deadline (plus grace) has passed, finalise now and return the fresh attempt row."""
    if a["status"] == "in_progress" and a["remaining"] < -GRACE_SECONDS:
        if finalize_attempt(db, a["id"], expired=True) and not a["is_sandbox"]:
            bg.add_task(post_process, a["id"])
        return None
    return a


def _open_attempt(db, attempt_id: int, user: dict, bg: BackgroundTasks) -> dict:
    a = get_attempt(db, attempt_id, user)
    if _close_if_overdue(db, a, bg) is None:
        raise HTTPException(409, "Time is up. Your answers were submitted automatically.")
    if a["status"] != "in_progress":
        raise HTTPException(409, "This attempt has already been submitted.")
    return a


def _apply_items(db, attempt_id: int, items: List[SaveItem]) -> list:
    """Save a batch of answers. Each item carries the question's full state and a version number:
    a save only wins if its version is newer, so late or repeated requests cannot overwrite newer answers."""
    if not items:
        return []
    rows = {r["id"]: r for r in q_all(db, """SELECT id, question_id, question_type FROM attempt_questions
                                            WHERE attempt_id=:a""", a=attempt_id)}
    options: dict = {}
    for o in q_all(db, """SELECT question_id, id FROM question_options WHERE question_id IN
                          (SELECT question_id FROM attempt_questions WHERE attempt_id=:a)""", a=attempt_id):
        options.setdefault(o["question_id"], set()).add(o["id"])
    results = []
    for it in items:
        row = rows.get(it.aq_id)
        if not row:
            results.append({"aq_id": it.aq_id, "saved": False, "error": "unknown question"})
            continue
        if row["question_type"] == "written":
            selected, written = [], it.written
        else:
            selected, written = list(dict.fromkeys(it.selected)), None
            if not set(selected) <= options.get(row["question_id"], set()) or (row["question_type"] == "mcq" and len(selected) > 1):
                results.append({"aq_id": it.aq_id, "saved": False, "error": "invalid selection"})
                continue
        answered = bool(selected) or bool((written or "").strip())
        res = run(db, """UPDATE attempt_questions SET selected_options=:s, written_answer=:w, marked_for_review=:m,
                         is_answered=:a, answer_version=:v, saved_at=UTC_TIMESTAMP()
                         WHERE id=:i AND attempt_id=:att AND answer_version<:v""",
                  s=json.dumps(selected) if selected else None, w=written, m=int(it.marked), a=int(answered),
                  v=it.version, i=it.aq_id, att=attempt_id)
        results.append({"aq_id": it.aq_id, "saved": res.rowcount > 0, "stale": res.rowcount == 0})
    return results


def _announcements(db, exam_id: int, since: int = 0) -> list:
    return q_all(db, """SELECT n.id, n.message, n.created_at, u.full_name AS author FROM announcements n
                        JOIN users u ON u.id=n.author_id WHERE n.exam_id=:e AND n.id>:s ORDER BY n.id""", e=exam_id, s=since)


# ---------------------------------------------------------------- start / resume
@router.post("/start")
def start(data: StartIn, bg: BackgroundTasks, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    sandbox = data.sandbox
    if sandbox:
        if user["role"] not in ("examiner", "admin"):
            raise HTTPException(403, "Only examiners can preview an exam.")
        exam = owned_exam(db, data.exam_id, user)
        old = q_one(db, """SELECT id, TIMESTAMPDIFF(SECOND, UTC_TIMESTAMP(), deadline_at) AS r FROM attempts
                           WHERE exam_id=:e AND candidate_id=:u AND is_sandbox=1 AND status='in_progress' ORDER BY id DESC LIMIT 1""",
                    e=data.exam_id, u=user["id"])
        if old and old["r"] > 0:
            return {"attempt_id": old["id"], "resumed": True}
        if old:
            finalize_attempt(db, old["id"], expired=True)
    else:
        if user["role"] != "candidate":
            raise HTTPException(403, "Only candidates can take an exam.")
        exam = q_one(db, f"SELECT e.*, {STATUS_SQL} AS eff_status, {ACCESS_SQL} AS access FROM exams e WHERE e.id=:i", i=data.exam_id)
        if not exam or exam["status"] == "draft":
            raise HTTPException(404, "This exam is not available.")
        if not q_one(db, "SELECT id FROM exam_enrollments WHERE exam_id=:e AND candidate_id=:c", e=data.exam_id, c=user["id"]):
            raise HTTPException(403, "You are not enrolled in this exam.")
        if exam["access"] == "upcoming":
            raise HTTPException(403, "This exam has not opened yet.")
        if exam["access"] == "closed":
            raise HTTPException(403, "The exam window has closed.")
        old = q_one(db, """SELECT id, status, TIMESTAMPDIFF(SECOND, UTC_TIMESTAMP(), deadline_at) AS r FROM attempts
                           WHERE exam_id=:e AND candidate_id=:c AND is_sandbox=0""", e=data.exam_id, c=user["id"])
        if old:
            if old["status"] == "in_progress" and old["r"] >= -GRACE_SECONDS:
                return {"attempt_id": old["id"], "resumed": True}
            if old["status"] == "in_progress" and finalize_attempt(db, old["id"], expired=True):
                bg.add_task(post_process, old["id"])
            raise HTTPException(409, "You have already taken this exam. Only one attempt is allowed.")

    pool = q_all(db, """SELECT eq.question_id, eq.marks, eq.position, q.question_type, q.difficulty, q.negative_marks,
                               q.multi_scheme, q.times_presented, q.times_correct
                        FROM exam_questions eq JOIN questions q ON q.id=eq.question_id
                        WHERE eq.exam_id=:e ORDER BY eq.position, eq.question_id""", e=data.exam_id)
    if not pool:
        raise HTTPException(409, "This exam has no questions yet.")
    used = set()
    if not sandbox and exam["paper_size"]:
        by_att: dict = {}
        for r in q_all(db, """SELECT aq.attempt_id, aq.question_id FROM attempt_questions aq JOIN attempts a ON a.id=aq.attempt_id
                              WHERE a.exam_id=:e AND a.is_sandbox=0""", e=data.exam_id):
            by_att.setdefault(r["attempt_id"], set()).add(r["question_id"])
        used = {frozenset(v) for v in by_att.values()}
    paper, index, _method = build_paper(pool, exam["paper_size"], float(exam["total_marks"]),
                                        balance=bool(exam["balance_difficulty"]), shuffle=bool(exam["randomize_questions"]), used=used)
    max_score = sum(float(p["marks"]) for p in paper)
    end_bound = parse_client_dt("2999-01-01T00:00:00Z") if sandbox else parse_client_dt(exam["end_time"])
    try:
        res = run(db, """INSERT INTO attempts (exam_id, candidate_id, is_sandbox, sandbox_seq, status, started_at, deadline_at,
                                               max_score, paper_difficulty, last_heartbeat_at)
                         VALUES (:e,:c,:sb,:seq,'in_progress', UTC_TIMESTAMP(),
                                 LEAST(DATE_ADD(UTC_TIMESTAMP(), INTERVAL :d MINUTE), :end), :ms, :pd, UTC_TIMESTAMP())""",
                  e=data.exam_id, c=user["id"], sb=int(sandbox), seq=int(time.time() * 1000) if sandbox else 0,
                  d=exam["duration_minutes"], end=end_bound, ms=max_score, pd=index)
    except IntegrityError:               # the database itself refuses a second real attempt
        db.rollback()
        again = q_one(db, "SELECT id FROM attempts WHERE exam_id=:e AND candidate_id=:c AND is_sandbox=0", e=data.exam_id, c=user["id"])
        if again:
            return {"attempt_id": again["id"], "resumed": True}
        raise HTTPException(409, "Could not start the exam. Please try again.")
    att_id = res.lastrowid
    opts: dict = {}
    for o in q_all(db, """SELECT o.id, o.question_id FROM question_options o
                          JOIN exam_questions eq ON eq.question_id=o.question_id WHERE eq.exam_id=:e
                          ORDER BY o.position, o.id""", e=data.exam_id):
        opts.setdefault(o["question_id"], []).append(o["id"])
    for pos, q in enumerate(paper, start=1):
        order = None
        if q["question_type"] != "written":
            order = list(opts.get(q["question_id"], []))
            if exam["randomize_options"]:
                random.shuffle(order)
        run(db, """INSERT INTO attempt_questions (attempt_id, question_id, position, question_type, marks, negative_marks,
                                                  multi_scheme, option_order)
                   VALUES (:a,:q,:p,:t,:m,:n,:s,:o)""",
            a=att_id, q=q["question_id"], p=pos, t=q["question_type"], m=q["marks"], n=q["negative_marks"],
            s=q["multi_scheme"], o=json.dumps(order) if order is not None else None)
    db.commit()
    return {"attempt_id": att_id, "resumed": False}


# ---------------------------------------------------------------- state (refresh-safe)
@router.get("/{attempt_id}")
def state(attempt_id: int, bg: BackgroundTasks, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    a = get_attempt(db, attempt_id, user)
    if _close_if_overdue(db, a, bg) is None:
        a = get_attempt(db, attempt_id, user)
    base = {"attempt_id": a["id"], "exam_id": a["exam_id"], "title": a["title"], "status": a["status"], "is_sandbox": bool(a["is_sandbox"])}
    if a["status"] != "in_progress":
        t = q_one(db, "SELECT COUNT(*) AS n, COALESCE(SUM(is_answered),0) AS answered FROM attempt_questions WHERE attempt_id=:a", a=attempt_id)
        base.update(submitted_at=a["submitted_at"], total_questions=t["n"], answered=int(t["answered"]))
        if a["is_sandbox"]:                      # a preview may show the score; real candidates wait for publication
            base.update(preview_score=a["total_score"], preview_max=a["max_score"], grading_status=a["grading_status"])
        return base
    qs = q_all(db, """SELECT aq.id, aq.position, aq.question_type, aq.marks, aq.negative_marks, aq.multi_scheme, aq.option_order,
                             aq.selected_options, aq.written_answer, aq.marked_for_review, aq.is_answered, aq.answer_version, q.body
                      FROM attempt_questions aq JOIN questions q ON q.id=aq.question_id
                      WHERE aq.attempt_id=:a ORDER BY aq.position""", a=attempt_id)
    texts = {o["id"]: o["option_text"] for o in q_all(db, """SELECT id, option_text FROM question_options WHERE question_id IN
                                                              (SELECT question_id FROM attempt_questions WHERE attempt_id=:a)""", a=attempt_id)}
    out = []
    for r in qs:
        order = json.loads(r["option_order"]) if r["option_order"] else []
        out.append({"id": r["id"], "position": r["position"], "type": r["question_type"], "body": r["body"],
                    "marks": r["marks"], "negative_marks": r["negative_marks"], "multi_scheme": r["multi_scheme"],
                    "options": [{"id": i, "text": texts.get(i, "")} for i in order],          # never includes is_correct
                    "selected": json.loads(r["selected_options"]) if r["selected_options"] else [],
                    "written": r["written_answer"] or "", "marked": bool(r["marked_for_review"]),
                    "answered": bool(r["is_answered"]), "version": r["answer_version"]})
    pad = q_one(db, "SELECT content FROM scratchpads WHERE attempt_id=:a", a=attempt_id)
    total_seconds = q_one(db, "SELECT TIMESTAMPDIFF(SECOND, started_at, deadline_at) AS t FROM attempts WHERE id=:i", i=attempt_id)["t"]
    run(db, "UPDATE attempts SET last_heartbeat_at=UTC_TIMESTAMP() WHERE id=:i", i=attempt_id)
    db.commit()
    base.update(instructions=a["instructions"], integrity_monitoring=bool(a["integrity_monitoring"]) and not a["is_sandbox"],
                remaining=a["remaining"], total_seconds=total_seconds, questions=out,
                scratchpad=(pad or {}).get("content") or "", announcements=_announcements(db, a["exam_id"]))
    return base


# ---------------------------------------------------------------- autosave
@router.post("/{attempt_id}/save")
def save(attempt_id: int, data: SaveIn, bg: BackgroundTasks, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    _open_attempt(db, attempt_id, user, bg)
    results = _apply_items(db, attempt_id, data.items)
    run(db, "UPDATE attempts SET last_heartbeat_at=UTC_TIMESTAMP() WHERE id=:i", i=attempt_id)
    db.commit()
    return {"results": results, "remaining": _remaining(db, attempt_id)}


@router.post("/{attempt_id}/heartbeat")
def heartbeat(attempt_id: int, bg: BackgroundTasks, since: int = 0, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    a = get_attempt(db, attempt_id, user)
    if _close_if_overdue(db, a, bg) is None:
        return {"status": "expired", "remaining": 0, "announcements": []}
    if a["status"] == "in_progress":
        run(db, "UPDATE attempts SET last_heartbeat_at=UTC_TIMESTAMP() WHERE id=:i", i=attempt_id)
        db.commit()
    return {"status": a["status"], "remaining": a["remaining"], "announcements": _announcements(db, a["exam_id"], since)}


# ---------------------------------------------------------------- submit (idempotent)
@router.post("/{attempt_id}/submit")
def submit(attempt_id: int, bg: BackgroundTasks, data: Optional[SaveIn] = None,
           user: dict = Depends(current_user), db: Session = Depends(get_db)):
    a = get_attempt(db, attempt_id, user)
    if a["status"] != "in_progress":
        return {"status": a["status"], "already": True}
    on_time = a["remaining"] >= -GRACE_SECONDS
    if on_time and data and data.items:
        _apply_items(db, attempt_id, data.items)      # last unsaved answers, only if they arrived in the permitted period
        db.commit()
    expired = a["remaining"] <= 0
    if finalize_attempt(db, attempt_id, expired=expired) and not a["is_sandbox"]:
        bg.add_task(post_process, attempt_id)
    return {"status": "expired" if expired else "submitted", "already": False}


# ---------------------------------------------------------------- scratchpad (4.8)
@router.put("/{attempt_id}/scratchpad")
def scratchpad(attempt_id: int, data: PadIn, bg: BackgroundTasks, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    _open_attempt(db, attempt_id, user, bg)
    run(db, """INSERT INTO scratchpads (attempt_id, content) VALUES (:a,:c)
               ON DUPLICATE KEY UPDATE content=VALUES(content)""", a=attempt_id, c=data.content)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- integrity observations (5.1)
@router.post("/{attempt_id}/events")
def events(attempt_id: int, data: EventsIn, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    a = get_attempt(db, attempt_id, user)
    if a["status"] != "in_progress" or a["is_sandbox"]:
        return {"recorded": 0}
    count = q_one(db, "SELECT COUNT(*) AS n FROM attempt_events WHERE attempt_id=:a", a=attempt_id)["n"]
    recorded = 0
    for ev in data.events:
        if ev.type not in EVENT_TYPES or count + recorded >= MAX_EVENTS_PER_ATTEMPT:
            continue
        if not a["integrity_monitoring"] and ev.type not in ALWAYS_RECORDED:
            continue
        run(db, "INSERT INTO attempt_events (attempt_id, event_type, detail) VALUES (:a,:t,:d)", a=attempt_id, t=ev.type, d=ev.detail)
        recorded += 1
    db.commit()
    return {"recorded": recorded}
