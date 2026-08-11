"""
Plugin-agnostic SQL string building for the SQLite/GeoPackage dialect.

Pure standard library: this module imports neither ``qgis`` nor ``osgeo`` (GDAL/OGR), so its
helpers stay usable from background threads, ``scripts/`` and osgeo-free tests. It owns the SQL
*text* concerns — identifier quoting and reserved-table-name guarding — while
:mod:`~.gpkg` owns the OGR and :mod:`sqlite3` work that consumes the quoting.
"""

from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__: list[str] = [
    "equality_operands",
    "quote_identifier",
    "safe_table_name",
    "sqlite_where_error",
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


_EQUALITY_OPERAND: Final = re.compile(r"(?:\w+\s*\.\s*)?(\w+)\s*=\s*(?:\w+\s*\.\s*)?(\w+)")
"""Both operands of an ``=`` comparison, with any ``table.``/``alias.`` qualifier dropped.

A word character never precedes the ``=`` of ``<=``, ``>=``, ``!=`` or ``<>``, so none of those
operators can match."""


def equality_operands(query: str, /) -> frozenset[str]:
    """
    Collect the identifiers an SQL query compares with ``=``, table qualifier dropped.

    Answers "which columns could an index serve here?" for a caller that intersects the result
    with a table's real column names. That intersection is what lets this stay a scan rather
    than a parser: an operand that is a literal, a function name or a table alias has no
    matching column and drops out, so over-matching costs nothing.

    :param query: SQL text, in any dialect.
    :return: The identifiers on both sides of every ``=`` whose two operands are bare words.
    """
    # ponytail: `=` between two bare operands, which is the join form an index actually serves
    # through a provider's constraint pushdown. USING (col), IN (...), function-wrapped columns
    # and comparisons against a quoted literal are not detected; widen the pattern if a query
    # needing them shows up.
    return frozenset(
        name for match in _EQUALITY_OPERAND.finditer(query) for name in match.groups()
    )


def sqlite_where_error(columns: Iterable[str], where: str, /) -> str | None:
    """
    Report why SQLite could not compile *where* as a ``WHERE`` clause over *columns*.

    A filter written for another provider's dialect (a PostgreSQL ``::`` cast, a
    schema-qualified table, a function SQLite lacks) is accepted by the layer API yet fails
    when the SQLite/GeoPackage backend prepares the statement — where the failure surfaces as
    a bare ``CPLError`` rather than a caller-visible one. Compiling it here answers the same
    question up front.

    The statement is compiled with ``EXPLAIN``, which resolves every table, column and function
    name **without executing anything**. Compilation runs against a throwaway in-memory table,
    so no GeoPackage is touched and the caller needs only the column names. Extension functions
    a real GeoPackage connection would register (SpatiaLite's, GDAL's) are absent here, so treat
    a complaint as advisory rather than proof the filter is unusable.

    :param columns: The column names the clause may reference.
    :param where: The candidate ``WHERE`` clause (no leading keyword).
    :return: SQLite's message, or :data:`None` when the clause compiles.
    """
    declarations = ", ".join(quote_identifier(name) for name in columns)
    if not declarations:
        return None
    # closing(), not the connection's own context manager: that one wraps a *transaction* and
    # leaves the handle open.
    with closing(sqlite3.connect(":memory:")) as connection:
        try:
            connection.execute(f"CREATE TABLE probe ({declarations})")
            connection.execute(f"EXPLAIN SELECT 1 FROM probe WHERE {where}")  # noqa: S608  # nosec B608  # compiling the caller's clause is the whole point; EXPLAIN never runs it
        except sqlite3.Error as err:
            return str(err)
    return None
