"""Source-integrity, availability, and report-export regression tests."""

from __future__ import annotations

import ast
import csv
import hashlib
import io
import json
import shutil
import socket
from datetime import UTC, date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from sugar_market_study.cftc import load_positioning_releases
from sugar_market_study.pipeline import build_outputs, render_outputs
from sugar_market_study.provenance import (
    MANIFEST_FIELDS,
    SourceIntegrityError,
    SourceRecord,
    load_manifest,
    verify_sources,
)
from sugar_market_study.signals import MIN_PRIOR_RELEASES, evaluate_releases
from sugar_market_study.wasde import (
    RATIO_ATTRIBUTE,
    RATIO_UNIT_WARNING,
    US_RAW_UNIT,
    WasdeFact,
    load_wasde_facts,
    visible_as_of,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")  # type: ignore[untyped-decorator]
def sources() -> tuple[SourceRecord, ...]:
    return verify_sources(PROJECT_ROOT)


def test_manifest_is_complete_content_addressed_and_append_only(
    sources: tuple[SourceRecord, ...],
) -> None:
    assert len(sources) == 21
    assert sum(item.source_type == "usda_wasde_sugar_snapshot" for item in sources) == 15
    assert sum(item.source_type == "cftc_release_calendar" for item in sources) == 4
    assert sum(item.source_type == "cftc_release_verification" for item in sources) == 1
    assert sum(item.source_type == "cftc_selected_history" for item in sources) == 1
    assert len({item.source_id for item in sources}) == len(sources)
    assert len({item.public_path for item in sources}) == len(sources)
    assert all(len(item.public_sha256) == 64 for item in sources)
    corrected = {item.source_version for item in sources if item.is_corrected_repost}
    assert corrected == {"WASDE-671-V2", "WASDE-672-V2"}
    multi_page = {
        item.source_id: item
        for item in sources
        if item.source_id
        in {
            "cftc_cot_weekly_page_timing_overrides_2009_2025",
            "cftc_cot_emitted_event_release_verification",
        }
    }
    assert set(multi_page) == {
        "cftc_cot_weekly_page_timing_overrides_2009_2025",
        "cftc_cot_emitted_event_release_verification",
    }
    assert all(item.upstream_byte_count is None for item in multi_page.values())
    assert all(item.upstream_sha256 is None for item in multi_page.values())


def test_cftc_live_classification_history_and_frozen_events(
    sources: tuple[SourceRecord, ...],
) -> None:
    releases = load_positioning_releases(PROJECT_ROOT, sources)
    evaluated = evaluate_releases(releases)
    signal_dates = [
        release.report_date for release, evaluation in evaluated if evaluation.signal_emitted
    ]

    assert len(releases) == 885
    assert releases[0].report_date == date(2009, 9, 1)
    assert releases[-1].report_date == date(2026, 8, 11)
    assert releases[-1].available_at_utc == datetime(2026, 8, 14, 19, 30, tzinfo=UTC)
    assert all(evaluation.prior_q10 is None for _, evaluation in evaluated[:MIN_PRIOR_RELEASES])
    assert evaluated[MIN_PRIOR_RELEASES][1].prior_release_count == MIN_PRIOR_RELEASES
    assert signal_dates == [
        date.fromisoformat(value)
        for value in (
            "2012-09-25",
            "2012-12-24",
            "2013-04-16",
            "2013-07-23",
            "2014-02-04",
            "2014-10-07",
            "2015-01-06",
            "2015-04-14",
            "2015-08-04",
            "2017-07-18",
            "2017-10-31",
            "2018-02-06",
            "2018-05-15",
            "2018-09-11",
            "2019-03-19",
            "2019-06-18",
            "2019-09-24",
            "2025-07-08",
            "2025-09-30",
            "2026-03-10",
            "2026-06-30",
        )
    ]


def test_rule_was_publicly_frozen_before_sugar_numeric_acquisition() -> None:
    config = json.loads((PROJECT_ROOT / "config/study.json").read_text(encoding="utf-8"))
    rule = config["signal_rule"]
    frozen_at = datetime.fromisoformat(rule["frozen_at_utc"].replace("Z", "+00:00"))
    acquired_at = datetime.fromisoformat(
        rule["first_sugar_numeric_retrieval_at_utc"].replace("Z", "+00:00")
    )

    assert rule["frozen_source_commit"] == "20f1e81afdccc7323af72f8c979da490c97ab21f"
    assert rule["independently_audited_event_parity"] == "21/21"
    assert frozen_at < acquired_at


def test_official_cftc_catch_up_timing_prevents_lookahead(
    sources: tuple[SourceRecord, ...],
) -> None:
    by_date = {item.report_date: item for item in load_positioning_releases(PROJECT_ROOT, sources)}
    delayed = by_date[date(2025, 9, 30)]
    assert delayed.available_at_utc == datetime(2025, 11, 19, 20, 30, tzinfo=UTC)
    assert delayed.availability_basis == (
        "cftc_official_appropriations_catch_up_and_event_page_verified"
    )


def _independent_eastern_utc(release_date: date, release_time: time) -> datetime:
    march_first = date(release_date.year, 3, 1)
    second_sunday_march = march_first + timedelta(days=(6 - march_first.weekday()) % 7 + 7)
    november_first = date(release_date.year, 11, 1)
    first_sunday_november = november_first + timedelta(days=(6 - november_first.weekday()) % 7)
    offset = timezone(
        timedelta(hours=-4 if second_sunday_march <= release_date < first_sunday_november else -5)
    )
    return datetime.combine(release_date, release_time, offset).astimezone(UTC)


def test_every_retained_historical_cftc_override_is_applied(
    sources: tuple[SourceRecord, ...],
) -> None:
    by_date = {item.report_date: item for item in load_positioning_releases(PROJECT_ROOT, sources)}
    paths = (
        PROJECT_ROOT / "data/raw/cftc/cftc-cot-weekly-page-timing-overrides-2009-2025.csv",
        PROJECT_ROOT / "data/raw/cftc/cftc-cot-special-timing-supplement-2009-2017.csv",
    )
    retained_rows: list[dict[str, str]] = []
    for path in paths:
        with path.open("r", encoding="utf-8", newline="") as handle:
            retained_rows.extend(csv.DictReader(handle))

    assert len(retained_rows) == 70
    assert len({row["report_date"] for row in retained_rows}) == 70
    for row in retained_rows:
        report_date = date.fromisoformat(row["report_date"])
        expected = _independent_eastern_utc(
            date.fromisoformat(row["release_date"]), time.fromisoformat(row["release_time"])
        )
        actual = by_date[report_date]
        assert actual.available_at_utc == expected
        assert actual.availability_basis.startswith(row["availability_basis"])

    assert by_date[date(2012, 11, 27)].available_at_utc == datetime(2012, 12, 5, 20, 30, tzinfo=UTC)
    assert by_date[date(2017, 3, 28)].available_at_utc == datetime(
        2017, 4, 5, 3, 59, 59, tzinfo=UTC
    )
    assert by_date[date(2019, 3, 26)].available_at_utc == datetime(
        2019, 4, 4, 3, 59, 59, tzinfo=UTC
    )


def test_every_emitted_event_has_official_page_timing_verification(
    sources: tuple[SourceRecord, ...],
) -> None:
    releases = load_positioning_releases(PROJECT_ROOT, sources)
    emitted = {
        release.report_date: release
        for release, evaluation in evaluate_releases(releases)
        if evaluation.signal_emitted
    }
    path = PROJECT_ROOT / "data/raw/cftc/cftc-cot-emitted-event-release-verification.csv"
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 21
    assert set(emitted) == {date.fromisoformat(row["report_date"]) for row in rows}
    for row in rows:
        report_date = date.fromisoformat(row["report_date"])
        expected = datetime.fromisoformat(row["available_at_utc"].replace("Z", "+00:00"))
        assert emitted[report_date].available_at_utc == expected
        assert "page_verified" in emitted[report_date].availability_basis


def _fact(
    facts: tuple[WasdeFact, ...],
    *,
    report_date: str,
    region: str,
    market_year: str,
    attribute: str,
) -> WasdeFact:
    matches = [
        item
        for item in facts
        if item.report_date.isoformat() == report_date
        and item.region == region
        and item.market_year == market_year
        and item.attribute == attribute
    ]
    assert len(matches) == 1
    return matches[0]


def test_usda_long_form_vintages_preserve_units_and_original_values(
    sources: tuple[SourceRecord, ...],
) -> None:
    facts = load_wasde_facts(PROJECT_ROOT, sources)
    ratios = [
        item
        for item in facts
        if item.region == "United States" and item.attribute == RATIO_ATTRIBUTE
    ]

    assert len(facts) == 1170
    assert len({item.vintage_id for item in facts}) == 15
    assert {item.region for item in facts} == {"United States", "Mexico"}
    assert ratios
    assert all(item.raw_unit == US_RAW_UNIT for item in ratios)
    assert all(item.normalized_unit == "Percent" for item in ratios)
    assert all(item.unit_warning == RATIO_UNIT_WARNING for item in ratios)
    assert all(item.raw_value for item in facts)


def test_august_2026_carry_in_loosening_story_is_source_derived(
    sources: tuple[SourceRecord, ...],
) -> None:
    facts = load_wasde_facts(PROJECT_ROOT, sources)

    def delta(region: str, attribute: str) -> Decimal:
        august = _fact(
            facts,
            report_date="2026-08-12",
            region=region,
            market_year="2026/27",
            attribute=attribute,
        )
        july = _fact(
            facts,
            report_date="2026-07-10",
            region=region,
            market_year="2026/27",
            attribute=attribute,
        )
        return august.value - july.value

    assert {
        attribute: delta("United States", attribute)
        for attribute in (
            "Beginning Stocks",
            "Production",
            "Total Supply",
            "Ending Stocks",
            "Stocks to Use Ratio",
        )
    } == {
        "Beginning Stocks": Decimal(218),
        "Production": Decimal(-54),
        "Total Supply": Decimal(168),
        "Ending Stocks": Decimal(168),
        "Stocks to Use Ratio": Decimal("1.3"),
    }
    assert {
        attribute: delta("Mexico", attribute)
        for attribute in (
            "Beginning Stocks",
            "Production",
            "Exports",
            "Ending Stocks",
        )
    } == {
        "Beginning Stocks": Decimal(64),
        "Production": Decimal(0),
        "Exports": Decimal(65),
        "Ending Stocks": Decimal(0),
    }


def test_june_v2_is_not_backdated_to_the_original_release(
    sources: tuple[SourceRecord, ...],
) -> None:
    facts = load_wasde_facts(PROJECT_ROOT, sources)
    just_before = visible_as_of(facts, datetime(2026, 6, 13, 3, 59, 58, tzinfo=UTC))
    at_boundary = visible_as_of(facts, datetime(2026, 6, 13, 3, 59, 59, tzinfo=UTC))
    before = next(
        item
        for item in just_before
        if item.region == "United States"
        and item.market_year == "2025/26"
        and item.attribute == "Deliveries"
    )
    after = next(
        item
        for item in at_boundary
        if item.region == "United States"
        and item.market_year == "2025/26"
        and item.attribute == "Deliveries"
    )

    assert before.report_label == "May 2026"
    assert before.value == Decimal(12364)
    assert after.report_label == "June 2026"
    assert after.value == Decimal(12490)
    assert after.is_corrected_repost is True


def test_committed_outputs_are_current_and_schema_stable() -> None:
    paths = build_outputs(PROJECT_ROOT, check=True)
    assert {path.name for path in paths} == {
        "positioning_releases.csv",
        "wasde_sugar_vintages.csv",
        "wasde_sugar_revisions.csv",
        "study_summary.json",
    }
    with (PROJECT_ROOT / "data/derived/positioning_releases.csv").open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    assert rows[-1]["report_date"] == "2026-08-11"
    assert rows[-1]["prior_q10"]
    summary = json.loads(
        (PROJECT_ROOT / "data/derived/study_summary.json").read_text(encoding="utf-8")
    )
    assert summary["wasde"]["artifact_version_count"] == 15
    assert summary["study"]["trade_or_execution_system"] is False
    assert summary["study"]["as_of_utc"] == "2026-08-20T23:59:59Z"
    assert summary["study"]["data_current_through"] == "2026-08-14"


def test_configured_as_of_is_enforced_on_every_export(tmp_path: Path) -> None:
    shutil.copytree(PROJECT_ROOT / "config", tmp_path / "config")
    shutil.copytree(PROJECT_ROOT / "data/raw", tmp_path / "data/raw")
    shutil.copy2(PROJECT_ROOT / "data/source_manifest.csv", tmp_path / "data/source_manifest.csv")
    config_path = tmp_path / "config/study.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    cutoff = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)
    config["as_of_utc"] = "2026-08-01T00:00:00Z"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    rendered = render_outputs(tmp_path)
    by_name = {path.name: payload for path, payload in rendered.items()}
    positioning = list(
        csv.DictReader(io.StringIO(by_name["positioning_releases.csv"].decode("utf-8")))
    )
    vintages = list(
        csv.DictReader(io.StringIO(by_name["wasde_sugar_vintages.csv"].decode("utf-8")))
    )
    summary = json.loads(by_name["study_summary.json"])

    assert positioning[-1]["report_date"] == "2026-07-28"
    assert (
        max(
            datetime.fromisoformat(row["available_at_utc"].replace("Z", "+00:00"))
            for row in positioning
        )
        <= cutoff
    )
    assert (
        max(
            datetime.fromisoformat(row["available_at_utc"].replace("Z", "+00:00"))
            for row in vintages
        )
        <= cutoff
    )
    assert summary["study"]["as_of_utc"] == "2026-08-01T00:00:00Z"
    assert summary["study"]["data_current_through"] == "2026-07-31"
    assert summary["wasde"]["august_2026_vs_july_2026"] == {}


def test_source_hash_tampering_is_detected(tmp_path: Path) -> None:
    raw = tmp_path / "data/raw/sample.csv"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"plainly synthetic source\n")
    digest = hashlib.sha256(raw.read_bytes()).hexdigest()
    manifest = tmp_path / "data/source_manifest.csv"
    row = {
        "source_id": "synthetic",
        "source_type": "cftc_selected_history",
        "provider": "Synthetic test fixture",
        "source_url": "https://www.cftc.gov/synthetic.csv",
        "landing_page_url": "https://www.cftc.gov/synthetic",
        "public_path": "data/raw/sample.csv",
        "source_effective_at_utc": "",
        "available_at_utc": "",
        "available_at_basis": "synthetic",
        "retrieved_at_utc": "2026-08-20T00:00:00Z",
        "source_version": "synthetic",
        "is_corrected_repost": "false",
        "upstream_byte_count": str(raw.stat().st_size),
        "upstream_sha256": digest,
        "public_byte_count": str(raw.stat().st_size),
        "public_sha256": digest,
        "extract_method": "synthetic test",
        "rights_note": "synthetic fixture",
        "notes": "plainly synthetic",
    }
    with manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerow(row)
    assert len(load_manifest(manifest)) == 1
    raw.write_bytes(b"tampered\n")
    with pytest.raises(SourceIntegrityError, match="byte count mismatch|SHA-256 mismatch"):
        verify_sources(tmp_path)


def test_offline_package_has_no_network_imports() -> None:
    forbidden = {"http", "http.client", "requests", "socket", "urllib.request", "urllib3"}
    imported: set[str] = set()
    for path in (PROJECT_ROOT / "src/sugar_market_study").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
    assert not {
        name
        for name in imported
        if name in forbidden or any(name.startswith(f"{root}.") for root in forbidden)
    }


def test_runtime_network_guard_fails_closed() -> None:
    with pytest.raises(AssertionError, match="must not access the network"):
        socket.getaddrinfo("example.com", 443)
