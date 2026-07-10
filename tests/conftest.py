"""
Global pytest configuration and shared fixtures.

This file provides test fixtures and hooks that are automatically discovered by pytest and
shared across all test subdirectories and modules.

Static configuration options should be set in ``pyproject.toml`` under ``[tool.pytest]``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from collections.abc import Generator


def pytest_addoption(parser: pytest.Parser, pluginmanager: pytest.PytestPluginManager) -> None:
    """
    Register an inert fallback for ``qgis_gui_enabled`` (pytest-qgis) when that plugin is
    inactive (e.g. under ``-p no:pytest_qgis -p no:pytest-qt`` in the QGIS-free job).

    ``qgis_gui_enabled`` is set unconditionally in ``pyproject.toml``; without this fallback,
    disabling pytest-qgis would make pytest reject the option as unknown. When pytest-qgis
    *is* active it registers its own option, so the fallback is skipped to avoid a
    duplicate-registration error. ``qt_api`` (pytest-qt) needs no such fallback: it is left
    unset in ``pyproject.toml`` so pytest-qt auto-detects the QGIS build's Qt binding.

    :param parser: The pytest command-line and ini-file parser.
    :param pluginmanager: The active plugin manager, used to detect the owning plugin.
    """
    if not pluginmanager.hasplugin("pytest_qgis"):
        parser.addini(
            "qgis_gui_enabled",
            "Inert fallback for pytest-qgis's option of the same name (plugin inactive).",
            default=True,
            type="bool",
        )


@pytest.fixture(autouse=True)
def block_qdialog_exec(request: pytest.FixtureRequest) -> Generator[None, None, None]:
    """
    Prevent any :class:`~QtWidgets.QDialog` from blocking the test process.

    :meth:`~QtWidgets.QDialog.exec` opens a modal dialog that waits for human input.
    Patching it ensures no test can accidentally block CI, regardless of how handlers or
    targets are configured.

    This fixture is automatically applied to all tests. It checks if the test is marked
    with ``qgis`` and only applies the patch if so, since otherwise the import of
    :class:`~QtWidgets.QDialog` would fail in non-QGIS test runs.
    """
    if request.node.get_closest_marker("qgis"):
        # Imported lazily so non-qgis runs need not have QGIS installed.
        from qgis.PyQt.QtWidgets import QDialog  # noqa: PLC0415

        with patch.object(QDialog, "exec", return_value=QDialog.DialogCode.Accepted):
            yield
    else:
        yield
