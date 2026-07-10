"""
Tests for the :mod:`stratified_packager.processing` provider.

Usage from the repo root folder:

.. code-block:: bash

    # for whole tests
    pytest tests/stratified_packager/processing/test_provider.py
    # for specific test
    pytest tests/stratified_packager/processing/test_provider.py::test_processing_provider
"""
# pylint: disable=redefined-outer-name

from __future__ import annotations

from typing import TYPE_CHECKING, Never
from unittest.mock import Mock

import pytest

pytest.importorskip("qgis", reason="QgsApplication and the provider require a running QGIS.")

# Imported only after the importorskip guard above confirms QGIS is available.
from qgis.core import (
    QgsApplication,
    QgsExpressionContextUtils,
    QgsProject,
    QgsVectorLayer,
)

from stratified_packager.processing.params import COMPRESSION_LEVEL, variable_name
from stratified_packager.processing.provider import StratifiedPackagerProvider

if TYPE_CHECKING:
    from collections.abc import Generator

pytestmark = pytest.mark.qgis
"""Marks the whole module as requiring a QGIS runtime."""


@pytest.fixture
def provider(
    qgis_processing: Never,  # noqa: ARG001  # only needed to initialise the Processing framework
) -> Generator[StratifiedPackagerProvider, None, None]:
    """
    Register the plugin's processing provider for the test, then unregister it.

    :param qgis_processing: pytest-qgis fixture that initialises the Processing framework.
    :yield: The freshly registered provider.
    """
    registry = QgsApplication.processingRegistry()
    assert registry is not None
    _provider = StratifiedPackagerProvider()
    registry.addProvider(_provider)
    yield _provider
    registry.removeProvider(_provider)


@pytest.fixture
def connected_provider(
    provider: StratifiedPackagerProvider,
    qgis_new_project: Never,  # noqa: ARG001  # start each test from an empty project
) -> Generator[StratifiedPackagerProvider, None, None]:
    """
    Yield a provider with its SPEC §5 default-refresh signal hookups connected.

    :param provider: The registered provider.
    :param qgis_new_project: pytest-qgis fixture giving each test a clean project.
    :yield: The provider with project signals connected.
    """
    provider.connect_project_signals()
    yield provider
    provider.disconnect_project_signals()


def test_processing_provider(provider: StratifiedPackagerProvider) -> None:
    """The registered provider must expose a non-empty name."""
    assert provider.name()


def test_connect_project_signals_is_idempotent(
    connected_provider: StratifiedPackagerProvider,
) -> None:
    """A second connect call is a no-op — the timer and connections are made once."""
    timer = connected_provider._refresh_timer
    connection_count = len(connected_provider._project_connections)
    connected_provider.connect_project_signals()
    assert connected_provider._refresh_timer is timer
    assert len(connected_provider._project_connections) == connection_count


def test_disconnect_project_signals_clears_state(
    connected_provider: StratifiedPackagerProvider,
) -> None:
    """Disconnecting drops the timer and every tracked connection."""
    connected_provider.disconnect_project_signals()
    assert connected_provider._refresh_timer is None
    assert connected_provider._project_connections == []
    assert connected_provider._layer_connections == {}
    # A second disconnect is harmless (reload safety).
    connected_provider.disconnect_project_signals()


def test_layer_property_change_filters_to_variable_keys(
    connected_provider: StratifiedPackagerProvider,
) -> None:
    """Only the variable-backing custom-property keys trigger a refresh (SPEC §5)."""
    schedule = Mock()
    connected_provider._schedule_refresh = schedule  # type: ignore[method-assign]  # spy
    connected_provider._on_layer_property_changed("variableNames")
    connected_provider._on_layer_property_changed("variableValues")
    connected_provider._on_layer_property_changed("opacity")  # unrelated → ignored
    assert schedule.call_count == 2


def test_layer_add_remove_updates_tracking(
    connected_provider: StratifiedPackagerProvider,
) -> None:
    """Adding/removing a layer connects/disconnects its property signal and refreshes."""
    schedule = Mock()
    connected_provider._schedule_refresh = schedule  # type: ignore[method-assign]  # spy
    project = QgsProject.instance()
    assert project is not None
    layer = QgsVectorLayer("Point?crs=EPSG:4326&field=id:integer", "tmp", "memory")
    assert layer.isValid()

    assert project.addMapLayer(layer) is not None
    layer_id = layer.id()
    assert layer_id in connected_provider._layer_connections

    project.removeMapLayer(layer_id)
    assert layer_id not in connected_provider._layer_connections
    # One refresh scheduled on add, one on remove.
    assert schedule.call_count == 2


def test_schedule_refresh_starts_the_coalescing_timer(
    connected_provider: StratifiedPackagerProvider,
) -> None:
    """``_schedule_refresh`` (re)starts the single-shot timer to coalesce signal bursts."""
    timer = connected_provider._refresh_timer
    assert timer is not None
    timer.stop()
    connected_provider._schedule_refresh()
    assert timer.isActive()


def test_refresh_repicks_project_variable_default(
    provider: StratifiedPackagerProvider,
    qgis_new_project: Never,  # noqa: ARG001  # clean project so the builtin default applies first
) -> None:
    """A refresh re-resolves dialog defaults from the current project variables (SPEC §5)."""
    project = QgsProject.instance()
    before = provider.algorithm("package")
    assert before is not None
    before_definition = before.parameterDefinition(COMPRESSION_LEVEL)
    assert before_definition is not None
    assert before_definition.defaultValue() == 6  # builtin

    # Project variable overrides the builtin; a refresh must pick it up.
    QgsExpressionContextUtils.setProjectVariable(project, variable_name(COMPRESSION_LEVEL), 1)
    provider._refresh_algorithms()

    after = provider.algorithm("package")
    assert after is not None
    after_definition = after.parameterDefinition(COMPRESSION_LEVEL)
    assert after_definition is not None
    assert after_definition.defaultValue() == 1
