"""
Stratum GeoPackage assembly on the algorithm thread (SPEC §8.3).

The former GDAL worker pipeline is gone: every GeoPackage is now written here, on the
algorithm thread, through the QGIS API. :class:`~qgis.core.QgsVectorFileWriter` reads a
layer through its provider, so memory, joined, virtual and edited sources need no staging
(the QGIS-fid ↔ OGR-FID equivalence problem disappears with it). Per-stratum filtering
selects features on a throwaway *read layer* — a clone of the user's layer, or a layer
over a staging/full-package GeoPackage, never the user's layer itself — and writes only
the selection (:attr:`~qgis.core.QgsVectorFileWriter.SaveVectorOptions.onlySelectedFeatures`);
an empty selection writes an empty table. Layers identical in every stratum
(``whole_export``) ride in a *template* GeoPackage copied per stratum (SPEC §8.1.5), so
their data is written once and copied N times rather than written N times.

Only this module touches the per-stratum gpkg; background zip/move stays off-thread in
:mod:`~.workers`. All user-facing messaging flows through the
:class:`~qgis.core.QgsProcessingFeedback` argument; a per-stratum failure is contained
(best-effort, SPEC §17) and surfaced as a result, never raised — the caller aggregates
failures into one final exception. Cancellation is observed through the feedback.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from qgis.core import (
    Qgis,
    QgsCoordinateTransformContext,
    QgsProcessingException,
    QgsProcessingMultiStepFeedback,
    QgsVectorFileWriter,
)
from qgis.PyQt.QtCore import QCoreApplication

from stratified_packager.toolbelt import gpkg

from .matching import (
    attribute_keys_for_stratum,
    in_filter_expressions,
    spatial_fids_for_stratum,
    stratum_geometry_in_layer_crs,
)
from .params import MatchingMethod
from .report import STATUS_EMPTY_KEPT, STATUS_EMPTY_SKIPPED, STATUS_OK, STATUS_WARM

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence
    from pathlib import Path

    from qgis.core import (
        QgsFeature,
        QgsProcessingFeedback,
        QgsProject,
        QgsVectorLayer,
    )

    from .matching import LayerMatchPlan

__all__: list[str] = [
    "LayerWrite",
    "LayerWriteResult",
    "StratumBuild",
    "StratumWriteResult",
    "StyleDoc",
    "discard_gpkg",
    "stage_union",
    "warm_rejection",
    "write_stratum",
    "write_template",
    "write_vector_table",
]


@dataclass(frozen=True)
class StyleDoc:
    """One named style row destined for ``layer_styles`` (SPEC §8.3 step 5)."""

    name: str
    """Style name."""

    qml: str
    """Full QML document."""

    sld: str = ""
    """SLD document (best-effort; may be empty)."""

    default: bool = False
    """Whether this is the table's default style."""

    description: str = ""
    """Optional description."""


@dataclass(frozen=True)
class LayerWrite:
    """One layer's contribution to a stratum gpkg (algorithm-thread plan; SPEC §8.3)."""

    layer_id: str
    """The QGIS layer id (round-trips into results and the embedded project)."""

    table: str
    """Target table name inside the stratum gpkg."""

    read_layer: QgsVectorLayer
    """The standalone layer features are read and selected from — a clone of the user's
    layer, or a layer over the staging/full-package GeoPackage. Its selection is mutated
    per stratum; it is never a layer owned by :class:`~qgis.core.QgsProject`."""

    members: tuple[LayerMatchPlan, ...]
    """The match plan(s) whose union defines membership. One element normally; more only
    for a dedup group sharing this table (SPEC §12) — the union of every member's match
    set is selected. A ``whole_export`` member makes the whole table unconditional."""

    kept_field_indexes: tuple[int, ...]
    """Indexes into :attr:`read_layer` ``.fields()`` to export (excluded fields dropped).
    An empty tuple exports every field (the writer's documented all-fields behavior)."""

    whole_export: bool = False
    """Whether this table is unconditional (rides in the template seed on cold runs)."""

    warm_marked: bool = False
    """Whether this table belongs to the warm cache (rides in the warm seed, SPEC §11)."""

    keep_if_empty: bool = True
    """``KEEP_EMPTY_LAYERS``: keep the empty table (with styles) or drop it."""

    styles: tuple[StyleDoc, ...] = ()
    """Styles written after the table lands (skipped when it rides in a seed)."""

    metadata_xml: str = ""
    """QMD layer metadata written after the table lands (empty = none)."""


