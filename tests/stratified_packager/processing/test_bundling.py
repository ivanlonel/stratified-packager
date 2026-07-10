"""
Tests for :mod:`stratified_packager.processing.bundling`.

Exercises §14: data/ payload collection (file + sidecars, directory sources, container
sharing), the style-asset walk (project-relative vs _ext, builtin exclusion) and QML
path rewriting.
"""
# pylint: disable=redefined-outer-name

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("qgis", reason="Bundling walks QGIS style entities and providers.")

# Imported only after the importorskip guard above confirms QGIS is available.
from osgeo import gdal  # must follow the importorskip guard
from qgis.core import (
    QgsApplication,
    QgsMarkerSymbol,
    QgsProcessingFeedback,
    QgsProject,
    QgsRasterLayer,
    QgsSingleSymbolRenderer,
    QgsSvgMarkerSymbolLayer,
    QgsVectorLayer,
)

from stratified_packager.processing.bundling import (
    container_sharers,
    data_payload_members,
    rewrite_asset_paths,
    style_asset_mapping,
)

pytestmark = pytest.mark.qgis
"""Marks the whole module as requiring a QGIS runtime."""


def _write_tif(path: Path) -> Path:
    """
    Write a one-pixel GeoTIFF via GDAL.

    :param path: Destination path.
    :return: *path*.
    """
    dataset = gdal.GetDriverByName("GTiff").Create(str(path), 1, 1, 1)
    dataset.GetRasterBand(1).Fill(1)
    dataset.FlushCache()
    del dataset
    return path


@pytest.fixture
def feedback() -> QgsProcessingFeedback:
    """Return a plain feedback sink."""
    return QgsProcessingFeedback()


class TestDataPayloads:
    """§14 data/ payload collection."""

    def test_file_source_with_sidecars(
        self, tmp_path: Path, feedback: QgsProcessingFeedback
    ) -> None:
        """The source file and its existing sidecars land under data/<table>/."""
        tif = _write_tif(tmp_path / "dem.tif")
        aux = tmp_path / "dem.tif.aux.xml"
        aux.write_text("<aux/>", encoding="utf-8")
        layer = QgsRasterLayer(str(tif), "dem", "gdal")
        assert layer.isValid()
        members = data_payload_members(layer, "dem", feedback)
        arcnames = sorted(arc for _src, arc in members)
        assert arcnames == ["data/dem/dem.tif", "data/dem/dem.tif.aux.xml"]

    def test_non_file_source_yields_nothing(self, feedback: QgsProcessingFeedback) -> None:
        """Memory/remote sources have no local payload."""
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "mem", "memory")
        assert not data_payload_members(layer, "mem", feedback)

    def test_container_sharers(self, qgis_new_project: QgsProject, tmp_path: Path) -> None:
        """Layers backed by the same file are reported (the §14 container caveat)."""
        tif = _write_tif(tmp_path / "shared.tif")
        one = QgsRasterLayer(str(tif), "one", "gdal")
        two = QgsRasterLayer(str(tif), "two", "gdal")
        assert one.isValid()
        assert two.isValid()
        assert qgis_new_project.addMapLayers([one, two], addToLegend=False)
        assert container_sharers(one, qgis_new_project) == ["two"]
        assert container_sharers(two, qgis_new_project) == ["one"]


class TestStyleAssets:
    """§14 resources/ asset walk + rewriting."""

    def _svg_layer(self, svg: Path) -> QgsVectorLayer:
        """Build a point layer whose marker symbol references *svg*."""
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "pts", "memory")
        marker = QgsSvgMarkerSymbolLayer(str(svg))
        symbol = QgsMarkerSymbol()
        symbol.changeSymbolLayer(0, marker)
        layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        return layer

    def test_project_relative_and_ext_assets(
        self, tmp_path: Path, feedback: QgsProcessingFeedback
    ) -> None:
        """Assets under the home keep their subtree; foreign ones land in _ext."""
        home = tmp_path / "home"
        (home / "icons").mkdir(parents=True)
        inside = home / "icons/marker.svg"
        inside.write_text("<svg/>", encoding="utf-8")
        outside = tmp_path / "elsewhere.svg"
        outside.write_text("<svg/>", encoding="utf-8")

        mapping_inside = style_asset_mapping([self._svg_layer(inside)], home, feedback)
        assert mapping_inside == {str(inside): "resources/icons/marker.svg"}

        mapping_outside = style_asset_mapping([self._svg_layer(outside)], home, feedback)
        assert len(mapping_outside) == 1
        arc = next(iter(mapping_outside.values()))
        assert arc.startswith("resources/_ext/")
        assert arc.endswith("_elsewhere.svg")

    def test_builtin_paths_are_excluded(self, feedback: QgsProcessingFeedback) -> None:
        """Assets under QgsApplication.svgPaths() are never bundled."""
        for root in QgsApplication.svgPaths():
            candidates = list(Path(root).rglob("*.svg")) if Path(root).is_dir() else []
            if candidates:
                builtin = candidates[0]
                break
        else:
            pytest.skip("no builtin svg available")
        mapping = style_asset_mapping([self._svg_layer(builtin)], None, feedback)
        assert not mapping

    def test_rewrite_asset_paths(self) -> None:
        """Originals (both spellings) rewrite to the to_root-prefixed arcname."""
        original = r"C:\data\home\icons\m.svg"
        mapping = {original: "resources/icons/m.svg"}
        qml = f'<prop v="{original}"/><prop v="C:/data/home/icons/m.svg"/>'
        rewritten = rewrite_asset_paths(qml, mapping, "../")
        assert rewritten == (
            '<prop v="../resources/icons/m.svg"/><prop v="../resources/icons/m.svg"/>'
        )
