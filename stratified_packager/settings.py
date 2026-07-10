"""The plugin's own typed settings schema, built on the toolbelt settings library."""

from __future__ import annotations

from typing import ClassVar

from .__about__ import __version__
from .identity import PLUGIN_SLUG
from .processing.params import PARAM_SPECS, STYLE_CATEGORY_TOKENS
from .toolbelt.settings import BoolSetting, IntSetting, PluginSettingsBase, StringSetting


def _setting_label(setting: str) -> str:
    """
    Return the canonical source-English label of the input backed by *setting*.

    :param setting: The settings attribute name (a ✓ row of SPEC §3).
    :return: The matching :attr:`~stratified_packager.processing.params.ParamSpec.label`,
        so the setting description can never drift from the algorithm-dialog text.
    """
    return next(spec.label for spec in PARAM_SPECS.values() if spec.setting == setting)


class StratifiedPackagerSettings(PluginSettingsBase):
    """
    Stratified Packager's global settings, scoped under ``plugins/<slug>``.

    Declares the plugin's known keys as typed :class:`~.toolbelt.settings.Setting`
    descriptors while remaining a full dict-like
    :class:`~.toolbelt.settings.SettingsProxy` for any additional keys. Because the
    scope matches the descriptors' entry keys, ``self.debug_mode`` and
    ``self["debug_mode"]`` address the same stored value.
    """

    _PLUGIN_NAME: ClassVar[str] = PLUGIN_SLUG
    """Plugin slug used as the settings-tree node and the ``plugins/<slug>`` scope."""

    debug_mode = BoolSetting(default=False, description="Enable verbose debug logging.")
    """Whether the plugin emits verbose debug output."""

    version_saved = StringSetting(
        default=__version__, description="Plugin version that last wrote the settings."
    )
    """Plugin version stamp recorded when the settings were last saved."""

    # ------------------------------------------------------------------
    # Algorithm defaults (the ✓ rows of SPEC §3). Resolution precedence:
    # explicit input > project variable > these settings > builtin default.
    # Enum-valued settings store the SPEC's string tokens (not indices), so
    # stored configuration survives enum reordering; the tokens are validated
    # by the parameter resolver in processing/params.py.
    # ------------------------------------------------------------------

    gpkg_path_expression = StringSetting(
        default="", description=_setting_label("gpkg_path_expression")
    )
    """Default gpkg-path expression; empty means ``@stratum_name_sanitized``."""

    zip_path_expression = StringSetting(
        default="", description=_setting_label("zip_path_expression")
    )
    """Default zip-path expression; empty means ``@gpkg_name``."""

    compression_level = IntSetting(default=6, description=_setting_label("compression_level"))
    """Default zip compression level (0 = ``ZIP_STORED``)."""

    overwrite_mode = StringSetting(
        default="overwrite", description=_setting_label("overwrite_mode")
    )
    """Default overwrite-mode token (see ``processing.params.OverwriteMode``)."""

    project_inclusion = StringSetting(
        default="none", description=_setting_label("project_inclusion")
    )
    """Default project-inclusion token (see ``processing.params.ProjectInclusion``)."""

    use_temp_folder = BoolSetting(default=True, description=_setting_label("use_temp_folder"))
    """Default for USE_TEMP_FOLDER."""

    include_styles = BoolSetting(default=True, description=_setting_label("include_styles"))
    """Default for INCLUDE_STYLES."""

    style_categories = StringSetting(
        default=",".join(STYLE_CATEGORY_TOKENS),
        description=_setting_label("style_categories"),
    )
    """Default for STYLE_CATEGORIES (every category; see ``processing.params``)."""

    include_metadata = BoolSetting(default=True, description=_setting_label("include_metadata"))
    """Default for INCLUDE_METADATA."""

    keep_empty_layers = BoolSetting(default=True, description=_setting_label("keep_empty_layers"))
    """Default for KEEP_EMPTY_LAYERS."""

    deduplicate_shared_sources = BoolSetting(
        default=True, description=_setting_label("deduplicate_shared_sources")
    )
    """Default for DEDUPLICATE_SHARED_SOURCES."""

    stage_providers = StringSetting(default="", description=_setting_label("stage_providers"))
    """Default for STAGE_PROVIDERS (stage no provider implicitly; see ``processing.params``)."""

    export_full_package = BoolSetting(
        default=False, description=_setting_label("export_full_package")
    )
    """Default for EXPORT_FULL_PACKAGE."""

    generate_report = BoolSetting(default=True, description=_setting_label("generate_report"))
    """Default for GENERATE_REPORT."""

    warm_start_mode = StringSetting(default="off", description=_setting_label("warm_start_mode"))
    """Default warm-start-mode token (see ``processing.params.WarmStartMode``)."""

    write_checksums = BoolSetting(default=False, description=_setting_label("write_checksums"))
    """Default for WRITE_CHECKSUMS."""
