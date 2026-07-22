"""
Embedded per-stratum project construction (SPEC §13).

Runs on the algorithm thread during Phase C — never against
:meth:`~qgis.core.QgsProject.instance`. The fresh project re-points included layers at
the stratum GeoPackage tables and the ``data/`` payload copies, restores the layer-tree
structure (groups, order, visibility) restricted to included layers, applies the full
(rewritten) styles, remaps relations among included layers, and carries the project
CRS, transform context and title. Paths are stored relative: the caller builds the
stratum inside a directory tree that mirrors the zip layout, so Qt's relative-path
storage produces portable ``./…`` sources (SPEC §13).
"""

from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsLayerTreeGroup,
    QgsLayerTreeLayer,
    QgsProcessingException,
    QgsProject,
    QgsRelation,
    QgsRelationContext,
    QgsVectorLayer,
    QgsVirtualLayerDefinition,
)
from qgis.PyQt.QtCore import QCoreApplication, QUrl
from qgis.PyQt.QtXml import QDomDocument

from stratified_packager.toolbelt.sql import sqlite_where_error

from .params import ProjectInclusion

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence
    from pathlib import Path

    from qgis.core import QgsMapLayer, QgsProcessingFeedback

__all__: list[str] = ["StratumProjectPlan", "build_stratum_project"]


@dataclass
class StratumProjectPlan:
    """Everything needed to build one stratum's embedded project."""

    title: str
    """Project title (the stratum name)."""

    mode: ProjectInclusion
    """``gpkg`` (project storage inside the GeoPackage) or ``qgz`` (file beside it)."""

    gpkg_path: Path
    """The stratum GeoPackage (absolute, already built, inside the zip-mirror tree)."""

    qgz_path: Path | None = None
    """The ``.qgz`` destination for ``qgz`` mode (beside the gpkg, same basename)."""

    vector_tables: dict[str, str] = field(default_factory=dict)
    """Included vector layers: source layer id -> table present in the stratum gpkg."""

    data_sources: dict[str, Path] = field(default_factory=dict)
    """Included payload layers: source layer id -> absolute path of the ``data/`` copy
    inside the zip-mirror tree."""

    embedded_only: tuple[str, ...] = ()
    """Source layer ids riding only in the project (remote sources, annotations)."""

    styles_qml: dict[str, str] = field(default_factory=dict)
    """Source layer id -> rewritten QML document (SPEC §14 asset paths)."""

    subsets: dict[str, str] = field(default_factory=dict)
    """Source layer id -> subset string to re-apply (SPEC §12/§13)."""

    display_names: dict[str, str] = field(default_factory=dict)
    """Source layer id -> custom display name for this stratum (SPEC §4 ``layer_name``,
    already evaluated). Absent ids keep the original layer name."""


def build_stratum_project(
    source: QgsProject, plan: StratumProjectPlan, feedback: QgsProcessingFeedback
) -> None:
    """
    Build and write one stratum's embedded project (SPEC §13).

    :param source: The open project being packaged (read-only here).
    :param plan: The stratum's project plan.
    :param feedback: Execution feedback channel.
    :raise QgsProcessingException: If writing the project fails.
    """
    fresh = QgsProject()
    fresh.setCrs(source.crs())
    fresh.setTransformContext(source.transformContext())
    fresh.setTitle(plan.title)
    fresh.setFilePathStorage(Qgis.FilePathType.Relative)

    replacements = _build_layers(source, plan, feedback)
    _replicate_tree(source, fresh, replacements, feedback)
    _apply_styles_and_subsets(plan, replacements, feedback)
    _remap_relations(source, fresh, replacements, feedback)

    if plan.mode is ProjectInclusion.QGZ:
        if plan.qgz_path is None:
            msg = "qgz mode requires a qgz path"
            raise QgsProcessingException(msg)
        destination = str(plan.qgz_path)
    else:
        destination = f"geopackage:{plan.gpkg_path}?projectName={plan.title}"

    # `write` returns only a bool; capture the log it emits to recover the reason on failure.
    with _capture_log() as messages:
        written = fresh.write(destination)
    if not written:
        # A failed QGZ write may leave a partial .qgz; drop it so the zip ships data only.
        # GPKG mode writes into the gpkg itself — never unlink there, that is the data.
        if plan.mode is ProjectInclusion.QGZ and plan.qgz_path is not None:
            try:
                plan.qgz_path.unlink(missing_ok=True)
            except OSError:
                feedback.pushWarning(
                    QCoreApplication.translate(
                        "ProjectBuilder", "Failed to remove project file {}"
                    ).format(plan.qgz_path)
                )
        raise QgsProcessingException(
            QCoreApplication.translate(
                "ProjectBuilder", "Writing the embedded project for stratum {} failed ({}): {}"
            ).format(plan.title, destination, _write_failure_detail(plan, messages))
        )
    feedback.pushDebugInfo(f"embedded project[{plan.title}] -> {destination}")


