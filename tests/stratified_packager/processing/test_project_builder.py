"""
Tests for :mod:`stratified_packager.processing.project_builder`.

Builds a source project (grouped vector layers + relation + raster payload + styles),
a stratum gpkg inside a zip-mirror tree, then writes embedded projects in both modes
and re-opens them to verify tree structure, CRS, initial map view, styles, relations, subset
strings and relative datasources (SPEC §13/§21).
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
    QgsCoordinateReferenceSystem,
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
    QgsRectangle,
    QgsReferencedRectangle,
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
    _rebuild_virtual_layer,
    build_stratum_project,
    index_virtual_join_columns,
    read_saved_view_extent,
    resolve_initial_view,
    snapshot_embedded_layers,
)
from tests.stratified_packager._qgis_helpers import add_relation
from tests.stratified_packager.processing.test_bundling import _write_tif

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.qgis
"""Marks the whole module as requiring a QGIS runtime."""


class _InfoRecordingFeedback(QgsProcessingFeedback):
    """Feedback that keeps every pushed info line, for asserting on the timing report."""

    def __init__(self) -> None:
        super().__init__()
        self.infos: list[str] = []
        """Every line passed to :meth:`pushInfo`."""

    @override
    def pushInfo(self, info: str | None = None) -> None:  # PyQGIS override
        self.infos.append(info or "")


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
    # A projected project CRS distinct from the 4326 layers, to prove the *project* CRS (not a
    # layer's) survives into the embedded project (SPEC §13).
    project.setCrs(QgsCoordinateReferenceSystem("EPSG:3857"))  # ty: ignore  # stub lacks ctor
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
        assert reopened.crs() == built.project.crs()  # project CRS carried (§13)
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

    def test_initial_view_round_trips(self, built: Built) -> None:
        """`initial_view` becomes the embedded project's default view extent (§13)."""
        plan = _plan(built, ProjectInclusion.QGZ)
        extent = QgsRectangle(10.0, 20.0, 30.0, 40.0)
        plan.initial_view = QgsReferencedRectangle(extent, built.project.crs())
        build_stratum_project(built.project, plan, QgsProcessingFeedback())

        reopened = QgsProject()
        assert reopened.read(str(built.gpkg.with_suffix(".qgz")))
        settings = reopened.viewSettings()
        assert settings is not None
        restored = settings.defaultViewExtent()
        assert not restored.isNull()
        assert restored.crs() == built.project.crs()
        assert restored.xMinimum() == pytest.approx(10.0)
        assert restored.yMinimum() == pytest.approx(20.0)
        assert restored.xMaximum() == pytest.approx(30.0)
        assert restored.yMaximum() == pytest.approx(40.0)

    def test_layer_tree_node_state_is_mirrored(self, built: Built) -> None:
        """Collapsed state, legend tweaks and mutually-exclusive groups carry over (§13)."""
        root = built.project.layerTreeRoot()
        assert root is not None
        group = root.findGroup("G")
        assert group is not None
        group.setExpanded(False)
        group.setIsMutuallyExclusive(True)
        # Would send QGIS looking for the packaging machine's project file on open.
        group.setCustomProperty("embedded", 1)
        group.setCustomProperty("embedded_project", "/elsewhere/other.qgs")
        cities_node = group.findLayer(built.cities)
        assert cities_node is not None
        cities_node.setExpanded(False)
        cities_node.setCustomProperty("showFeatureCount", 1)  # QGIS stores this flag as an int
        cities_node.setCustomProperty("legend/node-order", ["1", "0"])
        states_node = root.findLayer(built.states)
        assert states_node is not None
        states_node.setExpanded(True)

        build_stratum_project(
            built.project, _plan(built, ProjectInclusion.QGZ), QgsProcessingFeedback()
        )
        reopened = QgsProject()
        assert reopened.read(str(built.gpkg.with_suffix(".qgz")))
        new_root = reopened.layerTreeRoot()
        assert new_root is not None
        new_group = new_root.findGroup("G")
        assert new_group is not None
        assert not new_group.isExpanded()
        assert new_group.isMutuallyExclusive()
        assert "embedded" not in new_group.customProperties()
        assert "embedded_project" not in new_group.customProperties()

        # By name, not position: the reopened project's layer ids differ from the source's,
        # so `findLayer` is out and node order is not what this test is pinning.
        new_cities = next(child for child in new_group.children() if child.name() == "cities")
        assert not new_cities.isExpanded()
        assert new_cities.customProperty("showFeatureCount") == 1
        assert new_cities.customProperty("legend/node-order") == ["1", "0"]
        # Copied per node, not collapsed wholesale.
        new_states = next(child for child in new_root.children() if child.name() == "states")
        assert new_states.isExpanded()

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
    def _add_virtual(built: Built, ref: str, subset: str = "") -> QgsVectorLayer:
        """Add a by-id virtual layer over *ref* to the source project's tree."""
        definition = QgsVirtualLayerDefinition()
        definition.addSource("c", ref)
        definition.setQuery('SELECT * FROM "c"')
        # The suppression: the definition's setter returns None — QGS201 matches it by the name
        # of QgsVectorLayer's flag-returning method.
        definition.setSubsetString(subset)  # noqa: QGS201
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

    def test_rebuilt_layer_carries_no_computed_extent(self, built: Built) -> None:
        """Deriving a virtual layer's extent runs its query, once per stratum — skip it (§13)."""
        vlayer = self._add_virtual(built, built.cities.id())
        plan = _plan(built, ProjectInclusion.QGZ)
        plan.embedded_only = (vlayer.id(),)
        rebuilt = _rebuild_virtual_layer(vlayer, built.project, plan, QgsProcessingFeedback())

        assert rebuilt is not None
        assert rebuilt.extent().isNull()
        # The untouched source layer does resolve one, so the skip above is the deliberate act
        # and not an artefact of a query with nothing in it.
        assert not vlayer.extent().isNull()

    def test_delivers_its_features_without_a_stored_extent(self, built: Built) -> None:
        """Skipping the build-time extent must not cost the recipient the data (§13)."""
        vlayer = self._add_virtual(built, built.cities.id())
        plan = _plan(built, ProjectInclusion.QGZ)
        plan.embedded_only = (vlayer.id(),)
        build_stratum_project(built.project, plan, QgsProcessingFeedback())

        reopened = QgsProject()
        assert reopened.read(str(built.gpkg.with_suffix(".qgz")))
        new_v = next(
            layer for layer in reopened.mapLayers().values() if layer.name() == "v_cities"
        )
        assert new_v.isValid()
        assert "cid" in [field_def.name() for field_def in new_v.fields()]
        assert new_v.featureCount() == 1

    def test_subset_string_reaches_the_package(self, built: Built) -> None:
        """The author's filter is part of the definition and must not be dropped (§13)."""
        vlayer = self._add_virtual(built, built.cities.id(), subset='"cid" > 100')
        plan = _plan(built, ProjectInclusion.QGZ)
        plan.embedded_only = (vlayer.id(),)
        build_stratum_project(built.project, plan, QgsProcessingFeedback())

        reopened = QgsProject()
        assert reopened.read(str(built.gpkg.with_suffix(".qgz")))
        new_v = next(
            layer for layer in reopened.mapLayers().values() if layer.name() == "v_cities"
        )
        assert new_v.isValid()
        rebuilt = QgsVirtualLayerDefinition.fromUrl(QUrl(new_v.source()))
        assert rebuilt.subsetString() == '"cid" > 100'
        # The one fixture row is cid=1; dropping the filter would ship it.
        assert new_v.featureCount() == 0

    def test_build_reports_its_slowest_steps(self, built: Built) -> None:
        """One timing line per stratum, naming steps — the phase is not a black box (§8)."""
        vlayer = self._add_virtual(built, built.cities.id())
        plan = _plan(built, ProjectInclusion.QGZ)
        plan.embedded_only = (vlayer.id(),)
        recorder = _InfoRecordingFeedback()
        build_stratum_project(built.project, plan, recorder)

        timings = [line for line in recorder.infos if "in embedded-project steps" in line]
        assert len(timings) == 1, recorder.infos
        # Every opened layer and the project write are candidates for the slowest few.
        assert re.search(
            r"Stratum A: \d+\.\ds in embedded-project steps; slowest \S+ \d+\.\ds", timings[0]
        )
        assert any(
            name in timings[0] for name in ("cities", "states", "v_cities", "<project write>")
        )


