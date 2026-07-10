"""
Tests for :mod:`stratified_packager.processing.project_builder`.

Builds a source project (grouped vector layers + relation + raster payload + styles),
a stratum gpkg inside a zip-mirror tree, then writes embedded projects in both modes
and re-opens them to verify tree structure, styles, relations, subset strings and
relative datasources (SPEC §13/§21).
"""
# pylint: disable=redefined-outer-name

from __future__ import annotations

import re
import sqlite3
import zipfile
from dataclasses import dataclass
from typing import TYPE_CHECKING, override

import pytest

pytest.importorskip("qgis", reason="The builder constructs full QgsProjects.")

# Imported only after the importorskip guard above confirms QGIS is available.
from qgis.core import (
    QgsCoordinateTransformContext,
    QgsFeature,
    QgsGeometry,
    QgsLayerTreeGroup,
    QgsMarkerSymbol,
    QgsPointXY,
    QgsProcessingException,
    QgsProcessingFeedback,
    QgsProject,
    QgsRasterLayer,
    QgsSingleSymbolRenderer,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsVirtualLayerDefinition,
)
from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtXml import QDomDocument

from stratified_packager.processing.params import ProjectInclusion
from stratified_packager.processing.project_builder import (
    StratumProjectPlan,
    build_stratum_project,
)
from tests.stratified_packager._qgis_helpers import add_relation
from tests.stratified_packager.processing.test_bundling import _write_tif

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.qgis
"""Marks the whole module as requiring a QGIS runtime."""


@dataclass
class Built:
    """The source project and the zip-mirror build tree."""

    project: QgsProject
    cities: QgsVectorLayer
    states: QgsVectorLayer
    raster: QgsRasterLayer
    gpkg: Path
    data_tif: Path


def _points(name: str, fields: str, rows: list[tuple[object, ...]]) -> QgsVectorLayer:
    """Build a point memory layer with one point per row."""
    layer = QgsVectorLayer(f"Point?crs=EPSG:4326&{fields}", name, "memory")
    provider = layer.dataProvider()
    assert provider is not None
    for index, row in enumerate(rows):
        feature = QgsFeature(layer.fields())
        for column, value in enumerate(row):
            feature.setAttribute(column, value)
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(index, 0)))
        assert provider.addFeatures([feature])
    return layer


@pytest.fixture
def built(qgis_new_project: QgsProject, tmp_path: Path) -> Built:
    """Assemble the source project and the zip-mirror stratum tree."""
    cities = _points("cities", "field=cid:integer&field=state_code:string", [(1, "A")])
    states = _points("states", "field=code:string", [("A",)])
    cities.setRenderer(
        QgsSingleSymbolRenderer(
            QgsMarkerSymbol.createSimple({"name": "circle", "color": "255,0,0,255"})
        )
    )

    tif = _write_tif(tmp_path / "src_dem.tif")
    raster = QgsRasterLayer(str(tif), "dem", "gdal")
    assert raster.isValid()

    project = qgis_new_project
    assert project.addMapLayers([cities, states, raster], addToLegend=False)
    root = project.layerTreeRoot()
    assert root is not None
    group = root.addGroup("G")
    assert group is not None
    group.addLayer(cities)
    root.addLayer(states)
    root.addLayer(raster)
    add_relation("r_cs", cities, states, [("state_code", "code")])

    # Zip-mirror tree: gpkg at the root, data/ beside it.
    build_root = tmp_path / "build"
    build_root.mkdir()
    gpkg = build_root / "A.gpkg"
    for layer, table in ((cities, "cities"), (states, "states")):
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = table
        options.actionOnExistingFile = (
            QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer
            if gpkg.exists()
            else QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile
        )
        error, *_rest = QgsVectorFileWriter.writeAsVectorFormatV3(
            layer, str(gpkg), QgsCoordinateTransformContext(), options
        )
        assert error == QgsVectorFileWriter.WriterError.NoError
    data_tif = build_root / "data/dem/dem.tif"
    data_tif.parent.mkdir(parents=True)
    data_tif.write_bytes(tif.read_bytes())
    return Built(
        project=project,
        cities=cities,
        states=states,
        raster=raster,
        gpkg=gpkg,
        data_tif=data_tif,
    )


