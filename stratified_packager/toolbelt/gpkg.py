"""
Plugin-agnostic GeoPackage helpers: introspection, table dropping, style/metadata SQL.

Identifier and value quoting lives in the pure-stdlib :mod:`~.sql`; this module consumes
it and adds the GDAL/OGR and :mod:`sqlite3` work.

DO NOT import from the ``qgis`` package in this module (it must stay usable from background
threads and ``scripts/``); ``osgeo`` (GDAL/OGR), :mod:`sqlite3` and the standard library only.

Style and metadata payloads are written by raw SQL exactly the way QGIS writes them; a table
is dropped through OGR (``DeleteLayer`` also cleans the gpkg system tables and the r-tree).
"""

from __future__ import annotations

import contextlib
import sqlite3
from typing import TYPE_CHECKING, Final

from osgeo import gdal

from .sql import quote_identifier

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from pathlib import Path

__all__: list[str] = [
    "checkpoint_wal",
    "create_attribute_index",
    "drop_table",
    "feature_count",
    "geometry_column_of",
    "layer_names",
    "table_exists",
    "wal_session",
    "write_layer_metadata",
    "write_layer_style",
]


# ---------------------------------------------------------------------------
# Introspection helpers
# ---------------------------------------------------------------------------


def _connect_readonly(gpkg: Path) -> sqlite3.Connection:
    """
    Open a read-only connection (a plain ``connect`` would create a missing file).

    :param gpkg: GeoPackage path (must exist).
    :return: The read-only connection.
    """
    return sqlite3.connect(f"file:{gpkg.as_posix()}?mode=ro", uri=True)


def layer_names(gpkg: Path, /) -> list[str]:
    """
    List the feature tables registered in a GeoPackage.

    :param gpkg: GeoPackage path.
    :return: ``gpkg_contents`` table names with ``data_type = 'features'``, sorted;
        empty when the file does not exist.
    """
    if not gpkg.is_file():
        return []
    with contextlib.closing(_connect_readonly(gpkg)) as conn:
        rows = conn.execute(
            "SELECT table_name FROM gpkg_contents WHERE data_type = 'features' ORDER BY table_name"
        ).fetchall()
    return [name for (name,) in rows]


def table_exists(gpkg: Path, table: str, /) -> bool:
    """
    Report whether *table* exists in the GeoPackage.

    :param gpkg: GeoPackage path (a missing file reports :data:`False`).
    :param table: Table name.
    :return: :data:`True` if present in ``sqlite_master``.
    """
    if not gpkg.is_file():
        return False
    with contextlib.closing(_connect_readonly(gpkg)) as conn:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
    return row is not None


def geometry_column_of(gpkg: Path, table: str, /) -> str:
    """
    Return the geometry column name of *table*, or ``''`` for attribute-only tables.

    :param gpkg: GeoPackage path.
    :param table: Table name.
    :return: The ``gpkg_geometry_columns`` entry, or an empty string.
    """
    if not gpkg.is_file():
        return ""
    with contextlib.closing(_connect_readonly(gpkg)) as conn:
        row = conn.execute(
            "SELECT column_name FROM gpkg_geometry_columns WHERE table_name = ?", (table,)
        ).fetchone()
    return row[0] if row else ""


def drop_table(gpkg: Path, table: str, /) -> bool:
    """
    Drop a feature table from the GeoPackage, including its system-table registrations.

    Delegates to OGR's ``DeleteLayer``, which cleans ``gpkg_contents``,
    ``gpkg_geometry_columns``, the r-tree index tables and the OGR feature-count
    side table along with the table itself.

    :param gpkg: GeoPackage path (the caller must be its only writer).
    :param table: Table name.
    :return: :data:`True` if the table existed and was dropped.
    """
    with gdal.ExceptionMgr(useExceptions=True):
        dataset = gdal.OpenEx(str(gpkg), gdal.OF_VECTOR | gdal.OF_UPDATE)
        try:
            for index in range(dataset.GetLayerCount()):
                layer = dataset.GetLayer(index)
                if layer is not None and layer.GetName() == table:
                    dataset.DeleteLayer(index)
                    return True
        finally:
            dataset = None  # closes the dataset handle
    return False


def feature_count(gpkg: Path, table: str, /) -> int:
    """
    Count the rows of *table*.

    :param gpkg: GeoPackage path (must exist).
    :param table: Table name (must exist).
    :return: The row count.
    """
    with contextlib.closing(_connect_readonly(gpkg)) as conn:
        # S608: the table name is the only interpolation and it passes quote_identifier.
        query = f"SELECT COUNT(*) FROM {quote_identifier(table)}"  # noqa: S608
        return int(conn.execute(query).fetchone()[0])


