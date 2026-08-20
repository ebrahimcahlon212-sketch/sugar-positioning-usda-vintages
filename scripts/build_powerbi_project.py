"""Build the source-controlled Sugar No. 11 Power BI report project.

The report consumes the pipeline's stable CSV exports by relative path. The CSV
bytes are embedded as Base64 Power Query M expressions so that a clean clone can
refresh the PBIP without a machine-specific absolute path or credentials.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DERIVED_DIR = REPO_ROOT / "data" / "derived"
POWERBI_DIR = REPO_ROOT / "powerbi"
PROJECT_NAME = "SugarNo11"
REPORT_DIR = POWERBI_DIR / f"{PROJECT_NAME}.Report"
MODEL_DIR = POWERBI_DIR / f"{PROJECT_NAME}.SemanticModel"

PBIP_SCHEMA = (
    "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json"
)
PBISM_SCHEMA = (
    "https://developer.microsoft.com/json-schemas/fabric/item/"
    "semanticModel/definitionProperties/1.0.0/schema.json"
)
PBIR_SCHEMA = (
    "https://developer.microsoft.com/json-schemas/fabric/item/"
    "report/definitionProperties/2.0.0/schema.json"
)
VERSION_SCHEMA = (
    "https://developer.microsoft.com/json-schemas/fabric/item/report/"
    "definition/versionMetadata/1.0.0/schema.json"
)
PLATFORM_SCHEMA = (
    "https://developer.microsoft.com/json-schemas/fabric/"
    "gitIntegration/platformProperties/2.0.0/schema.json"
)
REPORT_SCHEMA = (
    "https://developer.microsoft.com/json-schemas/fabric/item/report/"
    "definition/report/3.3.0/schema.json"
)
PAGES_SCHEMA = (
    "https://developer.microsoft.com/json-schemas/fabric/item/report/"
    "definition/pagesMetadata/1.1.0/schema.json"
)
PAGE_SCHEMA = (
    "https://developer.microsoft.com/json-schemas/fabric/item/report/"
    "definition/page/2.1.0/schema.json"
)
VISUAL_SCHEMA = (
    "https://developer.microsoft.com/json-schemas/fabric/item/report/"
    "definition/visualContainer/2.9.0/schema.json"
)

INPUT_FILES = {
    "positioning": "positioning_releases.csv",
    "vintages": "wasde_sugar_vintages.csv",
    "revisions": "wasde_sugar_revisions.csv",
}

POSITIONING_COLUMNS = {
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
}

VINTAGE_COLUMNS = {
    "vintage_id",
    "wasde_number",
    "report_date",
    "effective_at_utc",
    "available_at_utc",
    "available_at_basis",
    "retrieved_at_utc",
    "source_version",
    "is_corrected_repost",
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
}

REVISION_COLUMNS = {
    "vintage_id",
    "prior_vintage_id",
    "wasde_number",
    "report_date",
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
}

STORY_DATE = "2026-08-12"
STORY_ATTRIBUTES = {
    "Beginning Stocks": 1,
    "Production": 2,
    "Total Supply": 3,
    "Ending Stocks": 4,
    "Stocks to Use Ratio": 5,
}

JSON = dict[str, Any]


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def read_csv(name: str, required_columns: set[str]) -> tuple[list[dict[str, str]], bytes]:
    path = DERIVED_DIR / name
    if not path.is_file():
        raise FileNotFoundError(
            f"Missing pipeline export: {path}. Run the deterministic pipeline first."
        )
    payload = path.read_bytes()
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig"), newline=""))
    fieldnames = set(reader.fieldnames or [])
    missing = sorted(required_columns - fieldnames)
    if missing:
        raise ValueError(f"{name} is missing required report columns: {missing}")
    rows = [dict(row) for row in reader]
    if not rows:
        raise ValueError(f"{name} contains no rows")
    return rows, payload


def month_label(iso_date: str) -> str:
    parsed = date.fromisoformat(iso_date)
    return parsed.strftime("%B %Y")


def add_report_columns(
    positioning: list[dict[str, str]],
    vintages: list[dict[str, str]],
    revisions: list[dict[str, str]],
) -> list[dict[str, str]]:
    for row in positioning:
        row["source_sha256_short"] = row["source_sha256"][:12]

    for row in vintages:
        row["report_label"] = row.get("report_label") or month_label(row["report_date"])
        row["source_sha256_short"] = row["source_sha256"][:12]
        row["has_unit_warning"] = "true" if row.get("unit_warning", "").strip() else "false"

    all_attributes = sorted({row["attribute"] for row in revisions})
    other_order = {attribute: index + 100 for index, attribute in enumerate(all_attributes)}
    for row in revisions:
        row["report_label"] = row.get("report_label") or month_label(row["report_date"])
        row["attribute_sort"] = str(
            STORY_ATTRIBUTES.get(row["attribute"], other_order[row["attribute"]])
        )
        is_story = (
            row["region"] == "United States"
            and row["market_year"] == "2026/27"
            and row["report_date"] == STORY_DATE
            and row["attribute"] in STORY_ATTRIBUTES
        )
        row["is_decision_story"] = "true" if is_story else "false"

    return build_audit_rows(positioning, vintages)


def build_audit_rows(
    positioning: list[dict[str, str]], vintages: list[dict[str, str]]
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in positioning:
        rows.append(
            {
                "dataset": "CFTC positioning",
                "record_key": row["source_id"],
                "report_label": row["report_date"],
                "report_date": row["report_date"],
                "available_at_utc": row["available_at_utc"],
                "availability_basis": row["availability_basis"],
                "source_version": "",
                "is_corrected_repost": "false",
                "source_url": row["source_url"],
                "source_sha256": row["source_sha256"],
                "sha256_short": row["source_sha256"][:12],
                "unit_warning_count": "0",
            }
        )

    grouped: dict[tuple[str, str, str], dict[str, str]] = {}
    warnings: dict[tuple[str, str, str], int] = {}
    for row in vintages:
        key = (row["vintage_id"], row["source_version"], row["source_sha256"])
        warnings[key] = warnings.get(key, 0) + bool(row.get("unit_warning", "").strip())
        grouped.setdefault(
            key,
            {
                "dataset": "USDA WASDE sugar",
                "record_key": row["vintage_id"],
                "report_label": row["report_label"],
                "report_date": row["report_date"],
                "available_at_utc": row["available_at_utc"],
                "availability_basis": row["available_at_basis"],
                "source_version": row["source_version"],
                "is_corrected_repost": row["is_corrected_repost"],
                "source_url": row["source_url"],
                "source_sha256": row["source_sha256"],
                "sha256_short": row["source_sha256"][:12],
                "unit_warning_count": "0",
            },
        )
    for key, row in grouped.items():
        row["unit_warning_count"] = str(warnings[key])
        rows.append(row)
    return rows


def csv_payload(rows: Sequence[dict[str, str]], columns: Sequence[str]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(columns), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in columns})
    return stream.getvalue().encode("utf-8")


def m_partition(payload: bytes, columns: Sequence[str], m_types: dict[str, str]) -> str:
    encoded = base64.b64encode(payload).decode("ascii")
    type_pairs = ",\n".join(
        f'\t\t\t{{"{column}", {m_types.get(column, "type text")}}}' for column in columns
    )
    quoted_columns = ", ".join(f'"{column}"' for column in columns)
    return (
        "let\n"
        f'\tEncoded = "{encoded}",\n'
        "\tRaw = Binary.FromText(Encoded, BinaryEncoding.Base64),\n"
        "\tParsed = Csv.Document(\n"
        "\t\tRaw,\n"
        f'\t\t[Delimiter = ",", Columns = {len(columns)}, Encoding = 65001, '
        "QuoteStyle = QuoteStyle.Csv]\n"
        "\t),\n"
        "\tHeaders = Table.PromoteHeaders(Parsed, [PromoteAllScalars = true]),\n"
        "\tBlanksToNull = Table.ReplaceValue(\n"
        "\t\tHeaders,\n"
        '\t\t"",\n'
        "\t\tnull,\n"
        "\t\tReplacer.ReplaceValue,\n"
        f"\t\t{{{quoted_columns}}}\n"
        "\t),\n"
        "\tTyped = Table.TransformColumnTypes(\n"
        "\t\tBlanksToNull,\n"
        "\t\t{\n"
        f"{type_pairs}\n"
        "\t\t},\n"
        '\t\t"en-US"\n'
        "\t)\n"
        "in\n"
        "\tTyped"
    )


def tmdl_identifier(name: str) -> str:
    if name.replace("_", "").isalnum() and " " not in name and name[0].isalpha():
        return name
    return "'" + name.replace("'", "''") + "'"


def dax_measure(name: str, expression: str, format_string: str | None = None) -> str:
    lines = [f"\tmeasure {tmdl_identifier(name)} = ```"]
    lines.extend(f"\t\t{line}" if line else "" for line in expression.splitlines())
    lines.append("\t\t```")
    if format_string:
        lines.append(f"\t\tformatString: {format_string}")
    lines.append("\t\tdisplayFolder: Report measures")
    return "\n".join(lines)


def tmdl_table(
    name: str,
    columns: Sequence[tuple[str, str, bool, str | None, str | None]],
    measures: Sequence[tuple[str, str, str | None]],
    partition: str,
) -> str:
    blocks = [f"table {tmdl_identifier(name)}", ""]
    for measure_name, expression, format_string in measures:
        blocks.extend([dax_measure(measure_name, expression, format_string), ""])
    for column, data_type, hidden, format_string, data_category in columns:
        blocks.append(f"\tcolumn {tmdl_identifier(column)}")
        blocks.append(f"\t\tdataType: {data_type}")
        if hidden:
            blocks.append("\t\tisHidden")
        if format_string:
            blocks.append(f"\t\tformatString: {format_string}")
        if data_category:
            blocks.append(f"\t\tdataCategory: {data_category}")
        blocks.append("\t\tsummarizeBy: none")
        blocks.append(f"\t\tsourceColumn: {column}")
        blocks.append("")
    blocks.append(f"\tpartition {tmdl_identifier(name)} = m")
    blocks.append("\t\tmode: import")
    blocks.append("\t\tsource =")
    blocks.extend(f"\t\t\t{line}" for line in partition.splitlines())
    blocks.append("")
    blocks.append("\tannotation PBI_ResultType = Table")
    return "\n".join(blocks).rstrip() + "\n"


def literal(value: str | bool | int | float) -> JSON:
    if isinstance(value, bool):
        rendered = "true" if value else "false"
    elif isinstance(value, int):
        rendered = f"{value}L"
    elif isinstance(value, float):
        rendered = f"{value}D"
    else:
        rendered = "'" + value.replace("'", "''") + "'"
    return {"expr": {"Literal": {"Value": rendered}}}


def color(value: str) -> JSON:
    return {"solid": {"color": literal(value)}}


def source_expression(table: str) -> JSON:
    return {"SourceRef": {"Entity": table}}


def projection(table: str, prop: str, kind: str = "Column", *, active: bool = False) -> JSON:
    item: JSON = {
        "field": {kind: {"Expression": source_expression(table), "Property": prop}},
        "queryRef": f"{table}.{prop}",
        "nativeQueryRef": prop,
    }
    if active:
        item["active"] = True
    return item


def container_objects(
    *, title: str | None = None, subtitle: str | None = None, alt_text: str
) -> JSON:
    objects: JSON = {
        "background": [
            {
                "properties": {
                    "show": literal(True),
                    "color": color("#FFFFFF"),
                    "transparency": literal(0.0),
                }
            }
        ],
        "border": [
            {
                "properties": {
                    "show": literal(True),
                    "color": color("#DCE4E8"),
                    "radius": literal(8.0),
                    "width": literal(1.0),
                }
            }
        ],
        "dropShadow": [
            {
                "properties": {
                    "show": literal(True),
                    "preset": literal("BottomRight"),
                    "color": color("#0F172A"),
                    "transparency": literal(88.0),
                    "position": literal("Outer"),
                }
            }
        ],
        "visualHeader": [{"properties": {"show": literal(False)}}],
        "general": [{"properties": {"altText": literal(alt_text)}}],
    }
    if title:
        objects["title"] = [
            {
                "properties": {
                    "show": literal(True),
                    "text": literal(title),
                    "fontColor": color("#153E52"),
                    "fontFamily": literal("Segoe UI Semibold"),
                    "fontSize": literal(13.0),
                    "bold": literal(True),
                    "titleWrap": literal(True),
                }
            }
        ]
    objects["subTitle"] = [
        {
            "properties": {
                "show": literal(bool(subtitle)),
                **({"text": literal(subtitle)} if subtitle else {}),
                "fontColor": color("#52656F"),
                "fontSize": literal(9.0),
            }
        }
    ]
    return objects


def textbox(
    visual_id: str,
    position: JSON,
    paragraphs: Sequence[tuple[str, int, str, bool]],
    *,
    background: str | None = None,
    border: str | None = None,
    alt_text: str,
) -> JSON:
    paragraph_items: list[JSON] = []
    for text, size, text_color, bold in paragraphs:
        style: JSON = {
            "fontFamily": "Segoe UI Semibold" if bold else "Segoe UI",
            "fontSize": f"{size}px",
            "color": text_color,
        }
        if bold:
            style["fontWeight"] = "bold"
        paragraph_items.append(
            {
                "textRuns": [{"value": text, "textStyle": style}],
                "horizontalTextAlignment": "left",
            }
        )
    vcos: JSON = {
        "background": [
            {
                "properties": {
                    "show": literal(background is not None),
                    **({"color": color(background)} if background else {}),
                    "transparency": literal(0.0),
                }
            }
        ],
        "border": [
            {
                "properties": {
                    "show": literal(border is not None),
                    **({"color": color(border), "radius": literal(8.0)} if border else {}),
                }
            }
        ],
        "padding": [
            {
                "properties": {
                    "top": literal(6.0),
                    "bottom": literal(6.0),
                    "left": literal(10.0),
                    "right": literal(10.0),
                }
            }
        ],
        "visualHeader": [{"properties": {"show": literal(False)}}],
        "general": [{"properties": {"altText": literal(alt_text)}}],
    }
    return {
        "$schema": VISUAL_SCHEMA,
        "name": visual_id,
        "position": position,
        "visual": {
            "visualType": "textbox",
            "objects": {"general": [{"properties": {"paragraphs": paragraph_items}}]},
            "visualContainerObjects": vcos,
        },
    }


def card(
    visual_id: str,
    position: JSON,
    measures: Sequence[tuple[str, str]],
    *,
    alt_text: str,
) -> JSON:
    return {
        "$schema": VISUAL_SCHEMA,
        "name": visual_id,
        "position": position,
        "visual": {
            "visualType": "cardVisual",
            "query": {
                "queryState": {
                    "Data": {
                        "projections": [
                            projection(table, measure, "Measure") for table, measure in measures
                        ]
                    }
                }
            },
            "objects": {
                "value": [
                    {
                        "properties": {
                            "show": literal(True),
                            "fontSize": literal(16.0),
                            "bold": literal(True),
                            "fontColor": color("#153E52"),
                            "horizontalAlignment": literal("center"),
                        },
                        "selector": {"id": "default"},
                    }
                ],
                "label": [
                    {
                        "properties": {
                            "show": literal(True),
                            "fontSize": literal(10.0),
                            "fontColor": color("#52656F"),
                            "textWrap": literal(True),
                            "horizontalAlignment": literal("center"),
                        },
                        "selector": {"id": "default"},
                    }
                ],
                "outline": [
                    {
                        "properties": {"show": literal(False)},
                        "selector": {"id": "default"},
                    }
                ],
                "cardCalloutArea": [
                    {
                        "properties": {
                            "show": literal(True),
                            "paddingUniform": literal(6),
                            "rectangleRoundedCurve": literal(6),
                            "backgroundFillColor": color("#F5F8F9"),
                            "backgroundTransparency": literal(0.0),
                        }
                    }
                ],
            },
            "visualContainerObjects": container_objects(alt_text=alt_text),
        },
    }


def chart(
    visual_id: str,
    position: JSON,
    visual_type: str,
    query_state: JSON,
    *,
    title: str,
    subtitle: str,
    objects: JSON,
    sort_definition: JSON | None,
    alt_text: str,
) -> JSON:
    query: JSON = {"queryState": query_state}
    if sort_definition:
        query["sortDefinition"] = sort_definition
    return {
        "$schema": VISUAL_SCHEMA,
        "name": visual_id,
        "position": position,
        "visual": {
            "visualType": visual_type,
            "query": query,
            "objects": objects,
            "visualContainerObjects": container_objects(
                title=title, subtitle=subtitle, alt_text=alt_text
            ),
            "drillFilterOtherVisuals": True,
        },
    }


def table_visual(
    visual_id: str,
    position: JSON,
    fields: Sequence[tuple[str, str, str]],
    *,
    title: str,
    subtitle: str,
    sort_table: str,
    sort_column: str,
    alt_text: str,
) -> JSON:
    return {
        "$schema": VISUAL_SCHEMA,
        "name": visual_id,
        "position": position,
        "visual": {
            "visualType": "tableEx",
            "query": {
                "queryState": {
                    "Values": {
                        "projections": [
                            projection(table, prop, kind) for table, prop, kind in fields
                        ]
                    }
                },
                "sortDefinition": {
                    "sort": [
                        {
                            "field": {
                                "Column": {
                                    "Expression": source_expression(sort_table),
                                    "Property": sort_column,
                                }
                            },
                            "direction": "Descending",
                        }
                    ],
                    "isDefaultSort": True,
                },
            },
            "objects": {
                "columnHeaders": [
                    {
                        "properties": {
                            "columnAdjustment": literal("growToFit"),
                            "autoSizeColumnWidth": literal(True),
                            "wordWrap": literal(True),
                            "fontSize": literal(9.0),
                            "bold": literal(True),
                            "fontColor": color("#FFFFFF"),
                            "backColor": color("#153E52"),
                        }
                    }
                ],
                "values": [
                    {
                        "properties": {
                            "fontSize": literal(9.0),
                            "fontColorPrimary": color("#20343E"),
                            "fontColorSecondary": color("#20343E"),
                            "backColorPrimary": color("#FFFFFF"),
                            "backColorSecondary": color("#F5F8F9"),
                            "urlIcon": literal(True),
                            "wordWrap": literal(False),
                        }
                    }
                ],
            },
            "visualContainerObjects": {
                **container_objects(title=title, subtitle=subtitle, alt_text=alt_text),
                "stylePreset": [{"properties": {"name": literal("None")}}],
            },
        },
    }


def position(x: int, y: int, width: int, height: int, z: int) -> JSON:
    return {"x": x, "y": y, "z": z, "height": height, "width": width, "tabOrder": z}


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    path.write_bytes(normalized.replace("\n", "\r\n").encode("utf-8"))


def write_json(path: Path, payload: JSON) -> None:
    write_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def write_visual(page_id: str, visual: JSON) -> None:
    visual_id = str(visual["name"])
    write_json(
        REPORT_DIR / "definition" / "pages" / page_id / "visuals" / visual_id / "visual.json",
        visual,
    )


def build_model(
    positioning: list[dict[str, str]],
    vintages: list[dict[str, str]],
    revisions: list[dict[str, str]],
    audit_rows: list[dict[str, str]],
) -> dict[str, dict[str, Any]]:
    position_columns = [
        "market_name",
        "cftc_contract_market_code",
        "report_date",
        "available_at_utc",
        "availability_basis",
        "source_id",
        "source_url",
        "source_sha256",
        "source_sha256_short",
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
    ]
    vintage_columns = [
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
        "source_url",
        "source_sha256",
        "source_sha256_short",
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
        "has_unit_warning",
    ]
    revision_columns = [
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
        "attribute_sort",
        "normalized_unit",
        "value",
        "prior_value",
        "revision",
        "source_version",
        "is_corrected_repost",
        "is_decision_story",
    ]
    audit_columns = [
        "dataset",
        "record_key",
        "report_label",
        "report_date",
        "available_at_utc",
        "availability_basis",
        "source_version",
        "is_corrected_repost",
        "source_url",
        "source_sha256",
        "sha256_short",
        "unit_warning_count",
    ]

    pos_types = {
        "report_date": "type date",
        "managed_money_long_contracts": "Int64.Type",
        "managed_money_short_contracts": "Int64.Type",
        "managed_money_net_contracts": "Int64.Type",
        "open_interest_contracts": "Int64.Type",
        "normalized_net": "type number",
        "prior_release_count": "Int64.Type",
        "prior_q10": "type number",
        "previous_normalized_net": "type number",
        "previous_was_q10_extreme": "type logical",
        "positive_reversal": "type logical",
        "cooldown_eligible": "type logical",
        "signal_emitted": "type logical",
    }
    vintage_types = {
        "wasde_number": "Int64.Type",
        "report_date": "type date",
        "is_corrected_repost": "type logical",
        "value": "type number",
        "has_unit_warning": "type logical",
    }
    revision_types = {
        "wasde_number": "Int64.Type",
        "report_date": "type date",
        "attribute_sort": "Int64.Type",
        "value": "type number",
        "prior_value": "type number",
        "revision": "type number",
        "is_corrected_repost": "type logical",
        "is_decision_story": "type logical",
    }
    audit_types = {
        "report_date": "type date",
        "is_corrected_repost": "type logical",
        "unit_warning_count": "Int64.Type",
    }

    model_payloads = {
        "positioning": csv_payload(positioning, position_columns),
        "vintages": csv_payload(vintages, vintage_columns),
        "revisions": csv_payload(revisions, revision_columns),
        "audit": csv_payload(audit_rows, audit_columns),
    }

    numeric_ints = {
        "managed_money_long_contracts",
        "managed_money_short_contracts",
        "managed_money_net_contracts",
        "open_interest_contracts",
        "prior_release_count",
    }
    numeric_doubles = {"normalized_net", "prior_q10", "previous_normalized_net"}
    booleans = {
        "previous_was_q10_extreme",
        "positive_reversal",
        "cooldown_eligible",
        "signal_emitted",
    }
    position_tmdl_columns = [
        (
            column,
            "int64"
            if column in numeric_ints
            else "double"
            if column in numeric_doubles
            else "boolean"
            if column in booleans
            else "dateTime"
            if column == "report_date"
            else "string",
            column == "source_sha256",
            "yyyy-mm-dd" if column == "report_date" else None,
            "WebUrl" if column == "source_url" else None,
        )
        for column in position_columns
    ]

    positioning_measures = [
        (
            "Latest Net Contracts",
            """VAR LatestDate =
    CALCULATE(MAX('Positioning Releases'[report_date]), REMOVEFILTERS('Positioning Releases'))
