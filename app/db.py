"""SQLite engine + session plumbing. One file, one service."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app import config


class Base(DeclarativeBase):
    pass


engine = None
SessionLocal = None


def init_engine(db_path: Path | None = None):
    """(Re)bind the engine. Called by create_app; tests point it at a tmp file."""
    global engine, SessionLocal
    config.ensure_dirs()
    engine = create_engine(
        config.database_url(db_path),
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _record):  # pragma: no cover - trivial
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return engine


def create_all() -> None:
    from app import models  # noqa: F401  (register tables)

    Base.metadata.create_all(bind=engine)
    _add_missing_columns()


def _add_missing_columns() -> None:
    """Add columns that create_all() cannot add to a table that already exists.

    There is no migration tool here on purpose, but silently running against a
    database missing a column fails much later and much more confusingly than
    one ALTER at startup.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue
        existing = {col["name"] for col in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing or not column.nullable:
                continue
            ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {column.type.compile(engine.dialect)}'
            with engine.begin() as conn:
                conn.execute(text(ddl))


@contextmanager
def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
