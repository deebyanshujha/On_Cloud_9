"""SQLite database setup. SQLite is used for local dev because it needs no
server/auth and the whole DB is a single file (backend/data/arbitrage.db) —
easy to inspect, easy to delete and rebuild. Swapping to Postgres later only
means changing DATABASE_URL; nothing else in the code depends on SQLite
specifically.
"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DATA_DIR.mkdir(exist_ok=True)
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'arbitrage.db'}")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    from app.models import (  # noqa: F401  (registers the tables)
        approved_indication,
        case,
        document,
        ingestion_status,
        known_drug,
        user,
    )

    Base.metadata.create_all(bind=engine)
    _migrate_add_missing_columns()


def _migrate_add_missing_columns() -> None:
    """SQLite has no ALTER-TABLE-driven ORM migration story, and this
    project's dev DB is a single checked-in file rather than something
    recreated from scratch each time. `create_all` only creates tables that
    don't exist yet — it never adds a column to a table that's already
    there. So when a table gains a new nullable column (e.g. the TheraLens
    safety-context fields on approved_indications), add it here via a plain
    `ALTER TABLE ... ADD COLUMN`, which SQLite supports for nullable
    columns with no default. Idempotent: skipped if the column already
    exists."""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    for table in Base.metadata.tables.values():
        if table.name not in existing_tables:
            continue
        existing_columns = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing_columns:
                continue
            col_type = column.type.compile(engine.dialect)
            with engine.begin() as conn:
                conn.execute(
                    text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}')
                )
