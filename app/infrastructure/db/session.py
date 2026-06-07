from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.infrastructure.db.models import Base


def create_session_factory(database_url: str) -> Callable[[], Session]:
    engine = create_engine(database_url, pool_pre_ping=True, future=True)
    return sessionmaker(bind=engine, autoflush=True, expire_on_commit=False)


def init_database(database_url: str) -> None:
    engine = create_engine(database_url, pool_pre_ping=True, future=True)
    if database_url.startswith("postgresql"):
        with engine.begin() as connection:
            connection.exec_driver_sql("SELECT pg_advisory_lock(424242)")
            try:
                Base.metadata.create_all(connection)
            finally:
                connection.exec_driver_sql("SELECT pg_advisory_unlock(424242)")
        return
    Base.metadata.create_all(engine)