@dataclass(frozen=True)
class StratumBuild:
    """Everything :func:`write_stratum` needs to assemble one stratum gpkg."""

    name: str
    """The sanitized stratum name (result/reporting key)."""

    gpkg_path: Path
    """Absolute build path of the stratum gpkg."""

    layers: tuple[LayerWrite, ...]
    """Layer contributions, already ordered per SPEC §8.3 step 3 (warm-marked first,
    then ``whole_export``, then the remaining partitioned layers)."""

    stratum_feature: QgsFeature | None = None
    """The stratum feature (membership source); :data:`None` for the ``<full>`` package."""

    template: Path | None = None
    """The ``whole_export`` template gpkg copied as the cold-run seed (SPEC §8.1.5)."""

    warm_start: Path | None = None
    """Warm cache file copied as the seed — on ``WARM_START_MODE=use`` runs, and on the
    deliverable pass of ``WARM_START_MODE=update`` runs, which seeds from the cache the
    warm pass just wrote (SPEC §11)."""

    expected_warm_tables: tuple[str, ...] = ()
    """Tables the warm file must hold exactly, or the build falls back cold (SPEC §11)."""

    snapshot_to: Path | None = None
    """Warm-cache destination of the ``WARM_START_MODE=update`` warm pass, whose builds hold
    only warm-marked layers (the snapshot is taken after the last warm-marked layer is
    written); :data:`None` = no snapshot."""

    data_payloads: tuple[tuple[Path, Path], ...] = ()
    """``(source file, destination)`` sidecar copies into the build dir (SPEC §14)."""


@dataclass(frozen=True)
class LayerWriteResult:
    """One layer's outcome inside a stratum gpkg (run-report material, SPEC §9.1)."""

    layer_id: str
    """The QGIS layer id."""

    table: str
    """The target table name."""

    feature_count: int
    """Rows in the table (0 for an empty/skipped layer)."""

    status: str
    """``ok`` | ``empty-kept`` | ``empty-skipped`` | ``warm``."""

    matched_fids: frozenset[int] = frozenset()
    """This stratum's matching feature ids in the read layer's id space (empty for
    ``whole_export``/seeded layers). The caller unions these across strata for the §9.1
    ``<unmatched>`` accounting (read-source total minus the union)."""


@dataclass
class StratumWriteResult:
    """A stratum build outcome (success or contained failure)."""

    name: str
    """The sanitized stratum name."""

    ok: bool
    """Whether the gpkg was assembled completely."""

    error: str = ""
    """Failure detail when :attr:`ok` is false."""

    warm_used: bool = False
    """Whether the build started from the warm cache."""

    warm_reason: str = ""
    """The cold-fallback trigger when a warm source existed but was rejected."""

    layers: list[LayerWriteResult] = field(default_factory=list)
    """Per-layer outcomes (empty when the build failed before any layer landed)."""


def write_template(
    template_path: Path, layers: Sequence[LayerWrite], /, *, feedback: QgsProcessingFeedback
) -> None:
    """
    Write the ``whole_export`` template gpkg once (SPEC §8.1.5).

    Each layer is written in full (no per-stratum selection); a plain file copy of the
    template then seeds every stratum that shares these layers. Styles and metadata are
    **not** written here — they are written per stratum after the seed copy, so the
    ``resources/`` prefix matches each stratum's gpkg depth (SPEC §13/§14).

    :param template_path: The template gpkg build path.
    :param layers: The ``whole_export`` layer writes (already deduplicated to primaries).
    :param feedback: Execution feedback channel.
    :raise QgsProcessingException: If a writer reports an error.
    """
    template_path.parent.mkdir(parents=True, exist_ok=True)
    steps = QgsProcessingMultiStepFeedback(len(layers), feedback)
    for index, layer_write in enumerate(layers, start=1):
        if feedback.isCanceled():
            return
        steps.setCurrentStep(index - 1)
        line = QCoreApplication.translate("Building", "Writing template layer {}/{}: {}").format(
            index, len(layers), layer_write.table
        )
        feedback.setProgressText(line)
        feedback.pushInfo(line)
        layer_write.read_layer.removeSelection()
        write_vector_table(
            template_path,
            layer_write.read_layer,
            layer_write.table,
            kept_field_indexes=layer_write.kept_field_indexes,
            only_selected=False,
            feedback=steps,
        )
    feedback.pushDebugInfo(
        QCoreApplication.translate(
            "Building", "template gpkg holds %n layer(s)", None, len(layers)
        )
    )


