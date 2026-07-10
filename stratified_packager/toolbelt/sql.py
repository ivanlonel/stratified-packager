"""
Plugin-agnostic SQL string building for the SQLite/GeoPackage dialect.

Pure standard library: this module imports neither ``qgis`` nor ``osgeo`` (GDAL/OGR), so its
helpers stay usable from background threads, ``scripts/`` and osgeo-free tests. It owns the SQL
*text* concerns — identifier quoting and reserved-table-name guarding — while
:mod:`~.gpkg` owns the OGR and :mod:`sqlite3` work that consumes the quoting.
"""

from __future__ import annotations

from typing import Final

__all__: list[str] = [
    "quote_identifier",
    "safe_table_name",
]

_RESERVED_TABLE_PREFIXES: Final = ("gpkg", "sqlite_")
"""Reserved table-name prefixes: OGR rejects ``gpkg``; SQLite reserves ``sqlite_``."""


def safe_table_name(name: str, /) -> str:
    """
    Prefix ``_`` to dodge GeoPackage/SQLite reserved table-name prefixes.

    OGR refuses to create a GeoPackage layer whose name begins with ``gpkg``, and SQLite
    reserves the ``sqlite_`` prefix for its own tables. A name that begins with either
    (case-insensitively, since both dialects fold table-name case) gets a leading ``_``;
    every other name is returned unchanged. Idempotent: ``_gpkg…`` no longer matches.

    :param name: A candidate (already-sanitized) table name.
    :return: The name, with a leading ``_`` when it would otherwise be reserved.
    """
    # ponytail: covers the two prefixes that actually reject a CREATE; add more if OGR grows them.
    return f"_{name}" if name.lower().startswith(_RESERVED_TABLE_PREFIXES) else name


def quote_identifier(name: str, /) -> str:
    """
    Quote an SQL identifier (table or column name) with double quotes.

    :param name: The raw identifier.
    :return: The double-quoted identifier with embedded quotes doubled.
    """
    escaped = name.replace('"', '""')
    return f'"{escaped}"'
