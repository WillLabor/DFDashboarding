"""Database session factory — supports Azure SQL (production) and SQLite (local dev)."""

from __future__ import annotations

import os
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

_engine = None
_SessionFactory = sessionmaker()


def get_engine():
    """Return a singleton SQLAlchemy engine.

    Connection string is read from AZURE_SQL_CONNECTION_STRING.
    Falls back to a local SQLite file for development.
    """
    global _engine
    if _engine is None:
        conn_str = os.environ.get(
            "AZURE_SQL_CONNECTION_STRING",
            "sqlite:///local.db",
        )
        _engine = create_engine(conn_str, pool_pre_ping=True)
    return _engine


@contextmanager
def get_session():
    """Yield a transactional DB session that auto-commits on success."""
    engine = get_engine()
    _SessionFactory.configure(bind=engine)
    session = _SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