def discard_gpkg(path: Path) -> bool:
    """
    Best-effort remove a partial stratum gpkg during failure cleanup (SPEC §17).

    Never raises: on Windows a just-failed
    :meth:`~qgis.core.QgsVectorFileWriter.writeAsVectorFormatV3` (including a writer
    aborted by cancellation) can leave the file locked, so :meth:`~pathlib.Path.unlink`
    would raise :exc:`PermissionError`. Swallowing it keeps a contained per-stratum
    failure from escalating into a fatal abort; a still-locked file is left for the run's
    ``workdir`` teardown / the OS.

    :param path: The partial gpkg to remove.
    :return: Whether the file was removed.
    """
    try:
        path.unlink(missing_ok=True)
    except OSError:
        success = False
    else:
        success = True
    return success


def write_stratum(
    build: StratumBuild,
    *,
    label: str = "",
    project: QgsProject,
    strat_layer: QgsVectorLayer | None,
    feedback: QgsProcessingFeedback,
) -> StratumWriteResult:
    """
    Assemble one stratum gpkg on the algorithm thread (SPEC §8.3); never raises.

    Pipeline: seed file (warm copy, template copy, or fresh) → ordered per-layer
    filtered appends (layers already in the seed are reported, not rewritten) → per-layer
    empty handling, styles and metadata → ``data/`` payload copies. A failure is contained
    and returned as ``ok=False`` (best-effort, SPEC §17); the partial gpkg is removed.

    :param build: The stratum build.
    :param label: Progress-text prefix naming this build, e.g. ``Stratum 4/93: urban``
        (falls back to the stratum name when empty).
    :param project: The run's project (resolves relation-chain intermediates).
    :param strat_layer: The stratification layer (spatial transforms); :data:`None` only
        for the ``<full>`` package, whose layers are all ``whole_export``.
    :param feedback: Execution feedback channel.
    :return: The stratum outcome, with per-layer results.
    """
    result = StratumWriteResult(name=build.name, ok=True)
    try:
        build.gpkg_path.parent.mkdir(parents=True, exist_ok=True)
        warm_used, template_used = _seed(build, result, feedback)
        warm_boundary = _warm_count(build) if build.snapshot_to is not None else -1
        steps = QgsProcessingMultiStepFeedback(len(build.layers), feedback)
        for index, layer_write in enumerate(build.layers):
            if feedback.isCanceled():
                result.ok, result.error = False, "canceled"
                return result
            steps.setCurrentStep(index)
            feedback.setProgressText(
                QCoreApplication.translate("Building", "{} — layer {}/{}: {}").format(
                    label or build.name, index + 1, len(build.layers), layer_write.table
                )
            )
            result.layers.append(
                _build_layer(
                    build,
                    layer_write,
                    warm_used=warm_used,
                    template_used=template_used,
                    project=project,
                    strat_layer=strat_layer,
                    feedback=steps,
                )
            )
            if index + 1 == warm_boundary and build.snapshot_to is not None:
                _snapshot_warm(build.gpkg_path, build.snapshot_to)
        for source, destination in build.data_payloads:
            if feedback.isCanceled():
                result.ok, result.error = False, "canceled"
                return result
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    except QgsProcessingException as err:
        if not discard_gpkg(build.gpkg_path):
            feedback.pushWarning(
                QCoreApplication.translate(
                    "Building", "Failed to remove partial gpkg {} after error: {}"
                ).format(build.gpkg_path, err)
            )
        result.ok, result.error = False, str(err)
    except Exception as err:  # noqa: BLE001  # stratum boundary: contain, never abort the run
        if not discard_gpkg(build.gpkg_path):
            feedback.pushWarning(
                QCoreApplication.translate(
                    "Building", "Failed to remove partial gpkg {} after error: {}"
                ).format(build.gpkg_path, err)
            )
        result.ok, result.error = False, f"{type(err).__name__}: {err}"
    return result


