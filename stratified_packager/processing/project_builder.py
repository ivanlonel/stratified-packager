"""
Embedded per-stratum project construction (SPEC §13).

Runs on the algorithm thread during Phase C — never against
:meth:`~qgis.core.QgsProject.instance`. The fresh project re-points included layers at
the stratum GeoPackage tables and the ``data/`` payload copies, restores the layer-tree
structure (groups, order) and each node's presentation state (check state, expanded state,
legend customizations) restricted to included layers, applies the full (rewritten) styles,
remaps relations among included layers, and carries the project CRS, transform context,
title and the source's initial map view (so it opens at the same position and zoom).
Paths are stored relative: the caller builds the
stratum inside a directory tree that mirrors the zip layout, so Qt's relative-path
storage produces portable ``./…`` sources (SPEC §13).
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Final

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsLayerTreeGroup,
    QgsLayerTreeLayer,
    QgsMapLayer,
    QgsProcessingException,
    QgsProject,
    QgsRasterLayer,
    QgsReadWriteContext,
    QgsRectangle,
    QgsReferencedRectangle,
    QgsRelation,
    QgsRelationContext,
    QgsVectorLayer,
    QgsVectorTileLayer,
    QgsVirtualLayerDefinition,
)
from qgis.PyQt.QtCore import QCoreApplication, QUrl
from qgis.PyQt.QtXml import QDomDocument, QDomElement

from stratified_packager.toolbelt import gpkg
from stratified_packager.toolbelt.sql import (
    equality_operands,
    source_tables,
    sqlite_where_error,
)

from .material import slowest_summary
from .params import ProjectInclusion

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Iterator, Mapping, Sequence

    from qgis.core import QgsLayerTreeNode, QgsProcessingFeedback

__all__: list[str] = [
    "StratumProjectPlan",
    "build_stratum_project",
    "index_join_columns",
    "read_saved_view_extent",
    "resolve_initial_view",
    "snapshot_embedded_layers",
    "validate_repointed_sources",
]

_WRITE_STEP: Final = "<project write>"
"""Name :func:`_report_slowest_steps` gives the project write, alongside the layer names.

Angle-bracketed like the SPEC's other pseudo-names (``<full>``, ``<unmatched>``), so it cannot
collide with a layer."""

_REVIVABLE_LAYER_TYPES: Final[dict[Qgis.LayerType, Callable[[], QgsMapLayer]]] = {
    Qgis.LayerType.Raster: QgsRasterLayer,
    Qgis.LayerType.Vector: QgsVectorLayer,
    Qgis.LayerType.VectorTile: QgsVectorTileLayer,
}
"""Layer types :func:`snapshot_embedded_layers` can reproduce from XML.

Each entry must construct an empty, source-less layer that
:meth:`~qgis.core.QgsMapLayer.readLayerXml` can then fill.
Types absent here keep the :meth:`~qgis.core.QgsMapLayer.clone` path — correct but, for a
remote provider, a blocking network round-trip per stratum."""

_TREE_NODE_SKIP_PROPERTIES: Final[frozenset[str]] = frozenset({"embedded", "embedded_project"})
"""Layer-tree node custom properties never carried into the embedded project.

