"""GUI surface: the Options page, the Project/Layer defaults pages and their factories."""

from .dlg_layers_table import LayersTableDialog
from .wdg_layer_options_page import LayerOptionsPageWidget, LayerOptionsPageWidgetFactory
from .wdg_plugin_options_page import PluginOptionsPageWidget, PluginOptionsPageWidgetFactory
from .wdg_project_options_page import ProjectOptionsPageWidget, ProjectOptionsPageWidgetFactory

__all__: list[str] = [
    "LayerOptionsPageWidget",
    "LayerOptionsPageWidgetFactory",
    "LayersTableDialog",
    "PluginOptionsPageWidget",
    "PluginOptionsPageWidgetFactory",
    "ProjectOptionsPageWidget",
    "ProjectOptionsPageWidgetFactory",
]
