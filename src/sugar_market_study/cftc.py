"""Offline loading and publication-timing controls for Sugar No. 11 COT data."""

from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime, time, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Final

from sugar_market_study.provenance import SourceRecord, StudyError, parse_timestamp
from sugar_market_study.signals import PositioningRelease

CFTC_CODE: Final = "080732"
EXPECTED_NAME_FRAGMENT: Final = "SUGAR NO. 11"
PUBLIC_FIELDS: Final = (
    "report_date",
    "cftc_contract_market_code",
    "market_and_exchange_names",
    "open_interest_contracts",
    "managed_money_long_contracts",
    "managed_money_short_contracts",
    "managed_money_spread_contracts",
    "contract_units_original",
    "report_type",
)
CALENDAR_FIELDS: Final = (
    "report_date",
    "release_date",
    "release_time",
    "release_timezone",
)
EVENT_VERIFICATION_FIELDS: Final = (
    "report_date",
    "release_date",
    "release_time",
    "release_timezone",
    "available_at_utc",
    "verification_basis",
    "source_url",
    "source_sha256",
    "source_bytes",
    "retrieved_at_utc",
)
EVENT_VERIFICATION_BASIS: Final = "official_weekly_page_updated_footer_plus_standing_1530_et_policy"
ORDINARY_RULE_BASIS: Final = "cftc_ordinary_rule_estimate_not_holiday_verified"
AvailabilityOverride = tuple[datetime, str]


def _eastern_offset(release_date: date) -> timezone:
    """Return the U.S. Eastern offset for a release date.

    COT releases occur well away from the 02:00 DST transition hour, so date-level
    U.S. rules are sufficient and avoid an external timezone-data dependency.
    """

    march_first = date(release_date.year, 3, 1)
    second_sunday_march = march_first + timedelta(days=(6 - march_first.weekday()) % 7 + 7)
    november_first = date(release_date.year, 11, 1)
    first_sunday_november = november_first + timedelta(days=(6 - november_first.weekday()) % 7)
    daylight = second_sunday_march <= release_date < first_sunday_november
    return timezone(timedelta(hours=-4 if daylight else -5))


def _release_at_utc(release_date: date, release_time: time = time(15, 30)) -> datetime:
    return datetime.combine(release_date, release_time, _eastern_offset(release_date)).astimezone(
        UTC
    )


def _row_release_at_utc(row: Mapping[str, str], *, public_path: str) -> datetime:
    if row["release_timezone"] != "America/New_York":
        raise StudyError(f"unexpected CFTC calendar timezone in {public_path}")
    try:
        parsed_time = time.fromisoformat(row["release_time"])
        release_date = date.fromisoformat(row["release_date"])
    except ValueError as exc:
        raise StudyError(f"invalid CFTC calendar timing in {public_path}") from exc
    if parsed_time.tzinfo is not None:
        raise StudyError(f"CFTC local release time must be timezone-naive in {public_path}")
    return _release_at_utc(release_date, parsed_time)


def _calendar_rows(
    repo_root: Path, sources: Iterable[SourceRecord]
) -> tuple[dict[date, AvailabilityOverride], dict[date, datetime]]:
    overrides: dict[date, AvailabilityOverride] = {}
    verifications: dict[date, datetime] = {}
    calendar_source_ids: set[str] = set()
    verification_source_ids: set[str] = set()
    for source in sources:
        if source.source_type not in {
            "cftc_release_calendar",
            "cftc_release_verification",
        }:
            continue
        path = repo_root.joinpath(*PurePosixPath(source.public_path).parts)
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = tuple(reader.fieldnames or ())
            expected = (
                CALENDAR_FIELDS
                if source.source_type == "cftc_release_calendar"
                else EVENT_VERIFICATION_FIELDS
            )
            if not all(field in fields for field in expected):
                raise StudyError(f"unexpected CFTC timing columns in {source.public_path}")
            rows = list(reader)
        if not rows:
            raise StudyError(f"empty CFTC timing extract: {source.public_path}")

        if source.source_type == "cftc_release_verification":
            verification_source_ids.add(source.source_id)
            for row in rows:
                if row["verification_basis"] != EVENT_VERIFICATION_BASIS:
                    raise StudyError(
                        f"unexpected CFTC event-verification basis in {source.public_path}"
                    )
                if row["release_time"] != "15:30":
                    raise StudyError(
                        f"unexpected CFTC event-verification time in {source.public_path}"
                    )
                report_date = date.fromisoformat(row["report_date"])
                verified_at = _row_release_at_utc(row, public_path=source.public_path)
                stated_at = parse_timestamp(row["available_at_utc"], field="available_at_utc")
                if stated_at != verified_at:
                    raise StudyError(f"CFTC event-verification UTC mismatch for {report_date}")
                digest = row["source_sha256"].lower()
                if len(digest) != 64 or any(
                    character not in "0123456789abcdef" for character in digest
                ):
                    raise StudyError(f"invalid CFTC event-verification digest for {report_date}")
                try:
                    source_bytes = int(row["source_bytes"])
                except ValueError as exc:
                    raise StudyError(
                        f"invalid CFTC event-verification byte count for {report_date}"
                    ) from exc
                if source_bytes <= 0:
                    raise StudyError(
                        f"invalid CFTC event-verification byte count for {report_date}"
                    )
                if not row["source_url"].startswith("https://www.cftc.gov/"):
                    raise StudyError(f"invalid CFTC event-verification URL for {report_date}")
                if parse_timestamp(row["retrieved_at_utc"], field="retrieved_at_utc") is None:
                    raise AssertionError("event-verification retrieval time unexpectedly absent")
                if report_date in verifications:
                    raise StudyError(f"duplicate CFTC event verification for {report_date}")
                verifications[report_date] = verified_at
            continue

        calendar_source_ids.add(source.source_id)
        for row in rows:
            report_date = date.fromisoformat(row["report_date"])
            available_at = _row_release_at_utc(row, public_path=source.public_path)
            basis = row.get("availability_basis", "").strip()
            kind = row.get("availability_kind", "").strip()
            if basis:
                if not basis.startswith("cftc_"):
                    raise StudyError(f"invalid CFTC availability basis for {report_date}")
                if kind not in {"verified_release", "current_snapshot_correction"}:
                    raise StudyError(f"invalid CFTC availability kind for {report_date}")
                if kind == "verified_release" and row["release_time"] != "15:30":
                    raise StudyError(f"verified CFTC release must use 15:30 for {report_date}")
                if kind == "current_snapshot_correction" and row["release_time"] not in {
                    "15:30",
                    "23:59:59",
                }:
                    raise StudyError(f"invalid CFTC correction boundary for {report_date}")
            elif "reason" in row:
                reason = row.get("reason", "")
                basis = (
                    "cftc_official_appropriations_catch_up"
                    if "appropriations" in reason
                    else "cftc_official_special_announcement"
                )
            else:
                basis = "cftc_official_release_schedule"
            if report_date in overrides:
                raise StudyError(f"duplicate CFTC calendar override for {report_date}")
            overrides[report_date] = (available_at, basis)
    if len(calendar_source_ids) != 4:
        raise StudyError("expected four official CFTC release-timing extracts")
    if len(verification_source_ids) != 1:
        raise StudyError("expected one official CFTC emitted-event verification extract")
    return overrides, verifications