RETURN
    CALCULATE(
        MAX('Positioning Releases'[managed_money_net_contracts]),
        REMOVEFILTERS('Positioning Releases'),
        'Positioning Releases'[report_date] = LatestDate
    )""",
            "#,0;−#,0;–",
        ),
        (
            "Previous Net Contracts",
            """VAR LatestDate =
    CALCULATE(MAX('Positioning Releases'[report_date]), REMOVEFILTERS('Positioning Releases'))
VAR PriorDate =
    CALCULATE(
        MAX('Positioning Releases'[report_date]),
        REMOVEFILTERS('Positioning Releases'),
        'Positioning Releases'[report_date] < LatestDate
    )
RETURN
    CALCULATE(
        MAX('Positioning Releases'[managed_money_net_contracts]),
        REMOVEFILTERS('Positioning Releases'),
        'Positioning Releases'[report_date] = PriorDate
    )""",
            "#,0;−#,0;–",
        ),
        (
            "Latest Net as % OI",
            """VAR LatestDate =
    CALCULATE(MAX('Positioning Releases'[report_date]), REMOVEFILTERS('Positioning Releases'))
RETURN
    CALCULATE(
        MAX('Positioning Releases'[normalized_net]),
        REMOVEFILTERS('Positioning Releases'),
        'Positioning Releases'[report_date] = LatestDate
    )""",
            "0.00%;−0.00%;–",
        ),
        (
            "Latest Rule Status",
            """VAR LatestDate =
    CALCULATE(MAX('Positioning Releases'[report_date]), REMOVEFILTERS('Positioning Releases'))
