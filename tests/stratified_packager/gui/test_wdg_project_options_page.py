"""
Tests for the Project Properties page (:mod:`stratified_packager.gui.wdg_project_options_page`).

Usage from the repo root folder:

.. code-block:: bash

    pytest tests/stratified_packager/gui/test_wdg_project_options_page.py
"""
# pylint: disable=redefined-outer-name

from __future__ import annotations

from typing import TYPE_CHECKING, Never

import pytest

pytest.importorskip("qgis", reason="the page is a Qt widget backed by a QGIS project.")

# Imported only after the importorskip guard above confirms QGIS is available.
from qgis.core import QgsExpressionContextUtils, QgsProject, QgsVectorLayer
from qgis.PyQt.QtWidgets import QWidget

from stratified_packager.gui import ProjectOptionsPageWidget, ProjectOptionsPageWidgetFactory
from stratified_packager.processing.params import VARIABLE_PREFIX
from stratified_packager.toolbelt.settings import ProjectVariables

if TYPE_CHECKING:
    from collections.abc import Generator

pytestmark = pytest.mark.qgis
"""Marks the whole module as requiring a QGIS runtime."""

_OVERWRITE_VAR = f"{VARIABLE_PREFIX}overwrite_mode"
_COMPRESSION_VAR = f"{VARIABLE_PREFIX}compression_level"
_STRAT_LAYER_VAR = f"{VARIABLE_PREFIX}stratification_layer"
_STRATUM_NAME_VAR = f"{VARIABLE_PREFIX}stratum_name_expression"


@pytest.fixture
def parent(
    qgis_new_project: Never,  # noqa: ARG001  # clean project per test
) -> Generator[QWidget, None, None]:
    """
    Yield a parent widget owning each constructed page (so Qt cleans it up).

    :param qgis_new_project: pytest-qgis fixture giving each test a clean project.
    :yield: The parent widget.
    """
    holder = QWidget()
    yield holder
    holder.deleteLater()


def test_load_reads_project_variables(parent: QWidget) -> None:
    """The page reflects existing project variables and leaves unset fields inheriting."""
    QgsExpressionContextUtils.setProjectVariable(QgsProject.instance(), _OVERWRITE_VAR, "error")
    page = ProjectOptionsPageWidget(parent)
    dumped = page.defaults_form.dump()
    assert dumped["overwrite_mode"] == "error"
    assert dumped["compression_level"] is None  # unset → inherit


def test_apply_writes_then_clears_variables(parent: QWidget) -> None:
    """Applying an explicit value writes a project variable; clearing removes it."""
    page = ProjectOptionsPageWidget(parent)
    page.defaults_form.set_value("compression_level", "3")
    page.apply()
    assert str(ProjectVariables(project=QgsProject.instance()).get(_COMPRESSION_VAR)) == "3"

    page.defaults_form.set_value("compression_level", None)  # back to inherit
    page.apply()
    assert ProjectVariables(project=QgsProject.instance()).get(_COMPRESSION_VAR) is None


def test_load_reads_project_only_variables(parent: QWidget) -> None:
    """The page reflects the two variable-only rows' project variables."""
    project = QgsProject.instance()
    assert project is not None
    layer = QgsVectorLayer("Point", "pts", "memory")
    assert project.addMapLayer(layer) is not None
    QgsExpressionContextUtils.setProjectVariable(project, _STRAT_LAYER_VAR, layer.id())
    QgsExpressionContextUtils.setProjectVariable(project, _STRATUM_NAME_VAR, '"name"')
    page = ProjectOptionsPageWidget(parent)
    dumped = page.defaults_form.dump()
    assert dumped["stratification_layer"] == layer.id()
    assert dumped["stratum_name_expression"] == '"name"'


def test_apply_writes_then_clears_project_only_variables(parent: QWidget) -> None:
    """Applying explicit values writes both variables; clearing removes them again."""
    project = QgsProject.instance()
    assert project is not None
    layer = QgsVectorLayer("Point", "pts", "memory")
    assert project.addMapLayer(layer) is not None
    page = ProjectOptionsPageWidget(parent)
    dumped = page.defaults_form.dump()
    assert dumped["stratification_layer"] is None  # fresh project: both rows unset
    assert dumped["stratum_name_expression"] is None

    page.defaults_form.set_value("stratification_layer", layer.id())
    page.defaults_form.set_value("stratum_name_expression", '"name"')
    page.apply()
    assert str(ProjectVariables(project=project).get(_STRAT_LAYER_VAR)) == layer.id()
    assert str(ProjectVariables(project=project).get(_STRATUM_NAME_VAR)) == '"name"'

    page.defaults_form.set_value("stratification_layer", None)
    page.defaults_form.set_value("stratum_name_expression", None)
    page.apply()
    assert ProjectVariables(project=project).get(_STRAT_LAYER_VAR) is None
    assert ProjectVariables(project=project).get(_STRATUM_NAME_VAR) is None


def test_stale_stratification_layer_id_clears_on_apply(parent: QWidget) -> None:
    """A variable naming a layer absent from the project loads unset and clears on apply."""
    project = QgsProject.instance()
    QgsExpressionContextUtils.setProjectVariable(project, _STRAT_LAYER_VAR, "no-such-layer")
    page = ProjectOptionsPageWidget(parent)
    assert page.defaults_form.dump()["stratification_layer"] is None
    page.apply()
    assert ProjectVariables(project=project).get(_STRAT_LAYER_VAR) is None


def test_factory_requires_a_parent(parent: QWidget) -> None:
    """The factory returns a page only when the dialog supplies a parent."""
    factory = ProjectOptionsPageWidgetFactory()
    assert factory.createWidget(None) is None
    assert isinstance(factory.createWidget(parent), ProjectOptionsPageWidget)
    assert factory.title()
