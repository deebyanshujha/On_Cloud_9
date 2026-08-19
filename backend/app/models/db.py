"""SQLite database setup. SQLite is used for local dev because it needs no
server/auth and the whole DB is a single file (backend/data/arbitrage.db) —
easy to inspect, easy to delete and rebuild. Swapping to Postgres later only
means changing DATABASE_URL; nothing else in the code depends on SQLite
specifically.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DATA_DIR.mkdir(exist_ok=True)
DATABASE_URL = f"sqlite:///{DATA_DIR / 'arbitrage.db'}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    from app.models import approved_indication, document  # noqa: F401  (registers the tables)

    Base.metadata.create_all(bind=engine)
