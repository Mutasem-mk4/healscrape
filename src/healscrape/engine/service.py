from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import structlog
from sqlalchemy.orm import Session

from healscrape.config import Settings
from healscrape.domain.schema_spec import ExtractSpec
from healscrape.engine.extract import extract_from_spec_map
from healscrape.engine.heal_context import build_healing_user_prompt, sha256_bytes
from healscrape.engine.validate import ValidationReport, validate_extraction
from healscrape.exit_codes import (
    FETCH_FAILED,
    HEALING_FAILED,
    LLM_UNAVAILABLE,
    RENDER_FAILED,
    SUCCESS,
    VALIDATION_FAILED,
)
from healscrape.persistence.models import HealingEvent, RunOutcome, SelectorStatus
from healscrape.persistence.repositories import (
    AuditRepository,
    HealingRepository,
    RunRepository,
    SelectorRepository,
    SiteRepository,
    SnapshotRepository,
)
from healscrape.providers.fetch import HttpFetcher
from healscrape.providers.llm.base import LlmProvider
from healscrape.spec.loaders import selectors_dict_from_spec

log = structlog.get_logger(__name__)

HEALING_SYSTEM_PROMPT = """You are a precise web scraping repair assistant.
Return ONLY valid JSON with this shape:
{
  "extracted": { "<field>": "<value>" , ... },
  "selectors": { "<field>": { "css": "<css selector>", "attr": "<attribute name or null>" } },
  "notes": "<short rationale>"
}
Rules:
- Prefer robust, specific CSS selectors that match the visible content.
- If a field should use an attribute (e.g. href), set attr accordingly; otherwise attr must be null.
- Do not invent data that is not supported by the provided page context.
"""


@dataclass
class ScrapeResult:
    exit_code: int
    outcome: RunOutcome
    data: dict[str, Any] | None
    validation: ValidationReport | None
    run_public_id: str | None
    trace_path: str | None
    error: str | None = None