They mark a node whose children QGIS reloads from *another* project file on open
(:meth:`~qgis.core.QgsProject.createEmbeddedGroup`), by an absolute path that does not ship
beside the packaged data — the tree walk flattens such a node's children into a plain group
instead, and carrying the markers would send QGIS looking for the source machine's project.
"""


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

    repointed: frozenset[str] = frozenset()
    """Source layer ids marked ``matching_method = project_only`` (§4) — a subset of
    :attr:`embedded_only` whose data source is re-pointed at this stratum's gpkg (§13)
    instead of carried over unchanged."""

    embedded_xml: dict[str, str] = field(default_factory=dict)
    """The run's :func:`snapshot_embedded_layers` result: source layer id -> serialized
    ``<maplayer>`` document. Shared by every stratum, so a remote layer is reproduced without
    reopening its source. Absent ids fall back to :meth:`~qgis.core.QgsMapLayer.clone`."""

    styles_qml: dict[str, str] = field(default_factory=dict)
    """Source layer id -> rewritten QML document (SPEC §14 asset paths)."""

    subsets: dict[str, str] = field(default_factory=dict)
    """Source layer id -> subset string to re-apply (SPEC §12/§13)."""

    display_names: dict[str, str] = field(default_factory=dict)
    """Source layer id -> custom display name for this stratum (SPEC §4 ``layer_name``,
    already evaluated). Absent ids keep the original layer name."""

    initial_view: QgsReferencedRectangle | None = None
    """The source project's initial map view (§13) — its saved canvas extent, else its
    configured default view extent — applied to the embedded project's view settings so it
    opens at the same position and zoom. :data:`None` leaves QGIS's full-extent default."""


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
    _apply_initial_view(fresh, plan)

    replacements, elapsed = _build_layers(source, plan, feedback)
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
    started = time.perf_counter()
    with _capture_log() as messages:
        written = fresh.write(destination)
    elapsed.append((time.perf_counter() - started, _WRITE_STEP))
    # Drop the layers as soon as the project is on disk: a §4 project_only layer whose subset
    # is a SELECT is backed by an OGR ExecuteSQL handle on the stratum gpkg, and a handle that
    # outlives this call blocks the §10 pre-zip WAL checkpoint — which would ship a gpkg
    # missing whatever is still in the (never zipped) -wal sidecar. Releasing here does not
    # wait on when this project object is collected.
    fresh.removeAllMapLayers()
    _report_slowest_steps(plan.title, elapsed, feedback)
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


def _report_slowest_steps(
    title: str, elapsed: Sequence[tuple[float, str]], feedback: QgsProcessingFeedback
) -> None:
    """
    Push one line breaking this stratum's embedded-project build down by step.

    Read against the caller's total for the whole phase: when the two agree the cost is in a
    layer this line names, and when they diverge it is in the tree/style/relation work between
    them. That pairing is what makes a stall in here attributable at all — see
    :func:`~stratified_packager.processing.material.slowest_summary`.

    :param title: The stratum's title.
    :param elapsed: One ``(seconds, name)`` pair per layer opened, plus the project write.
    :param feedback: Execution feedback channel.
    """
    if not elapsed:
        return
    total, slowest = slowest_summary(elapsed)
    feedback.pushInfo(
        QCoreApplication.translate(
            "ProjectBuilder", "Stratum {}: {:.1f}s in embedded-project steps; slowest {}"
        ).format(title, total, slowest)
    )


def _apply_initial_view(fresh: QgsProject, plan: StratumProjectPlan) -> None:
    """
    Set the embedded project's initial map view from the plan (§13).

    A headless :meth:`~qgis.core.QgsProject.write` emits no ``<mapcanvas>`` element, so the
    written project has no per-canvas saved extent; :class:`~qgis.core.QgsProjectViewSettings`'
    default view extent is therefore honoured on open, landing the canvas on the source
    project's view instead of the full layer extent.

    :param fresh: The project under construction.
    :param plan: The stratum's project plan.
    """
    if plan.initial_view is None or plan.initial_view.isNull():
        return
    settings = fresh.viewSettings()
    if settings is not None:
        settings.setDefaultViewExtent(plan.initial_view)


def resolve_initial_view(project: QgsProject) -> QgsReferencedRectangle | None:
    """
    Resolve where the source project opens, for the embedded projects (§13).

    Reproduces the original's initial view: its **saved** map-canvas extent (read from the
    project file — the normal GUI-saved case), else its configured default view extent, else
    :data:`None` (QGIS falls back to the full extent of the layers). The rectangle is returned
    in the project CRS, which the caller has already set on the embedded project, so applying
    it needs no reprojection.

    :param project: The open project being packaged.
    :return: The initial view rectangle, or :data:`None` when none can be determined.
    """
    saved = read_saved_view_extent(Path(project.fileName()))
    if saved is not None:
        return QgsReferencedRectangle(QgsRectangle(*saved), project.crs())
    settings = project.viewSettings()
    if settings is not None:
        default = settings.defaultViewExtent()
        if not default.isNull():
            return default
    return None


