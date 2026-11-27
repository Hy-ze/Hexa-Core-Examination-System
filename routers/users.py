"""User administration (admin only) and candidate lookup (for enrollment)."""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from routers.auth import EMAIL_RE
from security import hash_password, require_roles
from utils import audit, q_all, q_one, run

router = APIRouter(prefix="/api/users", tags=["users"])
admin_only = require_roles("admin")


class UserIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: str = Field(max_length=190)
    password: Optional[str] = Field(default=None, min_length=8, max_length=100)
    role: Literal["admin", "examiner", "candidate"]
    roll_no: Optional[str] = Field(default=None, max_length=40)
    is_active: bool = True


def _check_email(email: str) -> str:
    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(422, "Enter a valid email address.")
    return email


def _active_admins(db, excluding: int = 0) -> int:
    return q_one(db, "SELECT COUNT(*) AS n FROM users WHERE role='admin' AND is_active=1 AND id<>:i",
                 i=excluding)["n"]


@router.get("")
def list_users(role: Optional[str] = None, q: Optional[str] = None,
               _: dict = Depends(admin_only), db: Session = Depends(get_db)):
    sql = "SELECT id, full_name, email, role, roll_no, is_active, created_at FROM users WHERE 1=1"
    p = {}
    if role in ("admin", "examiner", "candidate"):
        sql += " AND role=:role"; p["role"] = role
    if q:
        sql += " AND (full_name LIKE :q OR email LIKE :q OR roll_no LIKE :q)"; p["q"] = f"%{q.strip()}%"
    return q_all(db, sql + " ORDER BY role, full_name", **p)


@router.get("/candidates")
def list_candidates(_: dict = Depends(require_roles("examiner", "admin")), db: Session = Depends(get_db)):
    return q_all(db, "SELECT id, full_name, email, roll_no FROM users "
                     "WHERE role='candidate' AND is_active=1 ORDER BY full_name")


@router.post("", status_code=201)
def create_user(data: UserIn, admin: dict = Depends(admin_only), db: Session = Depends(get_db)):
    email = _check_email(data.email)
    if not data.password:
        raise HTTPException(422, "A password of at least 8 characters is required for new users.")
    if q_one(db, "SELECT id FROM users WHERE email=:e", e=email):
        raise HTTPException(409, "A user with this email already exists.")
    res = run(db, """INSERT INTO users (full_name, email, password_hash, role, roll_no, is_active)
                     VALUES (:n, :e, :h, :r, :roll, :a)""",
              n=data.full_name.strip(), e=email, h=hash_password(data.password), r=data.role,
              roll=(data.roll_no or None), a=int(data.is_active))
    audit(db, "user", res.lastrowid, admin["id"], "create", new=data.role)
    db.commit()
    return {"id": res.lastrowid}


@router.put("/{user_id}")
def update_user(user_id: int, data: UserIn, admin: dict = Depends(admin_only), db: Session = Depends(get_db)):
    target = q_one(db, "SELECT * FROM users WHERE id=:i", i=user_id)
    if not target:
        raise HTTPException(404, "User not found.")
    email = _check_email(data.email)
    if q_one(db, "SELECT id FROM users WHERE email=:e AND id<>:i", e=email, i=user_id):
        raise HTTPException(409, "Another user already has this email.")
    losing_admin = target["role"] == "admin" and target["is_active"] and (data.role != "admin" or not data.is_active)
    if losing_admin and _active_admins(db, excluding=user_id) == 0:
        raise HTTPException(409, "At least one active administrator must remain.")
    if user_id == admin["id"] and (data.role != "admin" or not data.is_active):
        raise HTTPException(409, "You cannot remove your own administrator access.")
    run(db, """UPDATE users SET full_name=:n, email=:e, role=:r, roll_no=:roll, is_active=:a WHERE id=:i""",
        n=data.full_name.strip(), e=email, r=data.role, roll=(data.roll_no or None),
        a=int(data.is_active), i=user_id)
    if data.password:
        run(db, "UPDATE users SET password_hash=:h WHERE id=:i", h=hash_password(data.password), i=user_id)
        audit(db, "user", user_id, admin["id"], "password_reset")
    if target["role"] != data.role:
        audit(db, "user", user_id, admin["id"], "role_change", old=target["role"], new=data.role)
    if bool(target["is_active"]) != data.is_active:
        audit(db, "user", user_id, admin["id"], "activate" if data.is_active else "deactivate")
    db.commit()
    return {"ok": True}