def _seed(
    build: StratumBuild, result: StratumWriteResult, feedback: QgsProcessingFeedback
) -> tuple[bool, bool]:
    """
    Materialize the seed file: warm copy, template copy, or fresh (SPEC §8.3/§11).

    A ``warm_start`` equal to the build path means the §11 prefetch already copied the cache
    there — the seed is validated and used in place, no second copy. A rejected warm file
    (prefetched or not) falls through to the template/fresh path, whose copy overwrites any
    prefetched bytes.

    :param build: The stratum build.
    :param result: The result to stamp the warm decision onto.
    :param feedback: Execution feedback channel.
    :return: ``(warm seed used, template seed used)``.
    """
    if build.warm_start is not None:
        reason = _warm_rejection(build)
        if reason is None:
            if build.warm_start != build.gpkg_path:
                shutil.copyfile(build.warm_start, build.gpkg_path)
            result.warm_used = True
            feedback.pushDebugInfo(
                QCoreApplication.translate("Building", "warm start used for {}").format(build.name)
            )
            return True, False
        result.warm_reason = reason
        if build.warm_start == build.gpkg_path:
            # Discard the rejected prefetched seed: the template copy would overwrite it,
            # but the fresh path must start from no file at all.
            build.gpkg_path.unlink(missing_ok=True)
    if build.template is not None:
        shutil.copyfile(build.template, build.gpkg_path)
        return False, True
    return False, False


def warm_rejection(warm: Path | None, expected_tables: Collection[str]) -> str | None:
    """
    Check the §11 cold-fallback triggers against a warm-cache file.

    Shared by the seed-time check and the Phase-A pre-scan that decides whether staging of
    warm-covered groups can be skipped on a ``WARM_START_MODE=use`` run (§8.2/§11).

    :param warm: The warm-cache gpkg path (:data:`None` counts as missing).
    :param expected_tables: The warm-marked primaries' table names.
    :return: The rejection reason, or :data:`None` when the warm file is usable.
    """
    if warm is None or not warm.is_file():
        return "warm file is missing"
    present = set(gpkg.layer_names(warm))
    expected = set(expected_tables)
    if missing := expected - present:
        return f"warm file lacks expected table(s): {', '.join(sorted(missing))}"
    if extra := present - expected:
        return f"warm file holds non-warm-marked table(s): {', '.join(sorted(extra))}"
    return None


def _warm_rejection(build: StratumBuild) -> str | None:
    """
    Check the §11 cold-fallback triggers against the build's warm source.

    :param build: The stratum build (``warm_start`` is set).
    :return: The rejection reason, or :data:`None` when the warm file is usable.
    """
    return warm_rejection(build.warm_start, build.expected_warm_tables)


def _warm_count(build: StratumBuild) -> int:
    """
    Count the leading warm-marked layers (the snapshot boundary, SPEC §11).

    :param build: The stratum build (layers are ordered warm-marked first).
    :return: The number of leading warm-marked layer writes.
    """
    count = 0
    for layer_write in build.layers:
        if not layer_write.warm_marked:
            break
        count += 1
    return count


def _build_layer(
    build: StratumBuild,
    layer_write: LayerWrite,
    *,
    warm_used: bool,
    template_used: bool,
    project: QgsProject,
    strat_layer: QgsVectorLayer | None,
    feedback: QgsProcessingFeedback,
) -> LayerWriteResult:
    """
    Append (or recognize) one layer's slice and apply its epilogue (SPEC §8.3).

    Layers already present in the seed are reported without rewriting: a warm-marked table
    on a warm start counts as ``warm`` (an empty one follows ``keep_if_empty``); a
    non-warm-marked ``whole_export`` table on a template start keeps its template count and
    styles (warm-marked ones never ride the template, so they are written like any other
    layer).

    :param build: The stratum build.
    :param layer_write: The layer contribution.
    :param warm_used: Whether the build started from the warm seed.
    :param template_used: Whether the build started from the template seed.
    :param project: The run's project.
    :param strat_layer: The stratification layer.
    :param feedback: Execution feedback channel.
    :return: The layer outcome.
    :raise QgsProcessingException: On a writer or transform failure (contained upstream).
    """
    if warm_used and layer_write.warm_marked:
        return _report_seeded(build.gpkg_path, layer_write)
    if template_used and layer_write.whole_export and not layer_write.warm_marked:
        # Data already rides in the template seed; write this stratum's styles/metadata so the
        # resources prefix matches the stratum's gpkg depth (SPEC §13/§14).
        return _finalize_layer(build.gpkg_path, layer_write, drop_empty=False, write_styles=True)

    only_selected, matched_fids = _apply_membership(
        layer_write, build.stratum_feature, project, strat_layer, build.name, feedback
    )
    write_vector_table(
        build.gpkg_path,
        layer_write.read_layer,
        layer_write.table,
        kept_field_indexes=layer_write.kept_field_indexes,
        only_selected=only_selected,
        feedback=feedback,
    )
    return _finalize_layer(
        build.gpkg_path,
        layer_write,
        drop_empty=not layer_write.keep_if_empty,
        write_styles=True,
        matched_fids=matched_fids,
    )


