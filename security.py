"""Passwords, JWT cookie sessions and role-based access (enforced on the backend)."""
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from config import COOKIE_NAME, JWT_ALGORITHM, SECRET_KEY, TOKEN_EXPIRE_MINUTES
from database import get_db
from utils import q_one


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt(12)).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:72], hashed.encode())
    except ValueError:
        return False


def create_token(user_id: int) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=TOKEN_EXPIRE_MINUTES)
    return jwt.encode({"sub": str(user_id), "exp": exp}, SECRET_KEY, algorithm=JWT_ALGORITHM)


def current_user(request: Request, db: Session = Depends(get_db)) -> dict:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(401, "Please sign in.")
    try:
        data = jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
        uid = int(data["sub"])
    except Exception:
        raise HTTPException(401, "Your session has expired. Please sign in again.")
    # Always re-read the user: role changes and deactivation apply immediately.
    user = q_one(db, "SELECT id, full_name, email, role, roll_no, is_active FROM users WHERE id=:i", i=uid)
    if not user or not user["is_active"]:
        raise HTTPException(401, "This account is not active.")
    return user


def require_roles(*roles: str):
    def checker(user: dict = Depends(current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(403, "You do not have permission to do this.")
        return user
    return checker
