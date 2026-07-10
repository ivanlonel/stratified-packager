"""All-layers table dialog for per-layer packaging settings (SPEC §19)."""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, override

from qgis.core import Qgis, QgsProject, QgsVectorLayer
from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QStyle,
    QTableWidgetItem,
)

from stratified_packager.__about__ import __title__
from stratified_packager.processing.params import (
    LAYER_VAR_RELATION_PATH,
    LAYER_VAR_SPECS,
    VARIABLE_PREFIX,
)
from stratified_packager.toolbelt.logging import QgisLoggerWrapper, Target
from stratified_packager.toolbelt.settings import LayerVariables
from stratified_packager.toolbelt.utils import remove_diacritical_marks

from .widgets import (
    OverridePredicateCombo,
    ScopeEditor,
    apply_overrides,
    layer_fields,
    make_override_editor,
)

if TYPE_CHECKING:
    from qgis.core import QgsMapLayer
    from qgis.gui import QgisInterface
    from qgis.PyQt.QtWidgets import QTableWidget, QVBoxLayout, QWidget

    from . import LayerOptionsPageWidgetFactory

log = QgisLoggerWrapper.get_logger(__name__)

# uic.loadUiType has no type stubs; it returns dynamically-generated classes.
FORM_CLASS, _ = uic.loadUiType(Path(__file__).with_suffix(".ui"))  # type: ignore[no-untyped-call]


class _NameItem(QTableWidgetItem):
    """A layer-name cell sorted by name (accent-aware) or by layer-tree rank."""

    @override
    def __init__(self, text: str, tree_rank: int) -> None:
        """
        Build the name cell.

        :param text: The layer name to show.
        :param tree_rank: The row's position in the layer tree; sorted on to restore the default
            order (the third click of the header's sort cycle).
        """
        super().__init__(text)
        self.tree_rank = tree_rank
        """The row's layer-tree position, used to restore the default order."""
        self.sort_by_rank = False
        """When set, the next sort compares :attr:`tree_rank` instead of the name (restoring the
        default layer-tree order). Toggled by the host dialog before each sort."""

    @override
    def __lt__(self, other: QTableWidgetItem) -> bool:
        """
        Compare by layer-tree rank when restoring the default order, else by the name key.

        The name key is the ``(accent-free, accent-kept)`` casefolded pair (accent-insensitive
        primary, accents as tie-breaker). Names equal under it keep their relative order:
        :class:`QTableWidget` sorts with a stable sort (``QTableModel::sort`` uses
        ``std::stable_sort``), so identical names stay in layer-tree order in both directions.

        :param other: The item to compare against.
        :return: Whether this item sorts before *other*.
        """
        if self.sort_by_rank and isinstance(other, _NameItem):
            return self.tree_rank < other.tree_rank
        return self._key(self.text()) < self._key(other.text())

    @staticmethod
    def _key(text: str) -> tuple[str, str]:
        """
        Return the ``(accent-free, accent-kept)`` casefolded sort keys: primary, then tie-breaker.

        :param text: The cell text.
        :return: The accent-stripped key followed by the accent-keeping key.
        """
        folded = text.casefold()
        return remove_diacritical_marks(folded), folded


