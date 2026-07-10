"""
Parameter declarations, typed contracts and the shared default resolver (SPEC §3/§5).

One table (:data:`PARAM_SPECS`) drives everything: parameter declaration (with
``defaultValue`` computed through the resolution chain at declaration time, so the
Processing dialog shows the effective value), the project-variable naming rule
(input ``X`` → ``stratified_packager_<x_lower>``), and the runtime fallback for omitted
parameters. Resolution precedence per input: **explicit input > project variable >
plugin setting > builtin default**.

Enum-valued parameters use static string tokens (``usesStaticStrings``), so the same
tokens flow through ``qgis_process`` arguments, project variables and plugin settings
(SPEC §3 persists tokens, never indices).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Final, TypedDict, cast

from qgis.core import (
    Qgis,
    QgsMapLayer,
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingOutputNumber,
    QgsProcessingOutputString,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterExpression,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFile,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterMultipleLayers,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
    QgsProcessingParameterVectorLayer,
    QgsProviderRegistry,
)
from qgis.PyQt.QtCore import QT_TRANSLATE_NOOP, QCoreApplication

from stratified_packager.identity import PLUGIN_SLUG
from stratified_packager.toolbelt.settings import LayerVariables, ProjectVariables
from stratified_packager.toolbelt.utils import coerce_bool

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from qgis.core import (
        QgsProcessingAlgorithm,
        QgsProcessingContext,
        QgsProcessingParameterDefinition,
        QgsProject,
        QgsVectorLayer,
    )

    from stratified_packager.settings import StratifiedPackagerSettings

    from .algorithm import StratifiedPackagerAlgorithm

# ---------------------------------------------------------------------------
# Parameter / output ids (SPEC §3)
# ---------------------------------------------------------------------------

LAYERS: Final = "LAYERS"
STRATIFICATION_LAYER: Final = "STRATIFICATION_LAYER"
STRATUM_NAME_EXPRESSION: Final = "STRATUM_NAME_EXPRESSION"
STRATA_FROM_SELECTION: Final = "STRATA_FROM_SELECTION"
GPKG_PATH_EXPRESSION: Final = "GPKG_PATH_EXPRESSION"
ZIP_PATH_EXPRESSION: Final = "ZIP_PATH_EXPRESSION"
OUTPUT_DIRECTORY: Final = "OUTPUT_DIRECTORY"
COMPRESSION_LEVEL: Final = "COMPRESSION_LEVEL"
OVERWRITE_MODE: Final = "OVERWRITE_MODE"
PROJECT_INCLUSION: Final = "PROJECT_INCLUSION"
USE_TEMP_FOLDER: Final = "USE_TEMP_FOLDER"
INCLUDE_STYLES: Final = "INCLUDE_STYLES"
STYLE_CATEGORIES: Final = "STYLE_CATEGORIES"
INCLUDE_METADATA: Final = "INCLUDE_METADATA"
KEEP_EMPTY_LAYERS: Final = "KEEP_EMPTY_LAYERS"
DEDUPLICATE_SHARED_SOURCES: Final = "DEDUPLICATE_SHARED_SOURCES"
STAGE_PROVIDERS: Final = "STAGE_PROVIDERS"
EXPORT_FULL_PACKAGE: Final = "EXPORT_FULL_PACKAGE"
FULL_PACKAGE_PATH: Final = "FULL_PACKAGE_PATH"
GENERATE_REPORT: Final = "GENERATE_REPORT"
REPORT: Final = "REPORT"
EXTRA_DIR: Final = "EXTRA_DIR"
WARM_START_DIR: Final = "WARM_START_DIR"
WARM_START_MODE: Final = "WARM_START_MODE"
WRITE_CHECKSUMS: Final = "WRITE_CHECKSUMS"
DRY_RUN: Final = "DRY_RUN"

ZIP_PATHS: Final = "ZIP_PATHS"
STRATA_COUNT: Final = "STRATA_COUNT"
ZIP_COUNT: Final = "ZIP_COUNT"
FAILED_STRATA: Final = "FAILED_STRATA"

VARIABLE_PREFIX: Final = f"{PLUGIN_SLUG}_"
"""Prefix of every project/layer variable owned by this plugin."""

# Layer-scoped variables (SPEC §4), shared by the matching engine and the GUI.
LAYER_VAR_EXCLUDE: Final = f"{VARIABLE_PREFIX}exclude"
LAYER_VAR_MATCHING_METHOD: Final = f"{VARIABLE_PREFIX}matching_method"
LAYER_VAR_SPATIAL_PREDICATE: Final = f"{VARIABLE_PREFIX}spatial_predicate"
LAYER_VAR_RELATION_PATH: Final = f"{VARIABLE_PREFIX}relation_path"
LAYER_VAR_EXCLUDED_FIELDS: Final = f"{VARIABLE_PREFIX}excluded_fields"
LAYER_VAR_WARM_MARKED: Final = f"{VARIABLE_PREFIX}warm_marked"
LAYER_VAR_LAYER_NAME: Final = f"{VARIABLE_PREFIX}layer_name"
LAYER_VAR_MATERIALIZE_VIRTUAL: Final = f"{VARIABLE_PREFIX}materialize_virtual_layer"
LAYER_VAR_STAGE: Final = f"{VARIABLE_PREFIX}stage"


@dataclass(frozen=True)
class LayerVarSpec:
    """One §4 layer variable: the single source of its name, default and user-facing text."""

    name: str
    """The full ``stratified_packager_<x>`` variable name."""

    default: str
    """Builtin default, as the display token the per-layer GUI shows as a placeholder."""

    label: str
    """Short editor label (source English; translated at use in the
    ``StratifiedPackagerWidgets`` context)."""

    description: str
    """Help sentence following the variable name in the algorithm help (source English,
    HTML-fragment grade; translated at use in the ``StratifiedPackagerAlgorithm`` context)."""

    vector_only: bool = False
    """Whether the variable only applies to vector layers (its editors gate on that)."""

    virtual_only: bool = False
    """Whether the variable only applies to ``virtual``-provider layers."""

    @property
    def suffix(self) -> str:
        """
        The bare variable suffix — the GUI field tables' key.

        :return: :attr:`name` without the ``stratified_packager_`` prefix.
        """
        return self.name.removeprefix(VARIABLE_PREFIX)


LAYER_VAR_SPECS: Final[tuple[LayerVarSpec, ...]] = (
    LayerVarSpec(
        LAYER_VAR_EXCLUDE,
        "false",
        QT_TRANSLATE_NOOP("StratifiedPackagerWidgets", "Exclude layer"),
        QT_TRANSLATE_NOOP(
            "StratifiedPackagerAlgorithm", "(bool) — skip this layer when Layers is empty."
        ),
    ),
    LayerVarSpec(
        LAYER_VAR_LAYER_NAME,
        "",
        QT_TRANSLATE_NOOP("StratifiedPackagerWidgets", "Custom layer name (expression)"),
        QT_TRANSLATE_NOOP(
            "StratifiedPackagerAlgorithm",
            "(expression) — display name for this layer in the embedded per-stratum project;"
            " evaluated per stratum and may use <code>@stratum_name</code> /"
            " <code>@stratum_name_sanitized</code> (empty = original name; no effect without"
            " an embedded project).",
        ),
    ),
    LayerVarSpec(
        LAYER_VAR_MATCHING_METHOD,
        "auto",
        QT_TRANSLATE_NOOP("StratifiedPackagerWidgets", "Matching method"),
        QT_TRANSLATE_NOOP(
            "StratifiedPackagerAlgorithm", "— auto, attribute, spatial or whole_export."
        ),
        vector_only=True,
    ),
    LayerVarSpec(
        LAYER_VAR_SPATIAL_PREDICATE,
        "auto",
        QT_TRANSLATE_NOOP("StratifiedPackagerWidgets", "Spatial predicate(s)"),
        QT_TRANSLATE_NOOP(
            "StratifiedPackagerAlgorithm",
            "— auto, or a comma-separated list (combined with OR) of named predicates"
            " (intersects, contains, within, overlaps, crosses, touches) and 9-character"
            " DE-9IM patterns.",
        ),
        vector_only=True,
    ),
    LayerVarSpec(
        LAYER_VAR_EXCLUDED_FIELDS,
        "[]",
        QT_TRANSLATE_NOOP("StratifiedPackagerWidgets", "Excluded fields"),
        QT_TRANSLATE_NOOP(
            "StratifiedPackagerAlgorithm",
            "— JSON list of fields to drop from the exported table.",
        ),
        vector_only=True,
    ),
    LayerVarSpec(
        LAYER_VAR_STAGE,
        "auto",
        QT_TRANSLATE_NOOP("StratifiedPackagerWidgets", "Stage layer data"),
        QT_TRANSLATE_NOOP(
            "StratifiedPackagerAlgorithm",
            "(bool or auto) — force or forbid staging this layer's data into a local copy"
            " before the per-stratum writes; auto follows STAGE_PROVIDERS.",
        ),
        vector_only=True,
    ),
    LayerVarSpec(
        LAYER_VAR_WARM_MARKED,
        "false",
        QT_TRANSLATE_NOOP("StratifiedPackagerWidgets", "Warm-marked"),
        QT_TRANSLATE_NOOP(
            "StratifiedPackagerAlgorithm", "(bool) — layer belongs to the warm cache."
        ),
        vector_only=True,
    ),
    LayerVarSpec(
        LAYER_VAR_MATERIALIZE_VIRTUAL,
        "false",
        QT_TRANSLATE_NOOP("StratifiedPackagerWidgets", "Materialize virtual layer"),
        QT_TRANSLATE_NOOP(
            "StratifiedPackagerAlgorithm",
            "(bool) — write a virtual layer's features into each package instead of keeping"
            " the layer live (with its query) in the embedded project.",
        ),
        vector_only=True,
        virtual_only=True,
    ),
    LayerVarSpec(
        LAYER_VAR_RELATION_PATH,
        "",
        QT_TRANSLATE_NOOP("StratifiedPackagerWidgets", "Relation path (JSON ids)"),
        QT_TRANSLATE_NOOP(
            "StratifiedPackagerAlgorithm",
            "— JSON list of relation ids pinning an otherwise ambiguous attribute chain.",
        ),
        vector_only=True,
    ),
)
"""The §4 layer variables in GUI display order — the single source the field tables, the
all-layers dialog and the algorithm help build from (a new variable auto-appears in all)."""

LAYER_VARIABLE_DEFAULTS: Final[dict[str, str]] = {
    spec.name: spec.default for spec in LAYER_VAR_SPECS
}
"""Builtin defaults of the §4 layer variables, keyed by full variable name (a derived view
of :data:`LAYER_VAR_SPECS`)."""

LAYER_VARIABLE_PROPERTY_KEYS: Final[frozenset[str]] = frozenset(
    {"variableNames", "variableValues"}
)
"""Custom-property keys that backing-store layer variables write.

