"""
Database configuration and session management.
Uses SQLite via SQLAlchemy (synchronous) for simplicity.
"""

import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

# DB file lives next to the backend package so it persists via Docker volume
DB_PATH = os.environ.get("DB_PATH", "/app/data/pivot.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # required for SQLite + FastAPI
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI dependency — yields a DB session, closes after request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Bring the database schema up to date (called at startup).

    Uses Alembic migrations in backend/migrations. A database created by
    an older version of the app (via `create_all`, before migrations
    existed) has tables but no `alembic_version` row; it is stamped at the
    baseline revision first so only the newer migrations run.
    """
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    cfg = Config(os.path.join(backend_dir, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(backend_dir, "migrations"))

    tables = set(inspect(engine).get_table_names())
    if "alembic_version" not in tables and "datasets" in tables:
        command.stamp(cfg, "0001_baseline")
    command.upgrade(cfg, "head")