def create_attribute_index(gpkg: Path, table: str, columns: Sequence[str], /) -> None:
    """
    Create an attribute index on *columns* of *table* (idempotent).

    Speeds the per-stratum key filter (``key_fields IN (...)``) the GeoPackage provider pushes
    down when a staged copy is read once per stratum. A single multi-column index serves both
    the single-field ``IN`` and the composite-key equality forms. A no-op when *columns* is
    empty or the index already exists.

    :param gpkg: GeoPackage path (the caller must be its only writer).
    :param table: Feature table to index.
    :param columns: The columns to index, in query order (empty = no-op).
    """
    if not columns:
        return
    name = f"idx_{table}_{'_'.join(columns)}"
    cols = ", ".join(quote_identifier(column) for column in columns)
    with contextlib.closing(sqlite3.connect(gpkg)) as conn:
        # Every interpolated identifier passes quote_identifier (the index name, the table and
        # each column), so the statement carries no untrusted SQL text.
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS {quote_identifier(name)} "
            f"ON {quote_identifier(table)} ({cols})"
        )
        conn.commit()


@contextlib.contextmanager
def wal_session(gpkg: Path, /) -> Iterator[bool]:
    """
    Hold the database in WAL journal mode, with a live ``-wal`` sidecar, for the block.

    A reader that opens a SQLite file in *nolock* mode (as QGIS's OGR connection pool does for
    read-only GeoPackage opens) fails mid-statement when another connection materializes the
    ``-wal`` sidecar afterwards — but an open against a file whose sidecar *already exists* is
    detected and cleanly retried without nolock. Merely flipping the journal mode is not
    enough: closing the flipping connection auto-checkpoints and removes the sidecar again, so
    later opens still go nolock. This context manager therefore switches to
    WAL, materializes the sidecar with a no-op ``gpkg_contents`` touch (a plain table: no
    r-tree triggers fire), and keeps its connection open so the sidecar outlives every open
    made inside the block; :func:`checkpoint_wal` reverts the file before it is copied or
    zipped.

    :param gpkg: GeoPackage path.
    :yield: Whether the file is now held in WAL journal mode (``False`` = missing file or a
        SQLite error; the caller may proceed — the session is log-hygiene, not correctness).
    """
    if not gpkg.is_file():
        yield False
        return
    try:
        conn = sqlite3.connect(gpkg)
    except sqlite3.Error:
        yield False
        return
    try:
        try:
            mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            conn.execute("UPDATE gpkg_contents SET identifier = identifier")
            conn.commit()
        except sqlite3.Error:
            yield False
            return
        yield str(mode).lower() == "wal"
    finally:
        conn.close()


def checkpoint_wal(gpkg: Path, /) -> bool:
    """
    Fold any WAL content into the main database file (pre-copy safety).

    A GeoPackage that some connection switched to WAL journal mode (e.g. QGIS/OGR reads)
    carries ``-wal``/``-shm`` sidecars; copying or zipping only the main file would then ship
    a stale database. ``wal_checkpoint(TRUNCATE)`` moves every committed frame into the main
    file and zeroes the WAL, after which the main file is complete on its own. The follow-up
    ``journal_mode=DELETE`` tidies the sidecars away entirely but needs exclusive access, so
    its failure (another connection still holds the file) is ignored — a fully checkpointed
    WAL-mode file without its sidecars is still a valid, complete database.

    :param gpkg: GeoPackage path (a missing file is a successful no-op).
    :return: Whether the checkpoint completed (``False`` = busy/locked; the main file may be
        stale and the caller should surface it).
    """
    if not gpkg.is_file():
        return True
    try:
        with contextlib.closing(sqlite3.connect(gpkg)) as conn:
            busy = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]
            with contextlib.suppress(sqlite3.Error):
                conn.execute("PRAGMA journal_mode=DELETE")
    except sqlite3.Error:
        return False
    return int(busy) == 0


# ---------------------------------------------------------------------------
# Styles & metadata payload SQL
# ---------------------------------------------------------------------------

_LAYER_STYLES_DDL: Final = """
CREATE TABLE IF NOT EXISTS "layer_styles" (
  "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
  "f_table_catalog" TEXT(256),
  "f_table_schema" TEXT(256),
  "f_table_name" TEXT(256),
  "f_geometry_column" TEXT(256),
  "styleName" TEXT(30),
  "styleQML" TEXT,
  "styleSLD" TEXT,
  "useAsDefault" BOOLEAN,
  "description" TEXT,
  "owner" TEXT(30),
  "ui" TEXT(30),
  "update_time" DATETIME DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
)
"""
"""``layer_styles`` DDL exactly as QGIS creates it (captured from a 4.0.3-written gpkg)."""

_GPKG_METADATA_DDL: Final = """
CREATE TABLE IF NOT EXISTS gpkg_metadata (
  id INTEGER CONSTRAINT m_pk PRIMARY KEY ASC NOT NULL,
  md_scope TEXT NOT NULL DEFAULT 'dataset',
  md_standard_uri TEXT NOT NULL,
  mime_type TEXT NOT NULL DEFAULT 'text/xml',
  metadata TEXT NOT NULL DEFAULT ''
)
"""
"""``gpkg_metadata`` DDL per the GeoPackage metadata extension."""