``QgsExpressionContextUtils.setLayerVariable(s)`` mutates the layer's
``variableNames`` / ``variableValues`` custom properties, firing
``QgsMapLayer.customPropertyChanged`` with these keys — the precise trigger for the
GUI's ``LAYERS``-prefill refresh (SPEC §5)."""


class OverwriteMode(Enum):
    """``OVERWRITE_MODE`` tokens (SPEC §3/§10)."""

    OVERWRITE = "overwrite"
    ERROR = "error"
    SKIP_EXISTING = "skip-existing"


class ProjectInclusion(Enum):
    """``PROJECT_INCLUSION`` tokens (SPEC §3/§13)."""

    NONE = "none"
    GPKG = "gpkg"
    QGZ = "qgz"


class WarmStartMode(Enum):
    """``WARM_START_MODE`` tokens (SPEC §3/§11)."""

    OFF = "off"
    USE = "use"
    UPDATE = "update"


class MatchingMethod(Enum):
    """``stratified_packager_matching_method`` tokens (SPEC §4)."""

    AUTO = "auto"
    ATTRIBUTE = "attribute"
    SPATIAL = "spatial"
    WHOLE_EXPORT = "whole_export"


NAMED_SPATIAL_PREDICATES: Final[tuple[str, ...]] = (
    "intersects",
    "contains",
    "within",
    "overlaps",
    "crosses",
    "touches",
)
"""The named ``spatial_predicate`` tokens, in display order, each mapping 1:1 onto a QGIS
expression function (SPEC §4). The single source of truth shared by the matching engine and the
defaults GUI."""

DE9IM_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[TF012*]{9}$", re.IGNORECASE)
"""Valid DE-9IM intersection-matrix patterns (SPEC §4): nine characters of ``[TF012*]``. The
T/F characters are case-insensitive (lowercase ``t``/``f`` accepted; normalized to uppercase
before the GEOS ``relate()`` call, which expects uppercase)."""


