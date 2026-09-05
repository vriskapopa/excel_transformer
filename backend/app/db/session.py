from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base

# Import models so metadata is populated
from app.models import (  # noqa: F401
    Item,
    PermitDatabase,
    Shipment,
    UploadedFile,
    ValidationError,
)

DEFAULT_DB_URL = "sqlite:///./customs_declaration.db"


def get_database_url() -> str:
    return os.getenv("DATABASE_URL", DEFAULT_DB_URL)


def create_db_engine(url: str | None = None) -> Engine:
    db_url = url or get_database_url()
    connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}
    engine = create_engine(db_url, future=True, connect_args=connect_args)

    if db_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


engine = create_db_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    Path("uploads").mkdir(exist_ok=True)
    Path("exports").mkdir(exist_ok=True)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