def read_saved_view_extent(project_file: Path) -> tuple[float, float, float, float] | None:
    """
    Read the last-saved map-canvas extent from a project file.

    QGIS Desktop stores the canvas view under a top-level ``<mapcanvas>`` element; a headless
    :meth:`~qgis.core.QgsProject.write` never emits one, which is why generated projects open
    on the full layer extent rather than where the original was saved. This parses that
    element (preferring the primary ``theMapCanvas``) straight from the ``.qgs`` XML —
    extracting it from the ``.qgz`` archive first — and returns its extent.

    :param project_file: The source project file (``.qgs`` or ``.qgz``).
    :return: ``(xmin, ymin, xmax, ymax)`` in the project CRS, or :data:`None` when the file is
        not a readable project, carries no ``<mapcanvas>`` extent, or the extent is degenerate.
    """
    document = _read_project_document(project_file)
    if document is None:
        return None
    canvas = _primary_map_canvas(document)
    if canvas is None:
        return None
    extent = canvas.firstChildElement("extent")
    if extent.isNull():
        return None
    try:
        bounds = (
            float(extent.firstChildElement("xmin").text()),
            float(extent.firstChildElement("ymin").text()),
            float(extent.firstChildElement("xmax").text()),
            float(extent.firstChildElement("ymax").text()),
        )
    except ValueError:
        return None
    xmin, ymin, xmax, ymax = bounds
    if xmax <= xmin or ymax <= ymin:
        return None
    return bounds


def _read_project_document(project_file: Path) -> QDomDocument | None:
    """
    Load a project file's XML — ``.qgs`` directly, the ``.qgz`` archive's inner ``.qgs``.

    :param project_file: The source project file.
    :return: The parsed document, or :data:`None` when the file is missing, is not a
        ``.qgs``/``.qgz``, or does not parse as XML.
    """
    try:
        suffix = project_file.suffix.lower()
        if suffix == ".qgz":
            with zipfile.ZipFile(project_file) as archive:
                member = next((n for n in archive.namelist() if n.endswith(".qgs")), None)
                if member is None:
                    return None
                data = archive.read(member)
        elif suffix == ".qgs":
            data = project_file.read_bytes()
        else:
            return None
    except (OSError, zipfile.BadZipFile):
        return None
    document = QDomDocument()
    if not document.setContent(data.decode("utf-8", "replace"))[0]:
        return None
    return document


def _primary_map_canvas(document: QDomDocument) -> QDomElement | None:
    """
    Find the primary ``<mapcanvas>`` element, preferring the ``theMapCanvas`` main view.

    :param document: The parsed project XML.
    :return: The chosen element, or :data:`None` when the project has no ``<mapcanvas>``.
    """
    canvases = document.elementsByTagName("mapcanvas")
    fallback: QDomElement | None = None
    for index in range(canvases.count()):
        element = canvases.at(index).toElement()
        if element.isNull():
            continue
        if element.attribute("name") == "theMapCanvas":
            return element
        if fallback is None:
            fallback = element
    return fallback


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
) -> tuple[dict[str, QgsMapLayer], list[tuple[float, str]]]:
    """
    Create the fresh project's layers, keyed by their source layer id.

    Broken layers are never included (SPEC §13 bad-layer policy) — a re-pointed layer
    that fails to open is dropped with a warning.

    :param source: The open project being packaged.
    :param plan: The stratum's project plan.
    :param feedback: Execution feedback channel.
    :return: Source layer id -> replacement layer, and one ``(seconds, name)`` pair per layer
        opened, for the caller's timing line.
    """
    replacements: dict[str, QgsMapLayer] = {}
    elapsed: list[tuple[float, str]] = []
    for layer_id, table in plan.vector_tables.items():
        original = source.mapLayer(layer_id)
        if original is None:
            continue
        display = plan.display_names.get(layer_id) or original.name()
        started = time.perf_counter()
        # as_posix() matches _rebuild_virtual_layer's spelling: one pooled OGR dataset per
        # member gpkg instead of two (a second connection widens the §13 nolock/WAL window).
        replacement = QgsVectorLayer(
            f"{plan.gpkg_path.as_posix()}|layername={table}", display, "ogr", _fast_open()
        )
        elapsed.append((time.perf_counter() - started, table))
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
        started = time.perf_counter()
        payload_layer = original.clone()
        if payload_layer is None:
            continue
        display = plan.display_names.get(layer_id) or original.name()
        payload_layer.setDataSource(str(payload), display, original.providerType())
        elapsed.append((time.perf_counter() - started, payload.name))
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
        started = time.perf_counter()
        embedded_layer = _embedded_replacement(original, source, plan, feedback)
        elapsed.append((time.perf_counter() - started, original.name()))
        if embedded_layer is not None:
            replacements[layer_id] = embedded_layer
    return replacements, elapsed