# FORM_CLASS is a dynamically-generated form class — opaque to static checkers.
class LayersTableDialog(QDialog, FORM_CLASS):  # type: ignore[misc,valid-type]
    """Editable table of every layer's ``stratified_packager_*`` variables."""

    verticalLayout: QVBoxLayout  # noqa: N815
    lbl_header: QLabel
    btn_plugin_settings: QPushButton
    btn_project_defaults: QPushButton
    table: QTableWidget
    button_box: QDialogButtonBox

    _VECTOR_ONLY: frozenset[str] = frozenset(
        spec.suffix for spec in LAYER_VAR_SPECS if spec.vector_only
    )
    """Field keys (bare suffixes) that only apply to vector layers (disabled otherwise);
    derived from the variable table's ``vector_only`` flags."""

    _VIRTUAL_ONLY: frozenset[str] = frozenset(
        spec.suffix for spec in LAYER_VAR_SPECS if spec.virtual_only
    )
    """Field keys whose column is disabled for non-virtual layers; derived from the
    variable table's ``virtual_only`` flags."""

    @override
    def __init__(
        self,
        iface: QgisInterface,
        parent: QWidget | None = None,
        layer_options_page_widget_factory: LayerOptionsPageWidgetFactory | None = None,
    ) -> None:
        """
        Build the dialog and fill the table from the current project's layers.

        :param iface: The QGIS interface (for the page deep-link buttons).
        :param parent: The dialog parent.
        :param layer_options_page_widget_factory: the registered
            :class:`~.wdg_layer_options_page.LayerOptionsPageWidgetFactory` instance.
        """
        super().__init__(parent)
        self.setupUi(self)
        self._iface = iface
        self._layer_opts_factory = layer_options_page_widget_factory
        self._specs = {spec.key: spec for spec in layer_fields()}
        # Columns follow layer_fields() order (minus relation_path, which stays on the per-layer
        # page), so a new §4 variable auto-appears here without touching this dialog.
        _relation_key = LAYER_VAR_RELATION_PATH.removeprefix(VARIABLE_PREFIX)
        self._column_keys: tuple[str, ...] = tuple(k for k in self._specs if k != _relation_key)
        self._editors: dict[tuple[str, str], ScopeEditor] = {}
        self._name_sort_state = 0
        """The Layer column's sort cycle: 0 = layer-tree order, 1 = ascending, 2 = descending."""
        self._populate()
        self._wire()

    def _wire(self) -> None:
        """Connect the button box and the page deep-link buttons."""
        self.button_box.accepted.connect(self._on_accept)
        self.button_box.rejected.connect(self.reject)
        if apply_button := self.button_box.button(QDialogButtonBox.StandardButton.Apply):
            apply_button.clicked.connect(self.apply_changes)
        self.btn_plugin_settings.clicked.connect(self._open_plugin_settings)
        self.btn_project_defaults.clicked.connect(self._open_project_defaults)

    def _populate(self) -> None:
        """Create one row per (non-plugin) layer with an editor per §4 column."""
        project = QgsProject.instance()
        root = project.layerTreeRoot() if project is not None else None
        layers = [
            layer
            for node in (root.findLayers() if root is not None else [])
            if (layer := node.layer()) is not None and layer.type() != Qgis.LayerType.Plugin
        ]
        headers = [
            self.tr("Layer"),
            *(self._specs[key].label for key in self._column_keys),
            self.tr("Properties"),
        ]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setRowCount(len(layers))
        for row, layer in enumerate(layers):
            self._fill_row(row, layer)
        self._size_columns()
        self._fit_dialog_width()
        # The Layer column is click-sortable (the editor columns hold widgets, not sortable data).
        # Drive it manually rather than via setSortingEnabled, so the header cycles ascending →
        # descending → default (layer-tree) order instead of QHeaderView's built-in two-state
        # toggle. The cleared indicator means the initial view is unsorted (layer-tree order).
        if header := self.table.horizontalHeader():
            header.setSortIndicatorShown(True)
            header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
            header.setSectionsClickable(True)
            header.sectionClicked.connect(self._cycle_name_sort)

    def _fill_row(self, row: int, layer: QgsMapLayer) -> None:
        """
        Fill one table row for *layer*.

        :param row: The table row index.
        :param layer: The layer to represent.
        """
        name_item = _NameItem(layer.name(), row)
        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        # Anchor the row's identity so it maps back to its layer regardless of sort order.
        name_item.setData(Qt.ItemDataRole.UserRole, layer.id())
        self.table.setItem(row, 0, name_item)

        is_virtual = layer.providerType() == "virtual"
        is_vector = isinstance(layer, QgsVectorLayer)
        field_names = layer.fields().names() if isinstance(layer, QgsVectorLayer) else []
        variables = LayerVariables(layer)
        for column, key in enumerate(self._column_keys, start=1):
            if (key in self._VECTOR_ONLY and not is_vector) or (
                key in self._VIRTUAL_ONLY and not is_virtual
            ):
                placeholder = QLabel("—")
                placeholder.setEnabled(False)
                self.table.setCellWidget(row, column, placeholder)
                continue
            spec = self._specs[key]
            editor = make_override_editor(spec, field_names=field_names, inheriting=False)
            raw = variables.get(spec.variable)
            editor.set_scope_value(None if raw is None or str(raw) == "" else str(raw))
            self.table.setCellWidget(row, column, editor)
            self._editors[(layer.id(), key)] = editor

        layer_properties_button = QPushButton(self.tr("Properties…"))
        if self._layer_opts_factory is not None and self._layer_opts_factory.supportsLayer(layer):
            layer_properties_button.clicked.connect(
                partial(self._open_layer_properties, layer.id())
            )
        else:
            layer_properties_button.setEnabled(False)
        self.table.setCellWidget(row, len(self._column_keys) + 1, layer_properties_button)

    def _size_columns(self) -> None:
        """Size columns to content, then widen editor columns to fit their editors."""
        self.table.resizeColumnsToContents()
        widest: dict[int, int] = {}
        for (_layer_id, key), editor in self._editors.items():
            column = self._column_keys.index(key) + 1  # column 0 is the Layer name
            hint = editor.sizeHint().width()
            if isinstance(editor, OverridePredicateCombo):
                hint = max(hint, editor.de9im_row_width_hint())
            widest[column] = max(widest.get(column, 0), hint)
        for column, width in widest.items():
            if self.table.columnWidth(column) < width:
                self.table.setColumnWidth(column, width)

    def _fit_dialog_width(self) -> None:
        """Widen the dialog to show every column, capped at the available screen width."""
        header = self.table.horizontalHeader()
        row_header = self.table.verticalHeader()
        style = self.style()
        if header is None or row_header is None or style is None:
            return
        side_margins = 0
        if layout := self.layout():
            margins = layout.contentsMargins()
            side_margins = margins.left() + margins.right()
        width = (
            header.length()
            + row_header.width()
            + self.table.frameWidth() * 2
            + style.pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent)
            + side_margins
        )
        if screen := self.screen():
            width = min(width, screen.availableGeometry().width())
        self.resize(width, self.height())

    def _cycle_name_sort(self, column: int) -> None:
        """
        Cycle the Layer column: name-ascending → name-descending → default (layer-tree) order.

        Clicks on the editor columns are ignored — they hold widgets, not sortable values.

        :param column: The clicked header section.
        """
        if column != 0:
            return
        self._name_sort_state = (self._name_sort_state + 1) % 3
        restore_tree_order = self._name_sort_state == 0
        for row in range(self.table.rowCount()):
            if isinstance(item := self.table.item(row, 0), _NameItem):
                item.sort_by_rank = restore_tree_order
        header = self.table.horizontalHeader()
        if restore_tree_order:
            self.table.sortItems(0, Qt.SortOrder.AscendingOrder)  # by tree rank → default order
            if header is not None:
                header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
            return
        order = (
            Qt.SortOrder.AscendingOrder
            if self._name_sort_state == 1
            else Qt.SortOrder.DescendingOrder
        )
        self.table.sortItems(0, order)
        if header is not None:
            header.setSortIndicator(0, order)

    def apply_changes(self) -> None:
        """
        Write every edited cell back to its layer variable.

        Contained at this QGIS-invoked boundary: a failed write is reported, not raised.
        """
        project = QgsProject.instance()
        if project is None:
            return
        grouped: dict[str, dict[str, str | None]] = {}
        for (layer_id, key), editor in self._editors.items():
            grouped.setdefault(layer_id, {})[self._specs[key].variable] = editor.scope_value()
        try:
            for layer_id, values in grouped.items():
                layer = project.mapLayer(layer_id)
                if layer is not None:
                    apply_overrides(LayerVariables(layer), values)
        except RuntimeError:
            log.exception(
                self.tr("Could not save the layer settings."), targets=Target.LOG | Target.BAR
            )

    def _on_accept(self) -> None:
        """Apply the edits, then close the dialog."""
        self.apply_changes()
        self.accept()

    def _open_plugin_settings(self) -> None:
        """Open the plugin Options page."""
        self._iface.showOptionsDialog(currentPage="wdg_stratified_packager_plugin_options_page")

    def _open_project_defaults(self) -> None:
        """Open the plugin's Project Properties defaults page."""
        # QgsProjectProperties overwrites every factory page's objectName with the
        # factory title(), so setCurrentPage must match __title__ here — not the .ui
        # objectName the Options/Layer dialogs preserve and match on.
        self._iface.showProjectPropertiesDialog(currentPage=__title__)

    def _open_layer_properties(self, layer_id: str) -> None:
        """
        Open a layer's properties dialog.

        :param layer_id: The id of the layer whose properties to open.
        """
        project = QgsProject.instance()
        if project is None:
            return
        if layer := project.mapLayer(layer_id):
            self._iface.showLayerProperties(
                layer, page="wdg_stratified_packager_layer_options_page"
            )
