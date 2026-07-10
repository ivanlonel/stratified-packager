"""
Tests for :mod:`stratified_packager.toolbelt.sql`.

These helpers are pure standard-library SQL-text builders with no QGIS or GDAL dependency, so
the whole module runs without a QGIS/osgeo installation:

.. code-block:: bash

    pytest -p no:pytest_qgis -p no:pytest-qt tests/stratified_packager/toolbelt/test_sql.py
"""

from __future__ import annotations

import pytest

from stratified_packager.toolbelt.sql import quote_identifier, safe_table_name


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