@dataclass(frozen=True)
class StyleCategoryOption:
    """One selectable QML style category, mirroring a Copy Style menu entry (SPEC §8.1)."""

    token: str
    """Static-string token persisted in inputs, project variables and settings."""

    flag: QgsMapLayer.StyleCategory
    """The :class:`~qgis.core.QgsMapLayer.StyleCategory` flag this token maps to."""

    label: str
    """Translated, user-facing label (matches the layer-tree *Copy Style* menu)."""


STYLE_CATEGORY_OPTIONS: Final[tuple[StyleCategoryOption, ...]] = (
    StyleCategoryOption(
        "layer_configuration",
        QgsMapLayer.StyleCategory.LayerConfiguration,
        QCoreApplication.translate("StratifiedPackagerAlgorithm", "Layer Configuration"),
    ),
    StyleCategoryOption(
        "symbology",
        QgsMapLayer.StyleCategory.Symbology,
        QCoreApplication.translate("StratifiedPackagerAlgorithm", "Symbology"),
    ),
    StyleCategoryOption(
        "symbology_3d",
        QgsMapLayer.StyleCategory.Symbology3D,
        QCoreApplication.translate("StratifiedPackagerAlgorithm", "3D Symbology"),
    ),
    StyleCategoryOption(
        "labeling",
        QgsMapLayer.StyleCategory.Labeling,
        QCoreApplication.translate("StratifiedPackagerAlgorithm", "Labels"),
    ),
    StyleCategoryOption(
        "fields",
        QgsMapLayer.StyleCategory.Fields,
        QCoreApplication.translate("StratifiedPackagerAlgorithm", "Fields"),
    ),
    StyleCategoryOption(
        "forms",
        QgsMapLayer.StyleCategory.Forms,
        QCoreApplication.translate("StratifiedPackagerAlgorithm", "Attribute Form"),
    ),
    StyleCategoryOption(
        "actions",
        QgsMapLayer.StyleCategory.Actions,
        QCoreApplication.translate("StratifiedPackagerAlgorithm", "Actions"),
    ),
    StyleCategoryOption(
        "map_tips",
        QgsMapLayer.StyleCategory.MapTips,
        QCoreApplication.translate("StratifiedPackagerAlgorithm", "Map Tips"),
    ),
    StyleCategoryOption(
        "diagrams",
        QgsMapLayer.StyleCategory.Diagrams,
        QCoreApplication.translate("StratifiedPackagerAlgorithm", "Diagrams"),
    ),
    StyleCategoryOption(
        "attribute_table",
        QgsMapLayer.StyleCategory.AttributeTable,
        QCoreApplication.translate("StratifiedPackagerAlgorithm", "Attribute Table Configuration"),
    ),
    StyleCategoryOption(
        "rendering",
        QgsMapLayer.StyleCategory.Rendering,
        QCoreApplication.translate("StratifiedPackagerAlgorithm", "Rendering"),
    ),
    StyleCategoryOption(
        "custom_properties",
        QgsMapLayer.StyleCategory.CustomProperties,
        QCoreApplication.translate("StratifiedPackagerAlgorithm", "Custom Properties"),
    ),
    StyleCategoryOption(
        "geometry_options",
        QgsMapLayer.StyleCategory.GeometryOptions,
        QCoreApplication.translate("StratifiedPackagerAlgorithm", "Geometry Options"),
    ),
    StyleCategoryOption(
        "relations",
        QgsMapLayer.StyleCategory.Relations,
        QCoreApplication.translate("StratifiedPackagerAlgorithm", "Relations"),
    ),
    StyleCategoryOption(
        "temporal",
        QgsMapLayer.StyleCategory.Temporal,
        QCoreApplication.translate("StratifiedPackagerAlgorithm", "Temporal Properties"),
    ),
    StyleCategoryOption(
        "legend",
        QgsMapLayer.StyleCategory.Legend,
        QCoreApplication.translate("StratifiedPackagerAlgorithm", "Legend Settings"),
    ),
    StyleCategoryOption(
        "elevation",
        QgsMapLayer.StyleCategory.Elevation,
        QCoreApplication.translate("StratifiedPackagerAlgorithm", "Elevation Properties"),
    ),
    StyleCategoryOption(
        "notes",
        QgsMapLayer.StyleCategory.Notes,
        QCoreApplication.translate("StratifiedPackagerAlgorithm", "Notes"),
    ),
)
"""The single-bit :class:`~qgis.core.QgsMapLayer.StyleCategory` flags, in QGIS bit order,
as offered by the layer-tree *Copy Style* menu (the ``All*`` combinations are excluded)."""

STYLE_CATEGORY_TOKENS: Final[tuple[str, ...]] = tuple(o.token for o in STYLE_CATEGORY_OPTIONS)
"""Every style-category token in canonical (bit) order."""

DEFAULT_STYLE_CATEGORIES: Final[list[str]] = list(STYLE_CATEGORY_TOKENS)
"""Builtin ``STYLE_CATEGORIES`` default: every category (SPEC §3)."""

_STYLE_CATEGORY_BY_TOKEN: Final[dict[str, StyleCategoryOption]] = {
    o.token: o for o in STYLE_CATEGORY_OPTIONS
}


def style_categories_flags(tokens: Iterable[str], /) -> QgsMapLayer.StyleCategory:
    """
    OR the selected style-category tokens into a flag set (SPEC §8.1).

    An empty (or all-unknown) selection yields ``AllStyleCategories`` — the documented
    *select-none means select-all* rule; ``INCLUDE_STYLES=False`` is the real off switch.
    Unknown tokens are ignored here (the resolver validates them upstream).

    :param tokens: The selected category tokens.
    :return: The OR of the matching flags, or ``AllStyleCategories`` when none match.
    """
    selected = [_STYLE_CATEGORY_BY_TOKEN[t].flag for t in tokens if t in _STYLE_CATEGORY_BY_TOKEN]
    if not selected:
        return QgsMapLayer.StyleCategory.AllStyleCategories
    combined = 0
    for flag in selected:
        combined |= int(flag)
    return QgsMapLayer.StyleCategory(combined)


DEFAULT_STAGE_PROVIDERS: Final[list[str]] = []
"""Builtin ``STAGE_PROVIDERS`` default: no provider is staged implicitly (SPEC §3/§8.2)."""


def provider_keys() -> list[str]:
    """
    List the data-provider keys the ``STAGE_PROVIDERS`` multi-select offers.

    :return: The provider registry's keys, sorted.
    :raise RuntimeError: If the provider registry is unavailable (QGIS not initialized).
    """
    registry = QgsProviderRegistry.instance()
    if registry is None:  # only reachable outside a running QGIS
        msg = "QgsProviderRegistry is unavailable — QGIS is not initialized."
        raise RuntimeError(msg)
    return sorted(registry.providerList())