VAR SignalRows =
    CALCULATE(
        COUNTROWS('Positioning Releases'),
        REMOVEFILTERS('Positioning Releases'),
        'Positioning Releases'[report_date] = LatestDate,
        'Positioning Releases'[signal_emitted] = TRUE()
    )
RETURN IF(SignalRows > 0, "EMITTED", "NO SIGNAL")""",
            None,
        ),
        (
            "Normalized Net (Recent)",
            """VAR CurrentDate = MAX('Positioning Releases'[report_date])
RETURN
    IF(CurrentDate >= DATE(2024, 1, 1), MAX('Positioning Releases'[normalized_net]))""",
            "0.0%;−0.0%;–",
        ),
        (
            "Prior-only Q10 (Recent)",
            """VAR CurrentDate = MAX('Positioning Releases'[report_date])
RETURN
    IF(CurrentDate >= DATE(2024, 1, 1), MAX('Positioning Releases'[prior_q10]))""",
            "0.0%;−0.0%;–",
        ),
        (
            "Rule Event (Recent)",
            """VAR CurrentDate = MAX('Positioning Releases'[report_date])
VAR IsSignal =
    COUNTROWS(FILTER('Positioning Releases', 'Positioning Releases'[signal_emitted] = TRUE())) > 0
RETURN
    IF(
        CurrentDate >= DATE(2024, 1, 1) && IsSignal,
        MAX('Positioning Releases'[normalized_net])
    )""",
            "0.0%;−0.0%;–",
        ),
    ]

    vintage_tmdl_columns = []
    for column in vintage_columns:
        data_type = (
            "int64"
            if column == "wasde_number"
            else "double"
            if column == "value"
            else "boolean"
            if column in {"is_corrected_repost", "has_unit_warning"}
            else "dateTime"
            if column == "report_date"
            else "string"
        )
        vintage_tmdl_columns.append(
            (
                column,
                data_type,
                column == "source_sha256",
                "yyyy-mm-dd" if column == "report_date" else None,
                "WebUrl" if column == "source_url" else None,
            )
        )

    vintage_measures = [
        ("Vintage Count", "DISTINCTCOUNT('WASDE Vintages'[vintage_id])", "#,0"),
        (
            "Corrected Reposts",
            """CALCULATE(
    DISTINCTCOUNT('WASDE Vintages'[vintage_id]),
    'WASDE Vintages'[is_corrected_repost] = TRUE()
)""",
            "#,0",
        ),
        (
            "Unit Warning Rows",
            """CALCULATE(
    COUNTROWS('WASDE Vintages'),
    'WASDE Vintages'[has_unit_warning] = TRUE()
)""",
            "#,0",
        ),
    ]

    revision_tmdl_columns = []
    for column in revision_columns:
        data_type = (
            "int64"
            if column in {"wasde_number", "attribute_sort"}
            else "double"
            if column in {"value", "prior_value", "revision"}
            else "boolean"
            if column in {"is_corrected_repost", "is_decision_story"}
            else "dateTime"
            if column == "report_date"
            else "string"
        )
        revision_tmdl_columns.append(
            (
                column,
                data_type,
                column in {"attribute_sort", "is_decision_story"},
                "yyyy-mm-dd" if column == "report_date" else None,
                None,
            )
        )

    revision_measures = [
        (
            "Aug 2026 Revision (k STRV)",
            """CALCULATE(
    SUM('WASDE Revisions'[revision]),
    KEEPFILTERS('WASDE Revisions'[region] = "United States"),
    KEEPFILTERS('WASDE Revisions'[market_year] = "2026/27"),
    KEEPFILTERS('WASDE Revisions'[report_date] = DATE(2026, 8, 12)),
    KEEPFILTERS(
        'WASDE Revisions'[attribute] IN {
            "Beginning Stocks", "Production", "Total Supply", "Ending Stocks"
        }
    )
)""",
            "+#,0;−#,0;–",
        ),
        (
            "US 26/27 Stocks Use Jul",
            """DIVIDE(
    CALCULATE(
    MAX('WASDE Revisions'[prior_value]),
    REMOVEFILTERS('WASDE Revisions'),
    'WASDE Revisions'[region] = "United States",
    'WASDE Revisions'[market_year] = "2026/27",
    'WASDE Revisions'[report_date] = DATE(2026, 8, 12),
    'WASDE Revisions'[attribute] = "Stocks to Use Ratio"
    ),
    100
)""",
            "0.0%",
        ),
        (
            "US 26/27 Stocks Use Aug",
            """DIVIDE(
    CALCULATE(
    MAX('WASDE Revisions'[value]),
    REMOVEFILTERS('WASDE Revisions'),
    'WASDE Revisions'[region] = "United States",
    'WASDE Revisions'[market_year] = "2026/27",
    'WASDE Revisions'[report_date] = DATE(2026, 8, 12),
    'WASDE Revisions'[attribute] = "Stocks to Use Ratio"
    ),
    100
)""",
            "0.0%",
        ),
        (
            "US 26/27 Stocks Use Move",
            """CALCULATE(
    MAX('WASDE Revisions'[revision]),
    REMOVEFILTERS('WASDE Revisions'),
    'WASDE Revisions'[region] = "United States",
    'WASDE Revisions'[market_year] = "2026/27",
    'WASDE Revisions'[report_date] = DATE(2026, 8, 12),
    'WASDE Revisions'[attribute] = "Stocks to Use Ratio"
)""",
            "+0.0 pp;−0.0 pp;–",
        ),
    ]

    audit_tmdl_columns = []
    for column in audit_columns:
        data_type = (
            "dateTime"
            if column == "report_date"
            else "boolean"
            if column == "is_corrected_repost"
            else "int64"
            if column == "unit_warning_count"
            else "string"
        )
        audit_tmdl_columns.append(
            (
                column,
                data_type,
                column == "source_sha256",
                "yyyy-mm-dd" if column == "report_date" else None,
                "WebUrl" if column == "source_url" else None,
            )
        )

    audit_measures = [
        ("Positioning Release Count", "COUNTROWS('Positioning Releases')", "#,0"),
        ("WASDE Vintage Count", "DISTINCTCOUNT('WASDE Vintages'[vintage_id])", "#,0"),
        (
            "Audit Corrected Reposts",
            """CALCULATE(
    DISTINCTCOUNT('WASDE Vintages'[vintage_id]),
    'WASDE Vintages'[is_corrected_repost] = TRUE()
)""",
            "#,0",
        ),
        (
            "Provenance Complete",
            """DIVIDE(
    COUNTROWS(
        FILTER(
            'Audit Sources',
            NOT ISBLANK('Audit Sources'[source_url])
                && NOT ISBLANK('Audit Sources'[source_sha256])
                && NOT ISBLANK('Audit Sources'[available_at_utc])
        )
    ),
    COUNTROWS('Audit Sources')
)""",
            "0.0%",
        ),
        (
            "Audit Unit Warnings",
            "SUM('Audit Sources'[unit_warning_count])",
            "#,0",
        ),
    ]

    write_text(
        MODEL_DIR / "definition" / "tables" / "Positioning Releases.tmdl",
        tmdl_table(
            "Positioning Releases",
            position_tmdl_columns,
            positioning_measures,
            m_partition(model_payloads["positioning"], position_columns, pos_types),
        ),
    )
    write_text(
        MODEL_DIR / "definition" / "tables" / "WASDE Vintages.tmdl",
        tmdl_table(
            "WASDE Vintages",
            vintage_tmdl_columns,
            vintage_measures,
            m_partition(model_payloads["vintages"], vintage_columns, vintage_types),
        ),
    )
    revision_tmdl = tmdl_table(
        "WASDE Revisions",
        revision_tmdl_columns,
        revision_measures,
        m_partition(model_payloads["revisions"], revision_columns, revision_types),
    )
    revision_tmdl = revision_tmdl.replace(
        "\t\tsourceColumn: attribute\n",
        "\t\tsourceColumn: attribute\n\t\tsortByColumn: attribute_sort\n",
        1,
    )
    write_text(MODEL_DIR / "definition" / "tables" / "WASDE Revisions.tmdl", revision_tmdl)
    write_text(
        MODEL_DIR / "definition" / "tables" / "Audit Sources.tmdl",
        tmdl_table(
            "Audit Sources",
            audit_tmdl_columns,
            audit_measures,
            m_partition(model_payloads["audit"], audit_columns, audit_types),
        ),
    )

    return {
        key: {
            "rows": len(
                {
                    "positioning": positioning,
                    "vintages": vintages,
                    "revisions": revisions,
                    "audit": audit_rows,
                }[key]
            ),
            "embedded_sha256": sha256_bytes(payload),
            "embedded_bytes": len(payload),
        }
        for key, payload in model_payloads.items()
    }


def build_report() -> None:
    decision_page = "DecisionLens"
    audit_page = "AuditSources"

    write_json(
        REPORT_DIR / "definition" / "version.json",
        {"$schema": VERSION_SCHEMA, "version": "2.0.0"},
    )
    write_json(
        REPORT_DIR / "definition" / "report.json",
        {
            "$schema": REPORT_SCHEMA,
            "themeCollection": {},
            "objects": {
                "outspacePane": [
                    {
                        "properties": {
                            "expanded": literal(False),
                            "visible": literal(True),
                        }
                    }
                ]
            },
        },
    )
    write_json(
        REPORT_DIR / "definition" / "pages" / "pages.json",
        {
            "$schema": PAGES_SCHEMA,
            "pageOrder": [decision_page, audit_page],
            "activePageName": decision_page,
        },
    )

    page_background: JSON = {
        "background": [
            {
                "properties": {
                    "color": color("#EEF3F4"),
                    "transparency": literal(0.0),
                }
            }
        ],
        "outspace": [
            {
                "properties": {
                    "color": color("#DDE7EA"),
                    "transparency": literal(0.0),
                }
            }
        ],
    }
    for page_id, display_name in (
        (decision_page, "Decision Lens"),
        (audit_page, "Audit & Sources"),
    ):
        write_json(
            REPORT_DIR / "definition" / "pages" / page_id / "page.json",
            {
                "$schema": PAGE_SCHEMA,
                "name": page_id,
                "displayName": display_name,
                "displayOption": "FitToPage",
                "height": 720,
                "width": 1280,
                "objects": page_background,
            },
        )

    decision_visuals = [
        textbox(
            "d0010000000000000001",
            position(20, 18, 1240, 52, 1000),
            [("SUGAR NO. 11  |  DECISION LENS", 25, "#FFFFFF", True)],
            background="#153E52",
            border="#153E52",
            alt_text="Sugar No. 11 Decision Lens report title",
        ),
        textbox(
            "d0010000000000000002",
            position(20, 76, 1240, 32, 2000),
            [
                (
                    "PUBLIC DATA   •   NO PRICE SERIES   •   RULE NOT RETUNED",
                    12,
                    "#075E54",
                    True,
                )
            ],
            background="#DFF3ED",
            border="#8BC7B7",
            alt_text="Disclosure badges: public data, no price series, rule not retuned",
        ),
        textbox(
            "d0010000000000000003",
            position(20, 112, 820, 88, 3000),
            [
                ("AUGUST 2026 WASDE — U.S. 2026/27", 13, "#153E52", True),
                (
                    "Carry-in loosened the balance despite a crop downgrade: beginning stocks "
                    "+218k STRV; production −54k; total supply +168k; ending stocks +168k; "
                    "stocks/use 13.5% → 14.8%.",
                    12,
                    "#20343E",
                    False,
                ),
            ],
            background="#FFFFFF",
            border="#DCE4E8",
            alt_text="August 2026 WASDE frozen decision narrative",
        ),
        textbox(
            "d0010000000000000004",
            position(858, 112, 402, 88, 4000),
            [
                ("POSITIONING CHECK — 11 AUGUST 2026", 13, "#153E52", True),
                (
                    "Managed-money net +43,584 (+3.91% of OI), versus −87,188 "
                    "(−8.26%) on 4 August. Event status is determined only by the frozen rule.",
                    12,
                    "#20343E",
                    False,
                ),
            ],
            background="#FFFFFF",
            border="#DCE4E8",
            alt_text="Current and prior CFTC positioning context with frozen-rule caveat",
        ),
        card(
            "d0010000000000000005",
            position(20, 210, 600, 138, 5000),
            [
                ("WASDE Revisions", "US 26/27 Stocks Use Jul"),
                ("WASDE Revisions", "US 26/27 Stocks Use Aug"),
                ("WASDE Revisions", "US 26/27 Stocks Use Move"),
            ],
            alt_text="U.S. 2026/27 July and August stocks-to-use ratio and percentage-point move",
        ),
        card(
            "d0010000000000000006",
            position(638, 210, 622, 138, 6000),
            [
                ("Positioning Releases", "Latest Net Contracts"),
                ("Positioning Releases", "Latest Net as % OI"),
                ("Positioning Releases", "Previous Net Contracts"),
                ("Positioning Releases", "Latest Rule Status"),
            ],
            alt_text="Latest and prior CFTC managed-money positioning and frozen rule status",
        ),
        chart(
            "d0010000000000000007",
            position(20, 365, 470, 335, 7000),
            "clusteredBarChart",
            {
                "Category": {
                    "projections": [projection("WASDE Revisions", "attribute", active=True)]
                },
                "Y": {
                    "projections": [
                        projection("WASDE Revisions", "Aug 2026 Revision (k STRV)", "Measure")
                    ]
                },
            },
            title="U.S. 2026/27 August revision",
            subtitle="Change versus July • thousand short tons, raw value",
            objects={
                "categoryAxis": [
                    {"properties": {"show": literal(True), "fontSize": literal(10.0)}}
                ],
                "valueAxis": [
                    {
                        "properties": {
                            "show": literal(True),
                            "gridlineStyle": literal("dotted"),
                            "gridlineColor": color("#CBD5D9"),
                            "titleText": literal("k STRV"),
                        }
                    }
                ],
                "dataPoint": [{"properties": {"fill": color("#0F766E")}}],
                "labels": [
                    {
                        "properties": {
                            "show": literal(True),
                            "fontSize": literal(10.0),
                            "color": color("#20343E"),
                            "labelDisplayUnits": literal(0),
                        }
                    }
                ],
            },
            sort_definition={
                "sort": [
                    {
                        "field": {
                            "Column": {
                                "Expression": source_expression("WASDE Revisions"),
                                "Property": "attribute",
                            }
                        },
                        "direction": "Ascending",
                    }
                ],
                "isDefaultSort": True,
            },
            alt_text=(
                "Bar chart of August versus July U.S. 2026/27 revisions for beginning stocks, "
                "production, total supply, and ending stocks in thousand STRV"
            ),
        ),
        chart(
            "d0010000000000000008",
            position(508, 365, 752, 335, 8000),
            "lineChart",
            {
                "Category": {
                    "projections": [projection("Positioning Releases", "report_date", active=True)]
                },
                "Y": {
                    "projections": [
                        projection("Positioning Releases", "Normalized Net (Recent)", "Measure"),
                        projection("Positioning Releases", "Prior-only Q10 (Recent)", "Measure"),
                        projection("Positioning Releases", "Rule Event (Recent)", "Measure"),
                    ]
                },
            },
            title="Managed money positioning versus prior-only Q10",
            subtitle="Weekly CFTC Sugar No. 11 • event marker only when frozen rule emits",
            objects={
                "categoryAxis": [
                    {
                        "properties": {
                            "axisType": literal("Scalar"),
                            "show": literal(True),
                            "fontSize": literal(9.0),
                        }
                    }
                ],
                "valueAxis": [
                    {
                        "properties": {
                            "show": literal(True),
                            "gridlineStyle": literal("dotted"),
                            "gridlineColor": color("#CBD5D9"),
                            "labelDisplayUnits": literal(1),
                            "labelPrecision": literal(0),
                        }
                    }
                ],
                "dataPoint": [
                    {
                        "properties": {"fill": color("#0F766E")},
                        "selector": {"metadata": "Positioning Releases.Normalized Net (Recent)"},
                    },
                    {
                        "properties": {"fill": color("#D97706")},
                        "selector": {"metadata": "Positioning Releases.Prior-only Q10 (Recent)"},
                    },
                    {
                        "properties": {"fill": color("#BE123C")},
                        "selector": {"metadata": "Positioning Releases.Rule Event (Recent)"},
                    },
                ],
                "lineStyles": [
                    {
                        "properties": {
                            "strokeWidth": literal(2.0),
                            "showMarker": literal(False),
                        },
                        "selector": {"metadata": "Positioning Releases.Normalized Net (Recent)"},
                    },
                    {
                        "properties": {
                            "lineStyle": literal("dashed"),
                            "strokeWidth": literal(2.0),
                            "showMarker": literal(False),
                        },
                        "selector": {"metadata": "Positioning Releases.Prior-only Q10 (Recent)"},
                    },
                    {
                        "properties": {
                            "strokeWidth": literal(1.0),
                            "showMarker": literal(True),
                            "markerShape": literal("diamond"),
                            "markerSize": literal(9.0),
                        },
                        "selector": {"metadata": "Positioning Releases.Rule Event (Recent)"},
                    },
                ],
                "legend": [
                    {
                        "properties": {
                            "show": literal(True),
                            "position": literal("Top"),
                            "fontSize": literal(9.0),
                        }
                    }
                ],
            },
            sort_definition={
                "sort": [
                    {
                        "field": {
                            "Column": {
                                "Expression": source_expression("Positioning Releases"),
                                "Property": "report_date",
                            }
                        },
                        "direction": "Ascending",
                    }
                ],
                "isDefaultSort": True,
            },
            alt_text=(
                "Line chart from 2024 showing normalized managed-money net position, the "
                "prior-only tenth percentile, and frozen-rule signal event markers"
            ),
        ),
    ]

    audit_visuals = [
        textbox(
            "a0010000000000000001",
            position(20, 18, 1240, 52, 1000),
            [("AUDIT & SOURCES  |  AVAILABILITY & VINTAGE PROVENANCE", 25, "#FFFFFF", True)],
            background="#153E52",
            border="#153E52",
            alt_text="Audit and Sources report title",
        ),
        textbox(
            "a0010000000000000002",
            position(20, 78, 560, 202, 2000),
            [
                ("FROZEN RESEARCH CONTRACT", 13, "#153E52", True),
                (
                    "• CFTC 080732 • prior-only empirical Q10 after ≥156 releases • "
                    "positive reversal • 91-day cooldown.",
                    9,
                    "#20343E",
                    False,
                ),
                (
                    "• Retrospective publication-aware reconstruction: retained actual "
                    "release overrides where available; otherwise rule-modelled historical "
                    "release times and current snapshot values. Not a strict value-vintage "
                    "backtest.",
                    9,
                    "#20343E",
                    False,
                ),
                (
                    "• No price series enters the rule • not retuned for sugar.",
                    9,
                    "#20343E",
                    False,
                ),
                (
                    "• USDA available_at_utc gates genuine point-in-time vintages; corrected "
                    "reposts append a new source version rather than overwrite history.",
                    9,
                    "#20343E",
                    False,
                ),
                (
                    "• U.S./Mexico units never combine; ratio rows retain raw units + warning "
                    "and normalize to Percent.",
                    9,
                    "#20343E",
                    False,
                ),
            ],
            background="#FFFFFF",
            border="#DCE4E8",
            alt_text=(
                "Frozen positioning rule, retrospective CFTC reconstruction, genuine USDA "
                "point-in-time vintages, revisions, and unit methodology"
            ),
        ),
        card(
            "a0010000000000000003",
            position(598, 78, 662, 202, 3000),
            [
                ("Audit Sources", "Positioning Release Count"),
                ("Audit Sources", "WASDE Vintage Count"),
                ("Audit Sources", "Audit Corrected Reposts"),
                ("Audit Sources", "Provenance Complete"),
                ("Audit Sources", "Audit Unit Warnings"),
            ],
            alt_text="Coverage, correction, provenance completeness, and unit warning metrics",
        ),
        table_visual(
            "a0010000000000000004",
            position(20, 298, 1240, 206, 4000),
            [
                ("Audit Sources", "dataset", "Column"),
                ("Audit Sources", "record_key", "Column"),
                ("Audit Sources", "report_label", "Column"),
                ("Audit Sources", "available_at_utc", "Column"),
                ("Audit Sources", "availability_basis", "Column"),
                ("Audit Sources", "source_version", "Column"),
                ("Audit Sources", "is_corrected_repost", "Column"),
                ("Audit Sources", "sha256_short", "Column"),
                ("Audit Sources", "source_url", "Column"),
            ],
            title="Source ledger",
            subtitle="Availability boundary, version, correction flag, SHA-256 prefix, and URL",
            sort_table="Audit Sources",
            sort_column="report_date",
            alt_text="Auditable source ledger for CFTC and USDA inputs",
        ),
        table_visual(
            "a0010000000000000005",
            position(20, 520, 1240, 180, 5000),
            [
                ("WASDE Vintages", "report_label", "Column"),
                ("WASDE Vintages", "region", "Column"),
                ("WASDE Vintages", "market_year", "Column"),
                ("WASDE Vintages", "attribute", "Column"),
                ("WASDE Vintages", "raw_value", "Column"),
                ("WASDE Vintages", "raw_unit", "Column"),
                ("WASDE Vintages", "value", "Column"),
                ("WASDE Vintages", "normalized_unit", "Column"),
                ("WASDE Vintages", "unit_warning", "Column"),
            ],
            title="Unit audit",
            subtitle="Published raw value/unit retained beside normalized value/unit and warning",
            sort_table="WASDE Vintages",
            sort_column="report_date",
            alt_text="WASDE sugar raw and normalized units with explicit unit warnings",
        ),
    ]

    for visual in decision_visuals:
        write_visual(decision_page, visual)
    for visual in audit_visuals:
        write_visual(audit_page, visual)


def build_scaffold() -> None:
    write_json(
        POWERBI_DIR / f"{PROJECT_NAME}.pbip",
        {
            "$schema": PBIP_SCHEMA,
            "version": "1.0",
            "artifacts": [{"report": {"path": f"{PROJECT_NAME}.Report"}}],
            "settings": {"enableAutoRecovery": True},
        },
    )
    write_json(
        REPORT_DIR / "definition.pbir",
        {
            "$schema": PBIR_SCHEMA,
            "version": "4.0",
            "datasetReference": {"byPath": {"path": f"../{PROJECT_NAME}.SemanticModel"}},
        },
    )
    write_json(
        REPORT_DIR / ".platform",
        {
            "$schema": PLATFORM_SCHEMA,
            "metadata": {"type": "Report", "displayName": "Sugar No. 11"},
            "config": {
                "version": "2.0",
                "logicalId": "a9058ec1-f9b0-5f80-a7b9-8e3db39c8902",
            },
        },
    )
    write_json(
        MODEL_DIR / "definition.pbism",
        {"$schema": PBISM_SCHEMA, "version": "4.2", "settings": {"qnaEnabled": False}},
    )
    write_json(
        MODEL_DIR / ".platform",
        {
            "$schema": PLATFORM_SCHEMA,
            "metadata": {"type": "SemanticModel", "displayName": "Sugar No. 11"},
            "config": {
                "version": "2.0",
                "logicalId": "b60adbc5-6454-5a63-8653-f53be703d79b",
            },
        },
    )
    write_text(
        MODEL_DIR / "definition" / "database.tmdl",
        "database\n\tcompatibilityLevel: 1702\n\tcompatibilityMode: powerBI\n",
    )
    write_text(
        MODEL_DIR / "definition" / "model.tmdl",
        """model Model