@contextlib.contextmanager
def _capture_log() -> Iterator[list[str]]:
    """
    Collect :class:`~qgis.core.QgsMessageLog` entries emitted on the current thread.

    Surfaces why :meth:`~qgis.core.QgsProject.write` failed: it returns only a bool while the
    cause is logged. The write runs synchronously on the algorithm thread, so its emissions
    invoke the handler before the block exits. The handler is a plain callable with no
    receiver thread affinity, so an unrelated emission from another thread during this
    window would run it on *that* thread — a tolerated, GIL-safe append of a stray line.

    :yield: The list each entry (``[tag] message``) is appended to.
    """
    captured: list[str] = []
    log = QgsApplication.messageLog()
    if log is None:  # never None in a running app, but the binding types it optional
        yield captured
        return

    def _on_message(message: str, tag: str, _level: Qgis.MessageLevel) -> None:
        captured.append(f"[{tag}] {message}")

    log.messageReceived.connect(_on_message)
    try:
        yield captured
    finally:
        log.messageReceived.disconnect(_on_message)


def _write_failure_detail(plan: StratumProjectPlan, messages: Sequence[str]) -> str:
    """
    Describe why :meth:`~qgis.core.QgsProject.write` failed, for the raised exception.

    Prefers the captured log; falls back to filesystem facts about the destination when the
    log stayed silent.

    :param plan: The stratum's project plan.
    :param messages: Captured log entries from :func:`_capture_log`.
    :return: A single-line detail string.
    """
    if messages:
        return " | ".join(messages)
    target = plan.qgz_path if plan.mode is ProjectInclusion.QGZ else plan.gpkg_path
    if target is None:
        return "no log captured"
    parent = target.parent
    return (
        f"no log captured; parent_exists={parent.is_dir()} "
        f"parent_writable={os.access(parent, os.W_OK)} target_exists={target.exists()}"
    )


def _fast_open() -> QgsVectorLayer.LayerOptions:
    """
    Build the layer options of a re-pointed embedded-project layer.

    ``loadDefaultStyle=False``: the style is applied explicitly afterwards from the exported
    QML (the very payload the gpkg ``layer_styles`` rows carry — `_finalize_layer` writes both
    from the same source), so the per-layer default-style lookup is a redundant read.
    ``skipCrsValidation=True``: the CRS comes from the just-written gpkg (or the virtual
    query); there is nothing to interactively validate on a worker thread.

    :return: The options for :class:`~qgis.core.QgsVectorLayer` construction.
    """
    options = QgsVectorLayer.LayerOptions(loadDefaultStyle=False)
    options.skipCrsValidation = True
    return options


