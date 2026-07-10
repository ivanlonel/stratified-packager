"""
Tests for :mod:`stratified_packager.processing.algorithm`.

Builds a mixed in-test project — attribute matching over a relation, spatial matching,
a whole-export layer, staged (memory) and direct (gpkg) sources — and runs the real
algorithm end to end: zips, gpkg contents, per-zip and run reports, outputs map,
overwrite modes, dry run, bundling, extra-dir handling, and best-effort failure.
"""
# pylint: disable=redefined-outer-name

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast, override

import pytest

pytest.importorskip("qgis", reason="The algorithm drives the full Processing stack.")

# Imported only after the importorskip guard above confirms QGIS is available.
from qgis.core import (
    QgsCoordinateTransformContext,
    QgsExpressionContextUtils,
    QgsFeature,
    QgsGeometry,
    QgsMarkerSymbol,
    QgsPalLayerSettings,
    QgsPointXY,
    QgsProcessing,
    QgsProcessingContext,
    QgsProcessingException,
    QgsProcessingFeedback,
    QgsProject,
    QgsRasterLayer,
    QgsRectangle,
    QgsSingleSymbolRenderer,
    QgsSvgMarkerSymbolLayer,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
)
from qgis.PyQt.QtGui import QPalette
from qgis.PyQt.QtWidgets import QApplication

from stratified_packager.processing import algorithm as algorithm_module
from stratified_packager.processing import params as p
from stratified_packager.processing.algorithm import StratifiedPackagerAlgorithm
from stratified_packager.processing.building import StratumWriteResult, write_vector_table
from stratified_packager.processing.building import stage_union as real_stage_union_import
from stratified_packager.processing.building import write_stratum as real_write_stratum
from stratified_packager.processing.params import ProjectInclusion
from stratified_packager.processing.workers import run_prefetch as real_run_prefetch
from stratified_packager.toolbelt.gpkg import feature_count, layer_names
from tests.stratified_packager._qgis_helpers import add_relation, build_alpha_gpkg
from tests.stratified_packager.processing.test_bundling import _write_tif

pytestmark = pytest.mark.qgis
"""Marks the whole module as requiring a QGIS runtime."""


@dataclass
class Scenario:
    """The in-test project and its layers."""

    project: QgsProject
    states: QgsVectorLayer
    cities: QgsVectorLayer
    plots: QgsVectorLayer
    roads: QgsVectorLayer
    out_dir: Path


def _square(x0: float, y0: float, side: float) -> QgsGeometry:
    """Build an axis-aligned square geometry."""
    return QgsGeometry.fromRect(QgsRectangle(x0, y0, x0 + side, y0 + side))


@pytest.fixture
# pylint: disable-next=too-many-locals  # one block per scenario layer
def scenario(qgis_new_project: QgsProject, tmp_path: Path) -> Scenario:
    """
    Build the reference project.

    states (polygons A at 0..10, B at 20..30; field ``code``) is the stratification
    layer. cities (points; gpkg-backed, direct source) relates to states via
    ``state_code`` → A:2, B:1 features plus one orphan. plots (memory polygons,
    staged for fid equivalence) matches spatially → A:1, B:1 plus one far away.
    roads (memory points, ``whole_export``) rides complete into every package.
    """
    project = qgis_new_project

    states = QgsVectorLayer("Polygon?crs=EPSG:4326&field=code:string", "states", "memory")
    provider = states.dataProvider()
    assert provider is not None
    for code, x0 in (("A", 0.0), ("B", 20.0)):
        feature = QgsFeature(states.fields())
        feature.setAttribute(0, code)
        feature.setGeometry(_square(x0, 0.0, 10.0))
        assert provider.addFeatures([feature])

    cities_memory = QgsVectorLayer(
        "Point?crs=EPSG:4326&field=cid:integer&field=state_code:string", "cities", "memory"
    )
    provider = cities_memory.dataProvider()
    assert provider is not None
    for cid, code, x in ((1, "A", 1.0), (2, "A", 2.0), (3, "B", 21.0), (4, "Z", 50.0)):
        feature = QgsFeature(cities_memory.fields())
        feature.setAttribute(0, cid)
        feature.setAttribute(1, code)
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, 1.0)))
        assert provider.addFeatures([feature])
    cities_gpkg = tmp_path / "cities_src.gpkg"
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "GPKG"
    options.layerName = "cities"
    error, *_rest = QgsVectorFileWriter.writeAsVectorFormatV3(
        cities_memory, str(cities_gpkg), QgsCoordinateTransformContext(), options
    )
    assert error == QgsVectorFileWriter.WriterError.NoError
    cities = QgsVectorLayer(f"{cities_gpkg}|layername=cities", "cities", "ogr")
    assert cities.isValid()

    plots = QgsVectorLayer("Polygon?crs=EPSG:4326&field=tag:integer", "plots", "memory")
    provider = plots.dataProvider()
    assert provider is not None
    for tag, x0 in ((0, 2.0), (1, 22.0), (2, 80.0)):
        feature = QgsFeature(plots.fields())
        feature.setAttribute(0, tag)
        feature.setGeometry(_square(x0, 2.0, 2.0))
        assert provider.addFeatures([feature])

    roads = QgsVectorLayer("Point?crs=EPSG:4326&field=rid:integer", "roads", "memory")
    provider = roads.dataProvider()
    assert provider is not None
    for rid in (10, 11):
        feature = QgsFeature(roads.fields())
        feature.setAttribute(0, rid)
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(rid, 5.0)))
        assert provider.addFeatures([feature])
    QgsExpressionContextUtils.setLayerVariable(
        roads, "stratified_packager_matching_method", "whole_export"
    )

    assert project.addMapLayers([states, cities, plots, roads], addToLegend=False)

    add_relation("r_cities_states", cities, states, [("state_code", "code")])

    out_dir = tmp_path / "out"
    return Scenario(
        project=project,
        states=states,
        cities=cities,
        plots=plots,
        roads=roads,
        out_dir=out_dir,
    )


def _base_params(scenario: Scenario) -> dict[str | None, Any]:
    """All inputs supplied explicitly (GUI-style), isolating tests from settings."""
    return {
        p.LAYERS: [scenario.cities, scenario.plots, scenario.roads],
        p.STRATIFICATION_LAYER: scenario.states,
        p.STRATUM_NAME_EXPRESSION: '"code"',
        p.GPKG_PATH_EXPRESSION: "",
        p.ZIP_PATH_EXPRESSION: "",
        p.OUTPUT_DIRECTORY: str(scenario.out_dir),
        p.COMPRESSION_LEVEL: 1,
        p.OVERWRITE_MODE: "overwrite",
        p.PROJECT_INCLUSION: "none",
        p.USE_TEMP_FOLDER: True,
        p.INCLUDE_STYLES: True,
        p.STYLE_CATEGORIES: list(p.STYLE_CATEGORY_TOKENS),
        p.INCLUDE_METADATA: False,
        p.KEEP_EMPTY_LAYERS: True,
        p.DEDUPLICATE_SHARED_SOURCES: True,
        p.STAGE_PROVIDERS: [],
        p.EXPORT_FULL_PACKAGE: False,
        p.FULL_PACKAGE_PATH: "",
        p.GENERATE_REPORT: True,
        # Pin the run-report sink to a CSV path so its content is assertable on disk;
        # the no-path (memory layer) behavior is the framework's, exercised in the GUI.
        p.REPORT: str(scenario.out_dir / "report.csv"),
        p.EXTRA_DIR: "",
        p.WARM_START_DIR: "",
        p.WARM_START_MODE: "off",
        p.WRITE_CHECKSUMS: False,
        p.DRY_RUN: False,
    }