def _merge_selectors(base: dict[str, dict[str, Any]], promoted: dict[str, dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    out = {k: dict(v) for k, v in base.items()}
    if not promoted:
        return out
    for k, v in promoted.items():
        if isinstance(v, dict):
            cur = out.setdefault(k, {})
            if v.get("css"):
                cur["css"] = v["css"]
            if "attr" in v:
                cur["attr"] = v["attr"]
    return out


def _load_promoted_selectors(session: Session, site_id: int) -> dict[str, dict[str, Any]] | None:
    sel = SelectorRepository(session).latest_promoted(site_id)
    if not sel:
        return None
    return json.loads(sel.selectors_json)


def persist_snapshot(
    settings: Settings, run_public_id: str, html: str, fetch_mode: str
) -> tuple[Path, str, int]:
    root = settings.data_dir / "snapshots" / run_public_id
    root.mkdir(parents=True, exist_ok=True)
    path = root / "page.html"
    body = html.encode("utf-8")
    path.write_bytes(body)
    return path, sha256_bytes(body), len(body)


def write_trace(settings: Settings, run_public_id: str, payload: dict[str, Any]) -> Path:
    root = settings.data_dir / "traces"
    root.mkdir(parents=True, exist_ok=True)
    p = root / f"{run_public_id}.json"
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return p


def fetch_html(url: str, *, render: bool, settings: Settings, fetcher: HttpFetcher) -> tuple[str, str]:
    if render:
        from healscrape.providers.browser import render_page

        try:
            page = render_page(url, timeout_ms=settings.http_timeout_s * 1000)
            return page.html, "playwright"
        except Exception as e:
            raise RuntimeError(f"render_failed:{e}") from e
    try:
        fp = fetcher.get(url)
        if fp.status_code >= 400:
            raise RuntimeError(f"HTTP {fp.status_code}")
        return fp.body.decode("utf-8", errors="replace"), "httpx"
    except Exception as e:
        raise RuntimeError(f"fetch_failed:{e}") from e


def run_scrape(
    *,
    settings: Settings,
    session: Session,
    url: str,
    spec: ExtractSpec,
    command_name: str,
    fetcher: HttpFetcher,
    llm_factory: Callable[[], LlmProvider] | None,
    allow_healing: bool,
    force_healing: bool = False,
    output_format: str = "json",
) -> ScrapeResult:
    trace: dict[str, Any] = {"url": url, "command": command_name, "steps": []}
    site = SiteRepository(session).get_or_create(spec.site_slug)

    base_selectors = selectors_dict_from_spec(spec)
    promoted = _load_promoted_selectors(session, site.id)
    selector_map = _merge_selectors(base_selectors, promoted)
    trace["steps"].append({"step": "selectors_merged", "selector_map": selector_map})

    try:
        html, mode = fetch_html(url, render=spec.render, settings=settings, fetcher=fetcher)
    except Exception as e:
        log.error("fetch_failed", err=str(e))
        rr = RunRepository(session)
        err = str(e)
        is_render = err.startswith("render_failed:")
        run = rr.create(
            url=url,
            command=command_name,
            site_id=site.id,
            outcome=RunOutcome.fetch_failed,
            exit_code=RENDER_FAILED if is_render else FETCH_FAILED,
            error_detail=err,
            output_format=output_format,
            schema_snapshot_json=json.dumps(spec.json_schema, ensure_ascii=False),
        )
        session.flush()
        trace_path = write_trace(settings, str(run.public_id), trace | {"error": str(e)})
        run.trace_path = str(trace_path)
        session.flush()
        return ScrapeResult(
            exit_code=RENDER_FAILED if is_render else FETCH_FAILED,
            outcome=RunOutcome.fetch_failed,
            data=None,
            validation=None,
            run_public_id=str(run.public_id),
            trace_path=str(trace_path),
            error=str(e),
        )

    field_order = [f.name for f in spec.fields]
    data = extract_from_spec_map(html, selector_map, field_order)
    report = validate_extraction(data, spec)
    trace["steps"].append(
        {"step": "deterministic", "fetch_mode": mode, "data": data, "validation": json.loads(report.to_json())}
    )

    if (not report.ok or force_healing) and allow_healing:
        if llm_factory is None:
            run = RunRepository(session).create(
                url=url,
                command=command_name,
                site_id=site.id,
                outcome=RunOutcome.healing_failed,
                exit_code=LLM_UNAVAILABLE,
                output_format=output_format,
                schema_snapshot_json=json.dumps(spec.json_schema, ensure_ascii=False),
                validation_report_json=report.to_json(),
                error_detail="LLM provider not configured",
            )
            session.flush()
            trace["steps"].append({"step": "healing_skipped", "reason": "no_llm"})
            trace_path = write_trace(settings, str(run.public_id), trace)
            run.trace_path = str(trace_path)
            session.flush()
            return ScrapeResult(
                exit_code=LLM_UNAVAILABLE,
                outcome=RunOutcome.healing_failed,
                data=data,
                validation=report,
                run_public_id=str(run.public_id),
                trace_path=str(trace_path),
                error="LLM provider not configured",
            )
        try:
            provider = llm_factory()
        except Exception as e:
            run = RunRepository(session).create(
                url=url,
                command=command_name,
                site_id=site.id,
                outcome=RunOutcome.healing_failed,
                exit_code=LLM_UNAVAILABLE,
                output_format=output_format,
                schema_snapshot_json=json.dumps(spec.json_schema, ensure_ascii=False),
                validation_report_json=report.to_json(),
                error_detail=str(e),
            )
            session.flush()
            trace_path = write_trace(settings, str(run.public_id), trace)
            run.trace_path = str(trace_path)
            session.flush()
            return ScrapeResult(
                exit_code=LLM_UNAVAILABLE,
                outcome=RunOutcome.healing_failed,
                data=data,
                validation=report,
                run_public_id=str(run.public_id),
                trace_path=str(trace_path),
                error=str(e),
            )

        fields_meta = [
            {
                "name": f.name,
                "required": f.required,
                "type": f.json_type,
                "description": f.description,
            }
            for f in spec.fields
        ]
        user_prompt = build_healing_user_prompt(
            url=url,
            fields=fields_meta,
            current_selectors=selector_map,
            deterministic_payload=data,
            html=html,
            max_chars=settings.llm_max_input_chars,
        )
        failure_reason = ";".join(report.reasons + report.schema_errors) or "validation_failed"
        try:
            raw = provider.complete_json(HEALING_SYSTEM_PROMPT, user_prompt)
            parsed = json.loads(raw)
        except Exception as e:
            log.exception("healing_llm_failed")
            run = RunRepository(session).create(
                url=url,
                command=command_name,
                site_id=site.id,
                outcome=RunOutcome.healing_failed,
                exit_code=HEALING_FAILED,
                output_format=output_format,
                schema_snapshot_json=json.dumps(spec.json_schema, ensure_ascii=False),
                validation_report_json=report.to_json(),
                error_detail=str(e),
            )
            session.flush()
            trace["steps"].append({"step": "llm_error", "error": str(e)})
            trace_path = write_trace(settings, str(run.public_id), trace)
            run.trace_path = str(trace_path)
            session.flush()
            return ScrapeResult(
                exit_code=HEALING_FAILED,
                outcome=RunOutcome.healing_failed,
                data=data,
                validation=report,
                run_public_id=str(run.public_id),
                trace_path=str(trace_path),
                error=str(e),
            )

        candidate_sel = parsed.get("selectors") or {}
        llm_data = parsed.get("extracted") or {}

        trace["steps"].append({"step": "llm_response", "raw": raw, "parsed_extracted": llm_data})

        # Normalize candidate selectors to expected shape
        normalized: dict[str, dict[str, Any]] = {}
        for k, v in candidate_sel.items():
            if isinstance(v, str):
                normalized[k] = {"css": v, "attr": None}
            elif isinstance(v, dict):
                normalized[k] = {"css": v.get("css"), "attr": v.get("attr")}

        merged_for_test = _merge_selectors(base_selectors, normalized)
        repaired = extract_from_spec_map(html, merged_for_test, field_order)
        pass1 = validate_extraction(repaired, spec)
        repaired_again = extract_from_spec_map(html, merged_for_test, field_order)
        pass2 = validate_extraction(repaired_again, spec)

        trace["steps"].append(
            {
                "step": "post_heal_validation",
                "repaired": repaired,
                "pass1": json.loads(pass1.to_json()),
                "pass2": json.loads(pass2.to_json()),
            }
        )

        can_promote = (
            pass1.ok
            and pass2.ok
            and pass1.confidence >= settings.min_promotion_confidence
            and pass2.confidence >= settings.min_promotion_confidence
        )
        blocked = None
        promoted_version_id = None
        if not can_promote:
            if not pass1.ok:
                blocked = "first_validation_failed"
            elif not pass2.ok:
                blocked = "second_validation_failed"
            elif pass1.confidence < settings.min_promotion_confidence:
                blocked = "confidence_below_threshold"

        sel_repo = SelectorRepository(session)
        parent = sel_repo.latest_promoted(site.id)
        has_candidates = any((v.get("css") or "") for v in normalized.values())
        persist_selectors = {k: dict(v) for k, v in merged_for_test.items()}
        if can_promote:
            new_ver = sel_repo.create_version(
                site.id,
                persist_selectors,
                SelectorStatus.promoted,
                parent_id=parent.id if parent else None,
                confidence=pass1.confidence,
            )
            promoted_version_id = new_ver.id
            AuditRepository(session).write(
                actor="healscrape",
                action="promote_selectors",
                entity_type="selector_version",
                entity_id=str(new_ver.id),
                details={"site": site.slug, "version": new_ver.version},
            )
        elif has_candidates:
            sel_repo.create_version(
                site.id,
                persist_selectors,
                SelectorStatus.draft,
                parent_id=parent.id if parent else None,
                confidence=None,
            )

        outcome = RunOutcome.success if pass1.ok else RunOutcome.validation_failed
        exit_code = SUCCESS if pass1.ok else VALIDATION_FAILED
        final_data = repaired
        final_report = pass1

        active_selector_row_id = promoted_version_id or (parent.id if parent else None)

        run = RunRepository(session).create(
            url=url,
            command=command_name,
            site_id=site.id,
            outcome=outcome,
            exit_code=exit_code,
            output_format=output_format,
            result_json=json.dumps(final_data, ensure_ascii=False) if final_data is not None else None,
            schema_snapshot_json=json.dumps(spec.json_schema, ensure_ascii=False),
            validation_report_json=final_report.to_json(),
            confidence=final_report.confidence,
            selector_version_id=active_selector_row_id,
        )
        session.flush()
        event = HealingEvent(
            run_id=run.id,
            sequence=1,
            failure_reason=failure_reason,
            broken_selectors_json=json.dumps(selector_map, ensure_ascii=False),
            llm_prompt_excerpt=user_prompt[:8000],
            llm_raw_response=raw,
            candidate_selectors_json=json.dumps(normalized, ensure_ascii=False),
            validation_pass_1_ok=pass1.ok,
            validation_pass_2_ok=pass2.ok,
            promotion_blocked_reason=blocked,
            promoted_selector_version_id=promoted_version_id,
        )
        HealingRepository(session).add_event(event)

        snap_path, sha, blen = persist_snapshot(settings, str(run.public_id), html, mode)
        SnapshotRepository(session).add(run.id, snap_path, sha, blen, mode)

        trace_path = write_trace(settings, str(run.public_id), trace)
        run.trace_path = str(trace_path)
        session.flush()

        return ScrapeResult(
            exit_code=exit_code,
            outcome=outcome,
            data=final_data,
            validation=final_report,
            run_public_id=str(run.public_id),
            trace_path=str(trace_path),
            error=None if pass1.ok else "validation_failed_after_heal",
        )

    # No healing path
    outcome = RunOutcome.success if report.ok else RunOutcome.validation_failed
    exit_code = SUCCESS if report.ok else VALIDATION_FAILED
    sel_repo = SelectorRepository(session)
    promoted_row = sel_repo.latest_promoted(site.id)
    run = RunRepository(session).create(
        url=url,
        command=command_name,
        site_id=site.id,
        outcome=outcome,
        exit_code=exit_code,
        output_format=output_format,
        result_json=json.dumps(data, ensure_ascii=False),
        schema_snapshot_json=json.dumps(spec.json_schema, ensure_ascii=False),
        validation_report_json=report.to_json(),
        confidence=report.confidence,
        selector_version_id=promoted_row.id if promoted_row else None,
    )
    session.flush()
    snap_path, sha, blen = persist_snapshot(settings, str(run.public_id), html, mode)
    SnapshotRepository(session).add(run.id, snap_path, sha, blen, mode)
    trace_path = write_trace(settings, str(run.public_id), trace)
    run.trace_path = str(trace_path)
    session.flush()

    return ScrapeResult(
        exit_code=exit_code,
        outcome=outcome,
        data=data,
        validation=report,
        run_public_id=str(run.public_id),
        trace_path=str(trace_path),
        error=None if report.ok else "validation_failed",
    )


def inspect_page(url: str, settings: Settings, fetcher: HttpFetcher, render: bool = False) -> dict[str, Any]:
    html, mode = fetch_html(url, render=render, settings=settings, fetcher=fetcher)
    from selectolax.parser import HTMLParser

    tree = HTMLParser(html)
    title_node = tree.css_first("title")
    h1 = tree.css_first("h1")
    meta_desc = tree.css_first('meta[name="description"]')
    return {
        "url": url,
        "fetch_mode": mode,
        "title_tag": title_node.text(deep=True, strip=True) if title_node else None,
        "h1": h1.text(deep=True, strip=True) if h1 else None,
        "meta_description": meta_desc.attributes.get("content") if meta_desc else None,
        "approx_visible_text_chars": len(tree.body.text(deep=True) if tree.body else tree.text(deep=True) or ""),
    }
