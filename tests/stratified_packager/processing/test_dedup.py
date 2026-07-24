"""
Tests for :mod:`stratified_packager.processing.dedup` (SPEC §12 source keying).

The full group-merge is exercised end-to-end in ``test_algorithm``'s dedup scenarios; here we
cover the source-key normalization (subset ignored, path resolved), the subset-column scan, and
the §12 opt-out that keeps a layer whose subset the GeoPackage cannot evaluate out of a group.
"""
# pylint: disable=redefined-outer-name

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

pytest.importorskip("qgis", reason="Source keying drives the QGIS provider registry.")

# Imported only after the importorskip guard above confirms QGIS is available.
from qgis.core import QgsProcessingFeedback, QgsVectorLayer

from stratified_packager.processing import params
from stratified_packager.processing.dedup import (
    _subset_columns,
    apply_dedup,
    source_group_key,
)
from stratified_packager.processing.matching import LayerMatchPlan
from stratified_packager.processing.material import _field_indexes, _LayerPrep
from tests.stratified_packager._qgis_helpers import build_alpha_gpkg

if TYPE_CHECKING:
    from pathlib import Path

    from stratified_packager.processing.material import _Material

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


class TestApplyDedupPortability:
    """A subset the delivered GeoPackage cannot evaluate keeps its layer out of the group (§12)."""

    @staticmethod
    def _prep(gpkg: Path, name: str, subset: str) -> _LayerPrep:
        """
        Build a real prep over the shared ``alpha`` table, recording *subset*.

        :param gpkg: The backing GeoPackage.
        :param name: The prep's layer name and initial table.
        :param subset: The provider-native subset SQL (possibly empty).
        :return: The prep.
        """
        uri = f"{gpkg}|layername=alpha"
        layer = QgsVectorLayer(uri, name, "ogr")
        read_layer = QgsVectorLayer(uri, f"{name}_read", "ogr")
        assert layer.isValid()
        assert read_layer.isValid()
        return _LayerPrep(
            layer=layer,
            table=name,
            plan=LayerMatchPlan(layer_id=layer.id(), method=params.MatchingMethod.SPATIAL),
            read_layer=read_layer,
            kept_fields=("a", "b"),
            kept_field_indexes=_field_indexes(read_layer, ("a", "b")),
            excluded_fields=(),
            subset_sql=subset,
        )

    @staticmethod
    def _material(*preps: _LayerPrep) -> _Material:
        """Return a thin material carrying only what :func:`apply_dedup` reads."""
        return cast(
            "_Material",
            SimpleNamespace(inputs=SimpleNamespace(deduplicate=True), preps=list(preps)),
        )

    @pytest.mark.parametrize(
        "unportable",
        [
            "lpad(\"a\", 2, '0') = '01'",
            '"a" IN (SELECT x FROM other_db.foo)',
            "\"a\"::text = '1'",
            "missing = 1",
        ],
        ids=["lpad", "schema-qualified", "postgres-cast", "missing-column"],
    )
    def test_unportable_subset_opts_out_of_grouping(
        self, tmp_path: Path, feedback: QgsProcessingFeedback, unportable: str
    ) -> None:
        """
        The member the GeoPackage can't filter stays standalone; the portable pair still merges.

        :param tmp_path: Pytest temp dir.
        :param feedback: The feedback sink.
        :param unportable: A subset SQLite cannot compile (a foreign PostGIS dialect).
        """
        gpkg = build_alpha_gpkg(tmp_path / "src.gpkg")
        primary = self._prep(gpkg, "plain", "")
        portable = self._prep(gpkg, "portable", '"a" > 1')
        stranded = self._prep(gpkg, "stranded", unportable)
        apply_dedup(self._material(primary, portable, stranded), feedback)
        # The two portable members fold onto the unfiltered primary...
        assert primary.group_primary_id == primary.layer.id()
        assert portable.group_primary_id == primary.layer.id()
        assert portable.table == primary.table
        # ...but the member whose subset only PostGIS can run is left on its own table.
        assert stranded.group_primary_id is None
        assert stranded.table == "stranded"

    def test_portable_subset_still_groups(
        self, tmp_path: Path, feedback: QgsProcessingFeedback
    ) -> None:
        """
        A subset SQLite can compile does not split the group (§12 unchanged).

        :param tmp_path: Pytest temp dir.
        :param feedback: The feedback sink.
        """
        gpkg = build_alpha_gpkg(tmp_path / "src.gpkg")
        primary = self._prep(gpkg, "plain", "")
        portable = self._prep(gpkg, "portable", "substr(\"b\", 1, 3) = 'row'")
        apply_dedup(self._material(primary, portable), feedback)
        assert primary.group_primary_id == primary.layer.id()
        assert portable.group_primary_id == primary.layer.id()
        assert portable.table == primary.table