def variable_name(param: str, /) -> str:
    """
    Map an input id to its project variable name (SPEC §3 naming rule).

    :param param: The parameter id (e.g. ``COMPRESSION_LEVEL``).
    :return: ``stratified_packager_<param_lower>``.
    """
    return f"{VARIABLE_PREFIX}{param.lower()}"


# ---------------------------------------------------------------------------
# Typed contracts
# ---------------------------------------------------------------------------


class StratifiedPackagerAlgorithmInputDict(TypedDict, total=False):
    """Typed parameter map for Python callers of the algorithm (SPEC §3)."""

    LAYERS: Sequence[QgsMapLayer | str]
    STRATIFICATION_LAYER: QgsVectorLayer | str
    STRATUM_NAME_EXPRESSION: str
    STRATA_FROM_SELECTION: bool
    GPKG_PATH_EXPRESSION: str
    ZIP_PATH_EXPRESSION: str
    OUTPUT_DIRECTORY: str
    COMPRESSION_LEVEL: int
    OVERWRITE_MODE: str
    PROJECT_INCLUSION: str
    USE_TEMP_FOLDER: bool
    INCLUDE_STYLES: bool
    STYLE_CATEGORIES: Sequence[str]
    INCLUDE_METADATA: bool
    KEEP_EMPTY_LAYERS: bool
    DEDUPLICATE_SHARED_SOURCES: bool
    STAGE_PROVIDERS: Sequence[str]
    EXPORT_FULL_PACKAGE: bool
    FULL_PACKAGE_PATH: str
    GENERATE_REPORT: bool
    REPORT: str
    EXTRA_DIR: str
    WARM_START_DIR: str
    WARM_START_MODE: str
    WRITE_CHECKSUMS: bool
    DRY_RUN: bool


class StratifiedPackagerAlgorithmOutputDict(TypedDict):
    """Typed result map returned by the algorithm (SPEC §3 declared outputs)."""

    OUTPUT_DIRECTORY: str
    REPORT: str
    ZIP_PATHS: str
    STRATA_COUNT: int
    ZIP_COUNT: int
    FAILED_STRATA: str


# ---------------------------------------------------------------------------
# The spec table driving declaration and resolution
# ---------------------------------------------------------------------------


class _Kind(Enum):
    """Coercion kind of a parameter's variable/setting values."""

    BOOL = "bool"
    INT = "int"
    STRING = "string"
    OVERWRITE = "overwrite"
    INCLUSION = "inclusion"
    WARM = "warm"
    LAYER_LIST = "layer_list"
    STYLE_CATEGORIES = "style_categories"
    PROVIDER_LIST = "provider_list"


@dataclass(frozen=True)
class ParamSpec:
    """Declaration/resolution facts of one input (one row of the SPEC §3 table)."""

    name: str
    """Parameter id."""

    kind: _Kind
    """Coercion kind for variable/setting values."""

    builtin: object
    """Builtin default (the last tier of the resolution chain)."""

    label: str = ""
    """User-facing text of the input (source English, authored with
    :func:`~qgis.PyQt.QtCore.QT_TRANSLATE_NOOP`): the Processing-dialog description, reused
    verbatim as the Options-page label and the plugin-setting description, so the three
    surfaces cannot drift. Translated at use in the ``StratifiedPackagerAlgorithm``
    context."""

    setting: str | None = None
    """Attribute name on :class:`~stratified_packager.settings.StratifiedPackagerSettings`
    (only the ✓ rows of SPEC §3)."""

    has_variable: bool = True
    """Whether the input has a project variable (every non-multiple-layers input)."""

    @property
    def variable(self) -> str | None:
        """
        The project variable name, or :data:`None` for exempt inputs.

        :return: ``stratified_packager_<name_lower>`` or :data:`None`.
        """
        return variable_name(self.name) if self.has_variable else None


_ALG: Final = "StratifiedPackagerAlgorithm"
"""Translation context of every algorithm-facing string (labels, help, messages). Used as the
runtime :meth:`~qgis.PyQt.QtCore.QCoreApplication.translate` context; extraction sites
(:func:`~qgis.PyQt.QtCore.QT_TRANSLATE_NOOP`) MUST spell the literal instead, because
``pylupdate`` statically parses the context argument and silently drops a variable one."""

