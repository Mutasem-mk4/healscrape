from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String, Text, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class SelectorStatus(str, enum.Enum):
    draft = "draft"
    promoted = "promoted"
    deprecated = "deprecated"


class RunOutcome(str, enum.Enum):
    success = "success"
    validation_failed = "validation_failed"
    fetch_failed = "fetch_failed"
    healing_failed = "healing_failed"
    partial = "partial"


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(256), unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    selector_versions: Mapped[list[SelectorVersion]] = relationship(back_populates="site")
    runs: Mapped[list[ScrapeRun]] = relationship(back_populates="site")


class StoredSchema(Base):
    __tablename__ = "stored_schemas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    body_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StoredProfile(Base):
    __tablename__ = "stored_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    body_yaml: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SelectorVersion(Base):
    __tablename__ = "selector_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    selectors_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[SelectorStatus] = mapped_column(
        Enum(SelectorStatus, native_enum=False, length=32), nullable=False
    )
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("selector_versions.id"), nullable=True)
    confidence_at_promotion: Mapped[float | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    site: Mapped[Site] = relationship(back_populates="selector_versions")


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), unique=True, default=uuid.uuid4)
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id"), nullable=True, index=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    command: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[RunOutcome] = mapped_column(
        Enum(RunOutcome, native_enum=False, length=64), nullable=False
    )
    exit_code: Mapped[int] = mapped_column(Integer, nullable=False)
    output_format: Mapped[str] = mapped_column(String(16), nullable=False, default="json")
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    trace_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    selector_version_id: Mapped[int | None] = mapped_column(ForeignKey("selector_versions.id"), nullable=True)
    schema_snapshot_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_report_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    site: Mapped[Site | None] = relationship(back_populates="runs")
    snapshots: Mapped[list[PageSnapshot]] = relationship(back_populates="run")
    healing_events: Mapped[list[HealingEvent]] = relationship(back_populates="run")


class PageSnapshot(Base):
    __tablename__ = "page_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("scrape_runs.id"), nullable=False, index=True)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_length: Mapped[int] = mapped_column(Integer, nullable=False)
    fetch_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    run: Mapped[ScrapeRun] = relationship(back_populates="snapshots")


class HealingEvent(Base):
    __tablename__ = "healing_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("scrape_runs.id"), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    failure_reason: Mapped[str] = mapped_column(Text, nullable=False)
    broken_selectors_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_prompt_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    candidate_selectors_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_pass_1_ok: Mapped[bool] = mapped_column(default=False)
    validation_pass_2_ok: Mapped[bool] = mapped_column(default=False)
    promoted_selector_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("selector_versions.id"), nullable=True
    )
    promotion_blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    run: Mapped[ScrapeRun] = relationship(back_populates="healing_events")


class AuditLogEntry(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(128), nullable=False)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
