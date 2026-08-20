"""Deterministic offline build of report-ready Sugar No. 11 research tables."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Final

from sugar_market_study.cftc import load_positioning_releases
from sugar_market_study.provenance import (
    SourceRecord,
    StudyError,
    iso_utc,
    parse_timestamp,
    verify_sources,
)
from sugar_market_study.signals import SIGNAL_RULE_ID, evaluate_releases
from sugar_market_study.wasde import WasdeFact, build_revisions, load_wasde_facts

POSITIONING_FIELDS: Final = (
    "market_name",
    "cftc_contract_market_code",
    "report_date",
    "available_at_utc",
    "availability_basis",
    "source_id",
    "source_url",
    "source_sha256",
    "managed_money_long_contracts",
    "managed_money_short_contracts",
    "managed_money_net_contracts",
    "open_interest_contracts",
    "normalized_net",
    "prior_release_count",
    "prior_q10",
    "previous_normalized_net",
    "previous_was_q10_extreme",
    "positive_reversal",
    "cooldown_eligible",
    "signal_emitted",
    "rule_id",
)

WASDE_FIELDS: Final = (
    "vintage_id",
    "wasde_number",
    "report_date",
    "report_label",
    "effective_at_utc",
    "available_at_utc",
    "available_at_basis",
    "retrieved_at_utc",
    "source_version",
    "is_corrected_repost",
    "source_id",
    "source_url",
    "source_sha256",
    "report_title",
    "commodity",
    "region",
    "market_year",
    "projection_status",
    "attribute",
    "raw_value",
    "value",
    "raw_unit",
    "normalized_unit",
    "unit_warning",
)

REVISION_FIELDS: Final = (
    "vintage_id",
    "prior_vintage_id",
    "wasde_number",
    "report_date",
    "report_label",
    "effective_at_utc",
    "available_at_utc",
    "region",
    "market_year",
    "attribute",
    "normalized_unit",
    "value",
    "prior_value",
    "revision",
    "source_version",
    "is_corrected_repost",
)


def _decimal(value: Decimal | None) -> str:
    if value is None:
        return ""
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def _bool(value: bool | None) -> str:
    return "" if value is None else str(value).lower()


def _csv_bytes(fields: tuple[str, ...], rows: Iterable[Mapping[str, object]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def _load_study_config(repo_root: Path) -> tuple[datetime, date, date]:
    path = repo_root / "config" / "study.json"
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise StudyError(f"invalid study configuration: {path}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise StudyError("study configuration must be a schema-version 1 object")
    as_of_raw = raw.get("as_of_utc")
    cftc_raw = raw.get("cftc")
    if not isinstance(as_of_raw, str) or not isinstance(cftc_raw, dict):
        raise StudyError("study configuration is missing as_of_utc or cftc")
    if cftc_raw.get("contract_market_code") != "080732":
        raise StudyError("study configuration does not select Sugar No. 11 code 080732")
    first_raw = cftc_raw.get("first_report_date")
    last_raw = cftc_raw.get("last_report_date")
    if not isinstance(first_raw, str) or not isinstance(last_raw, str):
        raise StudyError("study configuration is missing CFTC date boundaries")
    as_of = parse_timestamp(as_of_raw, field="as_of_utc")
    if as_of is None:  # pragma: no cover - blank is not allowed
        raise AssertionError("as-of timestamp unexpectedly absent")
    try:
        first_report_date = date.fromisoformat(first_raw)
        last_report_date = date.fromisoformat(last_raw)
    except ValueError as exc:
        raise StudyError("invalid configured CFTC date boundary") from exc
    if first_report_date > last_report_date:
        raise StudyError("configured CFTC date boundaries are reversed")
    return as_of, first_report_date, last_report_date


def _positioning_csv(
    repo_root: Path,
    sources: tuple[SourceRecord, ...],
    *,
    as_of_utc: datetime,
    first_report_date: date,
    last_report_date: date,
) -> tuple[bytes, dict[str, object]]:
    source_releases = load_positioning_releases(repo_root, sources)
    if (
        source_releases[0].report_date != first_report_date
        or source_releases[-1].report_date != last_report_date
    ):
        raise StudyError("CFTC source history does not match configured report-date boundaries")
    releases = tuple(
        release for release in source_releases if release.available_at_utc <= as_of_utc
    )
    if not releases:
        raise StudyError("no CFTC release is eligible at the configured as_of_utc")
    evaluated = evaluate_releases(releases)
    rows: list[dict[str, object]] = []
    for release, evaluation in evaluated:
        rows.append(
            {
                "market_name": release.market_name,
                "cftc_contract_market_code": release.cftc_contract_market_code,
                "report_date": release.report_date.isoformat(),
                "available_at_utc": iso_utc(release.available_at_utc),
                "availability_basis": release.availability_basis,
                "source_id": release.source_id,
                "source_url": release.source_url,
                "source_sha256": release.source_sha256,
                "managed_money_long_contracts": release.managed_money_long_contracts,
                "managed_money_short_contracts": release.managed_money_short_contracts,
                "managed_money_net_contracts": release.managed_money_net_contracts,
                "open_interest_contracts": release.open_interest_contracts,
                "normalized_net": _decimal(release.normalized_net),
                "prior_release_count": evaluation.prior_release_count,
                "prior_q10": _decimal(evaluation.prior_q10),
                "previous_normalized_net": _decimal(evaluation.previous_normalized_net),
                "previous_was_q10_extreme": _bool(evaluation.previous_was_q10_extreme),
                "positive_reversal": _bool(evaluation.positive_reversal),
                "cooldown_eligible": _bool(evaluation.cooldown_eligible),
                "signal_emitted": _bool(evaluation.signal_emitted),
                "rule_id": SIGNAL_RULE_ID,
            }
        )
    signals = [
        release.report_date.isoformat()
        for release, evaluation in evaluated
        if evaluation.signal_emitted
    ]
    latest_release, latest_evaluation = evaluated[-1]
    summary = {
        "release_count": len(evaluated),
        "first_report_date": evaluated[0][0].report_date.isoformat(),
        "last_report_date": latest_release.report_date.isoformat(),
        "latest_available_at_utc": iso_utc(latest_release.available_at_utc),
        "latest_normalized_net": _decimal(latest_release.normalized_net),
        "latest_prior_q10": _decimal(latest_evaluation.prior_q10),
        "signal_count": len(signals),
        "signal_report_dates": signals,
    }
    return _csv_bytes(POSITIONING_FIELDS, rows), summary


def _fact_row(fact: WasdeFact) -> dict[str, object]:
    return {
        "vintage_id": fact.vintage_id,
        "wasde_number": fact.wasde_number,
        "report_date": fact.report_date.isoformat(),
        "report_label": fact.report_label,
        "effective_at_utc": iso_utc(fact.effective_at_utc),
        "available_at_utc": iso_utc(fact.available_at_utc),
        "available_at_basis": fact.available_at_basis,
        "retrieved_at_utc": iso_utc(fact.retrieved_at_utc),
        "source_version": fact.source_version,
        "is_corrected_repost": _bool(fact.is_corrected_repost),
        "source_id": fact.source_id,
        "source_url": fact.source_url,
        "source_sha256": fact.source_sha256,
        "report_title": fact.report_title,
        "commodity": fact.commodity,
        "region": fact.region,
        "market_year": fact.market_year,
        "projection_status": fact.projection_status,
        "attribute": fact.attribute,
        "raw_value": fact.raw_value,
        "value": _decimal(fact.value),
        "raw_unit": fact.raw_unit,
        "normalized_unit": fact.normalized_unit,
        "unit_warning": fact.unit_warning,
    }


def _value_by(
    facts: tuple[WasdeFact, ...], *, report: str, region: str, market_year: str, attribute: str
) -> Decimal:
    matches = [
        fact.value
        for fact in facts
        if fact.report_date.isoformat() == report
        and fact.region == region
        and fact.market_year == market_year
        and fact.attribute == attribute
    ]
    if len(matches) != 1:
        raise StudyError(
            f"expected one WASDE fact for {report}/{region}/{market_year}/{attribute}; "
            f"found {len(matches)}"
        )
    return matches[0]


def _wasde_outputs(
    repo_root: Path, sources: tuple[SourceRecord, ...], *, as_of_utc: datetime
) -> tuple[bytes, bytes, dict[str, object]]:
    all_facts = load_wasde_facts(repo_root, sources)
    facts = tuple(fact for fact in all_facts if fact.available_at_utc <= as_of_utc)
    if not facts:
        raise StudyError("no USDA fact is eligible at the configured as_of_utc")
    revisions = build_revisions(facts)
    fact_bytes = _csv_bytes(WASDE_FIELDS, (_fact_row(fact) for fact in facts))
    revision_rows = (
        {
            "vintage_id": revision.fact.vintage_id,
            "prior_vintage_id": revision.prior_vintage_id,
            "wasde_number": revision.fact.wasde_number,
            "report_date": revision.fact.report_date.isoformat(),
            "report_label": revision.fact.report_label,
            "effective_at_utc": iso_utc(revision.fact.effective_at_utc),
            "available_at_utc": iso_utc(revision.fact.available_at_utc),
            "region": revision.fact.region,
            "market_year": revision.fact.market_year,
            "attribute": revision.fact.attribute,
            "normalized_unit": revision.fact.normalized_unit,
            "value": _decimal(revision.fact.value),
            "prior_value": _decimal(revision.prior_value),
            "revision": _decimal(revision.revision),
            "source_version": revision.fact.source_version,
            "is_corrected_repost": _bool(revision.fact.is_corrected_repost),
        }
        for revision in revisions
    )
    revision_bytes = _csv_bytes(REVISION_FIELDS, revision_rows)

    comparison_reports = {"2026-07-10", "2026-08-12"}
    comparison_available = comparison_reports <= {fact.report_date.isoformat() for fact in facts}
    comparison: dict[str, dict[str, str]] = {}
    if comparison_available:
        us_changes = {
            attribute: _decimal(
                _value_by(
                    facts,
                    report="2026-08-12",
                    region="United States",
                    market_year="2026/27",
                    attribute=attribute,
                )
                - _value_by(
                    facts,
                    report="2026-07-10",
                    region="United States",
                    market_year="2026/27",
                    attribute=attribute,
                )
            )
            for attribute in (
                "Beginning Stocks",
                "Production",
                "Total Supply",
                "Ending Stocks",
                "Stocks to Use Ratio",
            )
        }
        mexico_changes = {
            attribute: _decimal(
                _value_by(
                    facts,
                    report="2026-08-12",
                    region="Mexico",
                    market_year="2026/27",
                    attribute=attribute,
                )
                - _value_by(
                    facts,
                    report="2026-07-10",
                    region="Mexico",
                    market_year="2026/27",
                    attribute=attribute,
                )
            )
            for attribute in ("Beginning Stocks", "Production", "Exports", "Ending Stocks")
        }
        comparison = {
            "United States 2026/27": us_changes,
            "Mexico 2026/27": mexico_changes,
        }
    summary = {
        "artifact_version_count": len({fact.vintage_id for fact in facts}),
        "fact_count": len(facts),
        "revision_count": len(revisions),
        "first_report_date": min(fact.report_date for fact in facts).isoformat(),
        "last_report_date": max(fact.report_date for fact in facts).isoformat(),
        "latest_available_at_utc": iso_utc(max(fact.available_at_utc for fact in facts)),
        "regions": sorted({fact.region for fact in facts}),
        "market_years": sorted({fact.market_year for fact in facts}),
        "august_2026_vs_july_2026": comparison,
        "corrected_reposts": sorted(
            {
                f"{fact.report_label} {fact.source_version}"
                for fact in facts
                if fact.is_corrected_repost
            }
        ),
        "unit_warning": (
            "The raw USDA CSV applies the table tonnage unit to Stocks to Use Ratio. "
            "The pipeline retains that raw unit and explicitly normalizes the ratio to percent."
        ),
    }
    return fact_bytes, revision_bytes, summary


def render_outputs(repo_root: Path) -> Mapping[Path, bytes]:
    """Render every deterministic output in memory after source-integrity checks."""

    sources = verify_sources(repo_root)
    as_of_utc, first_report_date, last_report_date = _load_study_config(repo_root)
    positioning, positioning_summary = _positioning_csv(
        repo_root,
        sources,
        as_of_utc=as_of_utc,
        first_report_date=first_report_date,
        last_report_date=last_report_date,
    )
    vintages, revisions, wasde_summary = _wasde_outputs(repo_root, sources, as_of_utc=as_of_utc)
    retrieved_at = max(source.retrieved_at_utc for source in sources).astimezone(UTC)
    positioning_latest_raw = positioning_summary.get("latest_available_at_utc")
    wasde_latest_raw = wasde_summary.get("latest_available_at_utc")
    if not isinstance(positioning_latest_raw, str) or not isinstance(wasde_latest_raw, str):
        raise StudyError("derived summaries are missing latest availability timestamps")
    positioning_latest = parse_timestamp(
        positioning_latest_raw, field="positioning.latest_available_at_utc"
    )
    wasde_latest = parse_timestamp(wasde_latest_raw, field="wasde.latest_available_at_utc")
    if positioning_latest is None or wasde_latest is None:  # pragma: no cover - nonblank above
        raise AssertionError("latest availability timestamp unexpectedly absent")
    data_current_through = max(positioning_latest, wasde_latest).date().isoformat()
    summary = {
        "schema_version": 1,
        "study": {
            "commodity": "Sugar No. 11",
            "as_of_utc": iso_utc(as_of_utc),
            "built_from_public_sources_only": True,
            "data_current_through": data_current_through,
            "latest_source_retrieval_at_utc": iso_utc(retrieved_at),
            "trade_or_execution_system": False,
        },
        "positioning": positioning_summary,
        "wasde": wasde_summary,
        "methodology_warnings": [
            (
                "The signal is a transferred, frozen research rule; it is not an "
                "investment recommendation."
            ),
            (
                "CFTC history is a current official snapshot, not a complete value-vintage "
                "archive; the positioning study is retrospective and publication-aware, not "
                "a strict point-in-time backtest."
            ),
            (
                "Ordinary historical COT release dates are rule-modelled when no retained "
                "official exception exists."
            ),
            "USDA consolidated CSV eligibility is conservatively later than the report release.",
            "October 2025 has no WASDE release and is not imputed.",
            (
                "No price series, return backtest, transaction costs, P&L, or broker "
                "action is included."
            ),
        ],
    }
    summary_bytes = (json.dumps(summary, indent=2, sort_keys=True) + "\n").encode("utf-8")
    derived = repo_root / "data" / "derived"
    return {
        derived / "positioning_releases.csv": positioning,
        derived / "wasde_sugar_vintages.csv": vintages,
        derived / "wasde_sugar_revisions.csv": revisions,
        derived / "study_summary.json": summary_bytes,
    }


def build_outputs(repo_root: Path, *, check: bool = False) -> tuple[Path, ...]:
    """Write derived artifacts, or verify that committed artifacts are current."""

    outputs = render_outputs(repo_root.resolve())
    for path, expected in outputs.items():
        if check:
            try:
                actual = path.read_bytes()
            except FileNotFoundError as exc:
                raise StudyError(f"derived output is missing: {path}") from exc
            if actual != expected:
                raise StudyError(f"derived output is stale: {path}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(expected)
    return tuple(outputs)