PARAM_SPECS: Final[dict[str, ParamSpec]] = {
    spec.name: spec
    for spec in (
        ParamSpec(
            LAYERS,
            _Kind.LAYER_LIST,
            builtin=None,
            label=QT_TRANSLATE_NOOP(
                "StratifiedPackagerAlgorithm", "Layers to package (empty = all eligible layers)"
            ),
            has_variable=False,
        ),
        ParamSpec(
            STRATIFICATION_LAYER,
            _Kind.STRING,
            builtin=None,
            label=QT_TRANSLATE_NOOP(
                "StratifiedPackagerAlgorithm", "Stratification layer (one stratum per feature)"
            ),
        ),
        ParamSpec(
            STRATUM_NAME_EXPRESSION,
            _Kind.STRING,
            builtin="",
            label=QT_TRANSLATE_NOOP(
                "StratifiedPackagerAlgorithm", "Stratum name expression (empty = feature id)"
            ),
        ),
        ParamSpec(
            STRATA_FROM_SELECTION,
            _Kind.BOOL,
            builtin=False,
            label=QT_TRANSLATE_NOOP(
                "StratifiedPackagerAlgorithm",
                "Only selected stratification features become strata",
            ),
        ),
        ParamSpec(
            GPKG_PATH_EXPRESSION,
            _Kind.STRING,
            builtin="",
            label=QT_TRANSLATE_NOOP(
                "StratifiedPackagerAlgorithm",
                "GeoPackage path expression (empty = sanitized stratum name)",
            ),
            setting="gpkg_path_expression",
        ),
        ParamSpec(
            ZIP_PATH_EXPRESSION,
            _Kind.STRING,
            builtin="",
            label=QT_TRANSLATE_NOOP(
                "StratifiedPackagerAlgorithm", "Zip path expression (empty = GeoPackage name)"
            ),
            setting="zip_path_expression",
        ),
        ParamSpec(
            OUTPUT_DIRECTORY,
            _Kind.STRING,
            builtin=None,
            label=QT_TRANSLATE_NOOP("StratifiedPackagerAlgorithm", "Output directory"),
        ),
        ParamSpec(
            COMPRESSION_LEVEL,
            _Kind.INT,
            builtin=6,
            label=QT_TRANSLATE_NOOP(
                "StratifiedPackagerAlgorithm", "Zip compression level (0 = store uncompressed)"
            ),
            setting="compression_level",
        ),
        ParamSpec(
            OVERWRITE_MODE,
            _Kind.OVERWRITE,
            builtin=OverwriteMode.OVERWRITE.value,
            label=QT_TRANSLATE_NOOP("StratifiedPackagerAlgorithm", "Existing outputs"),
            setting="overwrite_mode",
        ),
        ParamSpec(
            PROJECT_INCLUSION,
            _Kind.INCLUSION,
            builtin=ProjectInclusion.NONE.value,
            label=QT_TRANSLATE_NOOP(
                "StratifiedPackagerAlgorithm", "Embed a QGIS project per stratum"
            ),
            setting="project_inclusion",
        ),
        ParamSpec(
            USE_TEMP_FOLDER,
            _Kind.BOOL,
            builtin=True,
            label=QT_TRANSLATE_NOOP(
                "StratifiedPackagerAlgorithm",
                "Build in a temporary folder, publish zips atomically",
            ),
            setting="use_temp_folder",
        ),
        ParamSpec(
            INCLUDE_STYLES,
            _Kind.BOOL,
            builtin=True,
            label=QT_TRANSLATE_NOOP("StratifiedPackagerAlgorithm", "Include layer styles"),
            setting="include_styles",
        ),
        ParamSpec(
            STYLE_CATEGORIES,
            _Kind.STYLE_CATEGORIES,
            builtin=DEFAULT_STYLE_CATEGORIES,
            label=QT_TRANSLATE_NOOP(
                "StratifiedPackagerAlgorithm", "Style categories to copy (none checked = all)"
            ),
            setting="style_categories",
        ),
        ParamSpec(
            INCLUDE_METADATA,
            _Kind.BOOL,
            builtin=True,
            label=QT_TRANSLATE_NOOP("StratifiedPackagerAlgorithm", "Include layer metadata"),
            setting="include_metadata",
        ),
        ParamSpec(
            KEEP_EMPTY_LAYERS,
            _Kind.BOOL,
            builtin=True,
            label=QT_TRANSLATE_NOOP(
                "StratifiedPackagerAlgorithm",
                "Keep layers with no matching features as empty tables",
            ),
            setting="keep_empty_layers",
        ),
        ParamSpec(
            DEDUPLICATE_SHARED_SOURCES,
            _Kind.BOOL,
            builtin=True,
            label=QT_TRANSLATE_NOOP(
                "StratifiedPackagerAlgorithm", "Write layers sharing a data source as one table"
            ),
            setting="deduplicate_shared_sources",
        ),
        ParamSpec(
            STAGE_PROVIDERS,
            _Kind.PROVIDER_LIST,
            builtin=DEFAULT_STAGE_PROVIDERS,
            label=QT_TRANSLATE_NOOP(
                "StratifiedPackagerAlgorithm",
                "Stage every layer of these data providers (see the stage layer variable)",
            ),
            setting="stage_providers",
        ),
        ParamSpec(
            EXPORT_FULL_PACKAGE,
            _Kind.BOOL,
            builtin=False,
            label=QT_TRANSLATE_NOOP(
                "StratifiedPackagerAlgorithm", "Also export the full (unpartitioned) package"
            ),
            setting="export_full_package",
        ),
        ParamSpec(
            FULL_PACKAGE_PATH,
            _Kind.STRING,
            builtin="",
            label=QT_TRANSLATE_NOOP(
                "StratifiedPackagerAlgorithm", "Full package path (empty = <project name>_full)"
            ),
        ),
        ParamSpec(
            GENERATE_REPORT,
            _Kind.BOOL,
            builtin=True,
            label=QT_TRANSLATE_NOOP(
                "StratifiedPackagerAlgorithm", "Write a report.csv into each published zip"
            ),
            setting="generate_report",
        ),
        ParamSpec(
            EXTRA_DIR,
            _Kind.STRING,
            builtin=None,
            label=QT_TRANSLATE_NOOP(
                "StratifiedPackagerAlgorithm", "Extra files directory (copied into every zip root)"
            ),
        ),
        ParamSpec(
            WARM_START_DIR,
            _Kind.STRING,
            builtin=None,
            label=QT_TRANSLATE_NOOP("StratifiedPackagerAlgorithm", "Warm cache directory"),
        ),
        ParamSpec(
            WARM_START_MODE,
            _Kind.WARM,
            builtin=WarmStartMode.OFF.value,
            label=QT_TRANSLATE_NOOP("StratifiedPackagerAlgorithm", "Warm cache mode"),
            setting="warm_start_mode",
        ),
        ParamSpec(
            WRITE_CHECKSUMS,
            _Kind.BOOL,
            builtin=False,
            label=QT_TRANSLATE_NOOP(
                "StratifiedPackagerAlgorithm", "Write a .sha256 file next to each zip"
            ),
            setting="write_checksums",
        ),
        ParamSpec(
            DRY_RUN,
            _Kind.BOOL,
            builtin=False,
            label=QT_TRANSLATE_NOOP(
                "StratifiedPackagerAlgorithm",
                "Dry run (validate and report only, write no packages)",
            ),
        ),
    )
}
"""Every input of SPEC §3, keyed by id, in declaration order."""


def translated_label(name: str, /) -> str:
    """
    Return an input's translated user-facing label.

    :param name: The parameter id.
    :return: The :attr:`ParamSpec.label` translated in the algorithm context.
    """
    return QCoreApplication.translate(_ALG, PARAM_SPECS[name].label)


def _coerce_style_categories(raw: object) -> list[str]:
    """
    Interpret a stored value as a list of style-category tokens.

    Accepts a comma-separated string (the variable/setting form), a list/tuple (the
    builtin/explicit form) or a bare token; blanks are dropped and the result is returned
    in canonical order without duplicates.

    :param raw: The raw stored value.
    :return: The validated tokens in canonical order.
    :raise ValueError: If any token is not a known style category.
    """
    if isinstance(raw, (list, tuple)):
        items = [str(item).strip() for item in raw]
    else:
        items = [token.strip() for token in str(raw).split(",")]
    tokens = {token for token in items if token}
    if unknown := sorted(tokens - set(STYLE_CATEGORY_TOKENS)):
        msg = f"unknown style category token(s): {', '.join(unknown)}"
        raise ValueError(msg)
    return [token for token in STYLE_CATEGORY_TOKENS if token in tokens]