def _plan(built: Built, mode: ProjectInclusion) -> StratumProjectPlan:
    """Build the stratum project plan over the fixture tree."""
    qml = QDomDocument()
    built.cities.exportNamedStyle(qml)
    return StratumProjectPlan(
        title="A",
        mode=mode,
        gpkg_path=built.gpkg,
        qgz_path=built.gpkg.with_suffix(".qgz"),
        vector_tables={built.cities.id(): "cities", built.states.id(): "states"},
        data_sources={built.raster.id(): built.data_tif},
        styles_qml={built.cities.id(): qml.toString()},
        subsets={built.cities.id(): '"cid" > 0'},
    )


class TestQgzMode:
    """qgz beside the gpkg (SPEC §13)."""

    def test_round_trip(self, built: Built) -> None:
        """The qgz reopens with tree, relation, style, subset and relative sources."""
        build_stratum_project(
            built.project, _plan(built, ProjectInclusion.QGZ), QgsProcessingFeedback()
        )
        qgz = built.gpkg.with_suffix(".qgz")
        assert qgz.is_file()

        reopened = QgsProject()
        assert reopened.read(str(qgz))
        assert reopened.title() == "A"
        names = sorted(layer.name() for layer in reopened.mapLayers().values())
        assert names == ["cities", "dem", "states"]

        root = reopened.layerTreeRoot()
        assert root is not None
        group = root.findGroup("G")
        assert isinstance(group, QgsLayerTreeGroup)
        assert [child.name() for child in group.children()] == ["cities"]

        manager = reopened.relationManager()
        assert manager is not None
        relations = manager.relations()
        assert set(relations) == {"r_cs"}
        assert relations["r_cs"].isValid()

        new_cities = next(
            layer for layer in reopened.mapLayers().values() if layer.name() == "cities"
        )
        assert isinstance(new_cities, QgsVectorLayer)
        assert new_cities.subsetString() == '"cid" > 0'
        renderer = new_cities.renderer()
        assert isinstance(renderer, QgsSingleSymbolRenderer)
        symbol = renderer.symbol()
        assert symbol is not None
        assert symbol.color() == QColor(255, 0, 0)

        with zipfile.ZipFile(qgz) as archive:
            qgs = next(n for n in archive.namelist() if n.endswith(".qgs"))
            xml = archive.read(qgs).decode("utf-8", "replace")
        sources = re.findall(r"<datasource>([^<]+)</datasource>", xml)
        assert any(s.startswith("./A.gpkg|layername=") for s in sources)
        assert any(s == "./data/dem/dem.tif" for s in sources)

    def test_display_names_override_layer_labels(self, built: Built) -> None:
        """`display_names` renames rebuilt layers; unlisted layers keep their original name."""
        feedback = QgsProcessingFeedback()
        plan = _plan(built, ProjectInclusion.QGZ)
        plan.display_names = {built.cities.id(): "Cidades", built.raster.id(): "Modelo"}
        build_stratum_project(built.project, plan, feedback)
        reopened = QgsProject()
        assert reopened.read(str(built.gpkg.with_suffix(".qgz")))
        names = sorted(layer.name() for layer in reopened.mapLayers().values())
        assert names == ["Cidades", "Modelo", "states"]

    def test_broken_table_is_dropped(self, built: Built) -> None:
        """A table missing from the gpkg drops its layer (bad-layer policy)."""
        feedback = QgsProcessingFeedback()
        plan = _plan(built, ProjectInclusion.QGZ)
        plan.vector_tables[built.states.id()] = "no_such_table"
        build_stratum_project(built.project, plan, feedback)
        reopened = QgsProject()
        assert reopened.read(str(built.gpkg.with_suffix(".qgz")))
        names = sorted(layer.name() for layer in reopened.mapLayers().values())
        assert names == ["cities", "dem"]
        manager = reopened.relationManager()
        assert manager is not None
        assert manager.relations() == {}

    def test_write_failure_keeps_gpkg_and_reports_reason(
        self, built: Built, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        A failed write raises with a captured reason, clears a partial .qgz, keeps the gpkg.

        :param built: The source project and build tree.
        :param monkeypatch: Forces the fresh project's ``write`` to fail.
        """

        class _NoWriteProject(QgsProject):
            """A project whose ``write`` always fails (the degraded-delivery path)."""

            @override
            def write(self, *_args: object, **_kwargs: object) -> bool:
                """Report failure unconditionally."""
                return False

        monkeypatch.setattr(
            "stratified_packager.processing.project_builder.QgsProject", _NoWriteProject
        )
        qgz = built.gpkg.with_suffix(".qgz")
        qgz.write_bytes(b"partial")  # a leftover the failed write must clear
        with pytest.raises(QgsProcessingException, match="failed") as excinfo:
            build_stratum_project(
                built.project, _plan(built, ProjectInclusion.QGZ), QgsProcessingFeedback()
            )
        assert "parent_exists" in str(excinfo.value)  # filesystem-fallback detail captured
        assert not qgz.exists()  # partial cleaned
        assert built.gpkg.is_file()  # data gpkg untouched


class TestLiveVirtualLayer:
    """Live virtual layers re-pointed at the stratum gpkg (SPEC §13)."""

    @staticmethod
    def _add_virtual(built: Built, ref: str) -> QgsVectorLayer:
        """Add a by-id virtual layer over *ref* to the source project's tree."""
        definition = QgsVirtualLayerDefinition()
        definition.addSource("c", ref)
        definition.setQuery('SELECT * FROM "c"')
        vlayer = QgsVectorLayer(definition.toString(), "v_cities", "virtual")
        assert built.project.addMapLayer(vlayer, addToLegend=False)
        root = built.project.layerTreeRoot()
        assert root is not None
        root.addLayer(vlayer)
        return vlayer

    def test_repointed_to_stratum_gpkg(self, built: Built) -> None:
        """A live virtual layer reopens valid, its source re-pointed at the stratum gpkg."""
        vlayer = self._add_virtual(built, built.cities.id())
        plan = _plan(built, ProjectInclusion.QGZ)
        plan.embedded_only = (vlayer.id(),)
        build_stratum_project(built.project, plan, QgsProcessingFeedback())

        reopened = QgsProject()
        assert reopened.read(str(built.gpkg.with_suffix(".qgz")))
        new_v = next(
            (layer for layer in reopened.mapLayers().values() if layer.name() == "v_cities"),
            None,
        )
        assert new_v is not None
        assert new_v.isValid()
        rebuilt = QgsVirtualLayerDefinition.fromUrl(QUrl(new_v.source()))
        sources = rebuilt.sourceLayers()
        assert len(sources) == 1
        assert "cities" in sources[0].source()

    def test_dropped_when_source_missing(self, built: Built) -> None:
        """A virtual layer whose source is not packaged this stratum is dropped (§13)."""
        vlayer = self._add_virtual(built, "no_such_layer_id")
        plan = _plan(built, ProjectInclusion.QGZ)
        plan.embedded_only = (vlayer.id(),)
        build_stratum_project(built.project, plan, QgsProcessingFeedback())

        reopened = QgsProject()
        assert reopened.read(str(built.gpkg.with_suffix(".qgz")))
        assert "v_cities" not in [layer.name() for layer in reopened.mapLayers().values()]


class TestGpkgMode:
    """Project storage inside the GeoPackage (SPEC §13)."""

    def test_round_trip(self, built: Built) -> None:
        """The project lands in qgis_projects and reopens from the gpkg URL."""
        feedback = QgsProcessingFeedback()
        build_stratum_project(built.project, _plan(built, ProjectInclusion.GPKG), feedback)
        with sqlite3.connect(built.gpkg) as connection:
            rows = connection.execute("SELECT name FROM qgis_projects").fetchall()
        assert rows == [("A",)]
        reopened = QgsProject()
        assert reopened.read(f"geopackage:{built.gpkg}?projectName=A")
        assert sorted(layer.name() for layer in reopened.mapLayers().values()) == [
            "cities",
            "dem",
            "states",
        ]
