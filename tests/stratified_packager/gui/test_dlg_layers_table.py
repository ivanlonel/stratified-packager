"""
Tests for the all-layers table dialog (:mod:`stratified_packager.gui.dlg_layers_table`).

Usage from the repo root folder:

.. code-block:: bash

    pytest tests/stratified_packager/gui/test_dlg_layers_table.py
"""
# pylint: disable=redefined-outer-name

from __future__ import annotations

from typing import TYPE_CHECKING, Never

import pytest

pytest.importorskip("qgis", reason="the dialog is a Qt widget backed by a QGIS project.")

# Imported only after the importorskip guard above confirms QGIS is available.
from qgis.core import (
    Qgis,
    QgsAnnotationLayer,
    QgsExpressionContextUtils,
    QgsProject,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import Qt

from stratified_packager.gui import LayersTableDialog, ProjectOptionsPageWidgetFactory
from stratified_packager.gui.widgets import OverrideCheckBox, OverridePredicateCombo
from stratified_packager.processing.params import (
    LAYER_VAR_EXCLUDE,
    LAYER_VAR_MATCHING_METHOD,
    LAYER_VAR_SPATIAL_PREDICATE,
    LAYER_VAR_WARM_MARKED,
    VARIABLE_PREFIX,
)
from stratified_packager.toolbelt.settings import LayerVariables

if TYPE_CHECKING:
    from qgis.gui import QgisInterface
    from qgis.PyQt.QtWidgets import QTableWidgetItem

pytestmark = pytest.mark.qgis
"""Marks the whole module as requiring a QGIS runtime."""

# The dialog keys editors/columns by the bare suffix; layer variables keep their full names.
_EXCLUDE = LAYER_VAR_EXCLUDE.removeprefix(VARIABLE_PREFIX)
_METHOD = LAYER_VAR_MATCHING_METHOD.removeprefix(VARIABLE_PREFIX)
_PREDICATE = LAYER_VAR_SPATIAL_PREDICATE.removeprefix(VARIABLE_PREFIX)
_WARM = LAYER_VAR_WARM_MARKED.removeprefix(VARIABLE_PREFIX)


@pytest.fixture
def layers(
    qgis_new_project: Never,  # noqa: ARG001  # isolate each test
) -> list[QgsVectorLayer]:
    """
    Build two registered in-memory vector layers.

    :param qgis_new_project: pytest-qgis fixture giving each test a clean project.
    :return: The registered layers.
    """
    project = QgsProject.instance()
    assert project is not None
    created: list[QgsVectorLayer] = []
    for name in ("alpha", "beta"):
        vector = QgsVectorLayer("Point?crs=EPSG:4326&field=id:integer", name, "memory")
        assert vector.isValid()
        assert project.addMapLayer(vector) is not None
        created.append(vector)
    return created


def test_table_has_a_row_per_layer(
    layers: list[QgsVectorLayer], qgis_iface: QgisInterface
) -> None:
    """The dialog renders one row per project layer and a column per §4 variable."""
    dialog = LayersTableDialog(qgis_iface)
    assert dialog.table.rowCount() == len(layers)
    # Layer name + 8 variable columns + a Properties button.
    assert dialog.table.columnCount() == 10


def test_load_reflects_layer_variable(
    layers: list[QgsVectorLayer], qgis_iface: QgisInterface
) -> None:
    """An existing layer variable is shown in its cell editor."""
    alpha = layers[0]
    QgsExpressionContextUtils.setLayerVariable(alpha, LAYER_VAR_WARM_MARKED, "true")
    dialog = LayersTableDialog(qgis_iface)
    editor = dialog._editors[(alpha.id(), _WARM)]
    assert editor.scope_value() == "true"


def test_apply_writes_then_clears(layers: list[QgsVectorLayer], qgis_iface: QgisInterface) -> None:
    """Editing a cell and applying writes the variable; clearing removes it."""
    beta = layers[1]
    dialog = LayersTableDialog(qgis_iface)
    dialog._editors[(beta.id(), _METHOD)].set_scope_value("spatial")
    dialog.apply_changes()
    assert LayerVariables(beta).get(LAYER_VAR_MATCHING_METHOD) == "spatial"

    dialog._editors[(beta.id(), _METHOD)].set_scope_value(None)
    dialog.apply_changes()
    assert LayerVariables(beta).get(LAYER_VAR_MATCHING_METHOD) is None


def test_two_state_bool_column_uses_checkbox(
    layers: list[QgsVectorLayer], qgis_iface: QgisInterface
) -> None:
    """A 2-state bool column (exclude) renders as a checkbox, unchecked = unset (SPEC §19)."""
    dialog = LayersTableDialog(qgis_iface)
    editor = dialog._editors[(layers[0].id(), _EXCLUDE)]
    assert isinstance(editor, OverrideCheckBox)
    assert editor.scope_value() is None  # unchecked by default = unset


def test_predicate_column_fits_de9im_placeholder(
    layers: list[QgsVectorLayer], qgis_iface: QgisInterface
) -> None:
    """The Spatial predicate(s) column is widened to fit the DE-9IM placeholder row (SPEC §19)."""
    dialog = LayersTableDialog(qgis_iface)
    editor = dialog._editors[(layers[0].id(), _PREDICATE)]
    assert isinstance(editor, OverridePredicateCombo)
    column = dialog._column_keys.index(_PREDICATE) + 1
    assert dialog.table.columnWidth(column) >= editor.de9im_row_width_hint()


def test_dialog_width_fits_all_columns(
    layers: list[QgsVectorLayer], qgis_iface: QgisInterface
) -> None:
    """The dialog opens wide enough to span every column, unless capped at the screen width."""
    dialog = LayersTableDialog(qgis_iface)
    assert dialog.table.rowCount() == len(layers)
    columns_width = sum(
        dialog.table.columnWidth(column) for column in range(dialog.table.columnCount())
    )
    screen = dialog.screen()
    capped = screen is not None and dialog.width() >= screen.availableGeometry().width()
    assert capped or dialog.width() >= columns_width


def test_open_project_defaults_targets_plugin_tab(
    qgis_new_project: Never,  # noqa: ARG001  # isolate each test
    qgis_iface: QgisInterface,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    The Project-defaults deep-link must pass the factory ``title()`` as ``currentPage``.

    ``QgsProjectProperties`` renames each factory page's ``objectName`` to the factory ``title()``,
    so matching on the ``.ui`` objectName silently lands on the last-active tab instead.
    """
    dialog = LayersTableDialog(qgis_iface)
    captured: dict[str, object] = {}
    # raising=False: the mock iface need not predeclare the slot for the patch to take.
    monkeypatch.setattr(
        dialog._iface, "showProjectPropertiesDialog", captured.update, raising=False
    )
    dialog._open_project_defaults()
    assert captured["currentPage"] == ProjectOptionsPageWidgetFactory().title()


def _name_cells(dialog: LayersTableDialog) -> list[QTableWidgetItem]:
    """
    Return the Layer-name (column 0) item of every row, asserting each exists.

    :param dialog: The dialog whose table to read.
    :return: One :class:`QTableWidgetItem` per row, in current (sorted) row order.
    """
    cells: list[QTableWidgetItem] = []
    for row in range(dialog.table.rowCount()):
        item = dialog.table.item(row, 0)
        assert item is not None
        cells.append(item)
    return cells


def test_rows_follow_tree_order_and_sorting_is_opt_in(
    layers: list[QgsVectorLayer], qgis_iface: QgisInterface
) -> None:
    """Rows default to layer-tree order; sorting is enabled but not applied until requested."""
    project = QgsProject.instance()
    assert project is not None
    root = project.layerTreeRoot()
    assert root is not None
    expected = [
        layer.name()
        for node in root.findLayers()
        if (layer := node.layer()) is not None and layer.type() != Qgis.LayerType.Plugin
    ]
    dialog = LayersTableDialog(qgis_iface)
    assert dialog.table.rowCount() == len(layers)
    assert [item.text() for item in _name_cells(dialog)] == expected
    header = dialog.table.horizontalHeader()
    assert header is not None
    assert header.sortIndicatorSection() == -1  # default view is unsorted (layer-tree order)


def test_name_sort_is_case_and_accent_insensitive(
    qgis_new_project: Never,  # noqa: ARG001  # isolate each test
    qgis_iface: QgisInterface,
) -> None:
    """Layer sort ignores case/accents, but accents break ties (SPEC §19)."""
    project = QgsProject.instance()
    assert project is not None
    for name in ("Zulu", "ábaco", "Banana", "abaco"):
        vector = QgsVectorLayer("Point?crs=EPSG:4326", name, "memory")
        assert vector.isValid()
        assert project.addMapLayer(vector) is not None
    dialog = LayersTableDialog(qgis_iface)
    dialog.table.sortItems(0, Qt.SortOrder.AscendingOrder)
    # Accent-insensitive primary order; the abaco/ábaco pair tie-breaks accent-sensitively.
    assert [item.text() for item in _name_cells(dialog)] == ["abaco", "ábaco", "Banana", "Zulu"]


def test_layer_header_cycles_through_tree_order(
    qgis_new_project: Never,  # noqa: ARG001  # isolate each test
    qgis_iface: QgisInterface,
) -> None:
    """The Layer header cycles name-asc → name-desc → default layer-tree order (SPEC §19)."""
    project = QgsProject.instance()
    assert project is not None
    # Names inserted out of order so tree order differs from both ascending and descending.
    for name in ("mango", "apple", "zebra"):
        vector = QgsVectorLayer("Point?crs=EPSG:4326", name, "memory")
        assert vector.isValid()
        assert project.addMapLayer(vector) is not None
    root = project.layerTreeRoot()
    assert root is not None
    tree_order = [
        layer.name() for node in root.findLayers() if (layer := node.layer()) is not None
    ]
    dialog = LayersTableDialog(qgis_iface)
    header = dialog.table.horizontalHeader()
    assert header is not None
    assert [item.text() for item in _name_cells(dialog)] == tree_order  # default = tree order

    dialog._cycle_name_sort(0)  # 1st click → ascending
    assert [item.text() for item in _name_cells(dialog)] == sorted(tree_order)
    assert header.sortIndicatorSection() == 0

    dialog._cycle_name_sort(0)  # 2nd click → descending
    assert [item.text() for item in _name_cells(dialog)] == sorted(tree_order, reverse=True)

    dialog._cycle_name_sort(0)  # 3rd click → back to layer-tree order
    assert [item.text() for item in _name_cells(dialog)] == tree_order
    assert header.sortIndicatorSection() == -1

    dialog._cycle_name_sort(1)  # clicks on editor columns are ignored
    assert [item.text() for item in _name_cells(dialog)] == tree_order


def test_identical_names_keep_layer_tree_order_when_sorted(
    qgis_new_project: Never,  # noqa: ARG001  # isolate each test
    qgis_iface: QgisInterface,
) -> None:
    """Same-named layers retain their layer-tree order after sorting (stable sort, SPEC §19)."""
    project = QgsProject.instance()
    assert project is not None
    duplicate_ids: list[str] = []
    for _ in range(2):
        vector = QgsVectorLayer("Point?crs=EPSG:4326", "dup", "memory")
        assert vector.isValid()
        assert project.addMapLayer(vector) is not None
        duplicate_ids.append(vector.id())
    dups = set(duplicate_ids)
    root = project.layerTreeRoot()
    assert root is not None
    expected = [
        layer.id()
        for node in root.findLayers()
        if (layer := node.layer()) is not None and layer.id() in dups
    ]
    dialog = LayersTableDialog(qgis_iface)
    dialog.table.sortItems(0, Qt.SortOrder.AscendingOrder)
    actual = [
        item.data(Qt.ItemDataRole.UserRole) for item in _name_cells(dialog) if item.text() == "dup"
    ]
    assert actual == expected


def test_non_vector_layer_gates_warm_marked(
    qgis_new_project: Never,  # noqa: ARG001  # isolate each test
    qgis_iface: QgisInterface,
) -> None:
    """Non-vector rows expose only layer-agnostic columns; warm_marked is gated (SPEC §4)."""
    project = QgsProject.instance()
    assert project is not None
    annotation = QgsAnnotationLayer(
        "ann", QgsAnnotationLayer.LayerOptions(project.transformContext())
    )
    assert annotation.isValid()
    assert project.addMapLayer(annotation) is not None
    dialog = LayersTableDialog(qgis_iface)
    assert (annotation.id(), _EXCLUDE) in dialog._editors
    assert (annotation.id(), _WARM) not in dialog._editors
    assert (annotation.id(), _METHOD) not in dialog._editors
