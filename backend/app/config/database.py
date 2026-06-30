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
    """Create all tables defined in models (called at startup)."""
    # Import models so SQLAlchemy sees them before create_all
    from app.models import dataset  # noqa: F401
    Base.metadata.create_all(bind=engine)
