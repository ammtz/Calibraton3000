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


@contextmanager
def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