\tculture: en-GB
\tdefaultPowerBIDataSourceVersion: powerBI_V3
\tdiscourageImplicitMeasures
\tsourceQueryCulture: en-GB

\tdataAccessOptions
\t\tlegacyRedirects
\t\treturnErrorValuesAsNull

annotation Report_SourceFiles = [\"../../data/derived/positioning_releases.csv\",\
\"../../data/derived/wasde_sugar_vintages.csv\",\
\"../../data/derived/wasde_sugar_revisions.csv\"]
annotation Report_AsOfUTC = 2026-08-20T23:59:59Z
annotation Report_Disclosures = PUBLIC DATA | NO PRICE SERIES | RULE NOT RETUNED
annotation PBI_QueryOrder = [\"Positioning Releases\",\"WASDE Vintages\",\
\"WASDE Revisions\",\"Audit Sources\"]
annotation __PBI_TimeIntelligenceEnabled = 0

ref table 'Positioning Releases'
ref table 'WASDE Vintages'
ref table 'WASDE Revisions'
ref table 'Audit Sources'
""",
    )


def build() -> None:
    positioning, positioning_bytes = read_csv(INPUT_FILES["positioning"], POSITIONING_COLUMNS)
    vintages, vintages_bytes = read_csv(INPUT_FILES["vintages"], VINTAGE_COLUMNS)
    revisions, revisions_bytes = read_csv(INPUT_FILES["revisions"], REVISION_COLUMNS)
    audit_rows = add_report_columns(positioning, vintages, revisions)

    build_scaffold()
    embedded = build_model(positioning, vintages, revisions, audit_rows)
    build_report()

    input_bytes = {
        "positioning": positioning_bytes,
        "vintages": vintages_bytes,
        "revisions": revisions_bytes,
    }
    manifest: JSON = {
        "schema_version": 1,
        "built_for_power_bi_desktop": "2.157.879.0",
        "as_of_utc": "2026-08-20T23:59:59Z",
        "embedding": (
            "Deterministic raw CSV bytes encoded as Base64 inside Power Query M; refresh "
            "requires no absolute path or credentials. Re-run this script after pipeline "
            "exports change."
        ),
        "inputs": {
            key: {
                "relative_path": f"../data/derived/{INPUT_FILES[key]}",
                "sha256": sha256_bytes(payload),
                "bytes": len(payload),
                **embedded[key],
            }
            for key, payload in input_bytes.items()
        },
        "derived_model_tables": {"audit": embedded["audit"]},
    }
    write_json(POWERBI_DIR / "data_manifest.json", manifest)


if __name__ == "__main__":
    build()
