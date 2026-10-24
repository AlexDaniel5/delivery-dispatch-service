"""Database engine and session management."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models import Base


def create_db_engine(database_url: str | None = None) -> Engine:
    """Create an :class:`Engine` for ``database_url`` (defaults to settings)."""
    url = database_url or get_settings().database_url
    connect_args: dict[str, object] = {}
    if url.startswith("sqlite"):
        # Allow usage across FastAPI's threadpool workers and wait on write locks
        # instead of failing immediately (matters for the concurrency tests).
        connect_args["check_same_thread"] = False
        connect_args["timeout"] = 30
        return create_engine(url, connect_args=connect_args, future=True)
    # Networked databases (e.g. Postgres): recycle stale pooled connections.
    return create_engine(url, pool_pre_ping=True, future=True)


_engine: Engine = create_db_engine()
SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)


def get_engine() -> Engine:
    """Return the process-wide engine."""
    return _engine


def init_db(engine: Engine | None = None) -> None:
    """Create all tables."""
    Base.metadata.create_all(engine or _engine)


def get_session() -> Iterator[Session]:
    """FastAPI dependency that yields a session and always closes it."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context manager yielding a session, committing on success."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
