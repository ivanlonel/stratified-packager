"""
Tests for :mod:`stratified_packager.toolbelt.gpkg`.

QGIS-free, but the introspection, table-drop and style tests need GDAL's Python bindings
(``osgeo``), so the module skips where they are unavailable:

.. code-block:: bash

    pytest -p no:pytest_qgis -p no:pytest-qt tests/stratified_packager/toolbelt/test_gpkg.py
"""
# pylint: disable=redefined-outer-name

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("osgeo", reason="GDAL Python bindings are required")

from osgeo import gdal, ogr, osr  # must follow the importorskip guard

# Make fixture-side GDAL/OGR failures loud and silence the GDAL 4.0 FutureWarning.
gdal.UseExceptions()
ogr.UseExceptions()
osr.UseExceptions()

from stratified_packager.toolbelt.gpkg import (  # noqa: E402  # must follow the importorskip guard
    checkpoint_wal,
    create_attribute_index,
    drop_table,
    feature_count,
    geometry_column_of,
    layer_names,
    table_exists,
    wal_session,
    write_layer_metadata,
    write_layer_style,
)
from tests.stratified_packager._qgis_helpers import build_alpha_gpkg  # noqa: E402

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Translation & payload integration (real files)
# ---------------------------------------------------------------------------


@pytest.fixture
def source_gpkg(tmp_path: Path) -> Path:
    """Build a small source GeoPackage with one point layer ``alpha`` (a, b)."""
    return build_alpha_gpkg(tmp_path / "src.gpkg")


class TestIntrospection:
    """Tests for the sqlite/OGR introspection helpers and :func:`drop_table`."""

    def test_read_helpers(self, source_gpkg: Path) -> None:
        """The read helpers report the gpkg's feature tables, geometry column and count."""
        assert layer_names(source_gpkg) == ["alpha"]
        assert table_exists(source_gpkg, "alpha")
        assert not table_exists(source_gpkg, "missing")
        assert geometry_column_of(source_gpkg, "alpha") == "geom"
        assert feature_count(source_gpkg, "alpha") >= 1

    def test_drop_table(self, source_gpkg: Path) -> None:
        """``drop_table`` removes a layer and its registrations; a missing table reports False."""
        assert drop_table(source_gpkg, "alpha")
        assert not table_exists(source_gpkg, "alpha")
        assert layer_names(source_gpkg) == []
        assert not drop_table(source_gpkg, "missing")

    def test_create_attribute_index(self, source_gpkg: Path) -> None:
        """``create_attribute_index`` makes a named index, is idempotent, and no-ops on []."""
        create_attribute_index(source_gpkg, "alpha", ["a"])
        create_attribute_index(source_gpkg, "alpha", ["a"])  # idempotent: no error on re-run
        create_attribute_index(source_gpkg, "alpha", [])  # no-op
        with sqlite3.connect(f"file:{source_gpkg.as_posix()}?mode=ro", uri=True) as conn:
            names = {
                name
                for (name,) in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'alpha'"
                )
            }
        assert "idx_alpha_a" in names

    def test_checkpoint_wal_folds_and_preserves_rows(self, source_gpkg: Path) -> None:
        """A WAL-mode gpkg is checkpointed: main file complete, sidecars gone, rows intact."""
        rows = feature_count(source_gpkg, "alpha")
        with sqlite3.connect(source_gpkg) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            # Touch a page so the WAL holds frames; gpkg_contents has no geometry triggers
            # (updating a feature table would fire r-tree triggers needing GDAL's ST_* funcs).
            conn.execute("UPDATE gpkg_contents SET identifier = identifier")
        # The connection above is still open (sqlite3's ``with`` manages only the transaction),
        # mirroring the pooled-reader situation; checkpoint through a second connection.
        assert checkpoint_wal(source_gpkg)
        conn.close()
        assert not source_gpkg.with_name(source_gpkg.name + "-wal").exists()
        assert not source_gpkg.with_name(source_gpkg.name + "-shm").exists()
        assert feature_count(source_gpkg, "alpha") == rows

    def test_checkpoint_wal_missing_and_unreadable_files(self, tmp_path: Path) -> None:
        """A missing file is a successful no-op; a non-database file reports False."""
        assert checkpoint_wal(tmp_path / "missing.gpkg")
        garbage = tmp_path / "garbage.gpkg"
        garbage.write_bytes(b"this is not a sqlite database")
        assert not checkpoint_wal(garbage)

    def test_wal_session_round_trip(self, source_gpkg: Path) -> None:
        """``wal_session`` holds WAL + a live sidecar; ``checkpoint_wal`` reverts losslessly."""
        rows = feature_count(source_gpkg, "alpha")
        wal_sidecar = source_gpkg.with_name(source_gpkg.name + "-wal")
        with wal_session(source_gpkg) as wal_ok:
            assert wal_ok
            # GDAL's nolock decision keys on this file existing, so the session must keep it
            # on disk for its whole duration — that is the point of holding the connection.
            assert wal_sidecar.exists()
            # Probe and close before leaving: an open reader would block the close-time
            # checkpoint (sqlite3's ``with`` manages transactions, never the connection).
            conn = sqlite3.connect(f"file:{source_gpkg.as_posix()}?mode=ro", uri=True)
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            conn.close()
            assert mode == "wal"
        assert checkpoint_wal(source_gpkg)
        assert not wal_sidecar.exists()
        assert not source_gpkg.with_name(source_gpkg.name + "-shm").exists()
        assert feature_count(source_gpkg, "alpha") == rows

    def test_wal_session_missing_and_unreadable_files(self, tmp_path: Path) -> None:
        """Both a missing file and a non-database file yield False (nothing was enabled)."""
        with wal_session(tmp_path / "missing.gpkg") as wal_ok:
            assert not wal_ok
        garbage = tmp_path / "garbage.gpkg"
        garbage.write_bytes(b"this is not a sqlite database")
        with wal_session(garbage) as wal_ok:
            assert not wal_ok


