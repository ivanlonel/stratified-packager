"""
CSV reporting: the run-level report and the per-zip reports (SPEC §9).

CSV is data, not UI: UTF-8 without BOM, header row, untranslated column names and
status tokens (SPEC §20). This module needs no ``qgis`` import — rows arrive as plain
data from the algorithm thread.
"""

from __future__ import annotations

import csv
from dataclasses import astuple, dataclass, fields
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

__all__: list[str] = [
    "STATUS_COLD_FALLBACK",
    "STATUS_DRY_RUN",
    "STATUS_EMPTY_KEPT",
    "STATUS_EMPTY_SKIPPED",
    "STATUS_FAILED",
    "STATUS_OK",
    "STATUS_SKIPPED_EXISTING",
    "STATUS_WARM",
    "UNMATCHED_KEY",
    "RunReportRow",
    "ZipReportRow",
    "write_zip_report",
]

# §9.1 status vocabulary (shared by both reports).
STATUS_OK: Final = "ok"
STATUS_WARM: Final = "warm"
STATUS_COLD_FALLBACK: Final = "cold-fallback"
STATUS_EMPTY_KEPT: Final = "empty-kept"
STATUS_EMPTY_SKIPPED: Final = "empty-skipped"
STATUS_FAILED: Final = "failed"
STATUS_SKIPPED_EXISTING: Final = "skipped-existing"
STATUS_DRY_RUN: Final = "dry-run"

UNMATCHED_KEY: Final = "<unmatched>"
"""Pseudo-stratum of the orphan-accounting rows (SPEC §9.1)."""


@dataclass(frozen=True)
class RunReportRow:
    """One row of the run-level report (SPEC §9.1)."""

    stratum: str
    """Stratum name (or ``<unmatched>`` / ``<full>``)."""

    layer: str
    """Layer name."""

    feature_count: int | None = None
    """Features exported (empty cell when unknown/not applicable)."""

    status: str = STATUS_OK
    """One of the §9.1 status tokens."""

    detail: str = ""
    """Error text or note."""


@dataclass(frozen=True)
class ZipReportRow:
    """One row of a per-zip ``report.csv`` (SPEC §9.2)."""

    stratum: str
    """Member stratum name."""

    layer_name: str
    """Layer name."""

    gpkg_table: str = ""
    """Table inside the member gpkg (empty for layers without one)."""

    path_in_zip: str = ""
    """``<gpkg path>.gpkg``, a ``data/...`` payload path, or empty."""

    layer_type: str = ""
    """``vector`` | ``raster`` | ``mesh`` | ``point-cloud``."""

    geometry_type: str = ""
    """Geometry type (vector layers only)."""

    feature_count: int | None = None
    """Features exported into this stratum's table (empty for non-vector)."""

    field_count: int | None = None
    """Exported fields after exclusions (empty for non-vector)."""

    excluded_fields: str = ""
    """Semicolon-joined excluded field names."""

    matching_method: str = ""
    """``attribute`` | ``spatial`` | ``whole_export`` (as resolved)."""

    match_detail: str = ""
    """Relation-path ids or the spatial predicate used."""

    source_crs: str = ""
    """Source CRS authid."""

    status: str = STATUS_OK
    """One of the §9.1 status tokens."""

    detail: str = ""
    """Error text or note."""


def _write(path: Path, header: tuple[str, ...], rows: Iterable[tuple[object, ...]]) -> Path:
    """
    Write one CSV (UTF-8, no BOM, header row).

    :param path: Destination (parent directories are created).
    :param header: Column names.
    :param rows: Cell tuples; :data:`None` cells render empty.
    :return: *path*.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for row in rows:
            writer.writerow(["" if cell is None else cell for cell in row])
    return path


def write_zip_report(path: Path, rows: Iterable[ZipReportRow], /) -> Path:
    """
    Write one per-zip ``report.csv`` (SPEC §9.2).

    :param path: Destination CSV path (staged into the zip's build area).
    :param rows: One row per (member stratum x included layer).
    :return: *path*.
    """
    header = tuple(field.name for field in fields(ZipReportRow))
    # astuple keeps the body aligned with the fields()-derived header by construction.
    return _write(path, header, (astuple(row) for row in rows))
