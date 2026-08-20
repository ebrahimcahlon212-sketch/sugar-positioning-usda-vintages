"""Explicit network acquisition for public CFTC and USDA factual extracts.

The offline package never imports this module. Every acquired upstream payload and
public extract is content-addressed; an existing file is verified, never overwritten.
The source manifest is append-only by public content hash.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import sys
from datetime import UTC, date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Final, cast
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT: Final = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sugar_market_study.cftc import PUBLIC_FIELDS as CFTC_PUBLIC_FIELDS  # noqa: E402
from sugar_market_study.provenance import MANIFEST_FIELDS, iso_utc  # noqa: E402
from sugar_market_study.wasde import RAW_FIELDS as USDA_RAW_FIELDS  # noqa: E402

CFTC_DATASET: Final = "https://publicreporting.cftc.gov/resource/72hh-3qpy.json"
CFTC_LANDING: Final = (
    "https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalCompressed/index.htm"
)
CFTC_QUERY_FIELDS: Final = (
    "report_date_as_yyyy_mm_dd",
    "cftc_contract_market_code",
    "market_and_exchange_names",
    "open_interest_all",
    "m_money_positions_long_all",
    "m_money_positions_short_all",
    "m_money_positions_spread",
    "contract_units",
    "futonly_or_combined",
)
USDA_LANDING: Final = "https://www.usda.gov/historical-wasde-report-data-3"
USDA_BASE: Final = "https://www.usda.gov/sites/default/files/documents/"
USDA_FILES: Final = (
    "oce-wasde-report-data-2025-05.csv",
    "oce-wasde-report-data-2025-06.csv",
    "oce-wasde-report-data-2025-07.csv",
    "oce-wasde-report-data-2025-08.csv",
    "oce-wasde-report-data-2025-09.csv",
    "oce-wasde-report-data-2025-11.csv",
    "oce-wasde-report-data-2025-12.csv",
    "oce-wasde-report-data-2026-01.csv",
    "oce-wasde-report-data-2026-02.csv",
    "oce-wasde-report-data-2026-03.csv",
    "oce-wasde-report-data-2026-04.csv",
    "oce-wasde-report-data-2026-05-V2.csv",
    "oce-wasde-report-data-2026-06-V2.csv",
    "oce-wasde-report-data-2026-07.csv",
    "oce-wasde-report-data-2026-08.csv",
)
V2_OFFICIAL_RELEASE_DATES: Final = {
    "oce-wasde-report-data-2026-05-V2.csv": date(2026, 5, 12),
    "oce-wasde-report-data-2026-06-V2.csv": date(2026, 6, 11),
}


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _download(url: str, *, accept: str) -> bytes:
    request = Request(  # noqa: S310 - caller passes only fixed government endpoints
        url,
        headers={
            "Accept": accept,
            "User-Agent": "sugar-positioning-usda-vintages/0.1 (+public research)",
        },
    )
    with urlopen(request, timeout=90) as response:  # noqa: S310 - fixed endpoints above
        if response.status != 200:
            raise RuntimeError(f"source returned HTTP {response.status}: {url}")
        return cast(bytes, response.read())


def _write_immutable(path: Path, payload: bytes) -> None:
    if path.exists():
        if path.read_bytes() != payload:
            raise RuntimeError(f"refusing to overwrite different content: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _cftc_query_url() -> str:
    params = {
        "$select": ",".join(CFTC_QUERY_FIELDS),
        "$where": (
            "cftc_contract_market_code='080732' "
            "AND report_date_as_yyyy_mm_dd>='2009-09-01T00:00:00.000' "
            "AND report_date_as_yyyy_mm_dd<='2026-08-11T00:00:00.000'"
        ),
        "$order": "report_date_as_yyyy_mm_dd",
        "$limit": "5000",
    }
    return f"{CFTC_DATASET}?{urlencode(params)}"


def _cftc_extract(payload: bytes) -> bytes:
    decoded: Any = json.loads(payload)
    if not isinstance(decoded, list):
        raise ValueError("CFTC API response is not a JSON array")
    rows: list[dict[str, str]] = []
    dates: set[str] = set()
    for item in decoded:
        if not isinstance(item, dict) or set(item) != set(CFTC_QUERY_FIELDS):
            raise ValueError("CFTC API row has unexpected fields")
        raw = {field: str(item[field]).strip() for field in CFTC_QUERY_FIELDS}
        report_date = raw["report_date_as_yyyy_mm_dd"][:10]
        if report_date in dates:
            raise ValueError(f"duplicate CFTC report date: {report_date}")
        dates.add(report_date)
        if raw["cftc_contract_market_code"] != "080732":
            raise ValueError("CFTC query returned a non-Sugar No. 11 contract")
        if "SUGAR NO. 11" not in raw["market_and_exchange_names"].upper():
            raise ValueError("CFTC query returned an unexpected market")
        if raw["futonly_or_combined"] != "FutOnly":
            raise ValueError("CFTC query returned a non-futures-only report")
        for field in (
            "open_interest_all",
            "m_money_positions_long_all",
            "m_money_positions_short_all",
            "m_money_positions_spread",
        ):
            if int(raw[field]) < 0:
                raise ValueError(f"CFTC query returned a negative count: {field}")
        rows.append(
            {
                "report_date": report_date,
                "cftc_contract_market_code": raw["cftc_contract_market_code"],
                "market_and_exchange_names": raw["market_and_exchange_names"],
                "open_interest_contracts": raw["open_interest_all"],
                "managed_money_long_contracts": raw["m_money_positions_long_all"],
                "managed_money_short_contracts": raw["m_money_positions_short_all"],
                "managed_money_spread_contracts": raw["m_money_positions_spread"],
                "contract_units_original": raw["contract_units"],
                "report_type": raw["futonly_or_combined"],
            }
        )
    if len(rows) < 800:
        raise ValueError(f"unexpectedly short CFTC history: {len(rows)} rows")
    if rows[0]["report_date"] != "2009-09-01" or rows[-1]["report_date"] != "2026-08-11":
        raise ValueError("CFTC response does not match the frozen public-history boundary")
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CFTC_PUBLIC_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def _usda_extract(payload: bytes) -> tuple[bytes, list[dict[str, str]]]:
    text = payload.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if tuple(reader.fieldnames or ()) != USDA_RAW_FIELDS:
        raise ValueError(f"USDA snapshot has unexpected columns: {reader.fieldnames!r}")
    rows = [
        row
        for row in reader
        if row["Commodity"] == "Sugar"
        and row["AnnualQuarterFlag"] == "Annual"
        and (row["ReportTitle"], row["Region"])
        in {
            ("U.S. Sugar Supply and Use", "United States"),
            (
                "Mexico Sugar Supply and Use and High Fructose Corn Syrup Consumption",
                "Mexico",
            ),
        }
    ]
    if not rows or {row["Region"] for row in rows} != {"United States", "Mexico"}:
        raise ValueError("USDA snapshot is missing a target sugar table")
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=USDA_RAW_FIELDS,
        lineterminator="\n",
        quoting=csv.QUOTE_ALL,
    )
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8"), rows


def _eastern_datetime_utc(release_date: date, release_time: time) -> datetime:
    march_first = date(release_date.year, 3, 1)
    second_sunday_march = march_first + timedelta(days=(6 - march_first.weekday()) % 7 + 7)
    november_first = date(release_date.year, 11, 1)
    first_sunday_november = november_first + timedelta(days=(6 - november_first.weekday()) % 7)
    daylight = second_sunday_march <= release_date < first_sunday_november
    eastern = timezone(timedelta(hours=-4 if daylight else -5))
    return datetime.combine(release_date, release_time, eastern).astimezone(UTC)


def _eastern_noon_utc(release_date: date) -> datetime:
    return _eastern_datetime_utc(release_date, time(12))


def _eastern_end_of_day_utc(release_date: date) -> datetime:
    return _eastern_datetime_utc(release_date, time(23, 59, 59))


def _public_path(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _record(
    *,
    source_id: str,
    source_type: str,
    provider: str,
    source_url: str,
    landing_page_url: str,
    public_path: Path,
    retrieved_at: datetime,
    upstream: bytes,
    public: bytes,
    source_effective_at: datetime | None = None,
    available_at: datetime | None = None,
    available_at_basis: str,
    source_version: str,
    corrected: bool,
    extract_method: str,
    rights_note: str,
    notes: str,
) -> dict[str, str]:
    return {
        "source_id": source_id,
        "source_type": source_type,
        "provider": provider,
        "source_url": source_url,
        "landing_page_url": landing_page_url,
        "public_path": _public_path(public_path),
        "source_effective_at_utc": (
            iso_utc(source_effective_at) if source_effective_at is not None else ""
        ),
        "available_at_utc": iso_utc(available_at) if available_at is not None else "",
        "available_at_basis": available_at_basis,
        "retrieved_at_utc": iso_utc(retrieved_at),
        "source_version": source_version,
        "is_corrected_repost": str(corrected).lower(),
        "upstream_byte_count": str(len(upstream)),
        "upstream_sha256": _sha256(upstream),
        "public_byte_count": str(len(public)),
        "public_sha256": _sha256(public),
        "extract_method": extract_method,
        "rights_note": rights_note,
        "notes": notes,
    }


def _retained_schedule_records() -> list[dict[str, str]]:
    retrieved_at = datetime(2026, 8, 20, 11, 22, 31, tzinfo=UTC)
    specifications = (
        (
            "cftc_cot_release_schedule_2026_08",
            ROOT / "data/raw/cftc/cftc-cot-release-schedule-through-2026-08-14.csv",
            "https://www.cftc.gov/MarketReports/CommitmentsofTraders/ReleaseSchedule/index.htm",
            48667,
            "9bad1242474855b890e35414d15ffdffe3c10e67fd1244b3cdee8cd615544f22",
            "2026 schedule through the report dated 2026-08-11",
        ),
        (
            "cftc_cot_special_announcements_2026_08",
            ROOT / "data/raw/cftc/cftc-cot-special-release-facts-2025-2026.csv",
            (
                "https://www.cftc.gov/MarketReports/CommitmentsofTraders/"
                "HistoricalSpecialAnnouncements/index.htm"
            ),
            125751,
            "e168a42ae1143c9381ae78452cc872541d97e6f986396d1ed10344ba1abcb77a",
            "2025 special delay and lapse-in-appropriations catch-up dates",
        ),
    )
    records: list[dict[str, str]] = []
    for source_id, path, source_url, upstream_bytes, upstream_hash, notes in specifications:
        public = path.read_bytes()
        records.append(
            {
                "source_id": source_id,
                "source_type": "cftc_release_calendar",
                "provider": "U.S. Commodity Futures Trading Commission",
                "source_url": source_url,
                "landing_page_url": source_url,
                "public_path": _public_path(path),
                "source_effective_at_utc": "",
                "available_at_utc": "",
                "available_at_basis": "official CFTC schedule/announcement factual extract",
                "retrieved_at_utc": iso_utc(retrieved_at),
                "source_version": "retrieved-2026-08-20",
                "is_corrected_repost": "false",
                "upstream_byte_count": str(upstream_bytes),
                "upstream_sha256": upstream_hash,
                "public_byte_count": str(len(public)),
                "public_sha256": _sha256(public),
                "extract_method": "retained official factual calendar extract",
                "rights_note": "U.S. federal government work; public domain",
                "notes": notes,
            }
        )
    additional_specifications = (
        (
            "cftc_cot_weekly_page_timing_overrides_2009_2025",
            "cftc_release_calendar",
            ROOT / "data/raw/cftc/cftc-cot-weekly-page-timing-overrides-2009-2025.csv",
            "https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm",
            datetime(2026, 8, 20, 16, 28, 1, tzinfo=UTC),
            "verified-2026-08-20",
            "official weekly-page Updated-footer factual extract",
            (
                "68 official weekly Agriculture pages checked for final Updated footer; "
                "compact factual ledger retained; volatile page bodies not vendored"
            ),
            "",
            "",
            (
                "Exact row URLs are retained in the public extract; remaining historical "
                "dates are not implied to be verified."
            ),
        ),
        (
            "cftc_cot_special_timing_supplement_2009_2017",
            "cftc_release_calendar",
            ROOT / "data/raw/cftc/cftc-cot-special-timing-supplement-2009-2017.csv",
            (
                "https://www.cftc.gov/MarketReports/CommitmentsofTraders/"
                "HistoricalSpecialAnnouncements/index.htm"
            ),
            datetime(2026, 8, 20, 11, 22, 31, tzinfo=UTC),
            "retrieved-2026-08-20",
            "official historical-special-announcement factual extract",
            "retained official historical-special-announcement factual extract",
            "125751",
            "e168a42ae1143c9381ae78452cc872541d97e6f986396d1ed10344ba1abcb77a",
            (
                "Original 2009 holiday availability and conservative 2017 Sugar "
                "current-snapshot correction boundary."
            ),
        ),
        (
            "cftc_cot_emitted_event_release_verification",
            "cftc_release_verification",
            ROOT / "data/raw/cftc/cftc-cot-emitted-event-release-verification.csv",
            "https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm",
            datetime(2026, 8, 20, 16, 17, 21, tzinfo=UTC),
            "verified-2026-08-20",
            "official event-page footer verification plus standing 15:30 ET policy",
            (
                "21 official weekly page responses checked individually; compact ledger "
                "retains audit-time page hashes and bytes; volatile page bodies not vendored"
            ),
            "",
            "",
            (
                "All 21 emitted event availability dates are independently verified; this "
                "does not make non-event modelled history strict point-in-time."
            ),
        ),
    )
    for (
        source_id,
        source_type,
        path,
        source_url,
        source_retrieved_at,
        source_version,
        available_at_basis,
        extract_method,
        upstream_bytes,
        upstream_hash,
        notes,
    ) in additional_specifications:
        public = path.read_bytes()
        records.append(
            {
                "source_id": source_id,
                "source_type": source_type,
                "provider": "U.S. Commodity Futures Trading Commission",
                "source_url": source_url,
                "landing_page_url": source_url,
                "public_path": _public_path(path),
                "source_effective_at_utc": "",
                "available_at_utc": "",
                "available_at_basis": available_at_basis,
                "retrieved_at_utc": iso_utc(source_retrieved_at),
                "source_version": source_version,
                "is_corrected_repost": "false",
                "upstream_byte_count": upstream_bytes,
                "upstream_sha256": upstream_hash,
                "public_byte_count": str(len(public)),
                "public_sha256": _sha256(public),
                "extract_method": extract_method,
                "rights_note": "U.S. federal government work; public domain",
                "notes": notes,
            }
        )
    return records


def _acquire_cftc(retrieved_at: datetime) -> dict[str, str]:
    url = _cftc_query_url()
    upstream = _download(url, accept="application/json")
    public = _cftc_extract(upstream)
    digest = _sha256(public)
    external = ROOT / "data/external/cftc" / f"sugar-no11-selected-{_sha256(upstream)[:12]}.json"
    path = ROOT / "data/raw/cftc" / f"sugar-no11-selected-history-{digest[:12]}.csv"
    _write_immutable(external, upstream)
    _write_immutable(path, public)
    return _record(
        source_id=f"cftc_sugar_no11_selected_history_{digest[:12]}",
        source_type="cftc_selected_history",
        provider="U.S. Commodity Futures Trading Commission",
        source_url=url,
        landing_page_url=CFTC_LANDING,
        public_path=path,
        retrieved_at=retrieved_at,
        upstream=upstream,
        public=public,
        available_at_basis=(
            "row-level release eligibility is computed from official exceptions or the "
            "stated ordinary rule"
        ),
        source_version="current-history-snapshot",
        corrected=False,
        extract_method="scripts/acquire.py::_cftc_extract",
        rights_note="U.S. federal government work; public domain",
        notes=(
            "Selected futures-only facts from live-classification-era history beginning "
            "2009-09-01. "
            "Current official history is not a full value-vintage archive."
        ),
    )


def _acquire_usda(
    filename: str,
    retrieved_at: datetime,
    prior_records: list[dict[str, str]],
) -> dict[str, str]:
    url = USDA_BASE + filename
    upstream = _download(url, accept="text/csv,*/*")
    public, rows = _usda_extract(upstream)
    upstream_digest = _sha256(upstream)
    public_digest = _sha256(public)
    changed_same_url = any(
        row["source_type"] == "usda_wasde_sugar_snapshot"
        and row["source_url"] == url
        and row["upstream_sha256"] != upstream_digest
        for row in prior_records
    )
    external = ROOT / "data/external/usda" / f"{Path(filename).stem}-{upstream_digest[:12]}.csv"
    path = ROOT / "data/raw/usda" / f"{Path(filename).stem}-sugar-{public_digest[:12]}.csv"
    _write_immutable(external, upstream)
    _write_immutable(path, public)

    wasde_numbers = {row["WasdeNumber"] for row in rows}
    labels = {row["ReportDate"] for row in rows}
    raw_dates = {date.fromisoformat(row["ReleaseDate"]) for row in rows}
    raw_times = {row["ReleaseTime"].split(".", maxsplit=1)[0] for row in rows}
    if len(wasde_numbers) != 1 or len(labels) != 1 or len(raw_dates) != 1:
        raise ValueError(f"mixed USDA issue metadata in {filename}")
    if raw_times != {"12:00:00"}:
        raise ValueError(f"unexpected embedded USDA release time in {filename}")
    wasde_number = next(iter(wasde_numbers))
    raw_release_date = next(iter(raw_dates))
    explicit_v2 = filename in V2_OFFICIAL_RELEASE_DATES
    corrected = explicit_v2 or changed_same_url
    official_release_date = V2_OFFICIAL_RELEASE_DATES.get(filename, raw_release_date)
    effective_at = _eastern_noon_utc(official_release_date)
    if changed_same_url:
        # A silent same-URL replacement has no defensible historical upload time.
        # Make it eligible only when the changed bytes were first confirmed here.
        available_at = retrieved_at
    elif filename.endswith("2026-06-V2.csv"):
        # The corrected sugar file retains the original report date and USDA does not
        # publish an exact repost timestamp. Never make V2 eligible on the original day.
        availability_date = official_release_date + timedelta(days=1)
        available_at = _eastern_end_of_day_utc(availability_date)
    else:
        availability_date = raw_release_date if corrected else raw_release_date + timedelta(days=1)
        available_at = _eastern_end_of_day_utc(availability_date)
    if changed_same_url:
        marker = "V2-REPOST" if explicit_v2 else "REPOST"
        version = f"WASDE-{wasde_number}-{marker}-{upstream_digest[:8]}"
        basis = (
            "first confirmed retrieval of changed bytes at an existing official URL; "
            "historical repost time unavailable"
        )
    elif filename.endswith("2026-06-V2.csv"):
        version = f"WASDE-{wasde_number}-V2"
        basis = (
            "conservative end of day after original release in America/New_York; June "
            "sugar V2 exact repost time unavailable"
        )
    elif corrected:
        version = f"WASDE-{wasde_number}-V2"
        basis = (
            "conservative end of corrected V2 embedded release date in "
            "America/New_York; exact repost time unavailable"
        )
    else:
        version = f"WASDE-{wasde_number}-V1"
        basis = (
            "conservative end of next calendar day in America/New_York; USDA says "
            "consolidated CSV updates the day after WASDE"
        )
    notes = (
        f"{next(iter(labels))}; selected U.S. and Mexico annual sugar rows. "
        "Individual WASDE publications remain the official record."
    )
    if filename.endswith("2026-05-V2.csv"):
        notes += (
            " V2 was a wheat correction; retained because the linked structured artifact is V2."
        )
    if filename.endswith("2026-06-V2.csv"):
        notes += (
            " V2 corrected sugar deliveries; it is never backdated to the original report instant."
        )
    if changed_same_url:
        notes += (
            " Changed bytes at a previously acquired URL are append-only and become eligible "
            "only at first confirmed retrieval."
        )
    source_marker = "repost" if changed_same_url else ("v2" if corrected else "v1")
    return _record(
        source_id=f"usda_wasde_{wasde_number}_{source_marker}_{public_digest[:12]}",
        source_type="usda_wasde_sugar_snapshot",
        provider="U.S. Department of Agriculture",
        source_url=url,
        landing_page_url=USDA_LANDING,
        public_path=path,
        retrieved_at=retrieved_at,
        upstream=upstream,
        public=public,
        source_effective_at=effective_at,
        available_at=available_at,
        available_at_basis=basis,
        source_version=version,
        corrected=corrected,
        extract_method="scripts/acquire.py::_usda_extract",
        rights_note="U.S. federal government work; public domain",
        notes=notes,
    )


def _read_existing_manifest() -> list[dict[str, str]]:
    path = ROOT / "data/source_manifest.csv"
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != MANIFEST_FIELDS:
            raise ValueError("existing source manifest has unexpected columns")
        return list(reader)


def _write_manifest(new_records: list[dict[str, str]]) -> None:
    records = _read_existing_manifest()
    known_hashes = {row["public_sha256"] for row in records}
    known_ids = {row["source_id"] for row in records}
    for record in new_records:
        if record["public_sha256"] in known_hashes:
            continue
        if record["source_id"] in known_ids:
            raise ValueError(f"source_id collision: {record['source_id']}")
        records.append(record)
        known_hashes.add(record["public_sha256"])
        known_ids.add(record["source_id"])
    records.sort(
        key=lambda row: (
            row["source_type"],
            row["source_effective_at_utc"],
            row["retrieved_at_utc"],
            row["source_id"],
        )
    )
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=MANIFEST_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(records)
    (ROOT / "data/source_manifest.csv").write_text(output.getvalue(), encoding="utf-8", newline="")


def main() -> None:
    retrieved_at = datetime.now(tz=UTC).replace(microsecond=0)
    existing_records = _read_existing_manifest()
    records = _retained_schedule_records()
    records.append(_acquire_cftc(retrieved_at))
    for filename in USDA_FILES:
        records.append(_acquire_usda(filename, retrieved_at, existing_records))
        print(f"acquired {filename}")
    _write_manifest(records)
    print(f"wrote append-only manifest with {len(_read_existing_manifest())} records")


if __name__ == "__main__":
    main()
