"""Per-layer properties page editing the §4 layer variables (SPEC §4/§19)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, override

from qgis.core import Qgis, QgsVectorLayer
from qgis.gui import QgsMapLayerConfigWidget, QgsMapLayerConfigWidgetFactory
from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import QFormLayout

from stratified_packager.__about__ import __title__
from stratified_packager.identity import plugin_icon
from stratified_packager.processing.params import LAYER_VAR_MATERIALIZE_VIRTUAL, VARIABLE_PREFIX
from stratified_packager.toolbelt.logging import QgisLoggerWrapper, Target
from stratified_packager.toolbelt.settings import LayerVariables

from .widgets import FieldSpec, OverrideForm, apply_overrides, layer_fields

if TYPE_CHECKING:
    from qgis.core import QgsMapLayer
    from qgis.gui import QgsMapCanvas
    from qgis.PyQt.QtWidgets import QLabel, QVBoxLayout, QWidget

log = QgisLoggerWrapper.get_logger(__name__)

# uic.loadUiType has no type stubs; it returns dynamically-generated classes.
FORM_CLASS, _ = uic.loadUiType(Path(__file__).with_suffix(".ui"))  # type: ignore[no-untyped-call]


# FORM_CLASS is a dynamically-generated form class — opaque to static checkers.
class LayerOptionsPageWidget(QgsMapLayerConfigWidget, FORM_CLASS):  # type: ignore[misc,valid-type]
    """Layer Properties page editing one layer's ``stratified_packager_*`` variables."""

    verticalLayout: QVBoxLayout  # noqa: N815
    lbl_header: QLabel
    form_host: QWidget

    @override
    def __init__(
        self,
        layer: QgsMapLayer,
        canvas: QgsMapCanvas | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """
        Build the page and load *layer*'s variables.

        :param layer: The layer being configured.
        :param canvas: The map canvas (unused; kept for the framework signature).
        :param parent: The host widget supplied by the Layer Properties dialog.
        """
        super().__init__(layer, canvas, parent)
        self.setupUi(self)
        self._layer = layer
        self._fields: tuple[FieldSpec, ...] = layer_fields()
        self.variables_form: OverrideForm = OverrideForm(self._fields, inheriting=False)
        field_names = layer.fields().names() if isinstance(layer, QgsVectorLayer) else []
        self.variables_form.build(QFormLayout(self.form_host), self.form_host, field_names)
        if layer.providerType() != "virtual":
            self.variables_form.set_enabled(
                LAYER_VAR_MATERIALIZE_VIRTUAL.removeprefix(VARIABLE_PREFIX), enabled=False
            )
        self._load()

    def _load(self) -> None:
        """Populate the editors from the explicit layer variables (unset = builtin default)."""
        variables = LayerVariables(self._layer)
        current: dict[str, str | None] = {}
        for spec in self._fields:
            raw = variables.get(spec.variable)
            current[spec.key] = None if raw is None or str(raw) == "" else str(raw)
        self.variables_form.load(current, {})

    @override
    def apply(self) -> None:
        """
        Write the explicit layer variables, clearing inherited fields.

        Contained at this QGIS-invoked boundary: a failed write is reported, not raised.
        """
        try:
            apply_overrides(LayerVariables(self._layer), self.variables_form.dump_variables())
        except RuntimeError:
            log.exception(
                self.tr("Could not save the layer variables."),
                targets=Target.LOG | Target.BAR,
            )


class LayerOptionsPageWidgetFactory(QgsMapLayerConfigWidgetFactory):
    """Factory registering :class:`LayerOptionsPageWidget` in the Layer Properties dialog."""

    @override
    def __init__(self) -> None:
        """Initialize the factory: titled, plugin-iconed, properties-dialog only."""
        super().__init__(__title__, plugin_icon())
        self.setSupportLayerPropertiesDialog(True)
        self.setSupportsStyleDock(False)

    @override
    def supportsLayer(self, layer: QgsMapLayer | None) -> bool:
        """
        Report whether *layer* gets the page (vector layers only — §4 is vector-scoped).

        :param layer: The candidate layer.
        :return: :data:`True` for vector layers.
        """
        return layer is not None and layer.type() == Qgis.LayerType.Vector

    @override
    def supportLayerPropertiesDialog(self) -> bool:
        """
        Flag if widget is supported for use in layer properties dialog.

        :return: :data:`True`
        """
        return True

    @override
    def createWidget(
        self,
        layer: QgsMapLayer | None,
        canvas: QgsMapCanvas | None,
        dockWidget: bool = True,  # framework signature
        parent: QWidget | None = None,
    ) -> LayerOptionsPageWidget:
        """
        Create the per-layer variables page.

        :param layer: The layer being configured (the framework only calls this when
            :meth:`supportsLayer` returned :data:`True`, so it is never :data:`None`).
        :param canvas: The map canvas (unused by the page).
        :param dockWidget: Whether hosted in a dock (unused; framework signature).
        :param parent: The dialog-supplied parent widget.
        :return: The page.
        :raise ValueError: If called without a layer (a framework-contract violation).
        """
        if layer is None:
            msg = "createWidget requires a layer."
            raise ValueError(msg)
        return LayerOptionsPageWidget(layer, canvas, parent)
