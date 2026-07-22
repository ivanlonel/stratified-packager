"""
Tests for :mod:`stratified_packager.toolbelt.sql`.

These helpers are pure standard-library SQL-text builders with no QGIS or GDAL dependency, so
the whole module runs without a QGIS/osgeo installation:

.. code-block:: bash

    pytest -p no:pytest_qgis -p no:pytest-qt tests/stratified_packager/toolbelt/test_sql.py
"""

from __future__ import annotations

import pytest

from stratified_packager.toolbelt.sql import (
    quote_identifier,
    safe_table_name,
    sqlite_where_error,
)


class TestSafeTableName:
    """Tests for :func:`safe_table_name`."""

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("gpkg_ar_fcu_sp", "_gpkg_ar_fcu_sp"),
            ("GPKG_X", "_GPKG_X"),
            ("sqlite_x", "_sqlite_x"),
            ("roads", "roads"),
            ("_gpkg_x", "_gpkg_x"),
        ],
        ids=["gpkg", "gpkg-uppercase", "sqlite", "plain", "already-prefixed"],
    )
    def test_reserved_prefixes_dodged(self, name: str, expected: str) -> None:
        """
        Reserved-prefixed names gain a leading ``_``; others (and ``_``-led) stay put.

        :param name: Candidate table name.
        :param expected: The safe form.
        """
        assert safe_table_name(name) == expected

    def test_idempotent(self) -> None:
        """Applying the guard twice changes nothing the second time."""
        assert safe_table_name(safe_table_name("gpkg_x")) == "_gpkg_x"


class TestQuoting:
    """Tests for :func:`quote_identifier`."""

    @pytest.mark.parametrize(
        ("name", "expected"),
        [("plain", '"plain"'), ('we"ird', '"we""ird"'), ("tã ble", '"tã ble"')],
        ids=["plain", "embedded-quote", "unicode-space"],
    )
    def test_quote_identifier(self, name: str, expected: str) -> None:
        """
        Identifiers are double-quoted with embedded quotes doubled.

        :param name: Raw identifier.
        :param expected: Quoted form.
        """
        assert quote_identifier(name) == expected


class TestSqliteWhereError:
    """Tests for :func:`sqlite_where_error`."""

    COLUMNS = ("cod_uf_2000", "cod_setor", "nome mun")

    @pytest.mark.parametrize(
        "where",
        [
            '"cod_setor" = 1',
            "cod_setor IS NULL OR cod_uf_2000 > 35",
            "\"nome mun\" LIKE 'S%'",
            "substr(cod_setor, 1, 2) = '35'",
            "CAST(cod_uf_2000 AS text) = '35'",
        ],
        ids=["quoted", "boolean", "quoted-space", "builtin-function", "standard-cast"],
    )
    def test_compilable_clauses_pass(self, where: str) -> None:
        """
        A clause SQLite can compile reports nothing.

        :param where: The candidate clause.
        """
        assert sqlite_where_error(self.COLUMNS, where) is None

    @pytest.mark.parametrize(
        ("where", "expected"),
        [
            ("cod_uf_2000::text = '35'", 'unrecognized token: ":"'),
            (
                "EXISTS (SELECT 1 FROM consultas_e_criticas.cafa_cnefe_prioritarios c"
                " WHERE c.cod_setor = cod_setor)",
                "no such table",
            ),
            ("lpad(cod_setor, 2, '0') = '35'", "no such function"),
            ("no_such_column = 1", "no such column"),
            ("cod_setor = ", "incomplete input"),
        ],
        ids=["postgres-cast", "schema-qualified", "postgres-function", "unknown-column", "syntax"],
    )
    def test_foreign_dialect_reported(self, where: str, expected: str) -> None:
        """
        A clause SQLite cannot compile reports its own message.

        These are the shapes a PostGIS subset string arrives in: the ``::`` cast is what made a
        real run log one ``Failed to prepare SQL`` per stratum.

        :param where: The candidate clause.
        :param expected: A fragment of SQLite's complaint.
        """
        message = sqlite_where_error(self.COLUMNS, where)
        assert message is not None
        assert expected in message

    def test_no_columns_cannot_be_probed(self) -> None:
        """Without columns there is no table to compile against, so nothing is claimed."""
        assert sqlite_where_error((), "anything = 1") is None

    def test_clause_is_never_executed(self) -> None:
        """``EXPLAIN`` compiles the clause; a clause that would error at runtime still passes."""
        assert sqlite_where_error(("a",), "1 / 0 = a") is None
