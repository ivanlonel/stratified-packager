"""
Tests for :mod:`stratified_packager.processing.report`.

Pure standard-library CSV writing — runs without QGIS:

.. code-block:: bash

    pytest -p no:pytest_qgis -p no:pytest-qt tests/stratified_packager/processing/test_report.py
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from stratified_packager.processing.report import (
    ZipReportRow,
    write_zip_report,
)

if TYPE_CHECKING:
    from pathlib import Path


class TestZipReport:
    """The §9.2 per-zip CSV."""

    def test_golden_content(self, tmp_path: Path) -> None:
        """All fourteen columns render in order; None cells are empty."""
        path = write_zip_report(
            tmp_path / "report.csv",
            [
                ZipReportRow(
                    stratum="north",
                    layer_name="cities",
                    gpkg_table="cities",
                    path_in_zip="north.gpkg",
                    layer_type="vector",
                    geometry_type="Point",
                    feature_count=5,
                    field_count=3,
                    excluded_fields="secret;internal",
                    matching_method="attribute",
                    match_detail="r_cities_states",
                    source_crs="EPSG:4326",
                ),
                ZipReportRow(
                    stratum="north",
                    layer_name="dem",
                    path_in_zip="data/dem/dem.tif",
                    layer_type="raster",
                    matching_method="whole_export",
                ),
            ],
        )
        lines = path.read_text(encoding="utf-8").splitlines()
        assert lines[0] == (
            "stratum,layer_name,gpkg_table,path_in_zip,layer_type,geometry_type,"
            "feature_count,field_count,excluded_fields,matching_method,match_detail,"
            "source_crs,status,detail"
        )
        assert lines[1] == (
            "north,cities,cities,north.gpkg,vector,Point,5,3,secret;internal,"
            "attribute,r_cities_states,EPSG:4326,ok,"
        )
        assert lines[2] == ("north,dem,,data/dem/dem.tif,raster,,,,,whole_export,,,ok,")