def _apply_membership(
    layer_write: LayerWrite,
    stratum_feature: QgsFeature | None,
    project: QgsProject,
    strat_layer: QgsVectorLayer | None,
    stratum_name: str,
    feedback: QgsProcessingFeedback,
) -> tuple[bool, frozenset[int]]:
    """
    Select the union of the members' matching features on the read layer (SPEC §7/§12).

    A ``whole_export`` member makes the table unconditional (the whole layer is written).
    Otherwise each member contributes its match set: attribute keys become a selection by
    key expression, spatial fids a selection by id; selections accumulate (``AddToSelection``).

    :param layer_write: The layer contribution (its read layer's selection is replaced).
    :param stratum_feature: The stratum feature (membership source).
    :param project: The run's project.
    :param strat_layer: The stratification layer (spatial transforms).
    :param stratum_name: The stratum name (feedback only).
    :param feedback: Execution feedback channel.
    :return: ``(only the selection is written, the selected fids)`` — the second element
        feeds the §9.1 orphan accounting and is empty for an unconditional write.
    :raise QgsProcessingException: On a coordinate-transform failure.
    """
    read = layer_write.read_layer
    if any(member.method is MatchingMethod.WHOLE_EXPORT for member in layer_write.members):
        read.removeSelection()
        return False, frozenset()
    if (
        stratum_feature is None
    ):  # narrow for checkers; only <full> has no feature, all whole_export
        read.removeSelection()
        return False, frozenset()
    read.removeSelection()
    for member in layer_write.members:
        _select_member(
            read,
            member,
            stratum_feature,
            project=project,
            strat_layer=strat_layer,
            stratum_name=stratum_name,
            feedback=feedback,
        )
    return True, frozenset(read.selectedFeatureIds())


def _select_member(
    read_layer: QgsVectorLayer,
    member: LayerMatchPlan,
    stratum_feature: QgsFeature,
    *,
    project: QgsProject,
    strat_layer: QgsVectorLayer | None,
    stratum_name: str,
    feedback: QgsProcessingFeedback,
) -> None:
    """
    Add one member's matching features to *read_layer*'s selection (SPEC §7).

    Attribute matching selects by key expression (the provider compiles ``IN`` to native SQL
    where it can); spatial matching selects the fids matched against this stratum's geometry.
    Selections accumulate, so callers union members — and strata — by not resetting between
    calls.

    :param read_layer: The standalone read layer whose selection is extended.
    :param member: The member's resolved match plan (never ``whole_export``).
    :param stratum_feature: The stratum feature (membership source).
    :param project: The run's project (relation-chain intermediates).
    :param strat_layer: The stratification layer (spatial transforms).
    :param stratum_name: The stratum name (feedback only).
    :param feedback: Execution feedback channel.
    :raise QgsProcessingException: On a missing stratification layer or transform failure.
    """
    if member.method is MatchingMethod.ATTRIBUTE:
        condition = attribute_keys_for_stratum(
            member, stratum_feature, stratum_name, project, feedback
        )
        if condition.by_fid:
            read_layer.selectByIds(list(condition.fids), Qgis.SelectBehavior.AddToSelection)
        else:
            for expression in in_filter_expressions(condition.key_fields, condition.keys):
                read_layer.selectByExpression(expression, Qgis.SelectBehavior.AddToSelection)
        return
    if strat_layer is None:
        raise QgsProcessingException(
            QCoreApplication.translate("Building", "spatial matching needs a stratification layer")
        )
    geometry = stratum_geometry_in_layer_crs(
        stratum_feature.geometry(), strat_layer, read_layer, project, feedback
    )
    condition = spatial_fids_for_stratum(
        read_layer, geometry, stratum_name, member.predicates, feedback
    )
    read_layer.selectByIds(list(condition.fids), Qgis.SelectBehavior.AddToSelection)


