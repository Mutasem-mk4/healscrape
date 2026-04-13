from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import Select, desc, select
from sqlalchemy.orm import Session

from healscrape.persistence.models import (
    AuditLogEntry,
    HealingEvent,
    PageSnapshot,
    RunOutcome,
    ScrapeRun,
    SelectorStatus,
    SelectorVersion,
    Site,
    StoredProfile,
    StoredSchema,
)


class SiteRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_or_create(self, slug: str) -> Site:
        stmt: Select[tuple[Site]] = select(Site).where(Site.slug == slug)
        row = self.session.execute(stmt).scalar_one_or_none()
        if row:
            return row
        site = Site(slug=slug)
        self.session.add(site)
        self.session.flush()
        return site

    def get_by_slug(self, slug: str) -> Site | None:
        return self.session.execute(select(Site).where(Site.slug == slug)).scalar_one_or_none()


class SelectorRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def latest_promoted(self, site_id: int) -> SelectorVersion | None:
        stmt = (
            select(SelectorVersion)
            .where(
                SelectorVersion.site_id == site_id,
                SelectorVersion.status == SelectorStatus.promoted,
            )
            .order_by(desc(SelectorVersion.version))
            .limit(1)
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def next_version(self, site_id: int) -> int:
        stmt = select(SelectorVersion.version).where(SelectorVersion.site_id == site_id).order_by(
            desc(SelectorVersion.version)
        )
        rows = self.session.execute(stmt).scalars().first()
        return (rows or 0) + 1

    def create_version(
        self,
        site_id: int,
        selectors: dict,
        status: SelectorStatus,
        parent_id: int | None = None,
        confidence: float | None = None,
    ) -> SelectorVersion:
        v = SelectorVersion(
            site_id=site_id,
            version=self.next_version(site_id),
            selectors_json=json.dumps(selectors, ensure_ascii=False),
            status=status,
            parent_id=parent_id,
            confidence_at_promotion=confidence,
        )
        self.session.add(v)
        self.session.flush()
        return v


class RunRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        url: str,
        command: str,
        site_id: int | None,
        outcome: RunOutcome,
        exit_code: int,
        output_format: str = "json",
        result_json: str | None = None,
        error_detail: str | None = None,
        trace_path: str | None = None,
        selector_version_id: int | None = None,
        schema_snapshot_json: str | None = None,
        validation_report_json: str | None = None,
        confidence: float | None = None,
    ) -> ScrapeRun:
        run = ScrapeRun(
            url=url,
            command=command,
            site_id=site_id,
            outcome=outcome,
            exit_code=exit_code,
            output_format=output_format,
            result_json=result_json,
            error_detail=error_detail,
            trace_path=trace_path,
            selector_version_id=selector_version_id,
            schema_snapshot_json=schema_snapshot_json,
            validation_report_json=validation_report_json,
            confidence=confidence,
            ended_at=datetime.now(timezone.utc),
        )
        self.session.add(run)
        self.session.flush()
        return run

    def get_by_public_id(self, public_id: str) -> ScrapeRun | None:
        try:
            uid = uuid.UUID(public_id)
        except ValueError:
            return None
        return self.session.execute(select(ScrapeRun).where(ScrapeRun.public_id == uid)).scalar_one_or_none()


class SnapshotRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(
        self,
        run_id: int,
        storage_path: Path | str,
        content_sha256: str,
        byte_length: int,
        fetch_mode: str,
    ) -> PageSnapshot:
        snap = PageSnapshot(
            run_id=run_id,
            storage_path=str(storage_path),
            content_sha256=content_sha256,
            byte_length=byte_length,
            fetch_mode=fetch_mode,
        )
        self.session.add(snap)
        self.session.flush()
        return snap


class HealingRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_event(self, event: HealingEvent) -> HealingEvent:
        self.session.add(event)
        self.session.flush()
        return event


class ProfileRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_names(self) -> list[str]:
        return list(self.session.execute(select(StoredProfile.name)).scalars().all())

    def get_by_name(self, name: str) -> StoredProfile | None:
        return self.session.execute(select(StoredProfile).where(StoredProfile.name == name)).scalar_one_or_none()

    def upsert(self, name: str, yaml_text: str) -> StoredProfile:
        row = self.get_by_name(name)
        if row:
            row.body_yaml = yaml_text
            self.session.flush()
            return row
        row = StoredProfile(name=name, body_yaml=yaml_text)
        self.session.add(row)
        self.session.flush()
        return row


class AuditRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def write(
        self,
        *,
        actor: str,
        action: str,
        entity_type: str,
        entity_id: str,
        details: dict | None = None,
    ) -> None:
        self.session.add(
            AuditLogEntry(actor=actor, action=action, entity_type=entity_type, entity_id=entity_id, details=details)
        )
