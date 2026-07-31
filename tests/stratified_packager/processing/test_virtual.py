"""
Tests for :mod:`stratified_packager.processing.virtual` (SPEC §4/§13 virtual routing).

Exercises the materialize-vs-keep-live decision over by-id virtual layers built in-test.
The end-to-end routing through the algorithm is covered in ``test_algorithm``.
"""
# pylint: disable=redefined-outer-name

from __future__ import annotations

from typing import override

import pytest

pytest.importorskip("qgis", reason="Virtual-layer routing drives the QGIS provider stack.")

# Imported only after the importorskip guard above confirms QGIS is available.
from qgis.core import (
    QgsExpressionContextUtils,
    QgsFeature,
    QgsGeometry,
    QgsMapLayer,
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


def _setup(project: QgsProject, *, lazy: bool = False) -> tuple[QgsVectorLayer, QgsVectorLayer]:
    """Add a one-feature memory layer + a by-id virtual layer over it; return both."""
    cities = QgsVectorLayer("Point?crs=EPSG:4326&field=cid:integer", "cities", "memory")
    assert cities.isValid()
    feature = QgsFeature(cities.fields())
    feature.setAttribute("cid", 1)
    feature.setGeometry(QgsGeometry.fromWkt("POINT(0 0)"))
    provider = cities.dataProvider()
    assert provider is not None
    assert provider.addFeature(feature)
    assert project.addMapLayer(cities, addToLegend=False)
    definition = QgsVirtualLayerDefinition()
    definition.addSource("c", cities.id())
    definition.setQuery('SELECT * FROM "c"')
    definition.setLazy(lazy)
    vlayer = QgsVectorLayer(definition.toString(), "v_cities", "virtual")
    return cities, vlayer


class _RecordingFeedback(QgsProcessingFeedback):
    """Feedback sink that keeps the warnings and debug lines pushed to it."""

    def __init__(self) -> None:
        super().__init__()
        self.warnings: list[str] = []
        self.debug: list[str] = []

    @override
    def pushWarning(self, warning: str | None) -> None:
        """
        Record a warning instead of routing it to the log.

        :param warning: The warning text.
        """
        self.warnings.append(warning or "")

    @override
    def pushDebugInfo(self, info: str | None) -> None:
        """
        Record a debug line instead of routing it to the log.

        :param info: The debug text.
        """
        self.debug.append(info or "")


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


class TestRouteVirtualLayers:
    """The routing pass that splits virtual layers into packaged vs. embedded (SPEC §4/§13)."""

    def test_live_virtual_rides_the_embedded_project(self, qgis_new_project: QgsProject) -> None:
        """Every source packaged → the layer joins the embedded-only list, not the vectors."""
        cities, vlayer = _setup(qgis_new_project)
        vectors: list[QgsVectorLayer] = [cities]
        embedded: list[QgsMapLayer] = []
        virtual.route_virtual_layers(
            [vlayer], vectors, [], embedded, qgis_new_project, QgsProcessingFeedback()
        )
        assert embedded == [vlayer]
        assert vlayer not in vectors

    def test_materialized_virtual_joins_the_packaged_vectors(
        self, qgis_new_project: QgsProject
    ) -> None:
        """An unpackaged source → the layer is materialized alongside the packaged vectors."""
        _cities, vlayer = _setup(qgis_new_project)
        vectors: list[QgsVectorLayer] = []
        embedded: list[QgsMapLayer] = []
        virtual.route_virtual_layers(
            [vlayer], vectors, [], embedded, qgis_new_project, QgsProcessingFeedback()
        )
        assert vectors == [vlayer]
        assert not embedded

    def test_no_virtual_layers_is_a_no_op(self, qgis_new_project: QgsProject) -> None:
        """Nothing to route leaves both lists untouched."""
        vectors: list[QgsVectorLayer] = []
        embedded: list[QgsMapLayer] = []
        virtual.route_virtual_layers(
            [], vectors, [], embedded, qgis_new_project, QgsProcessingFeedback()
        )
        assert not vectors
        assert not embedded


class TestLoadLazyVirtual:
    """Loading a lazy virtual layer before anything reads its features (SPEC §4/§13)."""

    def test_lazy_layer_reads_nothing_until_loaded(self, qgis_new_project: QgsProject) -> None:
        """A lazy definition opens valid but bare; the helper runs the deferred query."""
        _cities, vlayer = _setup(qgis_new_project, lazy=True)
        assert vlayer.isValid()
        assert vlayer.fields().count() == 0
        assert vlayer.featureCount() == 0
        feedback = _RecordingFeedback()
        virtual.load_lazy_virtual(vlayer, feedback)
        assert vlayer.fields().count() > 0
        assert vlayer.featureCount() == 1
        assert len(feedback.debug) == 1
        assert "v_cities" in feedback.debug[0]

    def test_the_lazy_flag_survives_a_clone(self, qgis_new_project: QgsProject) -> None:
        """A clone is rebuilt from the provider uri, so it inherits `lazy` — hence the helper."""
        _cities, vlayer = _setup(qgis_new_project, lazy=True)
        clone = vlayer.clone()
        assert clone is not None
        assert clone.featureCount() == 0
        virtual.load_lazy_virtual(clone, _RecordingFeedback())
        assert clone.featureCount() == 1

    def test_eager_virtual_layer_is_left_alone(self, qgis_new_project: QgsProject) -> None:
        """An already-loaded virtual layer keeps its features and is not re-queried."""
        _cities, vlayer = _setup(qgis_new_project)
        feedback = _RecordingFeedback()
        virtual.load_lazy_virtual(vlayer, feedback)
        assert vlayer.featureCount() == 1
        assert not feedback.debug

    def test_non_virtual_layer_is_a_no_op(self, qgis_new_project: QgsProject) -> None:
        """A layer on any other provider is ignored, so callers need not check the type."""
        cities, _vlayer = _setup(qgis_new_project)
        feedback = _RecordingFeedback()
        virtual.load_lazy_virtual(cities, feedback)
        assert cities.featureCount() == 1
        assert not feedback.debug


class TestRemoteSourceWarning:
    """Materializing a virtual layer over a remote source warns but never re-routes."""

    def _remote_virtual(self) -> QgsVectorLayer:
        """Build a virtual layer whose single source is an embedded postgres URI."""
        definition = QgsVirtualLayerDefinition()
        definition.addSource("c", 'dbname=\'db\' table="public"."t" (geom)', "postgres")
        definition.setQuery('SELECT * FROM "c"')
        return QgsVectorLayer(definition.toString(), "v_remote", "virtual")

    def test_warns_and_names_the_remote_source(self, qgis_new_project: QgsProject) -> None:
        """A non-local provider is named in the warning, with the pushdown remedy."""
        feedback = _RecordingFeedback()
        virtual._warn_remote_sources(self._remote_virtual(), qgis_new_project, feedback)
        assert len(feedback.warnings) == 1
        assert "v_remote" in feedback.warnings[0]
        assert "postgres" in feedback.warnings[0]

    def test_local_sources_are_silent(self, qgis_new_project: QgsProject) -> None:
        """A memory-backed source resolved through the project raises no warning."""
        _cities, vlayer = _setup(qgis_new_project)
        feedback = _RecordingFeedback()
        virtual._warn_remote_sources(vlayer, qgis_new_project, feedback)
        assert not feedback.warnings

    def test_routing_still_materializes(self, qgis_new_project: QgsProject) -> None:
        """The warning is detection only: the layer lands in vectors exactly as before."""
        vlayer = self._remote_virtual()
        feedback = _RecordingFeedback()
        vectors: list[QgsVectorLayer] = []
        embedded: list[QgsMapLayer] = []
        virtual.route_virtual_layers([vlayer], vectors, [], embedded, qgis_new_project, feedback)
        assert vectors == [vlayer]
        assert not embedded
        assert feedback.warnings
