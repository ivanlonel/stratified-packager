"""
Tests for the Options settings page (:mod:`stratified_packager.gui.wdg_plugin_options_page`).

Usage from the repo root folder:

.. code-block:: bash

    pytest tests/stratified_packager/gui/test_wdg_plugin_options_page.py
"""
# pylint: disable=redefined-outer-name

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Never

import pytest

pytest.importorskip("qgis", reason="the page is a Qt widget backed by QGIS settings.")

# Imported only after the importorskip guard above confirms QGIS is available.
from qgis.core import QgsExpressionContextUtils, QgsProject
from qgis.PyQt.QtWidgets import QWidget

from stratified_packager.gui import (
    PluginOptionsPageWidget,
    PluginOptionsPageWidgetFactory,
)
from stratified_packager.gui.widgets import FieldSpec, concrete_value, default_fields
from stratified_packager.processing.params import VARIABLE_PREFIX
from stratified_packager.settings import StratifiedPackagerSettings

if TYPE_CHECKING:
    from collections.abc import Generator

pytestmark = pytest.mark.qgis
"""Marks the whole module as requiring a QGIS runtime."""

_SPECS: dict[str, FieldSpec] = {spec.key: spec for spec in default_fields()}


@pytest.fixture
def parent(
    qgis_new_project: Never,  # noqa: ARG001  # clean project per test
) -> Generator[QWidget, None, None]:
    """
    Yield a parent widget owning each page, resetting the plugin settings around the test.

    :param qgis_new_project: pytest-qgis fixture giving each test a clean project.
    :yield: The parent widget.
    """
    StratifiedPackagerSettings().reset_defaults()
    holder = QWidget()
    yield holder
    holder.deleteLater()
    StratifiedPackagerSettings().reset_defaults()


def test_load_reflects_current_setting(parent: QWidget) -> None:
    """The defaults editors are populated from the stored settings."""
    StratifiedPackagerSettings().compression_level = 1
    page = PluginOptionsPageWidget(parent)
    assert (
        concrete_value(_SPECS["compression_level"], page._default_editors["compression_level"])
        == "1"
    )


def test_apply_persists_defaults(parent: QWidget) -> None:
    """Applying writes every defaults editor back to the plugin settings."""
    page = PluginOptionsPageWidget(parent)
    page._default_editors["include_styles"].setChecked(False)  # type: ignore[attr-defined]
    page.apply()
    assert StratifiedPackagerSettings().include_styles is False


@pytest.mark.parametrize(
    ("checked", "expected_level"),
    [(True, logging.DEBUG), (False, logging.INFO)],
)
def test_apply_syncs_root_logger_level(
    parent: QWidget, checked: bool, expected_level: int
) -> None:
    """Applying syncs the live root logger level with the debug checkbox."""
    root_logger = logging.getLogger("stratified_packager")
    previous_level = root_logger.level
    try:
        page = PluginOptionsPageWidget(parent)
        page.opt_debug.setChecked(checked)
        page.apply()
        assert root_logger.level == expected_level
    finally:
        root_logger.setLevel(previous_level)


def test_override_note_marks_shadowed_settings(parent: QWidget) -> None:
    """A note appears for settings the active project shadows, and nowhere else."""
    QgsExpressionContextUtils.setProjectVariable(
        QgsProject.instance(), f"{VARIABLE_PREFIX}compression_level", "9"
    )
    page = PluginOptionsPageWidget(parent)
    assert "overridden" in page._default_notes["compression_level"].text()
    assert page._default_notes["include_styles"].text() == ""


def test_factory_requires_a_parent(parent: QWidget) -> None:
    """The factory returns a page only when a parent is supplied."""
    factory = PluginOptionsPageWidgetFactory()
    assert factory.createWidget(None) is None
    assert isinstance(factory.createWidget(parent), PluginOptionsPageWidget)
    assert factory.title()
