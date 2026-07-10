"""
Tests for :mod:`stratified_packager.processing.virtual` (SPEC §4/§13 virtual routing).

Exercises the materialize-vs-keep-live decision over by-id virtual layers built in-test.
The end-to-end routing through the algorithm is covered in ``test_algorithm``.
"""
# pylint: disable=redefined-outer-name

from __future__ import annotations

import pytest

pytest.importorskip("qgis", reason="Virtual-layer routing drives the QGIS provider stack.")

# Imported only after the importorskip guard above confirms QGIS is available.
from qgis.core import (
    QgsExpressionContextUtils,
    QgsProcessingFeedback,
    QgsProject,
    QgsVectorLayer,
    QgsVirtualLayerDefinition,
)

from stratified_packager.processing import params as p
from stratified_packager.processing import virtual
from stratified_packager.processing.dedup import source_group_key

pytestmark = pytest.mark.qgis
"""Marks the whole module as requiring a QGIS runtime."""


def _setup(project: QgsProject) -> tuple[QgsVectorLayer, QgsVectorLayer]:
    """Add a memory layer + a by-id virtual layer over it; return both."""
    cities = QgsVectorLayer("Point?crs=EPSG:4326&field=cid:integer", "cities", "memory")
    assert cities.isValid()
    assert project.addMapLayer(cities, addToLegend=False)
    definition = QgsVirtualLayerDefinition()
    definition.addSource("c", cities.id())
    definition.setQuery('SELECT * FROM "c"')
    vlayer = QgsVectorLayer(definition.toString(), "v_cities", "virtual")
    return cities, vlayer


class TestVirtualShouldMaterialize:
    """`materialize_virtual_layer` resolution for virtual layers (SPEC §4/§13)."""

    def test_live_when_sources_packaged(self, qgis_new_project: QgsProject) -> None:
        """Every queried source packaged → keep live (do not materialize)."""
        cities, vlayer = _setup(qgis_new_project)
        feedback = QgsProcessingFeedback()
        packaged_ids = frozenset({cities.id()})
        key = source_group_key(cities, feedback)
        packaged_keys = frozenset({key}) if key is not None else frozenset()
        assert (
            virtual._virtual_should_materialize(vlayer, packaged_ids, packaged_keys, feedback)
            is False
        )

    def test_materialize_when_source_unpackaged(self, qgis_new_project: QgsProject) -> None:
        """A source not packaged → materialize the virtual layer instead of keeping it live."""
        _cities, vlayer = _setup(qgis_new_project)
        feedback = QgsProcessingFeedback()
        assert (
            virtual._virtual_should_materialize(vlayer, frozenset(), frozenset(), feedback) is True
        )

    def test_flag_forces_materialize(self, qgis_new_project: QgsProject) -> None:
        """`materialize_virtual_layer=true` materializes even when sources are packaged."""
        cities, vlayer = _setup(qgis_new_project)
        QgsExpressionContextUtils.setLayerVariable(vlayer, p.LAYER_VAR_MATERIALIZE_VIRTUAL, "true")
        feedback = QgsProcessingFeedback()
        assert (
            virtual._virtual_should_materialize(
                vlayer, frozenset({cities.id()}), frozenset(), feedback
            )
            is True
        )