def stage_union(
    staging_gpkg: Path,
    read_layer: QgsVectorLayer,
    table: str,
    members: Sequence[LayerMatchPlan],
    stratum_features: Sequence[QgsFeature],
    *,
    kept_field_indexes: Sequence[int] = (),
    project: QgsProject,
    strat_layer: QgsVectorLayer | None,
    feedback: QgsProcessingFeedback,
) -> None:
    """
    Stage the union of every stratum's matches into a per-layer GeoPackage (SPEC §8.2).

    The staged copy holds only the features some stratum uses, so each stratum later reads its
    slice from this fast local file instead of re-fetching from a slow source. Matching is
    computed against the source here; per-stratum reads then re-match against the staged copy
    (its own fids/keys, so spatial matching survives the FID renumbering).

    :param staging_gpkg: The per-layer staging GeoPackage.
    :param read_layer: A standalone clone of the source layer (its selection is replaced).
    :param table: The staged table name.
    :param members: The match plan(s) whose union is staged (no ``whole_export`` member).
    :param stratum_features: The real strata features (the ``<full>`` pseudo-stratum excluded).
    :param kept_field_indexes: Field indexes to stage (empty = every field).
    :param project: The run's project.
    :param strat_layer: The stratification layer.
    :param feedback: Execution feedback channel.
    :raise QgsProcessingException: On a writer or transform failure.
    """
    read_layer.removeSelection()
    for index, feature in enumerate(stratum_features, start=1):
        if feedback.isCanceled():
            return
        feedback.setProgressText(
            QCoreApplication.translate("Building", "Staging {}: matching stratum {}/{}").format(
                table, index, len(stratum_features)
            )
        )
        for member in members:
            _select_member(
                read_layer,
                member,
                feature,
                project=project,
                strat_layer=strat_layer,
                stratum_name="",
                feedback=feedback,
            )
    feedback.setProgressText(
        QCoreApplication.translate("Building", "Staging {}: writing the staged copy").format(table)
    )
    write_vector_table(
        staging_gpkg,
        read_layer,
        table,
        kept_field_indexes=kept_field_indexes,
        only_selected=True,
        feedback=feedback,
    )


def write_vector_table(
    gpkg_path: Path,
    layer: QgsVectorLayer,
    table: str,
    *,
    kept_field_indexes: Sequence[int] = (),
    only_selected: bool,
    feedback: QgsProcessingFeedback,
) -> None:
    """
    Write a layer (whole or its current selection) into a GeoPackage as one table.

    Shared by stratum assembly, the template and per-layer staging: the table is created
    on the first write into *gpkg_path* and appended as a new layer afterwards. The
    writer reads through the QGIS provider, so joins, virtual fields and unsaved edits
    are honored without any staging.

    :param gpkg_path: The destination GeoPackage (created on first write).
    :param layer: The standalone layer to read; its current selection is honored when
        *only_selected* is set (never a layer owned by :class:`~qgis.core.QgsProject`).
    :param table: The target table name.
    :param kept_field_indexes: Field indexes (into ``layer.fields()``) to export; empty
        exports every field.
    :param only_selected: Whether to write only the current selection.
    :param feedback: Execution feedback channel (carries cancellation into the writer).
    :raise QgsProcessingException: If the writer reports an error.
    """
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "GPKG"
    options.layerName = table
    options.onlySelectedFeatures = only_selected
    if kept_field_indexes:
        options.attributes = list(kept_field_indexes)
    options.actionOnExistingFile = (
        QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer
        if gpkg_path.exists()
        else QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile
    )
    options.feedback = feedback
    error, message, _out_file, _out_table = QgsVectorFileWriter.writeAsVectorFormatV3(
        layer, str(gpkg_path), QgsCoordinateTransformContext(), options
    )
    if error != QgsVectorFileWriter.WriterError.NoError:
        # A canceled feedback aborts the writer with an (often empty) error; report it as the
        # cancellation it is, so a Ctrl-C mid-write is not surfaced as a spurious data failure.
        if feedback.isCanceled():
            raise QgsProcessingException(
                QCoreApplication.translate("Building", "writing table {} canceled").format(table)
            )
        raise QgsProcessingException(
            QCoreApplication.translate("Building", "writing table {} failed: {}").format(
                table, message
            )
        )


