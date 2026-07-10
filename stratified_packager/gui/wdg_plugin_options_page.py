"""Plugin settings form integrated into QGIS 'Options' menu."""

from __future__ import annotations

import logging
import platform
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, override
from urllib.parse import quote

from qgis.core import Qgis, QgsApplication, QgsProject
from qgis.gui import QgsOptionsPageWidget, QgsOptionsWidgetFactory
from qgis.PyQt import uic
from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtGui import QDesktopServices, QIcon
from qgis.PyQt.QtWidgets import QGridLayout, QLabel

from stratified_packager.__about__ import (
    __title__,
    __uri_homepage__,
    __uri_tracker__,
    __version__,
)
from stratified_packager.identity import plugin_icon
from stratified_packager.settings import StratifiedPackagerSettings
from stratified_packager.toolbelt.logging import QgisLoggerWrapper, Target
from stratified_packager.toolbelt.settings import ProjectVariables

from .widgets import (
    FieldKind,
    FieldSpec,
    concrete_value,
    default_fields,
    make_concrete_editor,
    set_concrete_value,
)

if TYPE_CHECKING:
    from qgis.PyQt.QtWidgets import (
        QCheckBox,
        QGroupBox,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )

log = QgisLoggerWrapper.get_logger(__name__)

# uic.loadUiType has no type stubs; it returns dynamically-generated classes.
FORM_CLASS, _ = uic.loadUiType(Path(__file__).with_suffix(".ui"))  # type: ignore[no-untyped-call]