_GPKG_METADATA_REFERENCE_DDL: Final = """
CREATE TABLE IF NOT EXISTS gpkg_metadata_reference (
  reference_scope TEXT NOT NULL,
  table_name TEXT,
  column_name TEXT,
  row_id_value INTEGER,
  timestamp DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  md_file_id INTEGER NOT NULL,
  md_parent_id INTEGER,
  CONSTRAINT crmr_mfi_fk FOREIGN KEY (md_file_id) REFERENCES gpkg_metadata(id),
  CONSTRAINT crmr_mpi_fk FOREIGN KEY (md_parent_id) REFERENCES gpkg_metadata(id)
)
"""
"""``gpkg_metadata_reference`` DDL per the GeoPackage metadata extension."""

_QGIS_METADATA_STANDARD_URI: Final = "http://mrcc.com/qgis.dtd"
"""``md_standard_uri`` QGIS stamps on its layer-metadata rows."""


def write_layer_style(
    gpkg: Path,
    /,
    *,
    table: str,
    geometry_column: str,
    style_name: str,
    qml: str,
    sld: str = "",
    use_as_default: bool = False,
    description: str = "",
) -> None:
    """
    Insert one named style row into the GeoPackage's ``layer_styles`` table.

    Creates the table and its ``gpkg_contents`` registration (data type ``attributes``)
    when missing, mirroring how QGIS itself stores styles.

    :param gpkg: GeoPackage path (the caller must be its only writer).
    :param table: Feature table the style applies to.
    :param geometry_column: The table's geometry column (empty for attribute tables).
    :param style_name: Style name shown in QGIS' style manager.
    :param qml: Full QML document.
    :param sld: Optional SLD document (QGIS fills both; SLD is best-effort here).
    :param use_as_default: Whether QGIS should load this style by default.
    :param description: Optional style description.
    """
    with contextlib.closing(sqlite3.connect(gpkg)) as conn:
        conn.execute(_LAYER_STYLES_DDL)
        conn.execute(
            "INSERT INTO gpkg_contents (table_name, data_type, identifier)"
            " SELECT 'layer_styles', 'attributes', 'layer_styles'"
            " WHERE NOT EXISTS ("
            "   SELECT 1 FROM gpkg_contents WHERE table_name = 'layer_styles'"
            " )"
        )
        conn.execute(
            "INSERT INTO layer_styles (f_table_catalog, f_table_schema, f_table_name,"
            " f_geometry_column, styleName, styleQML, styleSLD, useAsDefault,"
            " description, owner)"
            " VALUES ('', '', ?, ?, ?, ?, ?, ?, ?, '')",
            (table, geometry_column, style_name, qml, sld, int(use_as_default), description),
        )
        conn.commit()


def write_layer_metadata(gpkg: Path, /, *, table: str, qmd_xml: str) -> None:
    """
    Insert a QGIS layer-metadata (QMD) document for *table* into the GeoPackage.

    Creates the ``gpkg_metadata`` / ``gpkg_metadata_reference`` tables and their
    ``gpkg_extensions`` registrations when missing, then inserts the metadata row
    (scope ``dataset``, QGIS standard URI) and its ``table``-scoped reference,
    mirroring how QGIS itself stores metadata.

    :param gpkg: GeoPackage path (the caller must be its only writer).
    :param table: Feature table the metadata describes.
    :param qmd_xml: The QMD XML document.
    """
    with contextlib.closing(sqlite3.connect(gpkg)) as conn:
        conn.execute(_GPKG_METADATA_DDL)
        conn.execute(_GPKG_METADATA_REFERENCE_DDL)
        for metadata_table in ("gpkg_metadata", "gpkg_metadata_reference"):
            conn.execute(
                "INSERT INTO gpkg_extensions"
                " (table_name, column_name, extension_name, definition, scope)"
                " SELECT ?, NULL, 'gpkg_metadata',"
                "  'http://www.geopackage.org/spec120/#extension_metadata', 'read-write'"
                " WHERE NOT EXISTS ("
                "   SELECT 1 FROM gpkg_extensions"
                "   WHERE table_name = ? AND extension_name = 'gpkg_metadata'"
                " )",
                (metadata_table, metadata_table),
            )
        cursor = conn.execute(
            "INSERT INTO gpkg_metadata (md_scope, md_standard_uri, mime_type, metadata)"
            " VALUES ('dataset', ?, 'text/xml', ?)",
            (_QGIS_METADATA_STANDARD_URI, qmd_xml),
        )
        conn.execute(
            "INSERT INTO gpkg_metadata_reference"
            " (reference_scope, table_name, md_file_id)"
            " VALUES ('table', ?, ?)",
            (table, cursor.lastrowid),
        )
        conn.commit()