def publication_eligibility(
    report_date: date,
    overrides: Mapping[date, AvailabilityOverride],
) -> tuple[datetime, str]:
    """Return actual retained or explicitly rule-modelled publication eligibility."""

    override = overrides.get(report_date)
    if override is not None:
        return override
    if report_date.weekday() == 1:  # ordinary Tuesday observation
        release_date = report_date + timedelta(days=3)
    elif report_date.weekday() == 0:  # holiday-shifted Monday observation
        release_date = report_date + timedelta(days=4)
    else:
        raise StudyError(f"unmapped non-Monday/Tuesday CFTC report date: {report_date}")
    return _release_at_utc(release_date), ORDINARY_RULE_BASIS


def _integer(row: Mapping[str, str], field: str) -> int:
    try:
        parsed = int(row[field])
    except (KeyError, ValueError) as exc:
        raise StudyError(f"invalid CFTC integer field {field!r}") from exc
    if parsed < 0:
        raise StudyError(f"negative CFTC count in {field!r}")
    return parsed


def load_positioning_releases(
    repo_root: Path, sources: Iterable[SourceRecord]
) -> tuple[PositioningRelease, ...]:
    """Load the newest CFTC snapshot and apply publication-availability controls."""

    records = tuple(sources)
    history_sources = [
        source for source in records if source.source_type == "cftc_selected_history"
    ]
    if not history_sources:
        raise StudyError("CFTC selected-history source is missing")
    source = max(history_sources, key=lambda item: (item.retrieved_at_utc, item.source_id))
    overrides, event_verifications = _calendar_rows(repo_root, records)
    path = repo_root.joinpath(*PurePosixPath(source.public_path).parts)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != PUBLIC_FIELDS:
            raise StudyError(f"unexpected CFTC extract columns in {source.public_path}")
        rows = list(reader)
    if len(rows) < 157:
        raise StudyError("CFTC history is too short for one eligible signal evaluation")

    output: list[PositioningRelease] = []
    for row in rows:
        report_date = date.fromisoformat(row["report_date"])
        if row["cftc_contract_market_code"] != CFTC_CODE:
            raise StudyError("CFTC extract contains a non-Sugar No. 11 contract")
        market_name = row["market_and_exchange_names"]
        if EXPECTED_NAME_FRAGMENT not in market_name.upper():
            raise StudyError(f"unexpected CFTC market name: {market_name!r}")
        if row["report_type"] != "FutOnly":
            raise StudyError("CFTC extract is not futures-only")
        if row["contract_units_original"] != "(CONTRACTS OF 112,000 POUNDS)":
            raise StudyError("unexpected Sugar No. 11 contract units")
        available_at, basis = publication_eligibility(report_date, overrides)
        verified_event_at = event_verifications.get(report_date)
        if verified_event_at is not None:
            if available_at != verified_event_at:
                raise StudyError(f"CFTC emitted-event verification disagrees for {report_date}")
            basis = (
                "cftc_official_event_weekly_page_verified"
                if basis == ORDINARY_RULE_BASIS
                else f"{basis}_and_event_page_verified"
            )
        output.append(
            PositioningRelease(
                report_date=report_date,
                available_at_utc=available_at,
                managed_money_long_contracts=_integer(row, "managed_money_long_contracts"),
                managed_money_short_contracts=_integer(row, "managed_money_short_contracts"),
                open_interest_contracts=_integer(row, "open_interest_contracts"),
                availability_basis=basis,
                source_id=source.source_id,
                source_url=source.source_url,
                source_sha256=source.public_sha256,
                market_name=market_name,
                cftc_contract_market_code=CFTC_CODE,
            )
        )
    ordered = tuple(sorted(output, key=lambda item: item.available_at_utc))
    if len({item.report_date for item in ordered}) != len(ordered):
        raise StudyError("duplicate CFTC report dates")
    if {item.report_date for item in ordered} & set(event_verifications) != set(
        event_verifications
    ):
        raise StudyError("CFTC event verification contains a date outside the selected history")
    return ordered
