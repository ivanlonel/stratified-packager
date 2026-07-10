"""Main plugin module."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from qgis.core import QgsApplication, QgsSettings
from qgis.PyQt.QtCore import QCoreApplication, QLocale, QTranslator, QUrl
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import QAction

from .__about__ import (
    DIR_PLUGIN_ROOT,
    __title__,
    __uri_homepage__,
)
from .identity import PLUGIN_SLUG, plugin_icon
from .processing.provider import StratifiedPackagerProvider
from .settings import StratifiedPackagerSettings
from .toolbelt.debugging import start_debug_server
from .toolbelt.i18n import Translatable
from .toolbelt.logging import QgisLoggerWrapper, Target

if TYPE_CHECKING:
    from qgis.gui import QgisInterface

    from .gui import (
        LayerOptionsPageWidgetFactory,
        PluginOptionsPageWidgetFactory,
        ProjectOptionsPageWidgetFactory,
    )

log = QgisLoggerWrapper.get_logger(__name__)


class StratifiedPackager(Translatable):
    """The plugin entry object: wires the provider, settings UI and defaults pages."""

    def __init__(self, iface: QgisInterface) -> None:
        """
        Initialize the plugin and install its translator.

        :param iface: The running QGIS interface handle.
        """
        self.locale: str = QgsSettings().value("locale/userLocale", QLocale().name())[0:2]
        locale_path = DIR_PLUGIN_ROOT / f"resources/i18n/{PLUGIN_SLUG}_{self.locale}.qm"
        log.debug("Translation: %s, %s", self.locale, locale_path)
        if locale_path.exists():
            self.translator = QTranslator()
            if not self.translator.load(str(locale_path.resolve())):
                log.warning("Could not load translation file %s.", locale_path)
            elif not QCoreApplication.installTranslator(self.translator):
                log.warning("Could not install translator for locale %s.", self.locale)

        # Optionally open a debugpy listen socket (a no-op unless QGIS_DEBUGPY is set).
        # Done after setting up translation, so the logs can be translated.
        start_debug_server()

        self.iface: QgisInterface = iface
        self.provider: StratifiedPackagerProvider | None = None
        self.plugin_options_factory: PluginOptionsPageWidgetFactory | None = None
        self.project_options_factory: ProjectOptionsPageWidgetFactory | None = None
        self.layer_options_factory: LayerOptionsPageWidgetFactory | None = None
        self.action_help: QAction | None = None
        self.action_settings: QAction | None = None
        self.action_project_defaults: QAction | None = None
        self.action_layers: QAction | None = None
        self.action_plugin_help_menu_separator: QAction | None = None
        self.action_plugin_help_menu_documentation: QAction | None = None

        log.debug(self.tr("Plugin initialized successfully."))

    def initGui(self) -> None:  # noqa: N802
        """Set up plugin UI elements."""
        # Deferred import: qgis_process never calls initGui, so headless sessions skip
        # loading the four GUI modules (each compiles its .ui form at import time).
        from .gui import (  # noqa: PLC0415
            LayerOptionsPageWidgetFactory,
            PluginOptionsPageWidgetFactory,
            ProjectOptionsPageWidgetFactory,
        )

        # settings page within the QGIS preferences menu
        self.plugin_options_factory = PluginOptionsPageWidgetFactory()
        self.iface.registerOptionsWidgetFactory(self.plugin_options_factory)

        # -- Defaults-editing pages (SPEC §19): project-scope and per-layer scope.
        self.project_options_factory = ProjectOptionsPageWidgetFactory()
        self.iface.registerProjectPropertiesWidgetFactory(self.project_options_factory)
        self.layer_options_factory = LayerOptionsPageWidgetFactory()
        self.iface.registerMapLayerConfigWidgetFactory(self.layer_options_factory)

        # -- Actions
        self.action_help = QAction(
            QgsApplication.getThemeIcon("mActionHelpContents.svg"),
            self.tr("Help"),
            self.iface.mainWindow(),
        )
        self.action_help.setObjectName(f"action_{PLUGIN_SLUG}_help")
        self.action_help.triggered.connect(
            partial(QDesktopServices.openUrl, QUrl(__uri_homepage__))
        )

        self.action_settings = QAction(
            QgsApplication.getThemeIcon("console/iconSettingsConsole.svg"),
            self.tr("Settings"),
            self.iface.mainWindow(),
        )
        self.action_settings.setObjectName(f"action_{PLUGIN_SLUG}_settings")
        self.action_settings.triggered.connect(
            lambda: self.iface.showOptionsDialog(
                currentPage="wdg_stratified_packager_plugin_options_page"
            )
        )

        # -- Project-scope defaults page
        self.action_project_defaults = QAction(
            QgsApplication.getThemeIcon("mActionProjectProperties.svg"),
            self.tr("Project defaults…"),
            self.iface.mainWindow(),
        )
        self.action_project_defaults.setObjectName(f"action_{PLUGIN_SLUG}_project_defaults")
        self.action_project_defaults.triggered.connect(
            lambda: self.iface.showProjectPropertiesDialog(currentPage=__title__)
        )

        # -- All-layers packaging-settings dialog
        self.action_layers = QAction(
            QgsApplication.getThemeIcon("mActionOpenTable.svg"),
            self.tr("Configure layers for packaging…"),
            self.iface.mainWindow(),
        )
        self.action_layers.setObjectName(f"action_{PLUGIN_SLUG}_layers")
        self.action_layers.triggered.connect(self._open_layers_dialog)

        # -- Menu
        self.iface.addPluginToMenu(__title__, self.action_settings)
        self.iface.addPluginToMenu(__title__, self.action_project_defaults)
        self.iface.addPluginToMenu(__title__, self.action_layers)
        self.iface.addPluginToMenu(__title__, self.action_help)

        # Give the submenu that addPluginToMenu created (identified by the actions it holds,
        # not by title, dodging & mnemonics) the plugin icon. QGIS owns the submenu, so
        # removePluginMenu disposes it — and the icon — in unload(); nothing extra to track.
        if plugin_menu := self.iface.pluginMenu():
            for menu_action in plugin_menu.actions():
                submenu = menu_action.menu()
                if submenu is not None and self.action_settings in submenu.actions():
                    menu_action.setIcon(plugin_icon())
                    break

        # -- Processing
        self.initProcessing()

        # -- Keep the algorithm's dynamic defaults (SPEC §5) in step with project edits.
        # GUI sessions only: these signal hookups segfault qgis_process (SPEC §5).
        if self.provider is not None:
            self.provider.connect_project_signals()

        # -- Plugin help menu
        plugin_help_menu = self.iface.pluginHelpMenu()
        if plugin_help_menu is None:
            log.error(self.tr("Could not find QGIS plugin help menu to add documentation link."))
            return

        # documentation
        if action_plugin_help_menu_separator := plugin_help_menu.addSeparator():
            action_plugin_help_menu_separator.setObjectName(
                f"action_{PLUGIN_SLUG}_plugin_help_menu_separator"
            )
            self.action_plugin_help_menu_separator = action_plugin_help_menu_separator

        self.action_plugin_help_menu_documentation = QAction(
            plugin_icon(),
            self.tr("{} - Documentation").format(__title__),
            self.iface.mainWindow(),
        )
        self.action_plugin_help_menu_documentation.setObjectName(
            f"action_{PLUGIN_SLUG}_plugin_help_menu_documentation"
        )
        self.action_plugin_help_menu_documentation.triggered.connect(
            partial(QDesktopServices.openUrl, QUrl(__uri_homepage__))
        )

        plugin_help_menu.addAction(self.action_plugin_help_menu_documentation)

    def _open_layers_dialog(self) -> int:
        """Open the all-layers packaging-settings dialog."""
        from .gui import LayersTableDialog  # noqa: PLC0415  # deferred with the rest of .gui

        dialog = LayersTableDialog(self.iface, self.iface.mainWindow(), self.layer_options_factory)
        return dialog.exec()

    def initProcessing(self) -> None:  # noqa: N802
        """Initialize the processing provider."""
        self.provider = StratifiedPackagerProvider()
        if processing_registry := QgsApplication.processingRegistry():
            if processing_registry.addProvider(self.provider):
                log.debug(self.tr("Processing provider added successfully."))
            else:
                log.error(
                    self.tr("Failed to add processing provider."), targets=Target.LOG | Target.BAR
                )
        else:
            log.error(self.tr("Could not access QGIS processing registry to add provider."))

    def unload(self) -> None:
        """Clean up when plugin is disabled/uninstalled."""
        self._teardown_factories()

        # -- Unregister the plugin's settings-tree node so a reload re-registers cleanly.
        # Contained so the GUI cleanup below still runs if teardown fails.
        try:
            StratifiedPackagerSettings.teardown()
        except Exception:  # boundary: unload must finish cleaning up regardless
            log.exception(self.tr("Failed to tear down the plugin settings node."))

        self._teardown_provider()
        self._teardown_menu_actions()

        # -- Detach the logging handler last, so the steps above can still log through it.
        # A handler left attached would duplicate every log record after each plugin reload.
        try:
            QgisLoggerWrapper.teardown(__name__.partition(".")[0])
        except Exception:  # boundary: unload must finish cleaning up regardless
            log.exception(self.tr("Failed to tear down the plugin logging handler."))

    def _teardown_factories(self) -> None:
        """Unregister the Options, Project and Layer widget factories."""
        # Guarded per factory: unload() may run without initGui ever having been called
        # (headless sessions), leaving every factory None.
        if self.plugin_options_factory is not None:
            self.iface.unregisterOptionsWidgetFactory(self.plugin_options_factory)
            self.plugin_options_factory = None
        if self.project_options_factory is not None:
            self.iface.unregisterProjectPropertiesWidgetFactory(self.project_options_factory)
            self.project_options_factory = None
        if self.layer_options_factory is not None:
            self.iface.unregisterMapLayerConfigWidgetFactory(self.layer_options_factory)
            self.layer_options_factory = None

    def _teardown_provider(self) -> None:
        """Disconnect the §5 refresh hookups, then unregister the Processing provider."""
        if self.provider is None:
            return
        self.provider.disconnect_project_signals()
        if processing_registry := QgsApplication.processingRegistry():
            if not processing_registry.removeProvider(self.provider):
                log.warning(self.tr("Failed to remove processing provider during plugin unload."))
        else:
            log.warning(self.tr("Could not access QGIS processing registry to remove provider."))
        self.provider = None

    def _teardown_menu_actions(self) -> None:
        """Remove and delete every menu action added in :meth:`initGui`."""
        for action in (
            self.action_help,
            self.action_settings,
            self.action_project_defaults,
            self.action_layers,
        ):
            if action is not None:
                self.iface.removePluginMenu(__title__, action)
                action.deleteLater()
        self.action_help = None
        self.action_settings = None
        self.action_project_defaults = None
        self.action_layers = None

        plugin_help_menu = self.iface.pluginHelpMenu()
        for action in (
            self.action_plugin_help_menu_documentation,
            self.action_plugin_help_menu_separator,
        ):
            if action is not None:
                if plugin_help_menu is not None:
                    plugin_help_menu.removeAction(action)
                action.deleteLater()
        self.action_plugin_help_menu_documentation = None
        self.action_plugin_help_menu_separator = None