def _coerce_provider_list(raw: object) -> list[str]:
    """
    Interpret a stored value as a list of data-provider keys.

    Accepts a comma-separated string (the variable/setting form), a list/tuple (the
    builtin/explicit form) or a bare key; blanks are dropped and the result is returned
    sorted without duplicates.

    :param raw: The raw stored value.
    :return: The validated provider keys, sorted.
    :raise ValueError: If any key is not a registered data provider.
    """
    if isinstance(raw, (list, tuple)):
        items = [str(item).strip() for item in raw]
    else:
        items = [token.strip() for token in str(raw).split(",")]
    keys = {token for token in items if token}
    if unknown := sorted(keys - set(provider_keys())):
        msg = f"unknown data provider key(s): {', '.join(unknown)}"
        raise ValueError(msg)
    return sorted(keys)


def _coerce(kind: _Kind, raw: object) -> object:
    """
    Coerce a project-variable (or stored-setting) value to its parameter type.

    :param kind: The parameter's coercion kind.
    :param raw: The raw stored value.
    :return: The coerced value.
    :raise ValueError: If *raw* cannot represent the kind (bad boolean/integer/token).
    """
    result: object
    match kind:
        case _Kind.BOOL:
            result = coerce_bool(raw)
        case _Kind.INT:
            result = int(str(raw).strip())
        case _Kind.OVERWRITE:
            result = OverwriteMode(str(raw).strip()).value
        case _Kind.INCLUSION:
            result = ProjectInclusion(str(raw).strip()).value
        case _Kind.WARM:
            result = WarmStartMode(str(raw).strip()).value
        case _Kind.STYLE_CATEGORIES:
            result = _coerce_style_categories(raw)
        case _Kind.PROVIDER_LIST:
            result = _coerce_provider_list(raw)
        case _:
            result = str(raw)
    return result


def resolve_default(
    name: str,
    *,
    project: QgsProject | None = None,
    settings: StratifiedPackagerSettings | None = None,
    strict: bool = True,
) -> object:
    """
    Resolve the effective default of one input: project variable > setting > builtin.

    This is the shared tail of the SPEC §5 chain — explicit inputs are handled by the
    caller before consulting it. With ``strict=False`` (declaration-time prefill) an
    unusable stored value silently falls through to the next tier; with ``strict=True``
    (runtime fallback) it raises so the run aborts loudly instead of guessing.

    :param name: The parameter id.
    :param project: Project whose ``stratified_packager_<x>`` variable to consult.
    :param settings: Plugin settings to consult (the ✓ rows of SPEC §3).
    :param strict: Whether unusable stored values raise instead of falling through.
    :return: The resolved default (possibly :data:`None` for layer-ish inputs).
    :raise ValueError: If ``strict`` and a stored value cannot be coerced; the message
        names the parameter and the offending tier.
    """
    spec = PARAM_SPECS[name]
    if spec.variable is not None and project is not None:
        raw = ProjectVariables(project=project).get(spec.variable)
        if raw is not None and str(raw) != "":
            try:
                return _coerce(spec.kind, raw)
            except ValueError as err:
                if strict:
                    msg = f"project variable {spec.variable!r}: {err}"
                    raise ValueError(msg) from err
    if spec.setting is not None and settings is not None:
        raw = getattr(settings, spec.setting)
        # An empty stored value means unset and falls through to the builtin,
        # mirroring the project-variable tier above.
        if raw is not None and str(raw) != "":
            try:
                return _coerce(spec.kind, raw)
            except ValueError as err:
                if strict:
                    msg = f"plugin setting {spec.setting!r}: {err}"
                    raise ValueError(msg) from err
    return spec.builtin


def is_omitted(parameters: Mapping[str | None, Any], name: str, /) -> bool:
    """
    Report whether an input was omitted (absent or :data:`None`) by the caller.

    The GUI supplies every input, so this is the headless/model path detector that
    gates the runtime fallback of SPEC §5.

    :param parameters: The raw parameter map handed to the algorithm.
    :param name: The parameter id.
    :return: :data:`True` when the runtime fallback should resolve the value.
    """
    return name not in parameters or parameters[name] is None


class InputReader:
    """Reads single inputs through the §5 chain: explicit > variable > setting > builtin."""

    def __init__(
        self,
        algorithm: StratifiedPackagerAlgorithm,
        parameters: dict[str | None, Any],
        context: QgsProcessingContext,
        project: QgsProject,
        settings: StratifiedPackagerSettings,
    ) -> None:
        """
        Initialize the reader.

        :param algorithm: The running algorithm (parameter extraction + translation).
        :param parameters: Raw parameter values.
        :param context: The processing context.
        :param project: The run's project.
        :param settings: The plugin settings.
        """
        self._algorithm = algorithm
        self._parameters = parameters
        self._context = context
        self._project = project
        self._settings = settings

    def fallback(self, name: str) -> object:
        """
        Resolve an omitted input through variable > setting > builtin (strict).

        :param name: The parameter id.
        :return: The resolved default.
        :raise QgsProcessingException: On unusable stored values.
        """
        try:
            return resolve_default(name, project=self._project, settings=self._settings)
        except ValueError as err:
            raise QgsProcessingException(
                self._algorithm.tr("Cannot resolve {}: {}").format(name, err)
            ) from err

    def string(self, name: str) -> str:
        """
        Resolve a string input.

        :param name: The parameter id.
        :return: The resolved string (empty when nothing resolves).
        """
        if is_omitted(self._parameters, name):
            return str(self.fallback(name) or "")
        return self._algorithm.parameterAsString(self._parameters, name, self._context)

    def boolean(self, name: str) -> bool:
        """
        Resolve a boolean input.

        :param name: The parameter id.
        :return: The resolved boolean.
        """
        if is_omitted(self._parameters, name):
            return bool(self.fallback(name))
        return self._algorithm.parameterAsBoolean(self._parameters, name, self._context)

    def integer(self, name: str) -> int:
        """
        Resolve an integer input.

        :param name: The parameter id.
        :return: The resolved integer.
        """
        if is_omitted(self._parameters, name):
            return int(cast("int", self.fallback(name)))
        return self._algorithm.parameterAsInt(self._parameters, name, self._context)

    def enum_strings(self, name: str) -> list[str]:
        """
        Resolve a multi-select static-strings enum input to its token list.

        :param name: The parameter id.
        :return: The selected tokens (the resolved default when omitted).
        """
        if is_omitted(self._parameters, name):
            fallback = self.fallback(name)
            return [str(item) for item in fallback] if isinstance(fallback, list) else []
        return self._algorithm.parameterAsEnumStrings(self._parameters, name, self._context)


