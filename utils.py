"""Shared helpers: time, query helpers, audit log, status SQL."""
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import text


def now_utc() -> datetime:
    """Naive UTC datetime (all DB times are UTC)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def parse_client_dt(value: str) -> datetime:
    """Parse an ISO string sent by the browser into naive UTC."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _clean(v):
    if isinstance(v, datetime):
        return v.isoformat() + "Z"
    if isinstance(v, Decimal):
        return float(v)
    return v


def q_all(db, sql: str, **params) -> list[dict]:
    res = db.execute(text(sql), params)
    return [{k: _clean(v) for k, v in row._mapping.items()} for row in res]


def q_one(db, sql: str, **params):
    rows = q_all(db, sql, **params)
    return rows[0] if rows else None


def run(db, sql: str, **params):
    return db.execute(text(sql), params)


def audit(db, entity_type: str, entity_id: int, actor_id, action: str,
          old=None, new=None, note=None):
    run(db, """INSERT INTO audit_log (entity_type, entity_id, actor_id, action, old_value, new_value, note)
               VALUES (:t, :i, :a, :act, :o, :n, :note)""",
        t=entity_type, i=entity_id, a=actor_id, act=action,
        o=None if old is None else str(old)[:500],
        n=None if new is None else str(new)[:500], note=note)


# Exam status as seen "now", computed by the database clock in UTC (never the browser).
STATUS_SQL = ("CASE WHEN e.status='draft' THEN 'draft' "
              "WHEN UTC_TIMESTAMP() < e.start_time THEN 'published' "
              "WHEN UTC_TIMESTAMP() <= e.end_time THEN 'ongoing' ELSE 'completed' END")

ACCESS_SQL = ("CASE WHEN UTC_TIMESTAMP() < e.start_time THEN 'upcoming' "
              "WHEN UTC_TIMESTAMP() <= e.end_time THEN 'open' ELSE 'closed' END")