def _embedded_replacement(
    original: QgsMapLayer,
    source: QgsProject,
    plan: StratumProjectPlan,
    feedback: QgsProcessingFeedback,
) -> QgsMapLayer | None:
    """
    Build the embedded-only replacement for one layer.

    A §4 ``project_only`` layer keeps its uri options and only swaps the file path for this
    stratum's gpkg (:func:`_repoint_layer_source`); a live virtual layer is re-pointed source
    by source (:func:`_rebuild_virtual_layer`). Everything else is reproduced from the run's
    :func:`snapshot_embedded_layers` XML, which keeps the original source without reopening
    it; only a layer type the snapshot cannot reproduce falls back to
    :meth:`~qgis.core.QgsMapLayer.clone`.

    :param original: The source project's embedded-only layer.
    :param source: The open project being packaged.
    :param plan: The stratum's project plan.
    :param feedback: Execution feedback channel.
    :return: The replacement layer, or :data:`None` to drop it.
    """
    if original.id() in plan.repointed:
        return _repoint_layer_source(original, plan, feedback)
    if original.providerType() == "virtual":
        return _rebuild_virtual_layer(original, source, plan, feedback)
    xml = plan.embedded_xml.get(original.id())
    revived = _revive_embedded_layer(original, xml, plan) if xml else None
    if revived is not None:
        return revived
    clone = original.clone()
    if clone is None:
        return None
    custom_name = plan.display_names.get(original.id())
    if custom_name:
        clone.setName(custom_name)
    return clone


def snapshot_embedded_layers(layers: Iterable[QgsMapLayer]) -> dict[str, str]:
    """
    Serialize the embedded-only layers once for the whole run (SPEC §13).

    Every stratum's project carries the same embedded-only layers, and rebuilding one with
    :meth:`~qgis.core.QgsMapLayer.clone` re-constructs its provider from the URI. For a remote
    provider that construction is a blocking network request — a WMS layer fetches
    GetCapabilities — so cloning charges the run one round-trip per layer *per stratum*,
    against a server whose answer never changes and which may not answer at all.

    Serializing here instead makes :func:`_revive_embedded_layer` a pure XML operation.
    Live virtual layers are excluded: they are re-pointed at each stratum's gpkg, not reused.

    :param layers: The run's embedded-only layers.
    :return: Layer id -> serialized ``<maplayer>`` document, for the layers that can be
        reproduced; the rest are absent and keep the clone path.
    """
    snapshot: dict[str, str] = {}
    context = QgsReadWriteContext()
    for layer in layers:
        if layer.providerType() == "virtual" or layer.type() not in _REVIVABLE_LAYER_TYPES:
            continue
        document = QDomDocument()
        element = document.createElement("maplayer")
        document.appendChild(element)
        if layer.writeLayerXml(element, document, context):
            snapshot[layer.id()] = document.toString()
    return snapshot


def _revive_embedded_layer(
    original: QgsMapLayer, xml: str, plan: StratumProjectPlan
) -> QgsMapLayer | None:
    """
    Rebuild one embedded-only layer from its snapshot XML, without opening its source.

    ``FlagDontResolveLayers`` fills the layer's state from the document but skips provider
    construction, so no network request is made. The layer therefore has no provider to
    serialize itself back from, which is what
    :meth:`~qgis.core.QgsMapLayer.setOriginalXmlProperties` covers:
    :meth:`~qgis.core.QgsProject.write` emits those bytes verbatim. That also makes the
    stored document — not the layer object — authoritative, so a §4 ``layer_name`` override
    has to be patched into the XML rather than applied with ``setName``.

    :param original: The source project's layer (its type picks the empty layer to fill).
    :param xml: The layer's snapshot document.
    :param plan: The stratum's project plan.
    :return: The replacement layer, or :data:`None` for the caller to fall back to cloning.
    """
    factory = _REVIVABLE_LAYER_TYPES.get(original.type())
    document = QDomDocument()
    if factory is None or not document.setContent(xml)[0]:
        return None
    element = document.documentElement()
    custom_name = plan.display_names.get(original.id())
    if custom_name:
        _rename_layer_element(document, element, custom_name)
    revived = factory()
    if not revived.readLayerXml(
        element, QgsReadWriteContext(), QgsMapLayer.ReadFlag.FlagDontResolveLayers
    ):
        return None
    revived.setOriginalXmlProperties(document.toString())
    return revived


