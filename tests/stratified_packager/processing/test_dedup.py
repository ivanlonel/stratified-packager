"""
Tests for :mod:`stratified_packager.processing.dedup` (SPEC §12 source keying).

The full group-merge is exercised end-to-end in ``test_algorithm``'s dedup scenarios; here we
cover the source-key normalization (subset ignored, path resolved) and the subset-column scan.
"""
# pylint: disable=redefined-outer-name

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

pytest.importorskip("qgis", reason="Source keying drives the QGIS provider registry.")

# Imported only after the importorskip guard above confirms QGIS is available.
from qgis.core import QgsProcessingFeedback, QgsVectorLayer

from stratified_packager.processing.dedup import _subset_columns, source_group_key
from tests.stratified_packager._qgis_helpers import build_alpha_gpkg

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.qgis
"""Marks the whole module as requiring a QGIS runtime."""


@pytest.fixture
def feedback() -> QgsProcessingFeedback:
    """Return a plain feedback sink."""
    return QgsProcessingFeedback()


class TestSourceGroupKey:
    """`source_group_key` groups by normalized source, ignoring per-layer subsets (§12)."""

    def test_same_source_different_subset_shares_a_key(
        self, tmp_path: Path, feedback: QgsProcessingFeedback
    ) -> None:
        """Two layers over one table with different subsets normalize to the same key."""
        gpkg = build_alpha_gpkg(tmp_path / "src.gpkg")
        uri = f"{gpkg}|layername=alpha"
        first = QgsVectorLayer(uri, "a", "ogr")
        second = QgsVectorLayer(uri, "b", "ogr")
        assert first.isValid()
        assert second.isValid()
        assert second.setSubsetString('"a" > 1')
        assert source_group_key(first, feedback) == source_group_key(second, feedback)

    def test_different_tables_differ(
        self, tmp_path: Path, feedback: QgsProcessingFeedback
    ) -> None:
        """A different table in the same file is a different group."""
        gpkg = build_alpha_gpkg(tmp_path / "src.gpkg")
        alpha = QgsVectorLayer(f"{gpkg}|layername=alpha", "a", "ogr")
        memory = QgsVectorLayer("Point?crs=EPSG:4326&field=a:integer", "m", "memory")
        assert alpha.isValid()
        assert memory.isValid()
        assert source_group_key(alpha, feedback) != source_group_key(memory, feedback)


class TestSubsetColumns:
    """`_subset_columns` names the fields a subset string references."""

    def test_scans_quoted_and_bare_identifiers(self) -> None:
        """Both quoted and bare field references are detected, in field order."""
        layer = QgsVectorLayer(
            "Point?crs=EPSG:4326&field=a:integer&field=b:string&field=c:double", "pts", "memory"
        )
        assert _subset_columns('"a" > 1 AND c < 2', layer) == ["a", "c"]

    def test_empty_subset_is_empty(self) -> None:
        """No subset string references no fields."""
        layer = QgsVectorLayer("Point?crs=EPSG:4326&field=a:integer", "pts", "memory")
        assert not _subset_columns("", layer)
