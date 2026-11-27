"""4.7 Customizable examination workspace: per-user preferences that persist across exams and devices."""
import json
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from security import current_user
from utils import q_one, run

router = APIRouter(prefix="/api/preferences", tags=["preferences"])

DEFAULTS = {"theme": "light", "text_size": "md", "layout": "palette-right", "question_font": "serif"}


class PrefsIn(BaseModel):
    theme: Literal["light", "dark", "sepia"] = "light"
    text_size: Literal["sm", "md", "lg", "xl"] = "md"
    layout: Literal["palette-right", "palette-left", "palette-top", "focus"] = "palette-right"
    question_font: Literal["serif", "sans"] = "serif"


@router.get("")
def get_prefs(user: dict = Depends(current_user), db: Session = Depends(get_db)):
    row = q_one(db, "SELECT prefs FROM user_preferences WHERE user_id=:u", u=user["id"])
    try:
        saved = json.loads(row["prefs"]) if row else {}
    except ValueError:
        saved = {}
    return {**DEFAULTS, **{k: v for k, v in saved.items() if k in DEFAULTS}}


@router.put("")
def put_prefs(data: PrefsIn, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    run(db, """INSERT INTO user_preferences (user_id, prefs) VALUES (:u,:p) ON DUPLICATE KEY UPDATE prefs=VALUES(prefs)""",
        u=user["id"], p=json.dumps(data.model_dump()))
    db.commit()
    return data.model_dump()
