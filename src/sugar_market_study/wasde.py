"""Append-only USDA WASDE sugar vintage facts and deterministic revisions."""

from __future__ import annotations

import csv
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from typing import Final

from sugar_market_study.provenance import SourceRecord, StudyError

RAW_FIELDS: Final = (
    "WasdeNumber",
    "ReportDate",
    "ReportTitle",
    "Attribute",
    "ReliabilityProjection",
    "Commodity",
    "Region",
    "MarketYear",
    "ProjEstFlag",
    "AnnualQuarterFlag",
    "Value",
    "Unit",
    "ReleaseDate",
    "ReleaseTime",
    "ForecastYear",
    "ForecastMonth",
)

US_REPORT_TITLE: Final = "U.S. Sugar Supply and Use"
MEXICO_REPORT_TITLE: Final = "Mexico Sugar Supply and Use and High Fructose Corn Syrup Consumption"
US_REGION: Final = "United States"
MEXICO_REGION: Final = "Mexico"
US_RAW_UNIT: Final = "1000 Short Tons, Raw Value"
MEXICO_RAW_UNIT: Final = "1000 Metric Tons, Actual Weight"
RATIO_ATTRIBUTE: Final = "Stocks to Use Ratio"
RATIO_NORMALIZED_UNIT: Final = "Percent"
RATIO_UNIT_WARNING: Final = (
    "USDA historical CSV labels Stocks to Use Ratio with the table's tonnage unit; "
    "value is normalized as percent while the raw unit is retained."
)


@dataclass(frozen=True, slots=True)
class WasdeFact:
    """One immutable value from one exact USDA artifact version."""

    vintage_id: str
    wasde_number: int
    report_date: date
    report_label: str
    effective_at_utc: datetime
    available_at_utc: datetime
    available_at_basis: str
    retrieved_at_utc: datetime
    source_version: str
    is_corrected_repost: bool
    source_id: str
    source_url: str
    source_sha256: str
    report_title: str
    commodity: str
    region: str
    market_year: str
    projection_status: str
    attribute: str
    raw_value: str
    value: Decimal
    raw_unit: str
    normalized_unit: str
    unit_warning: str


@dataclass(frozen=True, slots=True)
class WasdeRevision:
    """Revision versus the immediately prior publicly eligible matching fact."""

    fact: WasdeFact
    prior_vintage_id: str
    prior_value: Decimal

    @property
    def revision(self) -> Decimal:
        return self.fact.value - self.prior_value


def _parse_release_time(value: str) -> str:
    whole, separator, fraction = value.partition(".")
    try:
        datetime.strptime(whole, "%H:%M:%S")
    except ValueError as exc:
        raise StudyError(f"invalid WASDE ReleaseTime: {value!r}") from exc
    if separator and (not fraction or not fraction.isdigit()):
        raise StudyError(f"invalid WASDE ReleaseTime fraction: {value!r}")
    return whole


def _validate_target_row(row: dict[str, str], source: SourceRecord) -> None:
    if row["Commodity"] != "Sugar" or row["AnnualQuarterFlag"] != "Annual":
        raise StudyError(f"non-target row in USDA sugar extract {source.public_path}")
    report_region = (row["ReportTitle"], row["Region"])
    if report_region not in {
        (US_REPORT_TITLE, US_REGION),
        (MEXICO_REPORT_TITLE, MEXICO_REGION),
    }:
        raise StudyError(f"unexpected report/region in USDA extract: {report_region!r}")
    if not row["MarketYear"] or not row["Attribute"]:
        raise StudyError(f"blank USDA fact key in {source.public_path}")
    expected_unit = US_RAW_UNIT if row["Region"] == US_REGION else MEXICO_RAW_UNIT
    if row["Unit"] != expected_unit:
        raise StudyError(f"unexpected raw unit in {source.public_path}: {row['Unit']!r}")
    if _parse_release_time(row["ReleaseTime"]) != "12:00:00":
        raise StudyError(f"unexpected USDA release time in {source.public_path}")


