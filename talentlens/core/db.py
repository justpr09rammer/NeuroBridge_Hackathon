"""Database engine/session management and safe schema initialisation."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from talentlens import config
from talentlens.core.models import Base

_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def _enable_sqlite_fk(dbapi_conn, _record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


def configure(url: str | None = None) -> Engine:
    """(Re)configure the engine. Tests call this with a temporary database URL."""
    global _engine, _SessionLocal
    url = url or config.DATABASE_URL
    if url.startswith("sqlite:///"):
        config.ensure_dirs()
    engine = create_engine(url, future=True, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
    if url.startswith("sqlite"):
        event.listen(engine, "connect", _enable_sqlite_fk)
    Base.metadata.create_all(engine)  # idempotent, safe schema initialisation
    _engine = engine
    _SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    return engine


def get_engine() -> Engine:
    if _engine is None:
        configure()
    assert _engine is not None
    return _engine


@contextmanager
def session_scope() -> Iterator[Session]:
    if _SessionLocal is None:
        configure()
    assert _SessionLocal is not None
    session: Session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
