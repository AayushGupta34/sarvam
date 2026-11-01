from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from .config.settings import settings


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Board(Base):
    __tablename__ = "boards"
    serial: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    inspections: Mapped[list["Inspection"]] = relationship(back_populates="board")


class Inspection(Base):
    __tablename__ = "inspections"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    serial: Mapped[str] = mapped_column(ForeignKey("boards.serial"), index=True)
    source: Mapped[str] = mapped_column(String(128))
    verdict: Mapped[str] = mapped_column(String(8))
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    board: Mapped[Board] = relationship(back_populates="inspections")
    defects: Mapped[list["DefectLog"]] = relationship(back_populates="inspection")


class DefectLog(Base):
    __tablename__ = "defect_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inspection_id: Mapped[int] = mapped_column(ForeignKey("inspections.id"), index=True)
    defect_class: Mapped[str] = mapped_column(String(32))
    designator: Mapped[str | None] = mapped_column(String(32), index=True)
    score: Mapped[float] = mapped_column(Float)
    inspection: Mapped[Inspection] = relationship(back_populates="defects")


class ReworkLog(Base):
    __tablename__ = "rework_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    serial: Mapped[str | None] = mapped_column(String(64), index=True)
    language_code: Mapped[str | None] = mapped_column(String(16))
    raw_transcript: Mapped[str] = mapped_column(Text)
    dictionary_text: Mapped[str] = mapped_column(Text)
    expanded_text: Mapped[str] = mapped_column(Text)
    styled_text: Mapped[str] = mapped_column(Text)
    style_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Feed(Base):
    __tablename__ = "feeds"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(32))
    role: Mapped[str] = mapped_column(String(32))
    url: Mapped[str | None] = mapped_column(String(512))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


_connect = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=_connect, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def init_db() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