def eligible_layer_ids(project: QgsProject, /, *, strict: bool = False) -> list[str]:
    """
    Return the layers an empty ``LAYERS`` input resolves to (SPEC §4/§5).

    Eligible = every project layer except plugin layers, minus layers whose
    ``stratified_packager_exclude`` variable is true. An unset value counts as included
    (the default: participate). A value that cannot be coerced to bool is treated like
    every other run-start config in the strict regime (cf. :func:`resolve_default`) via
    ``strict``: with ``strict=True`` (runtime resolution) it raises so the run aborts
    loudly instead of guessing inclusion; with ``strict=False`` (declaration-time
    ``LAYERS`` prefill) it falls back to included, because the runtime path re-checks
    strictly.

    :param project: The project to scan.
    :param strict: Whether an uncoercible ``exclude`` value raises instead of including.
    :return: Layer ids in layer-tree iteration order.
    :raise ValueError: If ``strict`` and a layer's ``exclude`` value cannot be coerced to
        bool; the message names the layer and the offending value.
    """
    ids: list[str] = []
    for layer in project.mapLayers().values():
        if layer.type() == Qgis.LayerType.Plugin:
            continue
        raw = LayerVariables(layer).get(LAYER_VAR_EXCLUDE)
        try:
            exclude = bool(_coerce(_Kind.BOOL, raw)) if raw is not None else False
        except ValueError as err:
            if strict:
                msg = f"layer {layer.name()!r}: exclude variable {raw!r}: {err}"
                raise ValueError(msg) from err
            exclude = False
        if not exclude:
            ids.append(layer.id())
    return ids


# ---------------------------------------------------------------------------
# Declaration (SPEC §3 table; defaults resolved through the chain)
# ---------------------------------------------------------------------------


def declare_parameters(
    algorithm: QgsProcessingAlgorithm,
    *,
    project: QgsProject | None = None,
    settings: StratifiedPackagerSettings | None = None,
) -> None:
    """
    Declare every SPEC §3 input on *algorithm*, defaults pre-resolved (SPEC §5).

    :param algorithm: The algorithm being initialized.
    :param project: Project consulted for variable-tier defaults (omit headless-safe).
    :param settings: Plugin settings consulted for setting-tier defaults.
    """

    def default(name: str) -> object:
        return resolve_default(name, project=project, settings=settings, strict=False)

    def add(parameter: QgsProcessingParameterDefinition, *, advanced: bool = False) -> None:
        if advanced:
            parameter.setFlags(parameter.flags() | Qgis.ProcessingParameterFlag.Advanced)
        if not algorithm.addParameter(parameter):
            msg = f"QGIS rejected the declaration of parameter {parameter.name()!r}."
            raise ValueError(msg)

    layers_default = eligible_layer_ids(project) if project is not None else None
    add(
        QgsProcessingParameterMultipleLayers(
            LAYERS,
            translated_label(LAYERS),
            # Scoped-enum access verified on QGIS 4.0.3; the bundled stubs lag it.
            QgsProcessing.SourceType.TypeMapLayer,  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
            defaultValue=layers_default,
            optional=True,
        )
    )
    add(
        QgsProcessingParameterVectorLayer(
            STRATIFICATION_LAYER,
            translated_label(STRATIFICATION_LAYER),
            # TypeVector admits geometryless tables (SPEC §3 footnote on the strat layer).
            # Scoped-enum access verified on QGIS 4.0.3; the bundled stubs lag it.
            types=[QgsProcessing.SourceType.TypeVector],  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
            optional=True,
        )
    )
    add(
        QgsProcessingParameterExpression(
            STRATUM_NAME_EXPRESSION,
            translated_label(STRATUM_NAME_EXPRESSION),
            defaultValue=default(STRATUM_NAME_EXPRESSION),
            parentLayerParameterName=STRATIFICATION_LAYER,
            optional=True,
        )
    )
    add(
        QgsProcessingParameterBoolean(
            STRATA_FROM_SELECTION,
            translated_label(STRATA_FROM_SELECTION),
            defaultValue=default(STRATA_FROM_SELECTION),
        )
    )
    add(
        QgsProcessingParameterExpression(
            GPKG_PATH_EXPRESSION,
            translated_label(GPKG_PATH_EXPRESSION),
            defaultValue=default(GPKG_PATH_EXPRESSION),
            parentLayerParameterName=STRATIFICATION_LAYER,
            optional=True,
        ),
        advanced=True,
    )
    add(
        QgsProcessingParameterExpression(
            ZIP_PATH_EXPRESSION,
            translated_label(ZIP_PATH_EXPRESSION),
            defaultValue=default(ZIP_PATH_EXPRESSION),
            parentLayerParameterName=STRATIFICATION_LAYER,
            optional=True,
        ),
        advanced=True,
    )
    add(
        QgsProcessingParameterFolderDestination(
            OUTPUT_DIRECTORY,
            translated_label(OUTPUT_DIRECTORY),
        )
    )
    add(
        QgsProcessingParameterNumber(
            COMPRESSION_LEVEL,
            translated_label(COMPRESSION_LEVEL),
            Qgis.ProcessingNumberParameterType.Integer,
            defaultValue=default(COMPRESSION_LEVEL),
            minValue=0,
            maxValue=9,
        ),
        advanced=True,
    )
    add(
        _static_enum(
            OVERWRITE_MODE,
            translated_label(OVERWRITE_MODE),
            OverwriteMode,
            str(default(OVERWRITE_MODE)),
        )
    )
    add(
        _static_enum(
            PROJECT_INCLUSION,
            translated_label(PROJECT_INCLUSION),
            ProjectInclusion,
            str(default(PROJECT_INCLUSION)),
        )
    )
    add(
        QgsProcessingParameterBoolean(
            USE_TEMP_FOLDER,
            translated_label(USE_TEMP_FOLDER),
            defaultValue=default(USE_TEMP_FOLDER),
        ),
        advanced=True,
    )
    add(
        QgsProcessingParameterBoolean(
            INCLUDE_STYLES,
            translated_label(INCLUDE_STYLES),
            defaultValue=default(INCLUDE_STYLES),
        )
    )
    add(
        _static_multi_enum(
            STYLE_CATEGORIES,
            translated_label(STYLE_CATEGORIES),
            default(STYLE_CATEGORIES),
            STYLE_CATEGORY_TOKENS,
        ),
        advanced=True,
    )
    add(
        QgsProcessingParameterBoolean(
            INCLUDE_METADATA,
            translated_label(INCLUDE_METADATA),
            defaultValue=default(INCLUDE_METADATA),
        )
    )
    add(
        QgsProcessingParameterBoolean(
            KEEP_EMPTY_LAYERS,
            translated_label(KEEP_EMPTY_LAYERS),
            defaultValue=default(KEEP_EMPTY_LAYERS),
        )
    )
    add(
        QgsProcessingParameterBoolean(
            DEDUPLICATE_SHARED_SOURCES,
            translated_label(DEDUPLICATE_SHARED_SOURCES),
            defaultValue=default(DEDUPLICATE_SHARED_SOURCES),
        ),
        advanced=True,
    )
    add(
        _static_multi_enum(
            STAGE_PROVIDERS,
            translated_label(STAGE_PROVIDERS),
            default(STAGE_PROVIDERS),
            provider_keys(),
        ),
        advanced=True,
    )
    add(
        QgsProcessingParameterBoolean(
            EXPORT_FULL_PACKAGE,
            translated_label(EXPORT_FULL_PACKAGE),
            defaultValue=default(EXPORT_FULL_PACKAGE),
        )
    )
    add(
        QgsProcessingParameterString(
            FULL_PACKAGE_PATH,
            translated_label(FULL_PACKAGE_PATH),
            defaultValue=default(FULL_PACKAGE_PATH),
            optional=True,
        ),
        advanced=True,
    )
    add(
        QgsProcessingParameterBoolean(
            GENERATE_REPORT,
            translated_label(GENERATE_REPORT),
            defaultValue=default(GENERATE_REPORT),
        )
    )
    add(
        QgsProcessingParameterFeatureSink(
            REPORT,
            QCoreApplication.translate(
                "StratifiedPackagerAlgorithm",
                "Run report (loaded as a memory layer when no path is given)",
            ),
            # TypeVector admits the geometryless run-report table.
            # Scoped-enum access verified on QGIS 4.0.3; the bundled stubs lag it.
            type=QgsProcessing.SourceType.TypeVector,  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
            createByDefault=True,
            # The sink itself stays required (§9.1: always produced), but the default
            # keeps the parameter omittable on qgis_process, matching §3's "no path ⇒
            # memory/temporary destination" (the GUI's createByDefault covers only itself).
            defaultValue=QgsProcessing.TEMPORARY_OUTPUT,
            optional=False,
        )
    )
    add(
        QgsProcessingParameterFile(
            EXTRA_DIR,
            translated_label(EXTRA_DIR),
            behavior=Qgis.ProcessingFileParameterBehavior.Folder,
            optional=True,
        ),
        advanced=True,
    )
    add(
        QgsProcessingParameterFile(
            WARM_START_DIR,
            translated_label(WARM_START_DIR),
            behavior=Qgis.ProcessingFileParameterBehavior.Folder,
            optional=True,
        ),
        advanced=True,
    )
    add(
        _static_enum(
            WARM_START_MODE,
            translated_label(WARM_START_MODE),
            WarmStartMode,
            str(default(WARM_START_MODE)),
        ),
        advanced=True,
    )
    add(
        QgsProcessingParameterBoolean(
            WRITE_CHECKSUMS,
            translated_label(WRITE_CHECKSUMS),
            defaultValue=default(WRITE_CHECKSUMS),
        ),
        advanced=True,
    )
    add(
        QgsProcessingParameterBoolean(
            DRY_RUN,
            translated_label(DRY_RUN),
            defaultValue=default(DRY_RUN),
        )
    )