def _build_layers(
    source: QgsProject, plan: StratumProjectPlan, feedback: QgsProcessingFeedback
) -> dict[str, QgsMapLayer]:
    """
    Create the fresh project's layers, keyed by their source layer id.

    Broken layers are never included (SPEC §13 bad-layer policy) — a re-pointed layer
    that fails to open is dropped with a warning.

    :param source: The open project being packaged.
    :param plan: The stratum's project plan.
    :param feedback: Execution feedback channel.
    :return: Source layer id -> replacement layer.
    """
    replacements: dict[str, QgsMapLayer] = {}
    for layer_id, table in plan.vector_tables.items():
        original = source.mapLayer(layer_id)
        if original is None:
            continue
        display = plan.display_names.get(layer_id) or original.name()
        # as_posix() matches _rebuild_virtual_layer's spelling: one pooled OGR dataset per
        # member gpkg instead of two (a second connection widens the §13 nolock/WAL window).
        replacement = QgsVectorLayer(
            f"{plan.gpkg_path.as_posix()}|layername={table}", display, "ogr", _fast_open()
        )
        if not replacement.isValid():
            feedback.pushWarning(
                QCoreApplication.translate(
                    "ProjectBuilder",
                    "Embedded project: table {} for layer {} did not open; dropped.",
                ).format(table, original.name())
            )
            continue
        replacements[layer_id] = replacement
    for layer_id, payload in plan.data_sources.items():
        original = source.mapLayer(layer_id)
        if original is None:
            continue
        payload_layer = original.clone()
        if payload_layer is None:
            continue
        display = plan.display_names.get(layer_id) or original.name()
        payload_layer.setDataSource(str(payload), display, original.providerType())
        if not payload_layer.isValid():
            feedback.pushWarning(
                QCoreApplication.translate(
                    "ProjectBuilder",
                    "Embedded project: payload {} for layer {} did not open; dropped.",
                ).format(payload.name, original.name())
            )
            continue
        replacements[layer_id] = payload_layer
    for layer_id in plan.embedded_only:
        original = source.mapLayer(layer_id)
        if original is None:
            continue
        embedded_layer = _embedded_replacement(original, source, plan, feedback)
        if embedded_layer is not None:
            replacements[layer_id] = embedded_layer
    return replacements


def _embedded_replacement(
    original: QgsMapLayer,
    source: QgsProject,
    plan: StratumProjectPlan,
    feedback: QgsProcessingFeedback,
) -> QgsMapLayer | None:
    """
    Build the embedded-only replacement for one layer.

    Live virtual layers are re-pointed at the stratum gpkg (:func:`_rebuild_virtual_layer`);
    remote and annotation layers are cloned with their original sources.

    :param original: The source project's embedded-only layer.
    :param source: The open project being packaged.
    :param plan: The stratum's project plan.
    :param feedback: Execution feedback channel.
    :return: The replacement layer, or :data:`None` to drop it.
    """
    if original.providerType() == "virtual":
        return _rebuild_virtual_layer(original, source, plan, feedback)
    clone = original.clone()
    if clone is None:
        return None
    custom_name = plan.display_names.get(original.id())
    if custom_name:
        clone.setName(custom_name)
    return clone


def _rebuild_virtual_layer(
    original: QgsMapLayer,
    source: QgsProject,
    plan: StratumProjectPlan,
    feedback: QgsProcessingFeedback,
) -> QgsMapLayer | None:
    """
    Re-point a live virtual layer's sources at this stratum's gpkg tables.

    Each source the virtual layer queries is rewritten to the GeoPackage table that holds
    that layer in this stratum; the query, uid and geometry definition are preserved. The
    layer is dropped (returning :data:`None`) when any source has no table in this stratum
    (e.g. an empty layer omitted under ``KEEP_EMPTY_LAYERS=False``). Style and attribute-form
    config ride along by cloning the original and only swapping its data source.

    :param original: The source project's virtual layer.
    :param source: The open project being packaged (resolves source references).
    :param plan: The stratum's project plan.
    :param feedback: Execution feedback channel.
    :return: The re-pointed virtual layer, or :data:`None` to drop it.
    """
    definition = QgsVirtualLayerDefinition.fromUrl(QUrl(original.source()))
    rebuilt = QgsVirtualLayerDefinition()
    for src in definition.sourceLayers():
        table = _resolve_virtual_source_table(src, source, plan)
        if table is None:
            feedback.pushWarning(
                QCoreApplication.translate(
                    "ProjectBuilder",
                    "Embedded project: virtual layer {} source {} has no table in this"
                    " stratum; dropped.",
                ).format(original.name(), src.name())
            )
            return None
        # Forward slashes: backslashes are mangled through the virtual layer's URL encoding
        # (Windows). Qt relativizes this absolute path on write (setFilePathStorage above).
        rebuilt.addSource(
            src.name(),
            f"{plan.gpkg_path.as_posix()}|layername={table}",
            "ogr",
            src.encoding() or "UTF-8",
        )
    rebuilt.setQuery(definition.query())
    if definition.uid():
        rebuilt.setUid(definition.uid())
    if definition.hasDefinedGeometry():
        rebuilt.setGeometryField(definition.geometryField())
        rebuilt.setGeometrySrid(definition.geometrySrid())
        rebuilt.setGeometryWkbType(definition.geometryWkbType())
    display = plan.display_names.get(original.id()) or original.name()
    # A fresh virtual layer (setDataSource does not re-init the virtual provider cleanly).
    rebuilt_layer = QgsVectorLayer(rebuilt.toString(), display, "virtual", _fast_open())
    if not rebuilt_layer.isValid():
        feedback.pushWarning(
            QCoreApplication.translate(
                "ProjectBuilder",
                "Embedded project: virtual layer {} did not re-open against the stratum"
                " gpkg; dropped.",
            ).format(original.name())
        )
        return None
    # Carry symbology and the attribute-form config (the QML Forms category) from the original.
    style = QDomDocument()
    original.exportNamedStyle(style)
    applied, message = rebuilt_layer.importNamedStyle(style)
    if not applied:
        feedback.pushWarning(
            QCoreApplication.translate(
                "ProjectBuilder",
                "Embedded project: style for virtual layer {} not applied: {}",
            ).format(original.name(), message)
        )
    return rebuilt_layer