class TestIndexVirtualJoinColumns:
    """A live virtual layer's queried columns are indexed in the stratum gpkg (SPEC §13)."""

    JOIN_QUERY = 'SELECT a.cid FROM "c" a LEFT JOIN "s" b ON a.state_code = b.code'

    @staticmethod
    def _add_join_virtual(built: Built, cities_ref: str, states_ref: str, query: str) -> str:
        """Add a two-source virtual layer to the source project and return its id."""
        definition = QgsVirtualLayerDefinition()
        definition.addSource("c", cities_ref)
        definition.addSource("s", states_ref)
        definition.setQuery(query)
        vlayer = QgsVectorLayer(definition.toString(), "v_join", "virtual")
        assert built.project.addMapLayer(vlayer, addToLegend=False)
        return vlayer.id()

    @staticmethod
    def _indexes(gpkg: Path, table: str) -> set[str]:
        """Name every index standing on *table*."""
        with sqlite3.connect(f"file:{gpkg.as_posix()}?mode=ro", uri=True) as conn:
            return {
                name
                for (name,) in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = ?",
                    (table,),
                )
            }

    def test_join_columns_indexed(self, built: Built) -> None:
        """Each side of the join predicate is indexed on the table that actually holds it."""
        layer_id = self._add_join_virtual(
            built, built.cities.id(), built.states.id(), self.JOIN_QUERY
        )
        plan = _plan(built, ProjectInclusion.QGZ)
        plan.embedded_only = (layer_id,)
        index_virtual_join_columns(built.project, plan, QgsProcessingFeedback())

        # Only the column each table owns: `code` is not a cities column, `state_code` not a
        # states one, so the intersection with the real columns keeps them apart.
        assert self._indexes(built.gpkg, "cities") == {"idx_cities_state_code"}
        assert self._indexes(built.gpkg, "states") == {"idx_states_code"}

    def test_source_without_a_stratum_table_is_skipped(self, built: Built) -> None:
        """An unpackaged source indexes nothing and does not disturb the packaged one (§13)."""
        layer_id = self._add_join_virtual(
            built, built.cities.id(), "no_such_layer_id", self.JOIN_QUERY
        )
        plan = _plan(built, ProjectInclusion.QGZ)
        plan.embedded_only = (layer_id,)
        index_virtual_join_columns(built.project, plan, QgsProcessingFeedback())

        assert self._indexes(built.gpkg, "cities") == {"idx_cities_state_code"}
        assert self._indexes(built.gpkg, "states") == set()

    def test_nothing_to_index_leaves_the_gpkg_alone(self, built: Built) -> None:
        """A query with no equality, and a non-virtual embedded layer, both index nothing."""
        layer_id = self._add_join_virtual(
            built, built.cities.id(), built.states.id(), 'SELECT * FROM "c"'
        )
        plan = _plan(built, ProjectInclusion.QGZ)
        plan.embedded_only = (layer_id, built.raster.id())
        index_virtual_join_columns(built.project, plan, QgsProcessingFeedback())

        assert self._indexes(built.gpkg, "cities") == set()
        assert self._indexes(built.gpkg, "states") == set()

    def test_repeated_runs_are_idempotent(self, built: Built) -> None:
        """A warm gpkg arriving with the index already on it is re-indexed without error."""
        layer_id = self._add_join_virtual(
            built, built.cities.id(), built.states.id(), self.JOIN_QUERY
        )
        plan = _plan(built, ProjectInclusion.QGZ)
        plan.embedded_only = (layer_id,)
        index_virtual_join_columns(built.project, plan, QgsProcessingFeedback())
        index_virtual_join_columns(built.project, plan, QgsProcessingFeedback())

        assert self._indexes(built.gpkg, "cities") == {"idx_cities_state_code"}


