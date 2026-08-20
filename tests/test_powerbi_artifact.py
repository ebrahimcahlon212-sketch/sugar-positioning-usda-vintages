from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
POWERBI = ROOT / "powerbi"
REPORT = POWERBI / "SugarNo11.Report"
MODEL = POWERBI / "SugarNo11.SemanticModel"


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def csv_row_count(path: Path) -> int:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return sum(1 for _ in csv.DictReader(stream))


def all_visuals(page_name: str) -> list[dict[str, Any]]:
    paths = sorted((REPORT / "definition" / "pages" / page_name / "visuals").glob("*/visual.json"))
    return [load_json(path) for path in paths]


def test_manifest_matches_pipeline_exports() -> None:
    manifest = load_json(POWERBI / "data_manifest.json")
    assert manifest["built_for_power_bi_desktop"] == "2.157.879.0"
    inputs = manifest["inputs"]
    assert isinstance(inputs, dict)

    expected_rows = {"positioning": 885, "vintages": 1170, "revisions": 1064}
    for name, expected_count in expected_rows.items():
        entry = inputs[name]
        assert isinstance(entry, dict)
        path = (POWERBI / entry["relative_path"]).resolve()
        assert path.is_relative_to(ROOT)
        assert sha256(path) == entry["sha256"]
        assert path.stat().st_size == entry["bytes"]
        assert csv_row_count(path) == expected_count == entry["rows"]


def test_pbip_has_two_ordered_report_pages() -> None:
    project = load_json(POWERBI / "SugarNo11.pbip")
    assert project["$schema"].endswith("pbipProperties/1.0.0/schema.json")
    assert project["artifacts"] == [{"report": {"path": "SugarNo11.Report"}}]

    report = load_json(REPORT / "definition" / "report.json")
    pane_properties = report["objects"]["outspacePane"][0]["properties"]
    assert pane_properties["expanded"]["expr"]["Literal"]["Value"] == "false"

    pages = load_json(REPORT / "definition" / "pages" / "pages.json")
    assert pages["pageOrder"] == ["DecisionLens", "AuditSources"]
    expected_names = {"DecisionLens": "Decision Lens", "AuditSources": "Audit & Sources"}
    for page_id, display_name in expected_names.items():
        page = load_json(REPORT / "definition" / "pages" / page_id / "page.json")
        assert page["name"] == page_id
        assert page["displayName"] == display_name


def test_visual_identity_and_current_schema_are_valid_by_construction() -> None:
    for page_id in ("DecisionLens", "AuditSources"):
        visual_root = REPORT / "definition" / "pages" / page_id / "visuals"
        for path in visual_root.glob("*/visual.json"):
            visual = load_json(path)
            assert visual["name"] == path.parent.name
            assert visual["$schema"].endswith("visualContainer/2.9.0/schema.json")


def test_decision_lens_freezes_the_intended_story_and_rule_disclosures() -> None:
    rendered = json.dumps(all_visuals("DecisionLens"), ensure_ascii=False)
    for disclosure in ("PUBLIC DATA", "NO PRICE SERIES", "RULE NOT RETUNED"):
        assert disclosure in rendered
    for story_fragment in (
        "beginning stocks +218k STRV",
        "production −54k",
        "total supply +168k",
        "ending stocks +168k",
        "stocks/use 13.5% → 14.8%",
        "Managed-money net +43,584 (+3.91% of OI)",
        "versus −87,188 (−8.26%)",
        "Event status is determined only by the frozen rule",
    ):
        assert story_fragment in rendered


def test_audit_page_states_the_cftc_value_vintage_boundary() -> None:
    rendered = json.dumps(all_visuals("AuditSources"), ensure_ascii=False)
    assert "Retrospective publication-aware reconstruction" in rendered
    assert "rule-modelled historical release times and current snapshot values" in rendered
    assert "Not a strict value-vintage backtest" in rendered
    assert "USDA available_at_utc gates genuine point-in-time vintages" in rendered


