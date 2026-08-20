"""Validation for immutable, content-addressed public source extracts."""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Final
from urllib.parse import urlparse

MANIFEST_FIELDS: Final = (
    "source_id",
    "source_type",
    "provider",
    "source_url",
    "landing_page_url",
    "public_path",
    "source_effective_at_utc",
    "available_at_utc",
    "available_at_basis",
    "retrieved_at_utc",
    "source_version",
    "is_corrected_repost",
    "upstream_byte_count",
    "upstream_sha256",
    "public_byte_count",
    "public_sha256",
    "extract_method",
    "rights_note",
    "notes",
)

SOURCE_TYPES: Final = frozenset(
    {
        "cftc_selected_history",
        "cftc_release_calendar",
        "cftc_release_verification",
        "usda_wasde_sugar_snapshot",
    }
)
ALLOWED_SOURCE_HOSTS: Final = frozenset(
    {
        "www.cftc.gov",
        "publicreporting.cftc.gov",
        "www.usda.gov",
    }
)


class StudyError(ValueError):
    """Base exception for invalid study data or configuration."""


class SourceIntegrityError(StudyError):
    """A committed extract no longer matches its provenance record."""


def parse_timestamp(value: str, *, field: str, allow_blank: bool = False) -> datetime | None:
    """Parse a timezone-aware timestamp and normalize it to UTC."""

    if not value and allow_blank:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise StudyError(f"invalid {field}: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise StudyError(f"{field} must include a UTC offset: {value!r}")
    return parsed.astimezone(UTC)


def iso_utc(value: datetime) -> str:
    """Return a second-precision ISO 8601 UTC timestamp."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise StudyError("timestamp must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    """Hash a file without loading the entire payload in memory."""

    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class SourceRecord:
    """Immutable provenance for one committed, rights-minimal source extract."""

    source_id: str
    source_type: str
    provider: str
    source_url: str
    landing_page_url: str
    public_path: str
    source_effective_at_utc: datetime | None
    available_at_utc: datetime | None
    available_at_basis: str
    retrieved_at_utc: datetime
    source_version: str
    is_corrected_repost: bool
    upstream_byte_count: int | None
    upstream_sha256: str | None
    public_byte_count: int
    public_sha256: str
    extract_method: str
    rights_note: str
    notes: str


def _content_path(value: str) -> PurePosixPath:
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise StudyError(f"public_path must be repository-relative: {value!r}")
    if candidate.parts[:2] != ("data", "raw"):
        raise StudyError(f"public_path must stay under data/raw: {value!r}")
    return candidate


def _validate_url(value: str, *, field: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_SOURCE_HOSTS:
        raise StudyError(f"{field} must be an approved HTTPS government URL: {value!r}")


def _positive_int(value: str, *, field: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise StudyError(f"invalid {field}: {value!r}") from exc
    if parsed <= 0:
        raise StudyError(f"{field} must be positive")
    return parsed


def _digest(value: str, *, field: str) -> str:
    normalized = value.lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise StudyError(f"invalid {field}: {value!r}")
    return normalized


def _optional_upstream_metadata(
    byte_count: str, digest: str, *, source_id: str
) -> tuple[int | None, str | None]:
    if not byte_count and not digest:
        return None, None
    if not byte_count or not digest:
        raise StudyError(f"incomplete upstream metadata for {source_id}")
    return (
        _positive_int(byte_count, field="upstream_byte_count"),
        _digest(digest, field="upstream_sha256"),
    )


def load_manifest(path: Path) -> tuple[SourceRecord, ...]:
    """Load the append-only manifest and reject ambiguous or unsafe records."""

    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != MANIFEST_FIELDS:
                raise StudyError(
                    f"unexpected manifest columns: {reader.fieldnames!r}; "
                    f"expected {MANIFEST_FIELDS!r}"
                )
            rows = list(reader)
    except FileNotFoundError as exc:
        raise StudyError(f"source manifest not found: {path}") from exc
    if not rows:
        raise StudyError("source manifest is empty")

    output: list[SourceRecord] = []
    ids: set[str] = set()
    paths: set[str] = set()
    public_hashes: set[str] = set()
    for row in rows:
        if None in row or None in row.values():
            raise StudyError("source manifest contains a malformed row")
        source_id = row["source_id"]
        if not source_id or source_id in ids:
            raise StudyError(f"blank or duplicate source_id: {source_id!r}")
        source_type = row["source_type"]
        if source_type not in SOURCE_TYPES:
            raise StudyError(f"invalid source_type for {source_id}: {source_type!r}")
        public_path = str(_content_path(row["public_path"]))
        if public_path in paths:
            raise StudyError(f"duplicate public_path: {public_path}")
        _validate_url(row["source_url"], field="source_url")
        _validate_url(row["landing_page_url"], field="landing_page_url")
        corrected = row["is_corrected_repost"].lower()
        if corrected not in {"true", "false"}:
            raise StudyError(f"invalid is_corrected_repost for {source_id}")
        public_sha = _digest(row["public_sha256"], field="public_sha256")
        if public_sha in public_hashes:
            raise StudyError(f"duplicate public content hash: {public_sha}")
        retrieved = parse_timestamp(row["retrieved_at_utc"], field="retrieved_at_utc")
        if retrieved is None:  # pragma: no cover - blank is not allowed
            raise AssertionError("retrieved timestamp unexpectedly absent")
        effective = parse_timestamp(
            row["source_effective_at_utc"],
            field="source_effective_at_utc",
            allow_blank=True,
        )
        available = parse_timestamp(
            row["available_at_utc"], field="available_at_utc", allow_blank=True
        )
        if source_type == "usda_wasde_sugar_snapshot":
            if effective is None or available is None:
                raise StudyError(f"USDA timing fields cannot be blank for {source_id}")
            if available < effective:
                raise StudyError(f"USDA availability precedes report release for {source_id}")
        upstream_byte_count, upstream_sha256 = _optional_upstream_metadata(
            row["upstream_byte_count"], row["upstream_sha256"], source_id=source_id
        )
        if upstream_sha256 is None and source_type not in {
            "cftc_release_calendar",
            "cftc_release_verification",
        }:
            raise StudyError(f"upstream metadata cannot be blank for {source_id}")

        ids.add(source_id)
        paths.add(public_path)
        public_hashes.add(public_sha)
        output.append(
            SourceRecord(
                source_id=source_id,
                source_type=source_type,
                provider=row["provider"],
                source_url=row["source_url"],
                landing_page_url=row["landing_page_url"],
                public_path=public_path,
                source_effective_at_utc=effective,
                available_at_utc=available,
                available_at_basis=row["available_at_basis"],
                retrieved_at_utc=retrieved,
                source_version=row["source_version"],
                is_corrected_repost=corrected == "true",
                upstream_byte_count=upstream_byte_count,
                upstream_sha256=upstream_sha256,
                public_byte_count=_positive_int(
                    row["public_byte_count"], field="public_byte_count"
                ),
                public_sha256=public_sha,
                extract_method=row["extract_method"],
                rights_note=row["rights_note"],
                notes=row["notes"],
            )
        )
    return tuple(sorted(output, key=lambda item: (item.retrieved_at_utc, item.source_id)))


def verify_sources(repo_root: Path) -> tuple[SourceRecord, ...]:
    """Verify every committed factual extract by byte count and SHA-256."""

    records = load_manifest(repo_root / "data" / "source_manifest.csv")
    for record in records:
        path = repo_root.joinpath(*PurePosixPath(record.public_path).parts)
        if not path.is_file():
            raise SourceIntegrityError(f"public source extract is missing: {record.public_path}")
        if path.stat().st_size != record.public_byte_count:
            raise SourceIntegrityError(f"byte count mismatch for {record.public_path}")
        if sha256_file(path) != record.public_sha256:
            raise SourceIntegrityError(f"SHA-256 mismatch for {record.public_path}")
    return records