def _rename_layer_element(document: QDomDocument, element: QDomElement, name: str) -> None:
    """
    Rewrite a serialized layer's ``<layername>`` in place.

    :param document: The document owning *element* (creates the node when absent).
    :param element: The ``<maplayer>`` element.
    :param name: The display name to store.
    """
    nodes = element.elementsByTagName("layername")
    if nodes.isEmpty():
        node = element.appendChild(document.createElement("layername"))
    else:
        node = nodes.at(0)
    text = document.createTextNode(name)
    children = node.childNodes()
    if children.isEmpty():
        node.appendChild(text)
    else:
        node.replaceChild(text, children.at(0))


def _rebuild_virtual_layer(
    original: QgsMapLayer,
    source: QgsProject,
    plan: StratumProjectPlan,
    feedback: QgsProcessingFeedback,
) -> QgsMapLayer | None:
    """
    Re-point a live virtual layer's sources at this stratum's gpkg tables.

    Each source the virtual layer queries is rewritten to the GeoPackage table that holds
    that layer in this stratum; the query, subset, uid and geometry definition are preserved,
    and the layer is left without a computed extent so the build never runs the query. The
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
    # The subset is the author's filter over the query result, so dropping it would ship more
    # features than they configured. ``lazy`` is deliberately *not* carried over: it defers the
    # provider's load, and a layer that only populates after a manual reload is not a delivered
    # layer. The build cost it would have hidden is dealt with by the extent below instead.
    # The suppression: this is QgsVirtualLayerDefinition's setter, which returns None — QGS201
    # matches it by the name of QgsVectorLayer's flag-returning method.
    rebuilt.setSubsetString(definition.subsetString())  # noqa: QGS201
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
    # Writing the project serializes every layer's extent, and a virtual layer derives its own
    # by running the query over the stratum gpkg — whose join columns QgsVectorFileWriter leaves
    # unindexed, making that a nested-loop scan whose cost grows faster than the stratum does
    # (measured superlinear; hours per stratum on a large one). Nothing in the package needs the
    # value: left unset the element is simply omitted, and the recipient's QGIS derives it once,
    # locally, when something first asks. The layer itself stays fully loaded either way.
    rebuilt_layer.setExtent(QgsRectangle())
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


def _source_options(layer: QgsMapLayer) -> str:
    """
    Return *layer*'s uri options: everything from the first ``|`` of its data source on.

    Read from the stored uri text rather than from the provider, so it answers for a layer
    whose source does not exist on this machine — the normal state of a §4 ``project_only``
    layer, and the reason it is never opened.

    :param layer: The layer whose data source is inspected.
    :return: ``|layername=…|subset=…`` and friends, leading separator included; empty when
        the uri carries no options.
    """
    _, separator, tail = layer.source().partition("|")
    return f"{separator}{tail}"


def validate_repointed_sources(layers: Iterable[QgsMapLayer], tables: Collection[str], /) -> None:
    """
    Check the §4 ``project_only`` layers can be re-pointed at the stratum gpkg (§13).

    Both guards are fatal at run start rather than at project-build time, where the only
    remaining move is to drop the layer — which ships a package quietly missing it.

    The provider guard is the load-bearing one: re-pointing replaces everything before the
    first ``|``, so a source that is not a file path (a database connection string) would be
    replaced *whole*, leaving a valid layer over the gpkg's first table — wrong data, no
    error. The table guard catches the drift that makes such a layer stop resolving: it is
    authored against the names Phase A mints from the layer names, so renaming a packaged
    layer (or a §12 duplicate earning a ``_2`` suffix) silently breaks it.

    :param layers: The run's ``project_only`` layers.
    :param tables: The table names Phase A minted for this run.
    :raise qgis.core.QgsProcessingException: If a layer's provider is not ``ogr``, or its
        query reads a table this run does not create.
    """
    known = {table.lower() for table in tables}
    for layer in layers:
        if layer.providerType() != "ogr":
            raise QgsProcessingException(
                QCoreApplication.translate(
                    "ProjectBuilder",
                    "Layer {}: matching_method = project_only re-points the data source at the"
                    " stratum GeoPackage, which only a file-based (ogr) source can express;"
                    " this layer's provider is {}.",
                ).format(layer.name(), layer.providerType())
            )
        unknown = sorted(
            name for name in source_tables(_source_options(layer)) if name.lower() not in known
        )
        if unknown:
            raise QgsProcessingException(
                QCoreApplication.translate(
                    "ProjectBuilder",
                    "Layer {}: its query reads table(s) this run does not create ({}). A"
                    " project_only layer is written against the packaged tables, which are:"
                    " {}.",
                ).format(layer.name(), ", ".join(unknown), ", ".join(sorted(tables)))
            )


def _repoint_layer_source(
    original: QgsMapLayer, plan: StratumProjectPlan, feedback: QgsProcessingFeedback
) -> QgsMapLayer | None:
    """
    Re-point a §4 ``project_only`` layer's data source at this stratum's gpkg (§13).

    Only the file path changes: every uri option after it rides along verbatim — including a
    ``|subset=`` holding a whole ``SELECT``, which is the layer's entire definition. Such a
    layer is authored against the *package*, naming the tables and columns the run writes, so
    rewriting anything else would break it. Nothing here reads the original, which is the
    point: its own source need not exist on the packaging machine.

    :param original: The source project's project-only layer.
    :param plan: The stratum's project plan.
    :param feedback: Execution feedback channel.
    :return: The re-pointed layer, or :data:`None` to drop it.
    """
    display = plan.display_names.get(original.id()) or original.name()
    # as_posix() matches the other re-pointed sources' spelling: one pooled OGR dataset per
    # member gpkg instead of two (a second connection widens the §13 nolock/WAL window).
    # Absolute here; Qt relativizes it on write (setFilePathStorage above).
    replacement = QgsVectorLayer(
        f"{plan.gpkg_path.as_posix()}{_source_options(original)}",
        display,
        original.providerType(),
        _fast_open(),
    )
    if not replacement.isValid():
        feedback.pushWarning(
            QCoreApplication.translate(
                "ProjectBuilder",
                "Embedded project: layer {} did not re-open against the stratum gpkg; dropped.",
            ).format(original.name())
        )
        return None
    # Writing the project serializes every layer's extent, and a layer whose subset is a join
    # over the stratum gpkg derives its own by running that join — once per stratum, for a
    # value the package never reads. Left unset the element is simply omitted and the
    # recipient's QGIS derives it on demand, locally, once (as for a live virtual layer).
    replacement.setExtent(QgsRectangle())
    # Carry symbology and the attribute-form config (the QML Forms category) from the original.
    style = QDomDocument()
    original.exportNamedStyle(style)
    applied, message = replacement.importNamedStyle(style)
    if not applied:
        feedback.pushWarning(
            QCoreApplication.translate(
                "ProjectBuilder", "Embedded project: style for layer {} not applied: {}"
            ).format(original.name(), message)
        )
    return replacement


def index_join_columns(
    source: QgsProject, plan: StratumProjectPlan, feedback: QgsProcessingFeedback
) -> None:
    """
    Index the columns this stratum's re-pointed layers join on, in its gpkg (SPEC §13).

    Both routes that keep a query live against the package — a live virtual layer and a §4
    ``project_only`` layer whose ``|subset=`` is a ``SELECT`` — re-run that whole query for
    every feature count and every render (the canvas extent filter wraps the query rather than
    entering it), and QGIS pushes each equality in it down as one filtered request *per outer
    row*. Against the columns :class:`~qgis.core.QgsVectorFileWriter` leaves unindexed, every
    one of those requests is a full scan of the inner table, so the recipient pays a
    nested-loop join each time the layer is drawn. An index turns each request into a b-tree
    seek: measured 35x end to end on a 73k x 61k join (a feature count of 446s down to 13s),
    for indexes built in hundredths of a second and about one percent of the GeoPackage's size.

    One single-column index per column rather than one composite: QGIS stops at the first usable
    constraint, so only ever one column is pushed down and a composite index would serve only
    its leading column.

    Best effort by design — an index that cannot be created costs the recipient speed, never
    correctness, so a failure is reported and the stratum ships regardless.

    :param source: The open project being packaged.
    :param plan: The stratum's project plan, whose gpkg is already written.
    :param feedback: Execution feedback channel.
    """
    for layer_id in plan.embedded_only:
        layer = source.mapLayer(layer_id)
        if layer is None:
            continue
        if layer_id in plan.repointed:
            # ponytail: offered every packaged table, not the ones the query names — the
            # column intersection in _index_source_table drops the rest for one pragma each.
            # Narrow with sql.source_tables() if that sweep ever shows up in a profile.
            candidates = equality_operands(_source_options(layer))
            for table in sorted(set(plan.vector_tables.values())):
                _index_source_table(plan.gpkg_path, table, candidates, layer.name(), feedback)
        elif layer.providerType() == "virtual":
            definition = QgsVirtualLayerDefinition.fromUrl(QUrl(layer.source()))
            candidates = equality_operands(definition.query())
            for src in definition.sourceLayers():
                source_table = _resolve_virtual_source_table(src, source, plan)
                if source_table is not None:
                    _index_source_table(
                        plan.gpkg_path, source_table, candidates, layer.name(), feedback
                    )


def _index_source_table(
    gpkg_path: Path,
    table: str,
    candidates: frozenset[str],
    layer_name: str,
    feedback: QgsProcessingFeedback,
) -> None:
    """
    Index the *candidates* that are real columns of *table* (SPEC §13).

    The intersection with the table's own columns is what keeps
    :func:`~stratified_packager.toolbelt.sql.equality_operands` a scan instead of a parser: a
    literal or alias it also matched has no column here and is dropped.

    :param gpkg_path: The stratum GeoPackage.
    :param table: A table the querying layer reads.
    :param candidates: Identifiers the querying layer compares with ``=``.
    :param layer_name: The querying layer's name, for messages.
    :param feedback: Execution feedback channel.
    """
    try:
        columns = sorted(candidates & gpkg.column_names(gpkg_path, table))
        for column in columns:
            gpkg.create_attribute_index(gpkg_path, table, [column])
    except (sqlite3.Error, OSError) as err:
        feedback.pushWarning(
            QCoreApplication.translate(
                "ProjectBuilder",
                "Embedded project: could not index table {} for layer {}: {}. It ships"
                " unindexed, so the layer will be slow to draw.",
            ).format(table, layer_name, err)
        )
    else:
        if columns:
            feedback.pushDebugInfo(
                QCoreApplication.translate(
                    "ProjectBuilder",
                    "Embedded project: indexed {} on table {} for layer {}.",
                ).format(", ".join(columns), table, layer_name)
            )


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


def _copy_node_state(source_node: QgsLayerTreeNode, target_node: QgsLayerTreeNode) -> None:
    """
    Mirror one layer-tree node's presentation state onto its replacement (SPEC §13).

    Carries the collapsed/expanded state, the check state, and every custom property the node
    holds. That property bag is where QGIS keeps the rest of what the Layers panel shows —
    the legend feature counts (``showFeatureCount``) and the legend-node customizations
    (renamed, reordered and hidden classes, under ``legend/…``) — so the packaged project's
    panel reads like the original's. It is copied wholesale rather than key by key so this
    does not drift as QGIS grows new node state; only the keys that would point QGIS back at
    the source machine are dropped (:data:`_TREE_NODE_SKIP_PROPERTIES`).

    :param source_node: The node in the project being packaged.
    :param target_node: The freshly created node in the embedded project.
    """
    target_node.setExpanded(source_node.isExpanded())
    target_node.setItemVisibilityChecked(source_node.itemVisibilityChecked())
    for key in source_node.customProperties():
        if key not in _TREE_NODE_SKIP_PROPERTIES:
            target_node.setCustomProperty(key, source_node.customProperty(key))


def _replicate_tree(
    source: QgsProject,
    fresh: QgsProject,
    replacements: Mapping[str, QgsMapLayer],
    feedback: QgsProcessingFeedback,
) -> None:
    """
    Replicate the layer tree (groups, order, node state) for included layers.

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
                    _copy_node_state(child, new_group)
                    walk(child, new_group)
                    # Only once the children exist: the default initial index (-1) resolves to
                    # whichever child the copied check state left checked.
                    new_group.setIsMutuallyExclusive(child.isMutuallyExclusive())
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
                    _copy_node_state(child, node)

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