def test_style_documents_honors_selected_categories() -> None:
    """A category subset narrows the exported QML; an empty selection keeps every category."""
    layer = QgsVectorLayer("Point?crs=EPSG:4326&field=name:string", "styled", "memory")
    label_settings = QgsPalLayerSettings()
    label_settings.fieldName = "name"
    layer.setLabelsEnabled(True)
    layer.setLabeling(QgsVectorLayerSimpleLabeling(label_settings))
    algorithm = StratifiedPackagerAlgorithm()

    def export(tokens: list[str]) -> str:
        inputs = cast(
            "Any",
            SimpleNamespace(
                include_styles=True, style_categories=p.style_categories_flags(tokens)
            ),
        )
        qml, _sld = algorithm._style_documents(layer, inputs, QgsProcessingFeedback())
        return qml

    symbology_only = export(["symbology"])
    every_category = export([])  # empty selection => all categories
    assert "<symbol" in symbology_only  # the selected category is present
    assert "<labeling" not in symbology_only  # the dropped category is gone
    assert "<labeling" in every_category  # empty == all, so labeling survives


def test_short_help_recolours_body_for_dark_theme() -> None:
    """Dark palettes get a <style> override beating QGIS's grey ``b{color:#333}`` help rule."""
    palette = QApplication.palette()
    text = palette.color(QPalette.ColorRole.WindowText)
    window = palette.color(QPalette.ColorRole.Window)
    html = StratifiedPackagerAlgorithm().shortHelpString()
    assert "<b>stratification layer</b>" in html  # emphasis preserved
    if text.lightnessF() > window.lightnessF():  # dark theme
        assert html.startswith(f"<style>h3,p,ul,li,b{{color:{text.name()};}}</style>")
    else:  # light theme: QGIS's own colours are fine, help left untouched
        assert not html.startswith("<style>")


def _run(
    scenario: Scenario,
    overrides: dict[str | None, Any] | None = None,
    feedback: QgsProcessingFeedback | None = None,
) -> dict[str, Any]:
    """Initialize and execute the algorithm against the scenario project."""
    parameters: dict[str | None, Any] = {**_base_params(scenario), **(overrides or {})}
    algorithm = StratifiedPackagerAlgorithm()
    algorithm.initAlgorithm()
    context = QgsProcessingContext()
    context.setProject(scenario.project)
    return algorithm.processAlgorithm(parameters, context, feedback or QgsProcessingFeedback())


def _extract(zip_path: Path, member: str, target_dir: Path) -> Path:
    """Extract one member from a zip and return its path."""
    with zipfile.ZipFile(zip_path) as archive:
        return Path(archive.extract(member, target_dir))


class _RecordingFeedback(QgsProcessingFeedback):
    """A feedback double collecting the pushed info/warning lines for assertions."""

    @override
    def __init__(self) -> None:
        super().__init__()
        self.infos: list[str] = []
        self.warnings: list[str] = []

    @override
    def pushInfo(self, info: str | None = None) -> None:
        """Record *info* and forward it."""
        self.infos.append(info or "")
        super().pushInfo(info or "")

    @override
    def pushWarning(self, warning: str | None = None) -> None:
        """Record *warning* and forward it."""
        self.warnings.append(warning or "")
        super().pushWarning(warning or "")