def _resolve_virtual_source_table(
    src: QgsVirtualLayerDefinition.SourceLayer,
    source: QgsProject,
    plan: StratumProjectPlan,
) -> str | None:
    """
    Find the stratum gpkg table backing one virtual-layer source.

    References by layer id resolve directly; embedded sources match the first packaged
    layer with the same provider and source string.

    :param src: A source layer of the virtual definition.
    :param source: The open project being packaged.
    :param plan: The stratum's project plan.
    :return: The table name, or :data:`None` when the source is not packaged here.
    """
    if src.isReferenced():
        return plan.vector_tables.get(src.reference())
    for layer_id, table in plan.vector_tables.items():
        candidate = source.mapLayer(layer_id)
        if (
            candidate is not None
            and candidate.providerType() == src.provider()
            and candidate.source() == src.source()
        ):
            return table
    return None


def _replicate_tree(
    source: QgsProject,
    fresh: QgsProject,
    replacements: Mapping[str, QgsMapLayer],
    feedback: QgsProcessingFeedback,
) -> None:
    """
    Replicate the layer tree (groups, order, visibility) for included layers.

    :param source: The open project being packaged.
    :param fresh: The project under construction.
    :param replacements: Source layer id -> replacement layer.
    :param feedback: Execution feedback channel.
    """
    source_root = source.layerTreeRoot()
    fresh_root = fresh.layerTreeRoot()
    if source_root is None or fresh_root is None:
        feedback.pushWarning(
            QCoreApplication.translate(
                "ProjectBuilder", "Embedded project: no layer tree available."
            )
        )
        return

    placed: set[str] = set()

    def walk(source_group: QgsLayerTreeGroup, target_group: QgsLayerTreeGroup) -> None:
        for child in source_group.children():
            if isinstance(child, QgsLayerTreeGroup):
                new_group = target_group.addGroup(child.name())
                if new_group is not None:
                    new_group.setItemVisibilityChecked(child.itemVisibilityChecked())
                    walk(child, new_group)
            elif isinstance(child, QgsLayerTreeLayer):
                replacement = replacements.get(child.layerId())
                if replacement is None:
                    continue
                placed.add(child.layerId())
                if fresh.addMapLayer(replacement, addToLegend=False) is None:
                    feedback.pushWarning(
                        QCoreApplication.translate(
                            "ProjectBuilder", "Embedded project: layer {} was rejected."
                        ).format(replacement.name())
                    )
                    continue
                node = target_group.addLayer(replacement)
                if node is not None:
                    node.setItemVisibilityChecked(child.itemVisibilityChecked())

    walk(source_root, fresh_root)
    _append_unplaced(fresh, fresh_root, replacements, placed)


def _append_unplaced(
    fresh: QgsProject,
    fresh_root: QgsLayerTreeGroup,
    replacements: Mapping[str, QgsMapLayer],
    placed: set[str],
) -> None:
    """
    Append included layers that had no source tree node (legend-less additions).

    :param fresh: The project under construction.
    :param fresh_root: Its layer-tree root.
    :param replacements: Source layer id -> replacement layer.
    :param placed: Layer ids already placed by the tree walk.
    """
    for layer_id, replacement in replacements.items():
        if layer_id not in placed and fresh.addMapLayer(replacement, addToLegend=False):
            fresh_root.addLayer(replacement)