class TestStyleAndMetadataPayloads:
    """Tests for :func:`write_layer_style` and :func:`write_layer_metadata`."""

    def test_styles_rows_and_registration(self, source_gpkg: Path) -> None:
        """Style rows land with registration; the DDL is idempotent."""
        write_layer_style(
            source_gpkg,
            table="alpha",
            geometry_column="geom",
            style_name="default",
            qml="<qgis/>",
            sld="<sld/>",
            use_as_default=True,
            description="d",
        )
        write_layer_style(
            source_gpkg,
            table="alpha",
            geometry_column="geom",
            style_name="alt",
            qml="<qgis2/>",
        )
        with sqlite3.connect(source_gpkg) as conn:
            rows = conn.execute(
                "SELECT styleName, styleQML, styleSLD, useAsDefault, f_table_name,"
                " f_geometry_column FROM layer_styles ORDER BY id"
            ).fetchall()
            registrations = conn.execute(
                "SELECT COUNT(*) FROM gpkg_contents WHERE table_name = 'layer_styles'"
            ).fetchone()[0]
        assert rows == [
            ("default", "<qgis/>", "<sld/>", 1, "alpha", "geom"),
            ("alt", "<qgis2/>", "", 0, "alpha", "geom"),
        ]
        assert registrations == 1

    def test_metadata_rows_references_and_extensions(self, source_gpkg: Path) -> None:
        """Metadata rows, table references and extension registrations land once."""
        write_layer_metadata(source_gpkg, table="alpha", qmd_xml="<qgis-md/>")
        write_layer_metadata(source_gpkg, table="alpha", qmd_xml="<qgis-md-2/>")
        with sqlite3.connect(source_gpkg) as conn:
            metadata = conn.execute(
                "SELECT id, md_scope, md_standard_uri, mime_type, metadata"
                " FROM gpkg_metadata ORDER BY id"
            ).fetchall()
            references = conn.execute(
                "SELECT reference_scope, table_name, md_file_id"
                " FROM gpkg_metadata_reference ORDER BY md_file_id"
            ).fetchall()
            extensions = conn.execute(
                "SELECT COUNT(*) FROM gpkg_extensions WHERE extension_name = 'gpkg_metadata'"
            ).fetchone()[0]
        assert [m[1:] for m in metadata] == [
            ("dataset", "http://mrcc.com/qgis.dtd", "text/xml", "<qgis-md/>"),
            ("dataset", "http://mrcc.com/qgis.dtd", "text/xml", "<qgis-md-2/>"),
        ]
        assert references == [
            ("table", "alpha", metadata[0][0]),
            ("table", "alpha", metadata[1][0]),
        ]
        assert extensions == 2
