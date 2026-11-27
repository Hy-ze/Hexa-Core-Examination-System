"""Database connection layer (SQLAlchemy + PyMySQL)."""
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from config import DATABASE_URL

# Free MySQL hosts allow very few simultaneous connections, so keep the pool small.
engine = create_engine(
    DATABASE_URL,
    pool_size=3,
    max_overflow=2,
    pool_recycle=280,     # reconnect before the host drops idle connections
    pool_pre_ping=True,   # test a connection before using it
    connect_args={"init_command": "SET time_zone='+00:00'"},   # TIMESTAMP columns behave as UTC too
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db():
    """FastAPI dependency: one session per request, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_connection() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        import logging
        logging.getLogger("exam").error("DB connection failed: %r", e)
        return False