def _apply_styles_and_subsets(
    plan: StratumProjectPlan,
    replacements: Mapping[str, QgsMapLayer],
    feedback: QgsProcessingFeedback,
) -> None:
    """
    Apply the rewritten QML styles and re-apply subset strings.

    :param plan: The stratum's project plan.
    :param replacements: Source layer id -> replacement layer.
    :param feedback: Execution feedback channel.
    """
    for layer_id, qml in plan.styles_qml.items():
        replacement = replacements.get(layer_id)
        if replacement is None or not qml:
            continue
        document = QDomDocument()
        if not document.setContent(qml)[0]:
            feedback.pushWarning(
                QCoreApplication.translate(
                    "ProjectBuilder", "Embedded project: style for layer {} did not parse."
                ).format(replacement.name())
            )
            continue
        ok, message = replacement.importNamedStyle(document)
        if not ok:
            feedback.pushWarning(
                QCoreApplication.translate(
                    "ProjectBuilder", "Embedded project: style for layer {} not applied: {}"
                ).format(replacement.name(), message)
            )
    for layer_id, subset in plan.subsets.items():
        replacement = replacements.get(layer_id)
        if not subset or not isinstance(replacement, QgsVectorLayer):
            continue
        # The subset is the source provider's SQL, but the replacement reads a GeoPackage: a
        # dialect the layer API accepts can still be one SQLite cannot prepare, and that failure
        # only ever reaches a GDAL error handler. Say so plainly, then apply it anyway — the
        # probe cannot see the extension functions a real GeoPackage connection registers.
        dialect_error = sqlite_where_error(
            (field.name() for field in replacement.fields().toList()), subset
        )
        if dialect_error is not None:
            feedback.pushWarning(
                QCoreApplication.translate(
                    "ProjectBuilder",
                    "Embedded project: layer {}'s subset is not valid SQLite ({}), so the"
                    " packaged project may show no features for it. This layer shares its"
                    " table with others, so the subset is what separates them — rewrite it in"
                    " SQL the GeoPackage understands. Subset: {}",
                ).format(replacement.name(), dialect_error, subset)
            )
        if not replacement.setSubsetString(subset):
            feedback.pushWarning(
                QCoreApplication.translate(
                    "ProjectBuilder", "Embedded project: subset for layer {} was not accepted: {}"
                ).format(replacement.name(), subset)
            )


def _remap_relations(
    source: QgsProject,
    fresh: QgsProject,
    replacements: Mapping[str, QgsMapLayer],
    feedback: QgsProcessingFeedback,
) -> None:
    """
    Recreate the relations whose both ends are included.

    Relations touching excluded layers are dropped.

    :param source: The open project being packaged.
    :param fresh: The project under construction.
    :param replacements: Source layer id -> replacement layer.
    :param feedback: Execution feedback channel.
    """
    source_manager = source.relationManager()
    fresh_manager = fresh.relationManager()
    if source_manager is None or fresh_manager is None:
        return
    for relation in source_manager.relations().values():
        if not relation.isValid():
            continue
        referencing = replacements.get(relation.referencingLayerId())
        referenced = replacements.get(relation.referencedLayerId())
        if referencing is None or referenced is None:
            continue
        original_referencing = relation.referencingLayer()
        original_referenced = relation.referencedLayer()
        if original_referencing is None or original_referenced is None:
            continue
        # The default relation context resolves layers against QgsProject.instance();
        # the remapped relation must validate against the fresh project instead.
        remapped = QgsRelation(QgsRelationContext(fresh))
        remapped.setId(relation.id())  # noqa: QGS201  # setId returns nothing; checker misattribution
        remapped.setName(relation.name())
        remapped.setReferencingLayer(referencing.id())
        remapped.setReferencedLayer(referenced.id())
        for child_index, parent_index in zip(
            relation.referencingFields(), relation.referencedFields(), strict=True
        ):
            remapped.addFieldPair(
                original_referencing.fields()[child_index].name(),
                original_referenced.fields()[parent_index].name(),
            )
        if remapped.isValid():
            fresh_manager.addRelation(remapped)
        else:
            feedback.pushWarning(
                QCoreApplication.translate(
                    "ProjectBuilder", "Embedded project: relation {} could not be remapped: {}"
                ).format(relation.name(), remapped.validationError())
            )