def _static_enum(
    name: str, description: str, enum_type: type[Enum], default_token: str
) -> QgsProcessingParameterEnum:
    """
    Build a static-strings enum parameter whose options are the SPEC tokens.

    :param name: Parameter id.
    :param description: Translated description.
    :param enum_type: The token enum.
    :param default_token: The resolved default token.
    :return: The parameter definition.
    """
    return QgsProcessingParameterEnum(
        name,
        description,
        options=[member.value for member in enum_type],
        defaultValue=default_token,
        usesStaticStrings=True,
    )


def _static_multi_enum(
    name: str, description: str, default_value: object, options: Sequence[str]
) -> QgsProcessingParameterEnum:
    """
    Build an optional multi-select static-strings enum over *options*.

    The parameter is optional so a fully-unchecked selection is accepted; what an empty
    selection means is the resolver's business (e.g. *all categories* for
    ``STYLE_CATEGORIES``, *stage nothing implicitly* for ``STAGE_PROVIDERS``).

    :param name: Parameter id.
    :param description: Translated description.
    :param default_value: The resolved default tokens (a list of tokens).
    :param options: The selectable tokens.
    :return: The parameter definition.
    """
    return QgsProcessingParameterEnum(
        name,
        description,
        options=list(options),
        defaultValue=default_value,
        usesStaticStrings=True,
        allowMultiple=True,
        optional=True,
    )


def declare_outputs(algorithm: QgsProcessingAlgorithm) -> None:
    """
    Declare the SPEC §3 outputs on *algorithm*.

    :param algorithm: The algorithm being initialized.
    :raise ValueError: If QGIS rejects an output declaration.
    """
    # OUTPUT_DIRECTORY's folder output and REPORT's layer output are auto-declared by
    # their destination parameters (a folder destination, a feature sink).
    outputs = (
        QgsProcessingOutputString(
            ZIP_PATHS,
            QCoreApplication.translate(
                "StratifiedPackagerAlgorithm", "Published zip paths (JSON array)"
            ),
        ),
        QgsProcessingOutputNumber(
            STRATA_COUNT,
            QCoreApplication.translate("StratifiedPackagerAlgorithm", "Strata resolved"),
        ),
        QgsProcessingOutputNumber(
            ZIP_COUNT, QCoreApplication.translate("StratifiedPackagerAlgorithm", "Zips published")
        ),
        QgsProcessingOutputString(
            FAILED_STRATA,
            QCoreApplication.translate(
                "StratifiedPackagerAlgorithm", "Failed strata (JSON array)"
            ),
        ),
    )
    for output in outputs:
        # addOutput takes ownership and deletes rejected objects: capture the name first.
        name = output.name()
        if not algorithm.addOutput(output):
            msg = f"QGIS rejected the declaration of output {name!r}."
            raise ValueError(msg)