class TestWorkerCount:
    """One run-scoped background pool at the fixed §8.4 width."""

    def test_pool_is_created_once_at_the_fixed_width(
        self, scenario: Scenario, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        A single pool spans the whole run, sized ``_POOL_WIDTH`` (no ``MAX_WORKERS`` knob).

        Measurement (SPEC §3 note) showed packaging never queues a second zip; the fixed
        second thread exists for the §11 warm prefetch.
        """
        captured: list[int] = []
        real_pool = ThreadPoolExecutor  # the genuine class, before the patch below

        def spy(*args: Any, **kwargs: Any) -> ThreadPoolExecutor:
            captured.append(kwargs["max_workers"])
            return real_pool(*args, **kwargs)

        monkeypatch.setattr(algorithm_module, "ThreadPoolExecutor", spy)
        _run(scenario)
        assert captured == [algorithm_module._POOL_WIDTH]


class TestEndToEnd:
    """The happy path across both matching methods and all source kinds."""

    def test_two_strata_full_pipeline(self, scenario: Scenario, tmp_path: Path) -> None:
        """Both zips publish with correct gpkg contents, reports and outputs."""
        results = _run(scenario)

        zip_a = scenario.out_dir / "A.zip"
        zip_b = scenario.out_dir / "B.zip"
        assert zip_a.is_file()
        assert zip_b.is_file()
        with zipfile.ZipFile(zip_a) as archive:
            assert sorted(archive.namelist()) == ["A.gpkg", "report.csv"]
            zip_report = archive.read("report.csv").decode("utf-8")
        assert "cities" in zip_report
        assert "attribute" in zip_report
        assert "whole_export" in zip_report

        gpkg_a = _extract(zip_a, "A.gpkg", tmp_path / "xa")
        assert layer_names(gpkg_a) == ["cities", "plots", "roads"]
        assert feature_count(gpkg_a, "cities") == 2
        assert feature_count(gpkg_a, "plots") == 1
        assert feature_count(gpkg_a, "roads") == 2
        gpkg_b = _extract(zip_b, "B.gpkg", tmp_path / "xb")
        assert feature_count(gpkg_b, "cities") == 1
        assert feature_count(gpkg_b, "plots") == 1
        assert feature_count(gpkg_b, "roads") == 2

        assert results[p.STRATA_COUNT] == 2
        assert results[p.ZIP_COUNT] == 2
        assert sorted(map(str, json.loads(results[p.ZIP_PATHS]))) == sorted(
            [str(zip_a), str(zip_b)]
        )
        assert json.loads(results[p.FAILED_STRATA]) == []
        assert results[p.REPORT]  # the run-report sink destination (here a CSV path)

        report = (scenario.out_dir / "report.csv").read_text(encoding="utf-8")
        assert "<unmatched>,cities,1" in report
        assert "<unmatched>,plots,1" in report
        assert "A,cities,2,ok" in report

    def test_generate_report_gates_only_the_zip_report(self, scenario: Scenario) -> None:
        """GENERATE_REPORT=False drops the per-zip report.csv; the run report stays."""
        results = _run(scenario, {p.GENERATE_REPORT: False})
        assert results[p.REPORT]
        assert (scenario.out_dir / "report.csv").is_file()  # run report (always written)
        with zipfile.ZipFile(scenario.out_dir / "A.zip") as archive:
            assert archive.namelist() == ["A.gpkg"]  # no per-zip report.csv

    def test_report_defaults_to_memory_when_no_path(self, scenario: Scenario) -> None:
        """REPORT = TEMPORARY_OUTPUT yields an in-memory layer, nothing written to disk."""
        results = _run(scenario, {p.REPORT: QgsProcessing.TEMPORARY_OUTPUT})
        assert results[p.REPORT]  # a memory-layer id, not a file path
        assert not (scenario.out_dir / "report.csv").exists()

    def test_styles_land_in_gpkg(self, scenario: Scenario, tmp_path: Path) -> None:
        """INCLUDE_STYLES writes one default style row per table."""
        _run(scenario)
        gpkg_a = _extract(scenario.out_dir / "A.zip", "A.gpkg", tmp_path / "xs")
        with sqlite3.connect(gpkg_a) as connection:
            rows = connection.execute(
                "SELECT f_table_name, useAsDefault FROM layer_styles ORDER BY f_table_name"
            ).fetchall()
        assert rows == [("cities", 1), ("plots", 1), ("roads", 1)]


class _HidesV3:
    """Layer proxy that hides ``exportSldStyleV3`` so ``_sld_text`` takes the V2 path."""

    def __init__(self, inner: QgsVectorLayer) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        if name == "exportSldStyleV3":
            raise AttributeError(name)
        return getattr(self._inner, name)


class TestSldExport:
    """The §8.1 SLD serialization and its ``exportSldStyleV2`` fallback (SPEC §1.1)."""

    @pytest.mark.parametrize("force_v2", [False, True])
    def test_sld_text_emits_descriptor_on_both_paths(self, force_v2: bool) -> None:
        """The native V3 export and the AttributeError-driven V2 fallback both yield SLD."""
        layer = QgsVectorLayer("Point?crs=EPSG:4326&field=id:integer", "styled", "memory")
        assert layer.isValid()
        layer.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol()))
        probe = cast("QgsVectorLayer", _HidesV3(layer)) if force_v2 else layer

        sld = StratifiedPackagerAlgorithm()._sld_text(probe)

        assert "<StyledLayerDescriptor" in sld


class TestModesAndEdges:
    """Overwrite modes, dry run, bundling, empty handling, extra dir, failures."""

    def test_keep_empty_layers_toggle(self, scenario: Scenario, tmp_path: Path) -> None:
        """An always-empty stratum keeps or drops its empty tables."""
        provider = scenario.states.dataProvider()
        assert provider is not None
        empty_state = QgsFeature(scenario.states.fields())
        empty_state.setAttribute(0, "C")
        empty_state.setGeometry(_square(200.0, 200.0, 5.0))
        assert provider.addFeatures([empty_state])

        _run(scenario, {p.KEEP_EMPTY_LAYERS: True})
        gpkg_c = _extract(scenario.out_dir / "C.zip", "C.gpkg", tmp_path / "xk")
        assert layer_names(gpkg_c) == ["cities", "plots", "roads"]
        assert feature_count(gpkg_c, "cities") == 0

        _run(scenario, {p.KEEP_EMPTY_LAYERS: False})
        gpkg_c2 = _extract(scenario.out_dir / "C.zip", "C.gpkg", tmp_path / "xk2")
        assert layer_names(gpkg_c2) == ["roads"]

    def test_overwrite_error_mode(self, scenario: Scenario) -> None:
        """Error mode aborts at validation, listing the existing targets."""
        scenario.out_dir.mkdir(parents=True)
        (scenario.out_dir / "A.zip").write_bytes(b"old")
        with pytest.raises(QgsProcessingException, match=r"A\.zip"):
            _run(scenario, {p.OVERWRITE_MODE: "error"})

    def test_overwrite_skip_existing(self, scenario: Scenario) -> None:
        """skip-existing leaves the existing zip alone and reports the skip per layer."""
        scenario.out_dir.mkdir(parents=True)
        (scenario.out_dir / "A.zip").write_bytes(b"old")
        results = _run(scenario, {p.OVERWRITE_MODE: "skip-existing"})
        assert (scenario.out_dir / "A.zip").read_bytes() == b"old"
        assert (scenario.out_dir / "B.zip").is_file()
        assert results[p.ZIP_COUNT] == 1
        report = (scenario.out_dir / "report.csv").read_text(encoding="utf-8")
        # §9.1: one row per (stratum, packaged layer) — never a blank-layer summary row.
        for layer_name in ("cities", "plots", "roads"):
            assert f"A,{layer_name},,skipped-existing,A.zip exists" in report
        assert "A,,skipped-existing" not in report

    def test_dry_run_writes_report_only(self, scenario: Scenario) -> None:
        """DRY_RUN produces the report and outputs, but no zips."""
        results = _run(scenario, {p.DRY_RUN: True})
        assert results[p.ZIP_COUNT] == 0
        assert json.loads(results[p.ZIP_PATHS]) == []
        assert not list(scenario.out_dir.glob("*.zip"))
        report = (scenario.out_dir / "report.csv").read_text(encoding="utf-8")
        assert "dry-run" in report
        # The dry run is matching-free (a fast structural preview): whole-export layers report
        # their full count, partitioned layers are left blank, and orphans are not accounted —
        # that lazy matching only runs during a real build.
        assert "A,roads,2,dry-run" in report
        assert "A,cities,,dry-run" in report
        assert "<unmatched>" not in report

    def test_bundled_zip(self, scenario: Scenario) -> None:
        """A constant zip expression bundles both strata into one zip."""
        results = _run(scenario, {p.ZIP_PATH_EXPRESSION: "'everything'"})
        bundle = scenario.out_dir / "everything.zip"
        assert bundle.is_file()
        with zipfile.ZipFile(bundle) as archive:
            assert sorted(archive.namelist()) == ["A.gpkg", "B.gpkg", "report.csv"]
            report = archive.read("report.csv").decode("utf-8")
        assert results[p.ZIP_COUNT] == 1
        assert ",A," not in report.splitlines()[0]
        assert any(line.startswith("A,") for line in report.splitlines())
        assert any(line.startswith("B,") for line in report.splitlines())

    def test_extra_dir_contents_and_conflicts(self, scenario: Scenario, tmp_path: Path) -> None:
        """EXTRA_DIR contents land at every zip root; reserved names abort."""
        extra = tmp_path / "extra"
        (extra / "docs").mkdir(parents=True)
        (extra / "readme.txt").write_text("hello", encoding="utf-8")
        (extra / "docs/manual.txt").write_text("manual", encoding="utf-8")
        _run(scenario, {p.EXTRA_DIR: str(extra)})
        with zipfile.ZipFile(scenario.out_dir / "A.zip") as archive:
            assert sorted(archive.namelist()) == [
                "A.gpkg",
                "docs/manual.txt",
                "readme.txt",
                "report.csv",
            ]

        (extra / "report.csv").write_text("clash", encoding="utf-8")
        with pytest.raises(QgsProcessingException, match="reserved"):
            _run(scenario, {p.EXTRA_DIR: str(extra)})

    def test_best_effort_failure(
        self, scenario: Scenario, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A failing stratum is contained; the rest publishes; the run raises at the end."""

        def flaky(build: Any, **kwargs: Any) -> StratumWriteResult:
            if build.name == "B":
                return StratumWriteResult(name="B", ok=False, error="injected failure")
            return real_write_stratum(build, **kwargs)

        monkeypatch.setattr(algorithm_module, "write_stratum", flaky)
        with pytest.raises(QgsProcessingException, match=r"injected|B"):
            _run(scenario)
        assert (scenario.out_dir / "A.zip").is_file()
        assert not (scenario.out_dir / "B.zip").exists()
        report = (scenario.out_dir / "report.csv").read_text(encoding="utf-8")
        assert "B,cities,,failed,injected failure" in report

    def test_precanceled_run_aborts(self, scenario: Scenario) -> None:
        """A canceled feedback aborts before any output is produced."""
        feedback = QgsProcessingFeedback()
        feedback.cancel()
        with pytest.raises(QgsProcessingException, match="cancel"):
            _run(scenario, feedback=feedback)
        assert not scenario.out_dir.exists() or not list(scenario.out_dir.glob("*.zip"))


class TestValidationSurface:
    """checkParameterValues and runtime fallback behavior."""

    def test_static_checks(self, scenario: Scenario) -> None:
        """Unparsable expressions and an unknown warm-start token fail statically."""
        algorithm = StratifiedPackagerAlgorithm()
        algorithm.initAlgorithm()
        context = QgsProcessingContext()
        context.setProject(scenario.project)
        ok, message = algorithm.checkParameterValues(
            _base_params(scenario) | {p.STRATUM_NAME_EXPRESSION: "((("}, context
        )
        assert not ok
        assert "parse" in message
        ok, _message = algorithm.checkParameterValues(
            _base_params(scenario) | {p.WARM_START_MODE: "bogus"}, context
        )
        assert not ok

    def test_missing_strat_layer_aborts(self, scenario: Scenario) -> None:
        """Without a stratification layer the run aborts with the §3 footnote."""
        with pytest.raises(QgsProcessingException, match="STRATIFICATION_LAYER"):
            _run(scenario, {p.STRATIFICATION_LAYER: None})

    def test_project_variable_fallback(self, scenario: Scenario) -> None:
        """An omitted input resolves through the project variable tier."""
        QgsExpressionContextUtils.setProjectVariable(
            scenario.project, "stratified_packager_compression_level", "0"
        )
        parameters = _base_params(scenario)
        del parameters[p.COMPRESSION_LEVEL]
        algorithm = StratifiedPackagerAlgorithm()
        algorithm.initAlgorithm()
        context = QgsProcessingContext()
        context.setProject(scenario.project)
        results = algorithm.processAlgorithm(parameters, context, QgsProcessingFeedback())
        assert results[p.ZIP_COUNT] == 2
        with zipfile.ZipFile(scenario.out_dir / "A.zip") as archive:
            assert {info.compress_type for info in archive.infolist()} == {zipfile.ZIP_STORED}


class TestEmbeddedProjectAndPayloads:
    """Payload bundling, embedded projects, resources (SPEC §13/§14)."""

    @pytest.fixture
    def enriched(self, scenario: Scenario, tmp_path: Path) -> Scenario:
        """
        Add a raster payload and an SVG-marker style to the base scenario.

        :param scenario: The base scenario.
        :param tmp_path: Temp dir for the raster + svg sources.
        :return: The same scenario (project enriched in place).
        """
        tif = _write_tif(tmp_path / "dem_src.tif")
        raster = QgsRasterLayer(str(tif), "dem", "gdal")
        assert raster.isValid()
        assert scenario.project.addMapLayer(raster, addToLegend=False)

        svg = tmp_path / "marker.svg"
        svg.write_text("<svg/>", encoding="utf-8")
        marker = QgsSvgMarkerSymbolLayer(str(svg))
        symbol = QgsMarkerSymbol()
        symbol.changeSymbolLayer(0, marker)
        scenario.cities.setRenderer(QgsSingleSymbolRenderer(symbol))
        return scenario

    def test_qgz_inclusion_with_payload_and_resources(
        self, enriched: Scenario, tmp_path: Path
    ) -> None:
        """The zip carries gpkg + qgz + data/ + resources/; the qgz reopens fully."""
        results = _run(
            enriched,
            {
                p.LAYERS: [enriched.cities, enriched.plots, enriched.roads]
                + [lyr for lyr in enriched.project.mapLayers().values() if lyr.name() == "dem"],
                p.PROJECT_INCLUSION: ProjectInclusion.QGZ.value,
            },
        )
        assert results[p.ZIP_COUNT] == 2
        zip_a = enriched.out_dir / "A.zip"
        with zipfile.ZipFile(zip_a) as archive:
            names = sorted(archive.namelist())
        assert "A.gpkg" in names
        assert "A.qgz" in names
        assert "data/dem/dem_src.tif" in names
        assert any(name.startswith("resources/") for name in names)

        extract_dir = tmp_path / "x_qgz"
        with zipfile.ZipFile(zip_a) as archive:
            archive.extractall(extract_dir)
        reopened = QgsProject()
        assert reopened.read(str(extract_dir / "A.qgz"))
        names = sorted(layer.name() for layer in reopened.mapLayers().values())
        assert names == ["cities", "dem", "plots", "roads"]
        for layer in reopened.mapLayers().values():
            assert layer.isValid(), layer.name()

    def test_gpkg_inclusion_writes_project_storage(
        self, enriched: Scenario, tmp_path: Path
    ) -> None:
        """Gpkg mode stores the project inside each member GeoPackage."""
        _run(enriched, {p.PROJECT_INCLUSION: ProjectInclusion.GPKG.value})
        gpkg_a = _extract(enriched.out_dir / "A.zip", "A.gpkg", tmp_path / "x_gpkg")
        with sqlite3.connect(gpkg_a) as connection:
            rows = connection.execute("SELECT name FROM qgis_projects").fetchall()
        assert rows == [("A",)]

    def test_payload_rows_in_reports(self, enriched: Scenario) -> None:
        """The raster payload appears in both report levels."""
        _run(
            enriched,
            {
                p.LAYERS: [enriched.cities, enriched.plots, enriched.roads]
                + [lyr for lyr in enriched.project.mapLayers().values() if lyr.name() == "dem"],
            },
        )
        run_report = (enriched.out_dir / "report.csv").read_text(encoding="utf-8")
        assert "A,dem,,ok" in run_report
        with zipfile.ZipFile(enriched.out_dir / "A.zip") as archive:
            zip_report = archive.read("report.csv").decode("utf-8")
        assert "data/dem/dem_src.tif" in zip_report
        assert ",raster," in zip_report


class TestWarmStart:
    """The §11 warm lifecycle (update, use, fallback, misconfiguration)."""

    def _mark_roads(self, scenario: Scenario) -> None:
        """Mark the roads layer as warm (§4 layer variable)."""
        QgsExpressionContextUtils.setLayerVariable(
            scenario.roads, "stratified_packager_warm_marked", "true"
        )

    def test_update_then_use_cycle(self, scenario: Scenario, tmp_path: Path) -> None:
        """UPDATE seeds the cache with exactly the warm tables; USE consumes it."""
        self._mark_roads(scenario)
        warm_dir = tmp_path / "warm"
        _run(scenario, {p.WARM_START_MODE: "update", p.WARM_START_DIR: str(warm_dir)})
        assert sorted(f.name for f in warm_dir.glob("*.gpkg")) == ["A.gpkg", "B.gpkg"]
        assert layer_names(warm_dir / "A.gpkg") == ["roads"]
        assert feature_count(warm_dir / "A.gpkg", "roads") == 2

        results = _run(scenario, {p.WARM_START_MODE: "use", p.WARM_START_DIR: str(warm_dir)})
        assert results[p.ZIP_COUNT] == 2
        report = (scenario.out_dir / "report.csv").read_text(encoding="utf-8")
        assert "A,roads,2,warm" in report
        assert "B,roads,2,warm" in report

    def test_cold_fallback_on_drift(self, scenario: Scenario, tmp_path: Path) -> None:
        """A warm file with a foreign table falls back cold, per stratum."""
        self._mark_roads(scenario)
        warm_dir = tmp_path / "warm"
        _run(scenario, {p.WARM_START_MODE: "update", p.WARM_START_DIR: str(warm_dir)})
        # Poison A's warm file with an extra table; B stays valid.
        extra = build_alpha_gpkg(tmp_path / "extra.gpkg")
        foreign = QgsVectorLayer(f"{extra}|layername=alpha", "f", "ogr")
        assert foreign.isValid()
        write_vector_table(
            warm_dir / "A.gpkg",
            foreign,
            "foreign",
            only_selected=False,
            feedback=QgsProcessingFeedback(),
        )
        results = _run(scenario, {p.WARM_START_MODE: "use", p.WARM_START_DIR: str(warm_dir)})
        assert results[p.ZIP_COUNT] == 2
        report = (scenario.out_dir / "report.csv").read_text(encoding="utf-8")
        assert "A,roads,2,cold-fallback" in report
        assert "B,roads,2,warm" in report

    def _mark_cities_warm_staged(self, scenario: Scenario) -> None:
        """Mark the (partitioned) cities layer both warm and stage=true (§4 variables)."""
        QgsExpressionContextUtils.setLayerVariable(
            scenario.cities, "stratified_packager_warm_marked", "true"
        )
        QgsExpressionContextUtils.setLayerVariable(
            scenario.cities, "stratified_packager_stage", "true"
        )

    def test_use_run_skips_staging_when_cache_covers_every_stratum(
        self, scenario: Scenario, tmp_path: Path
    ) -> None:
        """USE + complete cache: a fully-warm group's staging is skipped (SPEC §8.2/§11)."""
        self._mark_cities_warm_staged(scenario)
        warm_dir = tmp_path / "warm"
        _run(scenario, {p.WARM_START_MODE: "update", p.WARM_START_DIR: str(warm_dir)})

        feedback = _RecordingFeedback()
        results = _run(
            scenario,
            {p.WARM_START_MODE: "use", p.WARM_START_DIR: str(warm_dir)},
            feedback=feedback,
        )
        assert results[p.ZIP_COUNT] == 2
        assert any("Skipping staging" in line for line in feedback.infos)
        assert not any(line.startswith("Staging layer") for line in feedback.infos)
        report = (scenario.out_dir / "report.csv").read_text(encoding="utf-8")
        assert "A,cities,2,warm" in report
        assert "B,cities,1,warm" in report
        assert "cold-fallback" not in report

    def test_use_run_still_stages_when_a_cache_is_missing(
        self, scenario: Scenario, tmp_path: Path
    ) -> None:
        """USE + a missing cache file: the pre-scan warns once and staging proceeds."""
        self._mark_cities_warm_staged(scenario)
        warm_dir = tmp_path / "warm"
        _run(scenario, {p.WARM_START_MODE: "update", p.WARM_START_DIR: str(warm_dir)})
        (warm_dir / "B.gpkg").unlink()

        feedback = _RecordingFeedback()
        results = _run(
            scenario,
            {p.WARM_START_MODE: "use", p.WARM_START_DIR: str(warm_dir)},
            feedback=feedback,
        )
        assert results[p.ZIP_COUNT] == 2
        assert any("Warm cache unusable" in line for line in feedback.warnings)
        assert any(line.startswith("Staging layer") for line in feedback.infos)
        assert not any("Skipping staging" in line for line in feedback.infos)
        report = (scenario.out_dir / "report.csv").read_text(encoding="utf-8")
        assert "A,cities,2,warm" in report
        assert "B,cities,1,cold-fallback" in report

    def test_update_run_still_stages_warm_groups(self, scenario: Scenario, tmp_path: Path) -> None:
        """UPDATE always stages: its warm pass reads the staged copy once per stratum."""
        self._mark_cities_warm_staged(scenario)
        feedback = _RecordingFeedback()
        _run(
            scenario,
            {p.WARM_START_MODE: "update", p.WARM_START_DIR: str(tmp_path / "warm")},
            feedback=feedback,
        )
        assert any(line.startswith("Staging layer") for line in feedback.infos)
        assert not any("Skipping staging" in line for line in feedback.infos)

    def test_use_run_prefetches_every_cache_and_seeds_in_place(
        self, scenario: Scenario, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """USE runs copy each cache to its build path up front and still ship warm (§11)."""
        self._mark_roads(scenario)
        warm_dir = tmp_path / "warm"
        _run(scenario, {p.WARM_START_MODE: "update", p.WARM_START_DIR: str(warm_dir)})
        calls: list[str] = []

        def recording(source: Path, destination: Path, cancel: Any) -> bool:
            calls.append(source.name)
            return real_run_prefetch(source, destination, cancel)

        monkeypatch.setattr(algorithm_module, "run_prefetch", recording)
        results = _run(scenario, {p.WARM_START_MODE: "use", p.WARM_START_DIR: str(warm_dir)})
        assert sorted(calls) == ["A.gpkg", "B.gpkg"]
        assert results[p.ZIP_COUNT] == 2
        report = (scenario.out_dir / "report.csv").read_text(encoding="utf-8")
        assert "A,roads,2,warm" in report
        assert "B,roads,2,warm" in report

    def test_empty_warm_set_is_an_error(self, scenario: Scenario, tmp_path: Path) -> None:
        """Warm flags without any warm_marked layer abort at run start."""
        with pytest.raises(QgsProcessingException, match="warm_marked"):
            _run(
                scenario,
                {p.WARM_START_MODE: "use", p.WARM_START_DIR: str(tmp_path / "warm")},
            )

    def test_update_builds_all_caches_before_deliverables(
        self, scenario: Scenario, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The §11 warm pass publishes every cache before any deliverable build starts."""
        self._mark_roads(scenario)
        warm_dir = tmp_path / "warm"
        calls: list[tuple[str, bool]] = []

        def recording(build: Any, **kwargs: Any) -> StratumWriteResult:
            calls.append((build.name, build.snapshot_to is not None))
            return real_write_stratum(build, **kwargs)

        monkeypatch.setattr(algorithm_module, "write_stratum", recording)
        _run(scenario, {p.WARM_START_MODE: "update", p.WARM_START_DIR: str(warm_dir)})

        assert [flag for _, flag in calls] == [True, True, False, False]  # caches first
        assert {name for name, flag in calls if flag} == {"A", "B"}
        assert {name for name, flag in calls if not flag} == {"A", "B"}
        # The deliverable pass seeds from the fresh cache, so warm layers report `warm`.
        report = (scenario.out_dir / "report.csv").read_text(encoding="utf-8")
        assert "A,roads,2,warm" in report
        assert "B,roads,2,warm" in report

    def test_update_cache_holds_only_warm_tables_despite_template(
        self, scenario: Scenario, tmp_path: Path
    ) -> None:
        """
        Regression: the cache must exclude template (whole-export) tables (SPEC §11).

        The mid-build snapshot used to copy the template-seeded gpkg, so every cache
        carried the whole-export tables and every later USE run fell back cold.
        """
        # cities is warm-marked; roads stays whole-export and non-warm → a template exists.
        QgsExpressionContextUtils.setLayerVariable(
            scenario.cities, "stratified_packager_warm_marked", "true"
        )
        warm_dir = tmp_path / "warm"
        _run(scenario, {p.WARM_START_MODE: "update", p.WARM_START_DIR: str(warm_dir)})
        assert layer_names(warm_dir / "A.gpkg") == ["cities"]  # roads (template) stays out
        assert feature_count(warm_dir / "A.gpkg", "cities") == 2

        results = _run(scenario, {p.WARM_START_MODE: "use", p.WARM_START_DIR: str(warm_dir)})
        assert results[p.ZIP_COUNT] == 2
        report = (scenario.out_dir / "report.csv").read_text(encoding="utf-8")
        assert "A,cities,2,warm" in report
        assert "cold-fallback" not in report

    def test_warm_marked_whole_export_still_ships_without_warm_flags(
        self, scenario: Scenario, tmp_path: Path
    ) -> None:
        """
        Regression: a warm-marked whole-export layer must not vanish behind the template.

        The template-recognize branch used to match warm-marked whole-export layers too,
        but the template never contains them — the table was reported ``empty-skipped``
        and its data never shipped, even with both warm flags off.
        """
        self._mark_roads(scenario)  # roads: whole-export AND warm-marked
        alpha_path = build_alpha_gpkg(tmp_path / "alpha_src.gpkg")
        alpha = QgsVectorLayer(f"{alpha_path}|layername=alpha", "alpha", "ogr")
        assert alpha.isValid()
        QgsExpressionContextUtils.setLayerVariable(
            alpha, "stratified_packager_matching_method", "whole_export"
        )
        assert scenario.project.addMapLayer(alpha, addToLegend=False)

        _run(scenario, {p.LAYERS: [scenario.cities, scenario.plots, scenario.roads, alpha]})

        gpkg_a = _extract(scenario.out_dir / "A.zip", "A.gpkg", tmp_path / "xw")
        assert feature_count(gpkg_a, "roads") == 2  # was empty-skipped before the fix
        assert feature_count(gpkg_a, "alpha") == 6  # the template layer itself
        report = (scenario.out_dir / "report.csv").read_text(encoding="utf-8")
        assert "A,roads,2,ok" in report

    def test_failed_cache_write_still_ships_cold(
        self, scenario: Scenario, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A failed warm-pass write costs the cache, not the deliverable; the run still fails."""
        self._mark_roads(scenario)
        warm_dir = tmp_path / "warm"

        def flaky(build: Any, **kwargs: Any) -> StratumWriteResult:
            if build.snapshot_to is not None and build.name == "B":
                return StratumWriteResult(name="B", ok=False, error="cache disk full")
            return real_write_stratum(build, **kwargs)

        monkeypatch.setattr(algorithm_module, "write_stratum", flaky)
        with pytest.raises(QgsProcessingException, match=r"warm caches: \[B\]"):
            _run(scenario, {p.WARM_START_MODE: "update", p.WARM_START_DIR: str(warm_dir)})

        assert (scenario.out_dir / "A.zip").is_file()
        assert (scenario.out_dir / "B.zip").is_file()  # the deliverable still built (cold)
        assert (warm_dir / "A.gpkg").is_file()
        assert not (warm_dir / "B.gpkg").exists()
        report = (scenario.out_dir / "report.csv").read_text(encoding="utf-8")
        assert "A,roads,2,warm" in report
        assert "B,roads,2,cold-fallback" in report

    def test_update_caches_empty_warm_table_deliverable_drops_it(
        self, scenario: Scenario, tmp_path: Path
    ) -> None:
        """The cache always keeps an empty warm table; the deliverable honors KEEP_EMPTY_LAYERS."""
        ponds = QgsVectorLayer("Polygon?crs=EPSG:4326&field=pond:integer", "ponds", "memory")
        provider = ponds.dataProvider()
        assert provider is not None
        feature = QgsFeature(ponds.fields())
        feature.setAttribute(0, 1)
        feature.setGeometry(_square(3.0, 3.0, 1.0))  # inside stratum A only
        assert provider.addFeatures([feature])
        QgsExpressionContextUtils.setLayerVariable(
            ponds, "stratified_packager_warm_marked", "true"
        )
        assert scenario.project.addMapLayer(ponds, addToLegend=False)
        warm_dir = tmp_path / "warm"

        _run(
            scenario,
            {
                p.LAYERS: [scenario.cities, scenario.plots, scenario.roads, ponds],
                p.WARM_START_MODE: "update",
                p.WARM_START_DIR: str(warm_dir),
                p.KEEP_EMPTY_LAYERS: False,
            },
        )

        assert "ponds" in layer_names(warm_dir / "B.gpkg")  # cached despite being empty
        assert feature_count(warm_dir / "B.gpkg", "ponds") == 0
        gpkg_b = _extract(scenario.out_dir / "B.zip", "B.gpkg", tmp_path / "xe")
        assert "ponds" not in layer_names(gpkg_b)  # dropped from the deliverable
        gpkg_a = _extract(scenario.out_dir / "A.zip", "A.gpkg", tmp_path / "xa")
        assert feature_count(gpkg_a, "ponds") == 1
        report = (scenario.out_dir / "report.csv").read_text(encoding="utf-8")
        assert "B,ponds,0,empty-skipped" in report
        assert "A,ponds,1,warm" in report


class TestDedupAndFullPackage:
    """§12 dedup groups and the §3 full package."""

    def test_dedup_union_over_shared_source(self, scenario: Scenario, tmp_path: Path) -> None:
        """Two layers over one gpkg yield one union table with two style rows."""
        twin = QgsVectorLayer(scenario.cities.source(), "cities_twin", "ogr")
        assert twin.isValid()
        assert twin.setSubsetString('"cid" <= 1')
        assert scenario.project.addMapLayer(twin, addToLegend=False)

        _run(
            scenario,
            {p.LAYERS: [scenario.cities, twin, scenario.plots, scenario.roads]},
        )
        gpkg_a = _extract(scenario.out_dir / "A.zip", "A.gpkg", tmp_path / "xd")
        assert layer_names(gpkg_a) == ["cities", "plots", "roads"]
        # Union: cities (attribute, A -> cid 1+2) + twin (spatial within A, cid 1) = {1, 2}.
        assert feature_count(gpkg_a, "cities") == 2
        with sqlite3.connect(gpkg_a) as connection:
            styles = connection.execute(
                "SELECT styleName, useAsDefault FROM layer_styles"
                " WHERE f_table_name = 'cities' ORDER BY id"
            ).fetchall()
        assert styles == [("cities", 1), ("cities_twin", 0)]
        with zipfile.ZipFile(scenario.out_dir / "A.zip") as archive:
            zip_report = archive.read("report.csv").decode("utf-8")
        assert zip_report.count(",cities,") >= 1
        assert "cities_twin,cities," in zip_report  # member row points at shared table

    def test_staged_dedup_group_stages_once_and_stays_deduplicated(
        self, scenario: Scenario, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        A fully staged dedup group builds ONE staging copy and one shared output table.

        Regression: staging used to run per layer before dedup and staged preps were skipped
        by the grouping, so shared-source layers all marked ``stage=true`` each got their own
        staging gpkg AND their own (duplicate) table in every stratum (SPEC 8.2 x 12).
        """
        twin = QgsVectorLayer(scenario.cities.source(), "cities_twin", "ogr")
        assert twin.isValid()
        assert scenario.project.addMapLayer(twin, addToLegend=False)
        for layer in (scenario.cities, twin):
            QgsExpressionContextUtils.setLayerVariable(layer, "stratified_packager_stage", "true")

        staged_tables: list[str] = []
        real_stage_union = real_stage_union_import

        def counting_stage_union(
            staging_gpkg: Path, read_layer: QgsVectorLayer, table: str, *args: Any, **kwargs: Any
        ) -> None:
            staged_tables.append(table)
            real_stage_union(staging_gpkg, read_layer, table, *args, **kwargs)

        monkeypatch.setattr(algorithm_module, "stage_union", counting_stage_union)

        _run(scenario, {p.LAYERS: [scenario.cities, twin, scenario.plots, scenario.roads]})

        assert staged_tables == ["cities"]  # one staging copy for the whole group
        gpkg_a = _extract(scenario.out_dir / "A.zip", "A.gpkg", tmp_path / "xsd")
        names = layer_names(gpkg_a)
        assert "cities_twin" not in names  # dedup survived staging
        # Union over stratum A: cities (attribute -> cid 1+2) + twin (spatial -> cid 1) = {1, 2}.
        assert feature_count(gpkg_a, "cities") == 2

    def test_dedup_names_table_after_unfiltered_member(
        self, scenario: Scenario, tmp_path: Path
    ) -> None:
        """An unfiltered member names the shared table even when a filtered one sorts first."""
        view = QgsVectorLayer(scenario.cities.source(), "cities_view", "ogr")
        assert view.isValid()
        assert view.setSubsetString('"cid" <= 1')
        whole = QgsVectorLayer(scenario.cities.source(), "cities_all", "ogr")
        assert whole.isValid()
        assert scenario.project.addMapLayers([view, whole], addToLegend=False)

        # Filtered "cities_view" leads in tree order, unfiltered "cities_all" follows; the
        # shared table must be named (and styled) after the unfiltered member (§12), and
        # cities itself is excluded so the dedup group is exactly these two twins.
        _run(scenario, {p.LAYERS: [view, whole, scenario.plots, scenario.roads]})

        gpkg_a = _extract(scenario.out_dir / "A.zip", "A.gpkg", tmp_path / "xu")
        names = layer_names(gpkg_a)
        assert "cities_all" in names
        assert "cities_view" not in names
        assert feature_count(gpkg_a, "cities_all") == 2  # union {1, 2} over stratum A
        with sqlite3.connect(gpkg_a) as connection:
            default_style = connection.execute(
                "SELECT styleName FROM layer_styles"
                " WHERE f_table_name = 'cities_all' AND useAsDefault = 1"
            ).fetchone()
        assert default_style == ("cities_all",)

    def test_full_package(self, scenario: Scenario, tmp_path: Path) -> None:
        """EXPORT_FULL_PACKAGE adds the unpartitioned <full> zip."""
        results = _run(
            scenario,
            {p.EXPORT_FULL_PACKAGE: True, p.FULL_PACKAGE_PATH: "everything_full"},
        )
        assert results[p.ZIP_COUNT] == 3
        full_zip = scenario.out_dir / "everything_full.zip"
        assert full_zip.is_file()
        gpkg_full = _extract(full_zip, "everything_full.gpkg", tmp_path / "xf")
        assert feature_count(gpkg_full, "cities") == 4
        assert feature_count(gpkg_full, "plots") == 3
        assert feature_count(gpkg_full, "roads") == 2
        report = (scenario.out_dir / "report.csv").read_text(encoding="utf-8")
        assert "<full>,cities,4,ok" in report

    def test_full_only_run(self, scenario: Scenario, tmp_path: Path) -> None:
        """A blank stratification layer with EXPORT_FULL_PACKAGE builds only <full>."""
        results = _run(
            scenario,
            {
                p.STRATIFICATION_LAYER: None,
                p.EXPORT_FULL_PACKAGE: True,
                p.FULL_PACKAGE_PATH: "only_full",
            },
        )
        assert results[p.ZIP_COUNT] == 1
        assert results[p.STRATA_COUNT] == 1
        gpkg_full = _extract(scenario.out_dir / "only_full.zip", "only_full.gpkg", tmp_path / "xo")
        assert feature_count(gpkg_full, "cities") == 4

    def test_staged_partitioned_layers_keep_orphans_in_full_package(
        self, scenario: Scenario, tmp_path: Path
    ) -> None:
        """
        Under EXPORT_FULL_PACKAGE a staged partitioned layer stages all features (SPEC §8.2).

        The ``<full>`` package keeps every feature (orphans included) and orphan accounting is
        exact, while the partitioned strata still slice correctly from the staged-whole copy.
        """
        for layer in (scenario.cities, scenario.plots):  # attribute + spatial, both staged
            QgsExpressionContextUtils.setLayerVariable(layer, p.LAYER_VAR_STAGE, "true")

        _run(scenario, {p.EXPORT_FULL_PACKAGE: True, p.FULL_PACKAGE_PATH: "everything_full"})

        gpkg_full = _extract(
            scenario.out_dir / "everything_full.zip", "everything_full.gpkg", tmp_path / "xs"
        )
        assert feature_count(gpkg_full, "cities") == 4  # orphan cid 4 survives staging
        assert feature_count(gpkg_full, "plots") == 3  # orphan tag 2 survives staging

        gpkg_a = _extract(scenario.out_dir / "A.zip", "A.gpkg", tmp_path / "xsa")
        assert feature_count(gpkg_a, "cities") == 2  # slice still correct from the staged copy

        report = (scenario.out_dir / "report.csv").read_text(encoding="utf-8")
        assert "<unmatched>,cities,1," in report  # orphan accounting exact under export_full
        assert "<unmatched>,plots,1," in report

    def test_staged_partitioned_layer_union_without_full_package(
        self, scenario: Scenario, tmp_path: Path
    ) -> None:
        """
        Without EXPORT_FULL_PACKAGE a staged partitioned layer stages only the matched union.

        Exercises the staging path end-to-end (the per-layer ``staging/`` gpkg is created and
        sliced per stratum); orphans report zero — correct for the data actually packaged (§8.2).
        """
        QgsExpressionContextUtils.setLayerVariable(scenario.cities, p.LAYER_VAR_STAGE, "true")

        _run(scenario)

        gpkg_a = _extract(scenario.out_dir / "A.zip", "A.gpkg", tmp_path / "xu1")
        assert feature_count(gpkg_a, "cities") == 2  # stratum A slice from the staged union
        report = (scenario.out_dir / "report.csv").read_text(encoding="utf-8")
        assert "<unmatched>,cities" not in report  # union staging packages no orphans


class TestFinalizeMembers:
    """`_finalize_members` degraded-delivery containment (SPEC §17)."""

    def test_embed_failure_keeps_data_and_only_warns(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        An embedded-project failure keeps the member and its gpkg, and only warns.

        The pre-fix path unlinked the still-locked gpkg, raising ``PermissionError`` out of the
        whole run; the member must instead stay successful with its data intact.

        :param tmp_path: Holds the gpkg that must survive.
        :param monkeypatch: Forces ``build_stratum_project`` to fail.
        """
        gpkg = tmp_path / "A.gpkg"
        gpkg.write_bytes(b"data")

        def _boom(*_args: object, **_kwargs: object) -> None:
            msg = "embedded write failed"
            raise QgsProcessingException(msg)

        monkeypatch.setattr(algorithm_module, "build_stratum_project", _boom)

        material = SimpleNamespace(
            inputs=SimpleNamespace(project_inclusion=ProjectInclusion.QGZ),
            project=SimpleNamespace(),
            gpkg_paths={"A": gpkg},
        )
        state = SimpleNamespace(succeeded={"A"}, failed={})
        members = [SimpleNamespace(name="A")]
        feedback = QgsProcessingFeedback()

        algo = StratifiedPackagerAlgorithm()
        monkeypatch.setattr(algo, "_project_plan", lambda *_a, **_k: object())
        algo._finalize_members(
            cast("Any", material), cast("Any", members), cast("Any", state), feedback
        )

        assert state.succeeded == {"A"}  # member kept
        assert state.failed == {}  # not marked failed
        assert gpkg.is_file()  # gpkg NOT unlinked (no WinError 32 path)
        assert "A" in feedback.textLog()  # a warning was pushed for the member

    def test_layer_name_plan_failure_fails_the_member(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        A §4 failure while assembling the plan fails the stratum, unlike a write failure.

        ``_project_plan`` evaluates the strict ``layer_name`` expressions; its exception
        must drop the member from the succeeded set and clean its gpkg (SPEC §4/§17).

        :param tmp_path: Holds the gpkg that must be discarded.
        :param monkeypatch: Forces the plan assembly to fail.
        """
        gpkg = tmp_path / "A.gpkg"
        gpkg.write_bytes(b"data")

        material = SimpleNamespace(
            inputs=SimpleNamespace(project_inclusion=ProjectInclusion.QGZ),
            project=SimpleNamespace(),
            gpkg_paths={"A": gpkg},
        )
        state = SimpleNamespace(succeeded={"A"}, failed={})
        members = [SimpleNamespace(name="A")]
        feedback = QgsProcessingFeedback()

        algo = StratifiedPackagerAlgorithm()

        def _null_eval(*_args: object, **_kwargs: object) -> object:
            msg = "layer name evaluated to NULL"
            raise QgsProcessingException(msg)

        monkeypatch.setattr(algo, "_project_plan", _null_eval)
        algo._finalize_members(
            cast("Any", material), cast("Any", members), cast("Any", state), feedback
        )

        assert state.succeeded == set()  # the member failed
        assert "NULL" in state.failed["A"]
        assert not gpkg.exists()  # the failed member's partial is cleaned (§17)


class TestWorkdirCleanup:
    """The §10 build-directory lifecycle: end-of-run removal and stale-sibling sweep."""

    def test_discard_workdir_clears_refs_and_removes(self, tmp_path: Path) -> None:
        """The layer-holding material fields are cleared and the workdir is removed."""
        workdir = tmp_path / ".stratified_build_x"
        (workdir / "staging").mkdir(parents=True)
        (workdir / "staging/layer.gpkg").write_bytes(b"data")
        material = SimpleNamespace(
            preps=[object()],
            payloads=[object()],
            warm_prefetch={"A": object()},
            inputs=SimpleNamespace(use_temp_folder=True),
        )
        feedback = QgsProcessingFeedback()

        algo = StratifiedPackagerAlgorithm()
        algo._discard_workdir(cast("Any", material), workdir, feedback)

        assert not workdir.exists()
        assert material.preps == []  # read-layer handles released before removal
        assert material.payloads == []
        assert material.warm_prefetch == {}

    def test_discard_workdir_reports_residue(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Residue in a user-visible (non-temp) workdir is surfaced as a warning."""
        workdir = tmp_path / ".stratified_build_x"
        workdir.mkdir()
        monkeypatch.setattr(algorithm_module, "remove_tree", lambda *_a, **_k: False)
        material = SimpleNamespace(
            preps=[],
            payloads=[],
            warm_prefetch={},
            inputs=SimpleNamespace(use_temp_folder=False),
        )
        feedback = QgsProcessingFeedback()

        algo = StratifiedPackagerAlgorithm()
        algo._discard_workdir(cast("Any", material), workdir, feedback)

        assert workdir.name in feedback.textLog()

    def test_sweep_removes_only_stale_build_dirs(self, tmp_path: Path) -> None:
        """Only day-old ``.stratified_build_*`` siblings are swept at run start."""
        stale = tmp_path / ".stratified_build_old"
        (stale / "zip_000").mkdir(parents=True)
        two_days_ago = time.time() - 2 * 24 * 3600
        os.utime(stale, (two_days_ago, two_days_ago))
        fresh = tmp_path / ".stratified_build_live"
        fresh.mkdir()
        unrelated = tmp_path / "keep.zip"
        unrelated.write_bytes(b"zip")

        algo = StratifiedPackagerAlgorithm()
        algo._sweep_stale_workdirs(tmp_path, QgsProcessingFeedback())

        assert not stale.exists()  # crash residue collected
        assert fresh.is_dir()  # a possibly-live sibling is never touched
        assert unrelated.exists()


class TestAuditRegressionFixes:
    """End-to-end locks for the 2026-07 audit's behavioral fixes."""

    def test_write_checksums_publishes_sha256_sidecars(self, scenario: Scenario) -> None:
        """WRITE_CHECKSUMS=True writes a verifiable sha256sum sidecar per published zip (§10)."""
        _run(scenario, {p.WRITE_CHECKSUMS: True})
        for name in ("A", "B"):
            published = scenario.out_dir / f"{name}.zip"
            expected = hashlib.sha256(published.read_bytes()).hexdigest()
            sidecar = scenario.out_dir / f"{name}.zip.sha256"
            assert sidecar.read_text(encoding="ascii") == f"{expected}  {name}.zip\n"

    def test_full_package_gpkg_collision_with_a_stratum_aborts(self, scenario: Scenario) -> None:
        """SPEC (6.6): the full package joining a stratum's zip must not share its gpkg path."""
        with pytest.raises(QgsProcessingException, match="collide"):
            _run(scenario, {p.EXPORT_FULL_PACKAGE: True, p.FULL_PACKAGE_PATH: "A"})
        assert not list(scenario.out_dir.glob("*.zip"))  # rejected at run start, nothing built

    def test_full_package_bundles_into_a_stratum_zip(self, scenario: Scenario) -> None:
        """Identical zip paths still bundle; distinct gpkg paths inside the bundle are fine."""
        results = _run(scenario, {p.EXPORT_FULL_PACKAGE: True, p.FULL_PACKAGE_PATH: "full/A"})
        assert results[p.ZIP_COUNT] == 2  # <full> bundled into A.zip; B.zip separate
        with zipfile.ZipFile(scenario.out_dir / "A.zip") as archive:
            names = set(archive.namelist())
        assert {"A.gpkg", "full/A.gpkg"} <= names

    def test_warm_marked_t_token_is_warm_and_garbage_aborts(self, scenario: Scenario) -> None:
        """warm_marked follows coerce_bool: "t" is true; an uncoercible value aborts (SPEC 4/6)."""
        warm_dir = scenario.out_dir / "warm"
        QgsExpressionContextUtils.setLayerVariable(
            scenario.roads, "stratified_packager_warm_marked", "t"
        )
        _run(scenario, {p.WARM_START_MODE: "update", p.WARM_START_DIR: str(warm_dir)})
        assert (warm_dir / "A.gpkg").is_file()  # "t" counted as warm-marked
        QgsExpressionContextUtils.setLayerVariable(
            scenario.roads, "stratified_packager_warm_marked", "maybe"
        )
        with pytest.raises(QgsProcessingException, match="warm_marked"):
            _run(scenario, {p.WARM_START_MODE: "update", p.WARM_START_DIR: str(warm_dir)})

    def test_update_warm_start_refreshes_caches_of_skipped_strata(
        self, scenario: Scenario
    ) -> None:
        """SPEC (11): skip-existing skips deliverables, never the warm pass's cache refresh."""
        QgsExpressionContextUtils.setLayerVariable(
            scenario.roads, "stratified_packager_warm_marked", "true"
        )
        warm_dir = scenario.out_dir / "warm"
        scenario.out_dir.mkdir(parents=True)
        (scenario.out_dir / "A.zip").write_bytes(b"old")
        _run(
            scenario,
            {
                p.WARM_START_MODE: "update",
                p.WARM_START_DIR: str(warm_dir),
                p.OVERWRITE_MODE: "skip-existing",
            },
        )
        assert (scenario.out_dir / "A.zip").read_bytes() == b"old"  # deliverable skipped
        assert (warm_dir / "A.gpkg").is_file()  # its cache still refreshed (SPEC 11)
        assert (warm_dir / "B.gpkg").is_file()

    def test_warm_mark_on_a_non_primary_dedup_member_warms_the_group(
        self, scenario: Scenario
    ) -> None:
        """SPEC (11/12): a mark on any dedup member warms the shared table (it is one table)."""
        twin = QgsVectorLayer(scenario.cities.source(), "cities_twin", "ogr")
        assert twin.isValid()
        assert scenario.project.addMapLayers([twin], addToLegend=False)
        QgsExpressionContextUtils.setLayerVariable(twin, "stratified_packager_warm_marked", "true")
        warm_dir = scenario.out_dir / "warm"
        # LAYERS order pins tree order (legend-less layers keep input order), so the
        # unmarked `cities` is the group primary and `cities_twin` the non-primary member.
        _run(
            scenario,
            {
                p.LAYERS: [scenario.cities, twin, scenario.plots, scenario.roads],
                p.WARM_START_MODE: "update",
                p.WARM_START_DIR: str(warm_dir),
            },
        )
        assert "cities" in layer_names(warm_dir / "A.gpkg")  # the shared table is cached

    def test_layer_name_eval_null_fails_its_stratum(self, scenario: Scenario) -> None:
        """SPEC (4): a layer_name expression yielding NULL fails that stratum; others ship."""
        QgsExpressionContextUtils.setLayerVariable(
            scenario.roads,
            "stratified_packager_layer_name",
            "if(@stratum_name = 'A', NULL, 'roads renamed')",
        )
        with pytest.raises(QgsProcessingException, match=r"strata: \[A\]"):
            _run(scenario, {p.PROJECT_INCLUSION: "qgz"})
        assert not (scenario.out_dir / "A.zip").exists()  # the failed member's zip is skipped
        assert (scenario.out_dir / "B.zip").is_file()  # best-effort: B still shipped
        report = (scenario.out_dir / "report.csv").read_text(encoding="utf-8")
        assert "A,roads,,failed" in report
