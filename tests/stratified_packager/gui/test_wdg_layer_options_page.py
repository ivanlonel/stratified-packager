"""
Tests for the per-layer variables page (:mod:`stratified_packager.gui.wdg_layer_options_page`).

Usage from the repo root folder:

.. code-block:: bash

    pytest tests/stratified_packager/gui/test_wdg_layer_options_page.py
"""
# pylint: disable=redefined-outer-name

from __future__ import annotations

from typing import Never

import pytest

pytest.importorskip("qgis", reason="the page is a Qt widget backed by a QGIS layer.")

# Imported only after the importorskip guard above confirms QGIS is available.
from qgis.core import QgsExpressionContextUtils, QgsVectorLayer

from stratified_packager.gui import LayerOptionsPageWidget, LayerOptionsPageWidgetFactory
from stratified_packager.processing.params import (
    LAYER_VAR_EXCLUDE,
    LAYER_VAR_MATCHING_METHOD,
    LAYER_VAR_MATERIALIZE_VIRTUAL,
    LAYER_VAR_STAGE,
    VARIABLE_PREFIX,
)
from stratified_packager.toolbelt.settings import LayerVariables

pytestmark = pytest.mark.qgis
"""Marks the whole module as requiring a QGIS runtime."""

# The form keys editors/dump by the bare suffix; the layer variables keep their full names.
_EXCLUDE = LAYER_VAR_EXCLUDE.removeprefix(VARIABLE_PREFIX)
_METHOD = LAYER_VAR_MATCHING_METHOD.removeprefix(VARIABLE_PREFIX)
_STAGE = LAYER_VAR_STAGE.removeprefix(VARIABLE_PREFIX)
_MATERIALIZE = LAYER_VAR_MATERIALIZE_VIRTUAL.removeprefix(VARIABLE_PREFIX)


@pytest.fixture
def layer(
    qgis_new_project: Never,  # noqa: ARG001  # isolate each test
) -> QgsVectorLayer:
    """
    Build a standalone in-memory vector layer to configure.

    :param qgis_new_project: pytest-qgis fixture giving each test a clean project.
    :return: The vector layer.
    """
    vector = QgsVectorLayer("Point?crs=EPSG:4326&field=id:integer", "tmp", "memory")
    assert vector.isValid()
    return vector


def test_load_reads_layer_variables(layer: QgsVectorLayer) -> None:
    """The page reflects existing layer variables and inherits the rest."""
    QgsExpressionContextUtils.setLayerVariable(layer, LAYER_VAR_EXCLUDE, "true")
    page = LayerOptionsPageWidget(layer)
    dumped = page.variables_form.dump()
    assert dumped[_EXCLUDE] == "true"
    assert dumped[_METHOD] is None  # unset → inherit


def test_apply_writes_then_clears_variables(layer: QgsVectorLayer) -> None:
    """Applying an explicit value writes a layer variable; clearing removes it."""
    page = LayerOptionsPageWidget(layer)
    page.variables_form.set_value(_METHOD, "spatial")
    page.apply()
    assert LayerVariables(layer).get(LAYER_VAR_MATCHING_METHOD) == "spatial"

    page.variables_form.set_value(_METHOD, None)  # inherit again
    page.apply()
    assert LayerVariables(layer).get(LAYER_VAR_MATCHING_METHOD) is None


def test_stage_keeps_force_off_while_two_state_bool_clears(layer: QgsVectorLayer) -> None:
    """Tri-state ``stage`` keeps an explicit false; a 2-state bool's false collapses to unset."""
    page = LayerOptionsPageWidget(layer)
    page.variables_form.set_value(_STAGE, "false")  # force-off
    page.variables_form.set_value(_EXCLUDE, "false")
    dumped = page.variables_form.dump()
    assert dumped[_STAGE] == "false"  # tri-state combo preserves force-off
    assert dumped[_EXCLUDE] is None  # 2-state checkbox: false = unchecked = unset


@pytest.mark.parametrize(
    ("uri", "provider", "expected_enabled"),
    [
        ("Point?crs=EPSG:4326&field=id:integer", "memory", False),
        ("?query=SELECT 1 AS id", "virtual", True),
    ],
)
def test_materialize_virtual_editable_only_for_virtual_layers(
    qgis_new_project: Never,  # noqa: ARG001  # isolate each test
    uri: str,
    provider: str,
    expected_enabled: bool,
) -> None:
    """``materialize_virtual_layer`` is editable only for virtual layers (mirrors the table)."""
    vector = QgsVectorLayer(uri, "tmp", provider)
    assert vector.isValid()
    page = LayerOptionsPageWidget(vector)
    assert page.variables_form._editors[_MATERIALIZE].isEnabled() is expected_enabled


def test_factory_supports_vector_layers(layer: QgsVectorLayer) -> None:
    """The factory offers the page for vector layers and builds it."""
    factory = LayerOptionsPageWidgetFactory()
    assert factory.supportsLayer(layer) is True
    widget = factory.createWidget(layer, None)
    assert isinstance(widget, LayerOptionsPageWidget)
