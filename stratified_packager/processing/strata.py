"""
Strata resolution: snapshot, strict naming, gpkg/zip path evaluation, bundling (SPEC §6).

Runs on the algorithm thread during Phase A. Every fatal condition raises
:exc:`~qgis.core.QgsProcessingException` (the Processing framework's sanctioned failure
path); names and paths are validated, never silently rewritten.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Final, cast

from qgis.core import (
    QgsExpression,
    QgsExpressionContext,
    QgsExpressionContextScope,
    QgsExpressionContextUtils,
    QgsProcessingException,
)
from qgis.PyQt.QtCore import QCoreApplication

from stratified_packager.identity import PLUGIN_SLUG
from stratified_packager.toolbelt.utils import sanitize_filename
from stratified_packager.toolbelt.zipping import case_insensitive_collisions, split_archive_path

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from qgis.core import QgsFeature, QgsMapLayer, QgsProject, QgsVectorLayer

__all__: list[str] = [
    "StrataResolution",
    "StratumSpec",
    "bundle_strata",
    "evaluate_layer_display_name",
    "resolve_strata",
]

FULL_PACKAGE_KEY: Final = "<full>"
"""Pseudo-stratum key of the full package (SPEC §2/§11); sanitization strips ``<``/``>``,
so no real stratum can collide with it."""


@dataclass(frozen=True)
class StratumSpec:
    """One resolved stratum (plain data; safe to hand across threads)."""

    feature_id: int
    """Feature id of the stratum feature in the stratification layer."""

    raw_name: str
    """The evaluated (unsanitized) stratum name."""

    name: str
    """The sanitized stratum name — filename-grade, also the warm-cache key (SPEC §11)."""

    gpkg_rel: str
    """Zip-internal gpkg path, slash-separated, without the ``.gpkg`` extension."""

    zip_rel: str
    """Output-directory-relative zip path, slash-separated, without the ``.zip`` extension."""

    @property
    def gpkg_name(self) -> str:
        """
        The gpkg basename (no extension, no directories).

        :return: The last component of :attr:`gpkg_rel`.
        """
        return self.gpkg_rel.rpartition("/")[2]


@dataclass(frozen=True)
class StrataResolution:
    """The outcome of strata resolution."""

    strata: tuple[StratumSpec, ...]
    """All strata, ordered by stratum feature id."""

    bundles: Mapping[str, tuple[StratumSpec, ...]]
    """Members per zip path (``zip_rel``); multi-member values are bundled zips (§6.6)."""

    features: tuple[QgsFeature, ...]
    """The stratum features, aligned with :attr:`strata`. Phase-A (algorithm thread)
    material only — unlike the specs, these are live QGIS objects."""


def resolve_strata(
    layer: QgsVectorLayer,
    *,
    project: QgsProject,
    name_expression: str = "",
    gpkg_path_expression: str = "",
    zip_path_expression: str = "",
    strata_from_selection: bool = False,
) -> StrataResolution:
    """
    Resolve the run's strata from the stratification layer (SPEC §6).

    The snapshot honors the layer's ``subsetString``; when *strata_from_selection* is set,
    only the selected features become strata (an empty selection aborts — fail-fast, never
    a silent full run). Names follow the strict regime: NULL or
    evaluation errors, duplicate raw names and case-insensitive post-sanitization
    collisions all abort. Evaluated gpkg/zip paths are validated against the §6.5 path
    rules, and the §6.6 bundling rules are enforced.

    :param layer: The stratification layer.
    :param project: The project supplying the expression context scopes.
    :param name_expression: ``STRATUM_NAME_EXPRESSION``; empty means the feature id.
    :param gpkg_path_expression: ``GPKG_PATH_EXPRESSION``; empty means the sanitized name.
    :param zip_path_expression: ``ZIP_PATH_EXPRESSION``; empty means the gpkg basename.
    :param strata_from_selection: Whether an existing selection restricts the strata.
    :return: The resolved strata and their zip bundles (both empty for an empty layer).
    :raise QgsProcessingException: On any violation of the strict §6 rules.
    """
    features = _snapshot(layer, strata_from_selection=strata_from_selection)
    if not features:
        return StrataResolution(strata=(), bundles={}, features=())

    raw_names = _evaluate_names(layer, project, name_expression, features)
    _reject_duplicate_raw_names(raw_names)
    sanitized = [sanitize_filename(raw) for raw in raw_names]
    _reject_sanitization_collisions(raw_names, sanitized)

    strata: list[StratumSpec] = []
    for feature, raw, name in zip(features, raw_names, sanitized, strict=True):
        gpkg_rel = _evaluate_path(
            layer,
            project,
            gpkg_path_expression,
            feature,
            default=name,
            kind=_PathKind.GPKG,
            stratum_vars={"stratum_name": raw, "stratum_name_sanitized": name},
        )
        zip_rel = _evaluate_path(
            layer,
            project,
            zip_path_expression,
            feature,
            default=gpkg_rel.rpartition("/")[2],
            kind=_PathKind.ZIP,
            stratum_vars={
                "stratum_name": raw,
                "stratum_name_sanitized": name,
                "gpkg_path": gpkg_rel,
                "gpkg_name": gpkg_rel.rpartition("/")[2],
            },
        )
        strata.append(
            StratumSpec(
                feature_id=feature.id(),
                raw_name=raw,
                name=name,
                gpkg_rel=gpkg_rel,
                zip_rel=zip_rel,
            )
        )

    return StrataResolution(
        strata=tuple(strata), bundles=bundle_strata(strata), features=tuple(features)
    )


# ---------------------------------------------------------------------------
# Snapshot & naming
# ---------------------------------------------------------------------------


def _snapshot(layer: QgsVectorLayer, *, strata_from_selection: bool) -> list[QgsFeature]:
    """
    Materialize the stratum features once, ordered by feature id (SPEC §6.1).

    :param layer: The stratification layer (its ``subsetString`` applies implicitly).
    :param strata_from_selection: Whether only the selected features become strata.
    :return: The ordered features.
    :raise QgsProcessingException: If *strata_from_selection* is set but nothing is
        selected — fail-fast, never a silent full run (SPEC §6.1/§15).
    """
    if strata_from_selection:
        if layer.selectedFeatureCount() == 0:
            raise QgsProcessingException(
                QCoreApplication.translate(
                    "StrataResolution",
                    "STRATA_FROM_SELECTION is enabled but the stratification layer has no"
                    " selected features.",
                )
            )
        features = list(layer.selectedFeatures())
    else:
        # The stubs miss QgsFeatureIterator.__iter__; it is iterable at runtime.
        features = list(cast("Iterable[QgsFeature]", layer.getFeatures()))
    features.sort(key=lambda feature: feature.id())
    return features


def _base_context(layer: QgsMapLayer, project: QgsProject) -> QgsExpressionContext:
    """
    Build the full project + layer expression context (SPEC §6.2).

    :param layer: The layer supplying the layer scope (any map layer).
    :param project: The project.
    :return: A fresh expression context.
    """
    context = QgsExpressionContext()
    context.appendScope(QgsExpressionContextUtils.globalScope())
    context.appendScope(QgsExpressionContextUtils.projectScope(project))
    context.appendScope(QgsExpressionContextUtils.layerScope(layer))
    return context


def evaluate_layer_display_name(
    layer: QgsMapLayer,
    project: QgsProject,
    expression_text: str,
    *,
    stratum_name: str,
    stratum_name_sanitized: str,
) -> str:
    """
    Evaluate a packaged layer's display-name expression for one stratum (SPEC §4/§13).

    The expression sees the full project + layer context plus ``@stratum_name`` and
    ``@stratum_name_sanitized``. Unlike the §6 path expressions it is feature-less — it
    names a whole layer, not a stratum feature — and its layer scope is the *packaged*
    layer being renamed, so ``@layer_name`` resolves to that layer's original name.

    :param layer: The packaged layer being renamed.
    :param project: The project supplying the global/project/layer scopes.
    :param expression_text: The non-empty ``stratified_packager_layer_name`` expression.
    :param stratum_name: The raw stratum name (``@stratum_name``).
    :param stratum_name_sanitized: The sanitized stratum name (``@stratum_name_sanitized``).
    :return: The evaluated display name.
    :raise QgsProcessingException: On a parse error, an evaluation error or a NULL result.
    """
    expression = QgsExpression(expression_text)
    if expression.hasParserError():
        raise QgsProcessingException(
            QCoreApplication.translate(
                "StrataResolution", "Custom layer name expression failed to parse: {}"
            ).format(expression.parserErrorString())
        )
    context = _base_context(layer, project)
    scope = QgsExpressionContextScope(PLUGIN_SLUG)
    scope.setVariable("stratum_name", stratum_name)
    scope.setVariable("stratum_name_sanitized", stratum_name_sanitized)
    context.appendScope(scope)
    expression.prepare(context)
    value = expression.evaluate(context)
    if expression.hasEvalError():
        raise QgsProcessingException(
            QCoreApplication.translate(
                "StrataResolution",
                "Custom layer name expression failed for layer {} in stratum {}: {}",
            ).format(layer.name(), stratum_name, expression.evalErrorString())
        )
    if value is None:
        raise QgsProcessingException(
            QCoreApplication.translate(
                "StrataResolution",
                "Custom layer name expression returned NULL for layer {} in stratum {}.",
            ).format(layer.name(), stratum_name)
        )
    return str(value)


def _evaluate_names(
    layer: QgsVectorLayer,
    project: QgsProject,
    expression_text: str,
    features: Sequence[QgsFeature],
) -> list[str]:
    """
    Evaluate the stratum name per feature under the strict regime (SPEC §6.2).

    :param layer: The stratification layer.
    :param project: The project.
    :param expression_text: The name expression; empty means the feature id.
    :param features: The snapshot.
    :return: One raw name per feature, in order.
    :raise QgsProcessingException: On a parse error, an evaluation error or a NULL name.
    """
    if not expression_text.strip():
        return [str(feature.id()) for feature in features]
    expression = QgsExpression(expression_text)
    if expression.hasParserError():
        raise QgsProcessingException(
            QCoreApplication.translate(
                "StrataResolution", "Stratum name expression failed to parse: {}"
            ).format(expression.parserErrorString())
        )
    context = _base_context(layer, project)
    expression.prepare(context)
    names: list[str] = []
    for feature in features:
        context.setFeature(feature)
        value = expression.evaluate(context)
        if expression.hasEvalError():
            raise QgsProcessingException(
                QCoreApplication.translate(
                    "StrataResolution", "Stratum name expression failed for feature {}: {}"
                ).format(feature.id(), expression.evalErrorString())
            )
        if value is None:
            raise QgsProcessingException(
                QCoreApplication.translate(
                    "StrataResolution", "Stratum name expression returned NULL for feature {}."
                ).format(feature.id())
            )
        names.append(str(value))
    return names


def _reject_duplicate_raw_names(raw_names: Sequence[str]) -> None:
    """
    Abort on duplicate raw stratum names (SPEC §6.2).

    :param raw_names: The evaluated names.
    :raise QgsProcessingException: Listing every duplicated name.
    """
    seen: defaultdict[str, int] = defaultdict(int)
    for raw in raw_names:
        seen[raw] += 1
    duplicates = sorted(name for name, count in seen.items() if count > 1)
    if duplicates:
        raise QgsProcessingException(
            QCoreApplication.translate("StrataResolution", "Duplicate stratum names: {}").format(
                ", ".join(map(repr, duplicates))
            )
        )


def _reject_sanitization_collisions(raw_names: Sequence[str], sanitized: Sequence[str]) -> None:
    """
    Abort on case-insensitive post-sanitization collisions (SPEC §6.2, Windows rule).

    :param raw_names: The raw names (for the error message).
    :param sanitized: The sanitized names, aligned with *raw_names*.
    :raise QgsProcessingException: Listing the colliding raw-name groups.
    """
    by_key: defaultdict[str, list[str]] = defaultdict(list)
    for raw, name in zip(raw_names, sanitized, strict=True):
        by_key[name.casefold()].append(raw)
    collisions = [sorted(group) for group in by_key.values() if len(group) > 1]
    if collisions:
        rendered = "; ".join(" / ".join(map(repr, group)) for group in sorted(collisions))
        raise QgsProcessingException(
            QCoreApplication.translate(
                "StrataResolution", "Stratum names collide after sanitization: {}"
            ).format(rendered)
        )


# ---------------------------------------------------------------------------
# Path evaluation & bundling
# ---------------------------------------------------------------------------


class _PathKind(Enum):
    """Which §6 path is being evaluated (only affects error wording)."""

    GPKG = "GeoPackage"
    ZIP = "zip"


def _evaluate_path(
    layer: QgsVectorLayer,
    project: QgsProject,
    expression_text: str,
    feature: QgsFeature,
    *,
    default: str,
    kind: _PathKind,
    stratum_vars: Mapping[str, str],
) -> str:
    """
    Evaluate and validate one gpkg/zip path for one stratum (SPEC §6.4/§6.5).

    :param layer: The stratification layer.
    :param project: The project.
    :param expression_text: The path expression; empty selects *default*.
    :param feature: The stratum feature.
    :param default: The default path when the expression is empty.
    :param kind: Which path is being evaluated (error wording).
    :param stratum_vars: The §6.4 naming variables injected into the context.
    :return: The validated, slash-joined relative path (no extension).
    :raise QgsProcessingException: On parse/evaluation errors, NULL results or §6.5
        path-rule violations.
    """
    if not expression_text.strip():
        text = default
    else:
        expression = QgsExpression(expression_text)
        if expression.hasParserError():
            raise QgsProcessingException(
                QCoreApplication.translate(
                    "StrataResolution", "{} path expression failed to parse: {}"
                ).format(kind.value, expression.parserErrorString())
            )
        context = _base_context(layer, project)
        scope = QgsExpressionContextScope(PLUGIN_SLUG)
        for variable, value in stratum_vars.items():
            scope.setVariable(variable, value)
        context.appendScope(scope)
        expression.prepare(context)
        context.setFeature(feature)
        value = expression.evaluate(context)
        if expression.hasEvalError():
            raise QgsProcessingException(
                QCoreApplication.translate(
                    "StrataResolution", "{} path expression failed for stratum {}: {}"
                ).format(kind.value, stratum_vars["stratum_name"], expression.evalErrorString())
            )
        if value is None:
            raise QgsProcessingException(
                QCoreApplication.translate(
                    "StrataResolution", "{} path expression returned NULL for stratum {}."
                ).format(kind.value, stratum_vars["stratum_name"])
            )
        text = str(value)
    try:
        components = split_archive_path(text)
    except ValueError as err:
        raise QgsProcessingException(
            QCoreApplication.translate(
                "StrataResolution", "Invalid {} path for stratum {}: {}"
            ).format(kind.value, stratum_vars["stratum_name"], err)
        ) from err
    return "/".join(components)


def bundle_strata(strata: Sequence[StratumSpec]) -> dict[str, tuple[StratumSpec, ...]]:
    """
    Group strata into zip bundles and enforce the §6.6 uniqueness rules.

    Also called by the algorithm to re-bundle after appending the ``<full>`` pseudo-stratum,
    so the full package passes the same zip- and gpkg-collision checks as any stratum.

    :param strata: The resolved strata.
    :return: Members per exact zip path, in stratum order.
    :raise QgsProcessingException: On case-variant zip paths or on case-insensitive
        gpkg path collisions inside one bundle.
    """
    bundles: defaultdict[str, list[StratumSpec]] = defaultdict(list)
    for stratum in strata:
        bundles[stratum.zip_rel].append(stratum)

    zip_collisions = case_insensitive_collisions(bundles.keys())
    if zip_collisions:
        rendered = "; ".join(" / ".join(map(repr, group)) for group in zip_collisions)
        raise QgsProcessingException(
            QCoreApplication.translate(
                "StrataResolution",
                "Zip paths differ only by letter case (they would overwrite each other"
                " on Windows): {}",
            ).format(rendered)
        )

    for zip_rel, members in bundles.items():
        gpkg_paths = [f"{member.gpkg_rel}.gpkg" for member in members]
        collisions = case_insensitive_collisions(gpkg_paths)
        duplicate_exact = {path for path in gpkg_paths if gpkg_paths.count(path) > 1}
        if collisions or duplicate_exact:
            offenders = sorted(
                duplicate_exact.union(*collisions) if collisions else duplicate_exact
            )
            raise QgsProcessingException(
                QCoreApplication.translate(
                    "StrataResolution", "GeoPackage paths collide inside zip {}: {}"
                ).format(f"{zip_rel}.zip", ", ".join(map(repr, offenders)))
            )

    return {zip_rel: tuple(members) for zip_rel, members in bundles.items()}