# FORM_CLASS is a dynamically-generated form class — opaque to static checkers.
class PluginOptionsPageWidget(QgsOptionsPageWidget, FORM_CLASS):  # type: ignore[misc,valid-type]
    """Settings form embedded into QGIS 'options' menu."""

    verticalLayout: QVBoxLayout  # noqa: N815
    gridLayout: QGridLayout  # noqa: N815
    grp_misc: QGroupBox
    grp_defaults: QGroupBox
    defaults_host: QWidget
    lbl_title: QLabel
    lbl_version_saved_value: QLabel
    lbl_version_saved: QLabel
    btn_report: QPushButton
    btn_help: QPushButton
    btn_reset: QPushButton
    opt_debug: QCheckBox

    @override
    def __init__(self, parent: QWidget | None = None) -> None:
        """
        Initialize settings dialog.

        :param parent: base class for widgets for pages included in the options dialog.
        """
        super().__init__(parent)
        self.setupUi(self)
        self.plg_settings = StratifiedPackagerSettings()
        self._default_fields: tuple[FieldSpec, ...] = default_fields()
        self._default_editors: dict[str, QWidget] = {}
        self._default_notes: dict[str, QLabel] = {}
        self._build_defaults_editors()
        self.initGui()

    def _build_defaults_editors(self) -> None:
        """Build a concrete editor and an override-note label for each default field."""
        grid = QGridLayout(self.defaults_host)
        for row, spec in enumerate(self._default_fields):
            editor = make_concrete_editor(spec, self.defaults_host)
            note = QLabel("", self.defaults_host)
            note.setWordWrap(True)
            grid.addWidget(QLabel(spec.label, self.defaults_host), row, 0)
            grid.addWidget(editor, row, 1)
            grid.addWidget(note, row, 2)
            self._default_editors[spec.key] = editor
            self._default_notes[spec.key] = note
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 2)
        grid.setRowStretch(len(self._default_fields), 1)

    def initGui(self) -> None:  # noqa: N802
        """Set up UI elements."""
        # header
        report_context_message: str = quote(
            "> Reported from plugin settings\n\n"
            f"- operating system: {platform.system()} {platform.release()}_{platform.version()}\n"
            f"- QGIS: {Qgis.version()}\n"
            f"- plugin version: {__version__}\n"
        )

        # header
        self.lbl_title.setText(f"{__title__} - Version {__version__}")

        # customization
        self.btn_help.setIcon(QIcon(QgsApplication.iconPath("mActionHelpContents.svg")))
        self.btn_help.pressed.connect(partial(QDesktopServices.openUrl, QUrl(__uri_homepage__)))

        self.btn_report.setIcon(
            QIcon(QgsApplication.iconPath("console/iconSyntaxErrorConsole.svg"))
        )

        self.btn_report.pressed.connect(
            partial(
                QDesktopServices.openUrl,
                QUrl(
                    f"{__uri_tracker__}new/?"
                    "template=10_bug_report.yml"
                    f"&about-info={report_context_message}"
                ),
            )
        )

        self.btn_reset.setIcon(QIcon(QgsApplication.iconPath("mActionUndo.svg")))
        self.btn_reset.pressed.connect(self.on_reset_settings)

        # load previously saved settings
        self.load_settings()

    @override
    def apply(self) -> None:
        """
        Permanently apply settings shown in options page (e.g. save them to QgsSettings objects).

        This is usually called when the options dialog is accepted. A rejected
        write is contained and reported here, as this is a QGIS-invoked boundary
        and the failure must not escape into the options dialog.
        """
        try:
            # misc
            self.plg_settings.debug_mode = self.opt_debug.isChecked()
            self.plg_settings.version_saved = __version__

            # algorithm defaults (the ✓ rows of SPEC §3)
            for spec in self._default_fields:
                token = concrete_value(spec, self._default_editors[spec.key])
                setattr(self.plg_settings, spec.key, self._coerce_for_setting(spec, token))
        except RuntimeError:
            log.exception(
                self.tr("Could not save plugin settings."), targets=Target.LOG | Target.BAR
            )
            return

        # the project-variable overrides may now differ; refresh the notes.
        self._refresh_override_notes()

        # keep the live root logger level in sync with the just-saved debug_mode.
        QgisLoggerWrapper.get_logger(__name__.partition(".")[0]).logger.setLevel(
            logging.DEBUG if self.opt_debug.isChecked() else logging.INFO
        )
        log.debug("DEBUG - Settings successfully saved.")

    @staticmethod
    def _coerce_for_setting(spec: FieldSpec, raw: str) -> bool | int | str:
        """
        Coerce an editor's string token to the type its setting descriptor stores.

        :param spec: The field being written.
        :param raw: The editor's value as a string token.
        :return: The value typed for the setting (bool / int / str).
        """
        if spec.kind is FieldKind.BOOL:
            return raw == "true"
        if spec.kind is FieldKind.INT:
            return int(raw or 0)
        return raw

    def load_settings(self) -> None:
        """Load options from QgsSettings into UI form."""
        # global
        self.opt_debug.setChecked(self.plg_settings.debug_mode)
        self.lbl_version_saved_value.setText(self.plg_settings.version_saved)

        # algorithm defaults
        for spec in self._default_fields:
            set_concrete_value(
                spec, self._default_editors[spec.key], str(getattr(self.plg_settings, spec.key))
            )
        self._refresh_override_notes()

    def _refresh_override_notes(self) -> None:
        """Show, per field, whether the active project shadows the setting (SPEC §19)."""
        project_variables = ProjectVariables(project=QgsProject.instance())
        for spec in self._default_fields:
            raw = project_variables.get(spec.variable)
            note = self._default_notes[spec.key]
            if raw is not None and str(raw) != "":
                note.setText(self.tr("⚠️ overridden by project variable (= {})").format(raw))
            else:
                note.setText("")

    def on_reset_settings(self) -> None:
        """Reset settings to default values (set in the settings module)."""
        self.plg_settings.reset_defaults()

        # update the form
        self.load_settings()


class PluginOptionsPageWidgetFactory(QgsOptionsWidgetFactory):
    """Factory for options widget."""

    @override
    def icon(self) -> QIcon:
        """
        Return plugin icon, used as tab icon in QGIS options tab widget.

        :return: plugin's icon
        """
        return plugin_icon()

    @override
    def createWidget(self, parent: QWidget | None = None) -> PluginOptionsPageWidget | None:
        """
        Create settings widget.

        :param parent: Qt parent where to include the options page.
        :return: options page for tab widget
        """
        return PluginOptionsPageWidget(parent) if parent else None

    @override
    def title(self) -> str:
        """
        Return plugin title, used to name the tab in QGIS options tab widget.

        :return: plugin title from about module
        """
        return __title__
