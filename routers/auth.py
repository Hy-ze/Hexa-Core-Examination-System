"""Sign in / sign out / current user."""
import re
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from config import COOKIE_NAME, COOKIE_SECURE, TOKEN_EXPIRE_MINUTES
from database import get_db
from security import create_token, current_user, hash_password, verify_password
from utils import q_one, run

router = APIRouter(prefix="/api/auth", tags=["auth"])

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_failures: dict = {}   # (ip, email) -> [timestamps]   simple brute-force throttle


def _throttled(key) -> bool:
    now = time.time()
    recent = [t for t in _failures.get(key, []) if now - t < 300]
    _failures[key] = recent
    return len(recent) >= 6


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=190)
    password: str = Field(min_length=1, max_length=200)


class PasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=100)


def public_user(u: dict) -> dict:
    return {k: u[k] for k in ("id", "full_name", "email", "role", "roll_no")}


@router.post("/login")
def login(data: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    email = data.email.strip().lower()
    key = (request.client.host if request.client else "?", email)
    if _throttled(key):
        raise HTTPException(429, "Too many failed attempts. Wait a few minutes and try again.")
    user = q_one(db, "SELECT * FROM users WHERE email=:e", e=email)
    if not user or not verify_password(data.password, user["password_hash"]):
        _failures.setdefault(key, []).append(time.time())
        raise HTTPException(401, "Email or password is incorrect.")
    if not user["is_active"]:
        raise HTTPException(403, "This account has been deactivated. Contact an administrator.")
    response.set_cookie(COOKIE_NAME, create_token(user["id"]), httponly=True, samesite="lax",
                        secure=COOKIE_SECURE, max_age=TOKEN_EXPIRE_MINUTES * 60, path="/")
    _failures.pop(key, None)
    return public_user(user)


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: dict = Depends(current_user)):
    return public_user(user)


@router.post("/change-password")
def change_password(data: PasswordIn, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    row = q_one(db, "SELECT password_hash FROM users WHERE id=:i", i=user["id"])
    if not verify_password(data.current_password, row["password_hash"]):
        raise HTTPException(400, "Current password is incorrect.")
    run(db, "UPDATE users SET password_hash=:h WHERE id=:i", h=hash_password(data.new_password), i=user["id"])
    db.commit()
    return {"ok": True}
