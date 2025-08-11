from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, Generator, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    func,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker, Session

# Alembic programmatic API for running migrations
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")


class Base(DeclarativeBase):
    pass


class FeatureFlag(Base):
    __tablename__ = "feature_flags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    rollout_percent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), default="system", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    session_id: Mapped[str] = mapped_column(String(255), nullable=False)
    user_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    props: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    decision_key: Mapped[str] = mapped_column(String(255), nullable=False)
    issued_to: Mapped[str] = mapped_column(String(255), nullable=False)
    jwt: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(64), default="open", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class DLQ(Base):
    __tablename__ = "dlq"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


engine = create_engine(DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session, future=True)


def init_db() -> None:
    """Apply database migrations to the current DATABASE_URL using Alembic.

    During pytest runs with SQLite, reset the schema to ensure test isolation.
    """
    # Resolve path to alembic.ini regardless of current working directory
    repo_root = Path(__file__).resolve().parents[2]
    alembic_ini = repo_root / "infrastructure" / "alembic.ini"

    cfg = AlembicConfig(str(alembic_ini))
    # Ensure runtime DATABASE_URL is used for migrations (sqlite for tests by default)
    runtime_url = os.getenv("DATABASE_URL", DATABASE_URL)
    cfg.set_main_option("sqlalchemy.url", runtime_url)

    # Rebind engine/session to current runtime_url if it changed (important for pytest isolation)
    global engine, SessionLocal
    try:
        current_url_str = str(engine.url)
    except Exception:
        current_url_str = ""
    if current_url_str != runtime_url:
        try:
            engine.dispose()
        except Exception:
            pass
        engine = create_engine(runtime_url, future=True)
        SessionLocal.configure(bind=engine)

    # If running under pytest and using sqlite file or memory, fully reset to head
    is_pytest = os.getenv("PYTEST_CURRENT_TEST") is not None
    if is_pytest and runtime_url.startswith("sqlite"):
        try:
            alembic_command.downgrade(cfg, "base")
        except Exception:
            # best effort; continue to upgrade
            pass
    # Run migrations up to head (idempotent)
    alembic_command.upgrade(cfg, "head")


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def upsert_flag(
    *,
    session: Session,
    name: str,
    description: Optional[str] = None,
    enabled: Optional[bool] = None,
    rollout_percent: Optional[int] = None,
    created_by: str = "system",
) -> FeatureFlag:
    flag: Optional[FeatureFlag] = session.scalar(select(FeatureFlag).where(FeatureFlag.name == name))
    if flag is None:
        flag = FeatureFlag(
            name=name,
            description=description,
            enabled=bool(enabled) if enabled is not None else False,
            rollout_percent=int(rollout_percent) if rollout_percent is not None else 0,
            created_by=created_by,
        )
        session.add(flag)
        session.flush()
        return flag

    if description is not None:
        flag.description = description
    if enabled is not None:
        flag.enabled = enabled
    if rollout_percent is not None:
        flag.rollout_percent = rollout_percent
    return flag


def insert_event(
    *, session: Session, name: str, session_id: str, user_id: Optional[str], props: Dict[str, Any]
) -> Event:
    ev = Event(name=name, session_id=session_id, user_id=user_id, props=props)
    session.add(ev)
    session.flush()
    return ev


