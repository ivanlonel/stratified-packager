"""Project Properties page editing the project-scoped defaults (SPEC §5/§19)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, override

from qgis.core import QgsProject
from qgis.gui import QgsOptionsPageWidget, QgsOptionsWidgetFactory
from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import QFormLayout

from stratified_packager.__about__ import __title__
from stratified_packager.identity import plugin_icon
from stratified_packager.settings import StratifiedPackagerSettings
from stratified_packager.toolbelt.logging import QgisLoggerWrapper, Target
from stratified_packager.toolbelt.settings import ProjectVariables

from .widgets import (
    PROJECT_FIELD_STRATIFICATION_LAYER,
    PROJECT_FIELD_STRATUM_NAME_EXPRESSION,
    FieldKind,
    FieldSpec,
    OverrideExpressionEdit,
    OverrideForm,
    OverrideLayerCombo,
    apply_overrides,
    default_fields,
    project_only_fields,
)

if TYPE_CHECKING:
    from qgis.PyQt.QtGui import QIcon
    from qgis.PyQt.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

log = QgisLoggerWrapper.get_logger(__name__)

# uic.loadUiType has no type stubs; it returns dynamically-generated classes.
FORM_CLASS, _ = uic.loadUiType(Path(__file__).with_suffix(".ui"))  # type: ignore[no-untyped-call]


# FORM_CLASS is a dynamically-generated form class — opaque to static checkers.
class ProjectOptionsPageWidget(QgsOptionsPageWidget, FORM_CLASS):  # type: ignore[misc,valid-type]
    """Project Properties page editing the ``stratified_packager_*`` default variables."""

    verticalLayout: QVBoxLayout  # noqa: N815
    lbl_header: QLabel
    scroll_area: QScrollArea
    form_host: QWidget

    @override
    def __init__(self, parent: QWidget | None = None) -> None:
        """
        Build the page and load the current project variables.

        :param parent: The host widget supplied by the Project Properties dialog.
        """
        super().__init__(parent)
        self.setupUi(self)
        # Project-only rows (variable, no setting tier) first, mirroring the §3 input order.
        self._fields: tuple[FieldSpec, ...] = (*project_only_fields(), *default_fields())
        self.defaults_form: OverrideForm = OverrideForm(self._fields)
        self.defaults_form.build(QFormLayout(self.form_host), self.form_host)
        self._settings = StratifiedPackagerSettings()
        self._load()
        self._link_expression_context()

    def _load(self) -> None:
        """Populate the editors from the project variables and inherited settings."""
        project_variables = ProjectVariables(project=QgsProject.instance())
        current: dict[str, str | None] = {}
        effective: dict[str, str] = {}
        for spec in self._fields:
            raw = project_variables.get(spec.variable)
            current[spec.key] = None if raw is None or str(raw) == "" else str(raw)
            effective[spec.key] = self._effective(spec)
        self.defaults_form.load(current, effective)

    def _effective(self, spec: FieldSpec) -> str:
        """
        Return the inherited effective value of *spec* (the plugin setting).

        :param spec: The field whose inherited value to display.
        :return: The plugin-setting value as a display token; empty for a project-only field,
            which has no setting tier (its editor ignores the value).
        """
        if not hasattr(self._settings, spec.key):
            return ""
        raw = getattr(self._settings, spec.key)
        if spec.kind is FieldKind.BOOL:
            return "true" if bool(raw) else "false"
        return str(raw)

    def _link_expression_context(self) -> None:
        """Feed the stratification-layer selection to the stratum-name expression builder."""
        layer_editor = self.defaults_form.editor(PROJECT_FIELD_STRATIFICATION_LAYER)
        expression_editor = self.defaults_form.editor(PROJECT_FIELD_STRATUM_NAME_EXPRESSION)
        if isinstance(layer_editor, OverrideLayerCombo) and isinstance(
            expression_editor, OverrideExpressionEdit
        ):
            layer_editor.layerChanged.connect(expression_editor.set_context_layer)
            expression_editor.set_context_layer(layer_editor.currentLayer())

    @override
    def apply(self) -> None:
        """
        Write the explicit project variables, clearing inherited fields.

        Contained at this QGIS-invoked boundary: a failed write is reported, not raised.
        """
        try:
            apply_overrides(
                ProjectVariables(project=QgsProject.instance()),
                self.defaults_form.dump_variables(),
            )
        except RuntimeError:
            log.exception(
                self.tr("Could not save the project defaults."),
                targets=Target.LOG | Target.BAR,
            )


class ProjectOptionsPageWidgetFactory(QgsOptionsWidgetFactory):
    """Factory registering :class:`ProjectOptionsPageWidget` in the Project Properties dialog."""

    @override
    def icon(self) -> QIcon:
        """
        Return the page's tab icon.

        :return: The plugin icon.
        """
        return plugin_icon()

    @override
    def title(self) -> str:
        """
        Return the page's tab title.

        :return: The plugin title.
        """
        return __title__

    @override
    def createWidget(self, parent: QWidget | None = None) -> ProjectOptionsPageWidget | None:
        """
        Create the project-defaults page.

        :param parent: The dialog-supplied parent widget.
        :return: The page, or :data:`None` when no parent is supplied.
        """
        return ProjectOptionsPageWidget(parent) if parent else None