def _finalize_layer(
    gpkg_path: Path,
    layer_write: LayerWrite,
    *,
    drop_empty: bool,
    write_styles: bool,
    matched_fids: frozenset[int] = frozenset(),
) -> LayerWriteResult:
    """
    Apply the per-layer epilogue: empty handling, styles, metadata, outcome.

    :param gpkg_path: The stratum gpkg.
    :param layer_write: The finished layer contribution.
    :param drop_empty: Whether a zero-feature table is dropped (``KEEP_EMPTY_LAYERS=False``).
    :param write_styles: Whether to write styles/metadata (skipped for seeded tables).
    :param matched_fids: This stratum's matching fids (read-source id space, §9.1 accounting).
    :return: The layer outcome.
    """
    kept = gpkg.table_exists(gpkg_path, layer_write.table)
    count = gpkg.feature_count(gpkg_path, layer_write.table) if kept else 0
    if kept and count == 0 and drop_empty:
        gpkg.drop_table(gpkg_path, layer_write.table)
        kept = False
    if kept and write_styles:
        geometry_column = gpkg.geometry_column_of(gpkg_path, layer_write.table)
        for style in layer_write.styles:
            gpkg.write_layer_style(
                gpkg_path,
                table=layer_write.table,
                geometry_column=geometry_column,
                style_name=style.name,
                qml=style.qml,
                sld=style.sld,
                use_as_default=style.default,
                description=style.description,
            )
        if layer_write.metadata_xml:
            gpkg.write_layer_metadata(
                gpkg_path, table=layer_write.table, qmd_xml=layer_write.metadata_xml
            )
    return LayerWriteResult(
        layer_id=layer_write.layer_id,
        table=layer_write.table,
        feature_count=count,
        status=_empty_status(kept=kept, count=count),
        matched_fids=matched_fids,
    )


def _empty_status(*, kept: bool, count: int) -> str:
    """
    Map a table's presence and row count to its §9.1 status token.

    :param kept: Whether the table exists.
    :param count: Its row count.
    :return: ``ok`` | ``empty-kept`` | ``empty-skipped``.
    """
    if count:
        return STATUS_OK
    return STATUS_EMPTY_KEPT if kept else STATUS_EMPTY_SKIPPED


def _report_seeded(gpkg_path: Path, layer_write: LayerWrite) -> LayerWriteResult:
    """
    Report a warm-marked table that already rides in the warm seed (SPEC §11).

    The warm cache always retains empty warm-marked tables, so the deliverable's empty
    policy is applied here: an empty seeded table is dropped when ``keep_if_empty`` is
    false (``empty-skipped``), otherwise it stays ``warm`` (row count 0 tells the rest).

    :param gpkg_path: The stratum gpkg.
    :param layer_write: The seeded layer contribution.
    :return: The layer outcome.
    """
    kept = gpkg.table_exists(gpkg_path, layer_write.table)
    count = gpkg.feature_count(gpkg_path, layer_write.table) if kept else 0
    if kept and count == 0 and not layer_write.keep_if_empty:
        gpkg.drop_table(gpkg_path, layer_write.table)
        kept = False
    return LayerWriteResult(
        layer_id=layer_write.layer_id,
        table=layer_write.table,
        feature_count=count,
        status=STATUS_WARM if kept else STATUS_EMPTY_SKIPPED,
    )


def _snapshot_warm(gpkg_path: Path, destination: Path) -> None:
    """
    Snapshot the gpkg into the warm cache via ``.part`` + atomic rename (SPEC §11).

    :param gpkg_path: The stratum gpkg (holding only the warm-marked tables so far).
    :param destination: The warm-cache destination (``<warm dir>/<stratum>.gpkg``).
    :raise QgsProcessingException: If the WAL checkpoint is incomplete — copying only the
        main file would snapshot a stale cache, so this counts as a failed cache write
        (the §11 machinery then builds the stratum cold and fails the run at the end).
    """
    if not gpkg.checkpoint_wal(gpkg_path):
        raise QgsProcessingException(
            QCoreApplication.translate(
                "Building", "WAL checkpoint incomplete; not snapshotting a stale warm cache"
            )
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_name(destination.name + ".part")
    shutil.copyfile(gpkg_path, part)
    part.replace(destination)
