"""
Tests for the plugin entry point (:func:`stratified_packager.classFactory`).

``classFactory`` is QGIS's documented plugin loader: it configures the root plugin logger via
:meth:`QgisLoggerWrapper.setup` and returns a :class:`StratifiedPackager` bound to the
interface. The autouse :func:`clean_root_logger` fixture detaches that handler afterwards so
the process-global :mod:`logging` registry is not polluted across tests.

Usage from the repo root folder:

.. code-block:: bash

    pytest tests/stratified_packager/test___init__.py
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("qgis", reason="classFactory builds the QGIS plugin object and its logger.")

# Imported only after the importorskip guard above confirms QGIS is available.
import stratified_packager
from stratified_packager.main import StratifiedPackager
from stratified_packager.settings import StratifiedPackagerSettings
from stratified_packager.toolbelt.logging import QgisLoggerWrapper

if TYPE_CHECKING:
    from collections.abc import Generator

    from qgis.gui import QgisInterface

pytestmark = pytest.mark.qgis
"""Marks the whole module as requiring a QGIS runtime."""

_ROOT_LOGGER_NAME = "stratified_packager"
"""Root plugin logger name ``classFactory`` configures via :meth:`QgisLoggerWrapper.setup`."""


@pytest.fixture(autouse=True)
def clean_root_logger() -> Generator[None, None, None]:
    """
    Detach the handler ``classFactory`` attaches, keeping the global logging registry clean.

    :yield: Nothing; cleanup runs after each test.
    """
    yield
    QgisLoggerWrapper.teardown(_ROOT_LOGGER_NAME)
    prefix = _ROOT_LOGGER_NAME + "."
    for name in list(logging.Logger.manager.loggerDict):
        if name == _ROOT_LOGGER_NAME or name.startswith(prefix):
            logger = logging.getLogger(name)
            for handler in logger.handlers[:]:
                logger.removeHandler(handler)


def test_class_factory_returns_plugin(qgis_iface: QgisInterface) -> None:
    """``classFactory`` builds the plugin object bound to the given interface."""
    plugin = stratified_packager.classFactory(qgis_iface)
    assert isinstance(plugin, StratifiedPackager)
    assert plugin.iface is qgis_iface


def test_class_factory_configures_root_logger(qgis_iface: QgisInterface) -> None:
    """``classFactory`` configures the root plugin logger with a handler (via ``setup``)."""
    stratified_packager.classFactory(qgis_iface)
    assert logging.getLogger(_ROOT_LOGGER_NAME).handlers


@pytest.mark.parametrize(
    ("debug_mode", "expected_level"),
    [(True, logging.DEBUG), (False, logging.INFO)],
)
def test_class_factory_sets_level_from_debug_mode(
    qgis_iface: QgisInterface, debug_mode: bool, expected_level: int
) -> None:
    """``classFactory`` sets the root logger level from the ``debug_mode`` setting."""
    settings = StratifiedPackagerSettings()
    settings.debug_mode = debug_mode
    try:
        stratified_packager.classFactory(qgis_iface)
        assert logging.getLogger(_ROOT_LOGGER_NAME).level == expected_level
    finally:
        settings.reset_defaults()