class TestEmbeddedOnlyLayers:
    """Embedded-only layers reproduced from the run's XML snapshot (SPEC §13)."""

    @staticmethod
    def _add_basemap(built: Built, tmp_path: Path) -> QgsRasterLayer:
        """Add a second raster to the source project, standing in for a remote basemap."""
        basemap = QgsRasterLayer(str(_write_tif(tmp_path / "basemap.tif")), "basemap", "gdal")
        assert basemap.isValid()
        assert built.project.addMapLayer(basemap, addToLegend=False)
        root = built.project.layerTreeRoot()
        assert root is not None
        root.addLayer(basemap)
        return basemap

    @staticmethod
    def _spy_on_clone(monkeypatch: pytest.MonkeyPatch) -> list[str]:
        """Record the id of every raster layer put through ``clone``."""
        cloned: list[str] = []
        inherited = QgsRasterLayer.clone

        def spy(self: QgsRasterLayer) -> QgsRasterLayer | None:
            cloned.append(self.id())
            return inherited(self)

        monkeypatch.setattr(QgsRasterLayer, "clone", spy)
        return cloned

    def test_snapshot_covers_revivable_layers_only(self, built: Built, tmp_path: Path) -> None:
        """A live virtual layer stays out of the snapshot; a raster goes in."""
        basemap = self._add_basemap(built, tmp_path)
        definition = QgsVirtualLayerDefinition()
        definition.addSource("c", built.cities.id())
        definition.setQuery('SELECT * FROM "c"')
        vlayer = QgsVectorLayer(definition.toString(), "v_cities", "virtual")

        assert list(snapshot_embedded_layers([basemap, vlayer])) == [basemap.id()]

    def test_revived_without_reopening_the_source(
        self, built: Built, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        A snapshotted layer ships intact and never goes through ``clone``.

        ``clone`` re-constructs the provider from the URI, which for a remote source is a
        blocking network request charged once per stratum — the regression this guards.
        """
        basemap = self._add_basemap(built, tmp_path)
        cloned = self._spy_on_clone(monkeypatch)
        plan = _plan(built, ProjectInclusion.QGZ)
        plan.embedded_only = (basemap.id(),)
        plan.embedded_xml = snapshot_embedded_layers([basemap])
        build_stratum_project(built.project, plan, QgsProcessingFeedback())

        assert basemap.id() not in cloned
        reopened = QgsProject()
        assert reopened.read(str(built.gpkg.with_suffix(".qgz")))
        shipped = next(
            layer for layer in reopened.mapLayers().values() if layer.name() == "basemap"
        )
        assert shipped.providerType() == "gdal"
        assert "basemap.tif" in shipped.source()

    def test_display_name_override_reaches_the_shipped_project(
        self, built: Built, tmp_path: Path
    ) -> None:
        """A §4 ``layer_name`` override is patched into the XML, not lost to the stored bytes."""
        basemap = self._add_basemap(built, tmp_path)
        plan = _plan(built, ProjectInclusion.QGZ)
        plan.embedded_only = (basemap.id(),)
        plan.embedded_xml = snapshot_embedded_layers([basemap])
        plan.display_names = {basemap.id(): "basemap A"}
        build_stratum_project(built.project, plan, QgsProcessingFeedback())

        reopened = QgsProject()
        assert reopened.read(str(built.gpkg.with_suffix(".qgz")))
        assert "basemap A" in [layer.name() for layer in reopened.mapLayers().values()]

    def test_falls_back_to_clone_without_a_snapshot(
        self, built: Built, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unsnapshotted layer type still ships, through the original clone path."""
        basemap = self._add_basemap(built, tmp_path)
        cloned = self._spy_on_clone(monkeypatch)
        plan = _plan(built, ProjectInclusion.QGZ)
        plan.embedded_only = (basemap.id(),)
        plan.display_names = {basemap.id(): "basemap A"}
        build_stratum_project(built.project, plan, QgsProcessingFeedback())

        assert basemap.id() in cloned
        reopened = QgsProject()
        assert reopened.read(str(built.gpkg.with_suffix(".qgz")))
        assert "basemap A" in [layer.name() for layer in reopened.mapLayers().values()]


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
        assert reopened.crs() == built.project.crs()  # project CRS carried (§13)
        assert sorted(layer.name() for layer in reopened.mapLayers().values()) == [
            "cities",
            "dem",
            "states",
        ]


_MAPCANVAS_QGS = (
    "<qgis>"
    '<mapcanvas name="theMapCanvas">'
    "<extent><xmin>10</xmin><ymin>20</ymin><xmax>30</xmax><ymax>40</ymax></extent>"
    "</mapcanvas>"
    "</qgis>"
)
"""A minimal project XML carrying a saved primary map-canvas extent."""

_TWO_CANVAS_QGS = (
    "<qgis>"
    '<mapcanvas name="other">'
    "<extent><xmin>1</xmin><ymin>1</ymin><xmax>2</xmax><ymax>2</ymax></extent>"
    "</mapcanvas>"
    '<mapcanvas name="theMapCanvas">'
    "<extent><xmin>10</xmin><ymin>20</ymin><xmax>30</xmax><ymax>40</ymax></extent>"
    "</mapcanvas>"
    "</qgis>"
)
"""Two canvases, the primary listed second, to check the theMapCanvas preference."""

_DEGENERATE_QGS = (
    "<qgis>"
    '<mapcanvas name="theMapCanvas">'
    "<extent><xmin>5</xmin><ymin>5</ymin><xmax>5</xmax><ymax>9</ymax></extent>"
    "</mapcanvas>"
    "</qgis>"
)
"""A zero-width canvas extent (xmax == xmin), which must be rejected."""


class TestReadSavedViewExtent:
    """Parsing the saved map-canvas extent from a project file (SPEC §13)."""

    def test_reads_qgs(self, tmp_path: Path) -> None:
        """A .qgs with theMapCanvas yields its extent."""
        path = tmp_path / "p.qgs"
        path.write_text(_MAPCANVAS_QGS, encoding="utf-8")
        assert read_saved_view_extent(path) == (10.0, 20.0, 30.0, 40.0)

    def test_reads_qgz(self, tmp_path: Path) -> None:
        """A .qgz is unzipped and its inner .qgs parsed."""
        path = tmp_path / "p.qgz"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("p.qgs", _MAPCANVAS_QGS)
        assert read_saved_view_extent(path) == (10.0, 20.0, 30.0, 40.0)

    def test_prefers_the_map_canvas(self, tmp_path: Path) -> None:
        """The primary theMapCanvas wins over a secondary canvas listed first."""
        path = tmp_path / "p.qgs"
        path.write_text(_TWO_CANVAS_QGS, encoding="utf-8")
        assert read_saved_view_extent(path) == (10.0, 20.0, 30.0, 40.0)

    @pytest.mark.parametrize(
        "content",
        ["<qgis></qgis>", _DEGENERATE_QGS],
        ids=["no-canvas", "degenerate-extent"],
    )
    def test_returns_none_for_unusable_extent(self, tmp_path: Path, content: str) -> None:
        """No usable extent -> None (the full-extent fallback)."""
        path = tmp_path / "p.qgs"
        path.write_text(content, encoding="utf-8")
        assert read_saved_view_extent(path) is None

    def test_non_project_suffix_ignored(self, tmp_path: Path) -> None:
        """A file that is not a .qgs/.qgz project is ignored."""
        path = tmp_path / "p.txt"
        path.write_text(_MAPCANVAS_QGS, encoding="utf-8")
        assert read_saved_view_extent(path) is None

    def test_missing_file(self, tmp_path: Path) -> None:
        """A path that does not exist -> None."""
        assert read_saved_view_extent(tmp_path / "nope.qgs") is None


class TestResolveInitialView:
    """Resolving where the source project opens (SPEC §13)."""

    def test_reads_saved_canvas_from_file(self, tmp_path: Path) -> None:
        """A project whose file carries a saved canvas resolves to it, in the project CRS."""
        path = tmp_path / "src.qgs"
        path.write_text(_MAPCANVAS_QGS, encoding="utf-8")
        project = QgsProject()
        project.setFileName(str(path))
        project.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))  # ty: ignore  # stub lacks ctor
        resolved = resolve_initial_view(project)
        assert resolved is not None
        assert resolved.crs() == project.crs()
        bounds = (
            resolved.xMinimum(),
            resolved.yMinimum(),
            resolved.xMaximum(),
            resolved.yMaximum(),
        )
        assert bounds == (10.0, 20.0, 30.0, 40.0)

    def test_saved_canvas_wins_over_default_view_extent(
        self, qgis_new_project: QgsProject, tmp_path: Path
    ) -> None:
        """
        With both configured, the saved canvas wins — the SPEC §13 order.

        The sibling tests each exercise one branch with the other absent, so swapping the two
        checks in :func:`resolve_initial_view` leaves both of them passing.
        """
        path = tmp_path / "src.qgs"
        path.write_text(_MAPCANVAS_QGS, encoding="utf-8")
        project = qgis_new_project
        project.setFileName(str(path))
        project.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))  # ty: ignore  # stub lacks ctor
        settings = project.viewSettings()
        assert settings is not None
        settings.setDefaultViewExtent(
            QgsReferencedRectangle(QgsRectangle(1.0, 2.0, 3.0, 4.0), project.crs())
        )
        resolved = resolve_initial_view(project)
        assert resolved is not None
        bounds = (
            resolved.xMinimum(),
            resolved.yMinimum(),
            resolved.xMaximum(),
            resolved.yMaximum(),
        )
        assert bounds == (10.0, 20.0, 30.0, 40.0)  # the saved canvas, not the default view

    def test_falls_back_to_default_view_extent(self, qgis_new_project: QgsProject) -> None:
        """Without a saved canvas, the configured default view extent is used."""
        project = qgis_new_project
        project.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))  # ty: ignore  # stub lacks ctor
        settings = project.viewSettings()
        assert settings is not None
        settings.setDefaultViewExtent(
            QgsReferencedRectangle(QgsRectangle(1.0, 2.0, 3.0, 4.0), project.crs())
        )
        resolved = resolve_initial_view(project)
        assert resolved is not None
        assert (resolved.xMinimum(), resolved.yMaximum()) == (1.0, 4.0)

    def test_returns_none_without_any_view(self, qgis_new_project: QgsProject) -> None:
        """A project with no file and no default view extent resolves to None."""
        assert resolve_initial_view(qgis_new_project) is None