def test_model_is_portable_and_preserves_point_in_time_fields() -> None:
    table_files = sorted((MODEL / "definition" / "tables").glob("*.tmdl"))
    assert {path.stem for path in table_files} == {
        "Audit Sources",
        "Positioning Releases",
        "WASDE Revisions",
        "WASDE Vintages",
    }
    combined = "\n".join(path.read_text(encoding="utf-8") for path in table_files)
    assert "Binary.FromText(Encoded, BinaryEncoding.Base64)" in combined
    assert "Binary.Decompress" not in combined
    assert "Compression.GZip" not in combined
    assert "File.Contents" not in combined
    assert "C:\\Users\\" not in combined
    for field in ("effective_at_utc", "available_at_utc", "source_sha256"):
        assert field in combined


def test_measure_names_do_not_collide_with_model_table_names() -> None:
    table_names = {path.stem for path in (MODEL / "definition" / "tables").glob("*.tmdl")}
    for path in (MODEL / "definition" / "tables").glob("*.tmdl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped.startswith("measure "):
                continue
            measure_name = stripped.removeprefix("measure ").split(" =", maxsplit=1)[0]
            assert measure_name.strip("'").replace("''", "'") not in table_names


def test_quantity_revisions_and_ratio_are_not_mixed() -> None:
    revisions = (MODEL / "definition" / "tables" / "WASDE Revisions.tmdl").read_text(
        encoding="utf-8"
    )
    quantity_measure = revisions.split("measure 'Aug 2026 Revision (k STRV)'", maxsplit=1)[1].split(
        "measure 'US 26/27 Stocks Use Jul'", maxsplit=1
    )[0]
    for attribute in ("Beginning Stocks", "Production", "Total Supply", "Ending Stocks"):
        assert attribute in quantity_measure
    assert "Stocks to Use Ratio" not in quantity_measure
    assert revisions.count("Stocks to Use Ratio") == 3
    assert revisions.count("DIVIDE(") >= 2
    assert revisions.count("    100") >= 2


def test_official_schema_copies_match_pinned_hashes() -> None:
    schema_root = POWERBI / "schemas"
    manifest = load_json(schema_root / "manifest.json")
    assert manifest["upstream_commit"] == "f891f5bfc1ce0030aa53d805d90881a1b8b07643"
    license_path = schema_root / manifest["license_file"]
    assert sha256(license_path) == manifest["license_sha256"]
    assert "Copyright (c) Microsoft Corporation" in license_path.read_text(encoding="utf-8")
    files = manifest["files"]
    assert isinstance(files, dict)
    assert len(files) == 9
    for filename, expected_hash in files.items():
        assert sha256(schema_root / filename) == expected_hash


def test_two_consecutive_project_builds_are_byte_identical() -> None:
    script = ROOT / "scripts" / "build_powerbi_project.py"

    def build_and_hash() -> dict[Path, str]:
        subprocess.run([sys.executable, str(script)], cwd=ROOT, check=True)
        generated = [POWERBI / "SugarNo11.pbip", POWERBI / "data_manifest.json"]
        generated.extend(
            path for path in REPORT.rglob("*") if path.is_file() and ".pbi" not in path.parts
        )
        generated.extend(
            path for path in MODEL.rglob("*") if path.is_file() and ".pbi" not in path.parts
        )
        return {path.relative_to(ROOT): sha256(path) for path in sorted(generated)}

    assert build_and_hash() == build_and_hash()


def test_desktop_cache_is_ignored_and_recruiter_pbix_is_deliberately_tracked() -> None:
    ignore_text = (POWERBI / ".gitignore").read_text(encoding="utf-8")
    assert "**/.pbi/localSettings.json" in ignore_text
    assert "**/.pbi/cache.abf" in ignore_text

    root_ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "*.pbix" in root_ignore
    assert "!/powerbi/SugarNo11.pbix" in root_ignore

    pbix = POWERBI / "SugarNo11.pbix"
    assert list(POWERBI.rglob("*.pbix")) == [pbix]
    assert pbix.stat().st_size == 350_195
    assert sha256(pbix) == "902afdb7ee057d40e53214a5c80cf074468bd8a9400e2a0011bc054f263968c0"
    with zipfile.ZipFile(pbix) as archive:
        assert archive.testzip() is None
        assert "DataModel" in archive.namelist()