def _read_source(repo_root: Path, source: SourceRecord) -> tuple[WasdeFact, ...]:
    if source.source_effective_at_utc is None or source.available_at_utc is None:
        raise StudyError(f"USDA source lacks timing metadata: {source.source_id}")
    path = repo_root.joinpath(*PurePosixPath(source.public_path).parts)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != RAW_FIELDS:
            raise StudyError(f"unexpected USDA extract columns in {source.public_path}")
        rows = list(reader)
    if not rows:
        raise StudyError(f"empty USDA sugar extract: {source.public_path}")

    wasde_numbers: set[int] = set()
    report_labels: set[str] = set()
    seen_keys: set[tuple[str, str, str]] = set()
    output: list[WasdeFact] = []
    vintage_id = f"{source.source_version}:{source.public_sha256[:12]}"
    for row in rows:
        _validate_target_row(row, source)
        try:
            wasde_number = int(row["WasdeNumber"])
            value = Decimal(row["Value"])
        except (InvalidOperation, ValueError) as exc:
            raise StudyError(f"invalid numeric USDA fact in {source.public_path}") from exc
        # Some legitimate decomposition rows (for example balancing/miscellaneous)
        # can be negative; preserve them rather than imposing a commodity assumption.
        if wasde_number <= 0 or not value.is_finite():
            raise StudyError(f"invalid USDA value in {source.public_path}")
        key = (row["Region"], row["MarketYear"], row["Attribute"])
        if key in seen_keys:
            raise StudyError(f"duplicate USDA fact key in {source.public_path}: {key!r}")
        seen_keys.add(key)
        wasde_numbers.add(wasde_number)
        report_labels.add(row["ReportDate"])
        ratio = row["Region"] == US_REGION and row["Attribute"] == RATIO_ATTRIBUTE
        output.append(
            WasdeFact(
                vintage_id=vintage_id,
                wasde_number=wasde_number,
                report_date=source.source_effective_at_utc.date(),
                report_label=row["ReportDate"],
                effective_at_utc=source.source_effective_at_utc.astimezone(UTC),
                available_at_utc=source.available_at_utc.astimezone(UTC),
                available_at_basis=source.available_at_basis,
                retrieved_at_utc=source.retrieved_at_utc.astimezone(UTC),
                source_version=source.source_version,
                is_corrected_repost=source.is_corrected_repost,
                source_id=source.source_id,
                source_url=source.source_url,
                source_sha256=source.public_sha256,
                report_title=row["ReportTitle"],
                commodity="Sugar",
                region=row["Region"],
                market_year=row["MarketYear"],
                projection_status=row["ProjEstFlag"],
                attribute=row["Attribute"],
                raw_value=row["Value"],
                value=value,
                raw_unit=row["Unit"],
                normalized_unit=RATIO_NORMALIZED_UNIT if ratio else row["Unit"],
                unit_warning=RATIO_UNIT_WARNING if ratio else "",
            )
        )
    if len(wasde_numbers) != 1 or len(report_labels) != 1:
        raise StudyError(f"mixed WASDE issue metadata in {source.public_path}")
    return tuple(sorted(output, key=lambda fact: (fact.region, fact.market_year, fact.attribute)))


def load_wasde_facts(repo_root: Path, sources: Iterable[SourceRecord]) -> tuple[WasdeFact, ...]:
    """Load every committed USDA artifact version without overwriting history."""

    usda_sources = [
        source for source in sources if source.source_type == "usda_wasde_sugar_snapshot"
    ]
    if not usda_sources:
        raise StudyError("USDA sugar snapshots are missing")
    ordered_sources = sorted(
        usda_sources,
        key=lambda item: (
            item.available_at_utc or datetime.min.replace(tzinfo=UTC),
            item.retrieved_at_utc,
            item.source_id,
        ),
    )
    facts = tuple(fact for source in ordered_sources for fact in _read_source(repo_root, source))
    identities = [
        (fact.vintage_id, fact.region, fact.market_year, fact.attribute) for fact in facts
    ]
    if len(identities) != len(set(identities)):
        raise StudyError("duplicate append-only USDA fact identity")
    return facts


def visible_as_of(facts: Iterable[WasdeFact], cutoff: datetime) -> tuple[WasdeFact, ...]:
    """Return the newest eligible fact for each region/market-year/attribute key."""

    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise StudyError("cutoff must include a UTC offset")
    normalized = cutoff.astimezone(UTC)
    visible: dict[tuple[str, str, str], WasdeFact] = {}
    for fact in sorted(
        facts,
        key=lambda item: (item.available_at_utc, item.retrieved_at_utc, item.vintage_id),
    ):
        if fact.available_at_utc <= normalized:
            visible[(fact.region, fact.market_year, fact.attribute)] = fact
    return tuple(
        sorted(visible.values(), key=lambda item: (item.region, item.market_year, item.attribute))
    )


def build_revisions(facts: Iterable[WasdeFact]) -> tuple[WasdeRevision, ...]:
    """Compare each fact with the immediately prior eligible matching fact."""

    grouped: dict[tuple[str, str, str, str], list[WasdeFact]] = defaultdict(list)
    for fact in facts:
        grouped[(fact.region, fact.market_year, fact.attribute, fact.normalized_unit)].append(fact)
    output: list[WasdeRevision] = []
    for group in grouped.values():
        ordered = sorted(
            group,
            key=lambda item: (item.available_at_utc, item.retrieved_at_utc, item.vintage_id),
        )
        for previous, current in zip(ordered[:-1], ordered[1:], strict=True):
            output.append(
                WasdeRevision(
                    fact=current,
                    prior_vintage_id=previous.vintage_id,
                    prior_value=previous.value,
                )
            )
    return tuple(
        sorted(
            output,
            key=lambda item: (
                item.fact.available_at_utc,
                item.fact.region,
                item.fact.market_year,
                item.fact.attribute,
            ),
        )
    )
