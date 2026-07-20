"""
The Stratified Packager Processing algorithm: orchestration of Phases A/B/C (SPEC §8).

All user-facing messaging inside algorithm execution goes through the
:class:`qgis.core.QgsProcessingFeedback` instance supplied by the Processing
framework — never the plugin logger (whose records do not reach the algorithm's log
panel or ``qgis_process`` output). Fatal failures raise
:exc:`qgis.core.QgsProcessingException`, the framework's sanctioned failure path;
per-stratum failures are contained (best-effort policy, SPEC §17) and surface in one
final exception listing the failed strata. Helpers invoked during execution take the
feedback as an explicit parameter.

Build layout: every zip gets its own build root mirroring the zip's internal layout
(gpkgs at their ``gpkg_rel`` paths, ``data/`` and ``resources/`` beside them), so
Qt's relative-path storage produces portable ``./…`` sources in embedded projects
(SPEC §13) and zip assembly is a plain tree walk. The Phase-A→B/C records and the
per-phase helpers live in the sibling ``material``, ``dedup``, ``virtual`` and ``reporting``
modules; this module orchestrates them.
"""
# pylint: disable=too-many-lines  # single orchestrator module fixed by SPEC §18 layout

from __future__ import annotations

import gc
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import fields, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, cast, override

from qgis.core import (
    Qgis,
    QgsExpression,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsMapLayer,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingFeedback,
    QgsProcessingMultiStepFeedback,
    QgsProcessingUtils,
    QgsProject,
    QgsSldExportContext,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QCoreApplication, QMetaType, Qt
from qgis.PyQt.QtGui import QPalette
from qgis.PyQt.QtWidgets import QApplication
from qgis.PyQt.QtXml import QDomDocument

from stratified_packager.settings import StratifiedPackagerSettings
from stratified_packager.toolbelt import gpkg, sql
from stratified_packager.toolbelt.i18n import slugify
from stratified_packager.toolbelt.relations import build_relation_graph
from stratified_packager.toolbelt.settings import LayerVariables
from stratified_packager.toolbelt.utils import (
    dedupe_names,
    remove_tree,
    sanitize_filename,
)
from stratified_packager.toolbelt.zipping import (
    iter_file_members,
    remove_stale_parts,
    split_archive_path,
)

from . import params
from .building import (
    LayerWrite,
    StratumBuild,
    StratumWriteResult,
    StyleDoc,
    discard_gpkg,
    stage_union,
    warm_rejection,
    write_stratum,
    write_template,
    write_vector_table,
)
from .bundling import (
    container_sharers,
    data_payload_members,
    local_source_path,
    payload_source_arcname,
    rewrite_asset_paths,
    style_asset_mapping,
)
from .dedup import apply_dedup, promote_warm_groups
from .matching import ChainContext, LayerMatchPlan, resolve_layer_methods
from .material import (
    _BuildState,
    _field_indexes,
    _Inputs,
    _is_warm_marked,
    _LayerPrep,
    _Material,
    _PayloadPrep,
    _warm_file_name,
)

# Re-exported runtime contracts (also referenced by __all__).
from .params import (
    StratifiedPackagerAlgorithmInputDict,
    StratifiedPackagerAlgorithmOutputDict,
)
from .project_builder import (
    StratumProjectPlan,
    build_stratum_project,
)
from .report import (
    STATUS_DRY_RUN,
    STATUS_EMPTY_SKIPPED,
    STATUS_SKIPPED_EXISTING,
    RunReportRow,
    write_zip_report,
)
from .reporting import account_orphans, collect_report_rows, zip_report_rows
from .staging import effective_stage, staged_layer_uri
from .strata import (
    FULL_PACKAGE_KEY,
    StrataResolution,
    StratumSpec,
    bundle_strata,
    evaluate_layer_display_name,
    resolve_strata,
)
from .virtual import route_virtual_layers
from .workers import ZipJob, ZipOutcome, run_prefetch, run_zip

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping, Sequence

    from qgis.core import QgsProcessingContext


__all__: list[str] = [
    "StratifiedPackagerAlgorithm",
    "StratifiedPackagerAlgorithmInputDict",
    "StratifiedPackagerAlgorithmOutputDict",
]

_RESERVED_EXTRA_ROOTS: tuple[str, ...] = ("data", "resources")
"""Zip-root directory names reserved for the packager's own payloads (SPEC §10)."""

_LAYER_TYPE_TOKENS: dict[Qgis.LayerType, str] = {
    Qgis.LayerType.Raster: "raster",
    Qgis.LayerType.Mesh: "mesh",
    Qgis.LayerType.PointCloud: "point-cloud",
}
"""§9.2 ``layer_type`` tokens of the payload-capable layer types."""

_SQLITE_SIDECAR_SUFFIXES: tuple[str, ...] = ("-wal", "-shm", "-journal")
"""SQLite sidecar suffixes excluded from zips (checkpointed away beforehand, SPEC §10)."""

_HOP_TABLE: Final = "hop"
"""Table name inside a staged relation-chain intermediate's GeoPackage (SPEC §7.1/§8.2); each
hop layer gets its own file, so one fixed name never collides."""


def _report_chain_memo(chain_context: ChainContext, feedback: QgsProcessingFeedback) -> None:
    """
    Report how much re-querying the §7.1 chain memo saved, once per run.

    Debug-level: the memo is an optimization whose effect never changes an output, so it
    belongs with the other diagnostics rather than in the run's info stream.

    :param chain_context: The run's relation-chain context.
    :param feedback: Execution feedback channel.
    """
    if chain_context.hits or chain_context.misses:
        feedback.pushDebugInfo(
            f"relation-chain memo: {chain_context.hits} hit(s), {chain_context.misses} miss(es)"
        )


_POOL_WIDTH: Final = 2
"""Background pool width (SPEC §8.4).

One thread keeps zip packaging ahead of the sequential builds — a bundle's zip is a single
DEFLATE stream that finishes well within the next bundle's build time, so jobs never queue
(measured on the 94-zip field project: the pool never held more than one active zip) — and
the second overlaps the §11 warm-cache prefetch with Phase A."""

_STALE_WORKDIR_AGE: Final = 24 * 3600.0
"""Minimum age in seconds before a leftover ``.stratified_build_*`` directory from an
earlier run is swept at run start (§10); younger siblings could belong to a live
concurrent run against the same output directory."""


class _BandFeedback(QgsProcessingFeedback):
    """
    Proxy feedback whose full 0-100 progress range maps into a band of a parent feedback.

    Handed to a sub-operation (a :class:`~qgis.core.QgsVectorFileWriter` write, or a
    :class:`~qgis.core.QgsProcessingMultiStepFeedback` stepping over several of them), it
    scales the sub-operation's raw ``setProgress`` sweeps into the ``[start, end]`` slice of
    the run's overall bar, so the bar always reads overall progress (SPEC §8.4). Messages
    and progress text forward to the parent unchanged; cancellation propagates from the
    parent the way :class:`~qgis.core.QgsProcessingMultiStepFeedback` propagates it (a
    direct-connected ``canceled`` signal, so no spinning event loop is needed).

    :meth:`~qgis.core.QgsFeedback.setProgress` is **not** virtual, so a C++ caller bypasses
    any Python override — the scaling therefore rides this object's own ``progressChanged``
    signal, the same mechanism :class:`~qgis.core.QgsProcessingMultiStepFeedback` uses.
    """

    def __init__(self, parent: QgsProcessingFeedback, start: float, end: float) -> None:
        """
        Wire the proxy onto *parent*.

        :param parent: The feedback receiving the scaled progress and forwarded messages.
        :param start: The parent progress this proxy's ``0`` maps to.
        :param end: The parent progress this proxy's ``100`` maps to.
        """
        super().__init__(logFeedback=False)  # everything forwards to the parent, never log
        self._parent = parent
        """The wrapped feedback (also keeps the Python wrapper alive for C++ callees)."""
        self._start = start
        """Parent progress at this proxy's ``0``."""
        self._span = end - start
        """Parent progress distance covered by this proxy's ``0`` → ``100``."""
        parent.canceled.connect(self.cancel, Qt.ConnectionType.DirectConnection)  # type: ignore[call-arg]  # ty: ignore[too-many-positional-arguments]  # PyQt6-stubs omit connect()'s type argument; the runtime accepts it
        if parent.isCanceled():  # the signal fired before the connection existed
            self.cancel()
        self.progressChanged.connect(self._scale_to_parent)

    def _scale_to_parent(self, progress: float) -> None:
        """
        Relay an own-progress change into the parent band.

        :param progress: This proxy's progress in ``[0, 100]``.
        """
        self._parent.setProgress(self._start + self._span * progress / 100)

    @override
    def setProgressText(self, text: str | None = None) -> None:
        """
        Forward the progress text to the parent.

        :param text: The progress text.
        """
        self._parent.setProgressText(text or "")

    @override
    def pushInfo(self, info: str | None = None) -> None:
        """
        Forward an info message to the parent.

        :param info: The message.
        """
        self._parent.pushInfo(info or "")

    @override
    def pushWarning(self, warning: str | None = None) -> None:
        """
        Forward a warning message to the parent.

        :param warning: The message.
        """
        self._parent.pushWarning(warning or "")

    @override
    def pushDebugInfo(self, info: str | None = None) -> None:
        """
        Forward a debug message to the parent.

        :param info: The message.
        """
        self._parent.pushDebugInfo(info or "")

    @override
    def pushCommandInfo(self, info: str | None = None) -> None:
        """
        Forward a command message to the parent.

        :param info: The message.
        """
        self._parent.pushCommandInfo(info or "")

    @override
    def pushConsoleInfo(self, info: str | None = None) -> None:
        """
        Forward a console-output message to the parent.

        :param info: The message.
        """
        self._parent.pushConsoleInfo(info or "")

    @override
    def pushFormattedMessage(self, html: str | None = None, text: str | None = None) -> None:
        """
        Forward a formatted message to the parent.

        :param html: The HTML form of the message.
        :param text: The plain-text form of the message.
        """
        self._parent.pushFormattedMessage(html or "", text or "")

    @override
    def reportError(self, error: str | None = None, fatalError: bool = False) -> None:
        """
        Forward an error to the parent.

        :param error: The error message.
        :param fatalError: Whether the error prevents the algorithm from completing.
        """
        self._parent.reportError(error or "", fatalError)


class StratifiedPackagerAlgorithm(QgsProcessingAlgorithm):
    """``stratified_packager:package`` — one zipped GeoPackage per stratum (SPEC §1)."""

    @override
    def initAlgorithm(self, configuration: dict[str | None, Any] | None = None) -> None:
        """
        Declare the SPEC §3 inputs and outputs, defaults pre-resolved (SPEC §5).

        :param configuration: Unused framework configuration map.
        """
        params_settings = StratifiedPackagerSettings()
        params.declare_parameters(self, project=QgsProject.instance(), settings=params_settings)
        params.declare_outputs(self)

    @override
    def flags(self) -> Qgis.ProcessingAlgorithmFlag:
        """Return the algorithm flags; a project is required."""
        return super().flags() | Qgis.ProcessingAlgorithmFlag.RequiresProject

    @override
    def checkParameterValues(
        self, parameters: dict[str | None, Any], context: QgsProcessingContext
    ) -> tuple[bool, str]:
        """
        Run the static (no data access) §15 checks.

        :param parameters: Raw parameter values.
        :param context: The processing context.
        :return: ``(ok, message)``.
        """
        for name in (
            params.STRATUM_NAME_EXPRESSION,
            params.GPKG_PATH_EXPRESSION,
            params.ZIP_PATH_EXPRESSION,
        ):
            text = self.parameterAsString(parameters, name, context).strip()
            if text:
                expression = QgsExpression(text)
                if expression.hasParserError():
                    return False, self.tr("{} does not parse: {}").format(
                        name, expression.parserErrorString()
                    )
        return super().checkParameterValues(parameters, context)

    @override
    def processAlgorithm(
        self,
        parameters: dict[str | None, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback | None,
    ) -> dict[str, Any]:
        """
        Run the algorithm: validation → Phase A → Phase B/C → report + outputs.

        :param parameters: Input parameter values, keyed by parameter name.
        :param context: Context in which the algorithm runs.
        :param feedback: The sole channel for user-facing messages, progress reporting,
            and cancellation during execution.
        :return: Output value map, keyed by output name (SPEC §3 declared outputs).
        :raise qgis.core.QgsProcessingException: On a fatal error that must abort the
            run, and at the end of a best-effort run in which any stratum failed
            (listing the failed strata).
        """
        if feedback is None:
            feedback = QgsProcessingFeedback()
        project = context.project()
        if project is None:
            raise QgsProcessingException(
                self.tr("This algorithm requires an open project (use --project_path).")
            )
        inputs = self._resolve_inputs(
            parameters, context, project, StratifiedPackagerSettings(), feedback
        )

        resolution = self._resolve_strata_validated(inputs, project, feedback)
        feedback.setProgress(5)
        if feedback.isCanceled():
            raise QgsProcessingException(self.tr("Operation was canceled."))

        self._validate_warm_inputs(inputs)
        resolution = self._with_full_package(inputs, project, resolution)

        report_rows: list[RunReportRow] = []
        bundles = self._apply_overwrite_mode(inputs, resolution, report_rows, feedback)
        active = {member.name for members in bundles.values() for member in members}
        strata = [stratum for stratum in resolution.strata if stratum.name in active]
        features_by_name = dict(
            zip(
                (spec.name for spec in resolution.strata if spec.feature_id >= 0),
                resolution.features,
                strict=True,
            )
        )

        self._scan_extra_dir(inputs, bundles, feedback)

        workdir = self._make_workdir(inputs, feedback)
        material = _Material(project=project, inputs=inputs, bundles=dict(bundles))
        try:
            cancel = threading.Event()
            with ThreadPoolExecutor(max_workers=_POOL_WIDTH) as pool:
                try:
                    self._layout_zip_roots(material, workdir)
                    self._submit_warm_prefetch(material, strata, pool, cancel)
                    self._phase_a(material, strata, features_by_name, workdir, feedback)
                    feedback.setProgress(25)

                    if inputs.dry_run:
                        outputs = self._finish_dry_run(
                            material, strata, report_rows, parameters, context, feedback
                        )
                    else:
                        outputs = self._phases_b_c(
                            material,
                            strata,
                            # §11: the update pass refreshes EVERY stratum's cache, even
                            # ones whose deliverable zip skip-existing filtered out above.
                            warm_strata=resolution.strata,
                            features_by_name=features_by_name,
                            workdir=workdir,
                            report_rows=report_rows,
                            parameters=parameters,
                            context=context,
                            pool=pool,
                            cancel=cancel,
                            feedback=feedback,
                        )
                except BaseException:
                    # Flush the pool: queued prefetch/zip jobs no-op once canceled, so the
                    # executor's shutdown-wait at `with` exit cannot stall a failed run.
                    cancel.set()
                    raise
        finally:
            self._discard_workdir(material, workdir, feedback)
        return cast("dict[str, Any]", outputs)

    # ------------------------------------------------------------------
    # Input resolution (§5 runtime fallback)
    # ------------------------------------------------------------------

    def _resolve_inputs(
        self,
        parameters: dict[str | None, Any],
        context: QgsProcessingContext,
        project: QgsProject,
        settings: StratifiedPackagerSettings,
        feedback: QgsProcessingFeedback,
    ) -> _Inputs:
        """
        Resolve every input through explicit value > variable > setting > builtin.

        :param parameters: Raw parameter values.
        :param context: The processing context.
        :param project: The run's project.
        :param settings: The plugin settings.
        :param feedback: Execution feedback channel.
        :return: The typed inputs.
        :raise QgsProcessingException: On unusable stored defaults or missing
            requirements (§3 footnotes).
        """
        reader = params.InputReader(self, parameters, context, project, settings)
        vectors, payloads, embedded = self._collect_layers(parameters, context, project, feedback)
        strat_layer = self._resolve_strat_layer(parameters, context, project, reader)

        output_dir_text = reader.string(params.OUTPUT_DIRECTORY)
        if not output_dir_text:
            raise QgsProcessingException(self.tr("OUTPUT_DIRECTORY is required."))
        output_dir = Path(output_dir_text)

        extra_text = reader.string(params.EXTRA_DIR).strip()
        extra_dir = (
            (Path(extra_text) if Path(extra_text).is_absolute() else output_dir / extra_text)
            if extra_text
            else None
        )
        warm_text = reader.string(params.WARM_START_DIR).strip()
        warm_dir = (
            (Path(warm_text) if Path(warm_text).is_absolute() else output_dir / warm_text)
            if warm_text
            else None
        )
        warm_mode = params.WarmStartMode(reader.string(params.WARM_START_MODE) or "off")

        return _Inputs(
            layers=vectors,
            payload_layers=payloads,
            embedded_layers=embedded,
            strat_layer=strat_layer,
            name_expression=reader.string(params.STRATUM_NAME_EXPRESSION),
            gpkg_expression=reader.string(params.GPKG_PATH_EXPRESSION),
            zip_expression=reader.string(params.ZIP_PATH_EXPRESSION),
            output_dir=output_dir,
            compression_level=reader.integer(params.COMPRESSION_LEVEL),
            overwrite_mode=params.OverwriteMode(
                reader.string(params.OVERWRITE_MODE) or "overwrite"
            ),
            project_inclusion=params.ProjectInclusion(
                reader.string(params.PROJECT_INCLUSION) or "none"
            ),
            use_temp_folder=reader.boolean(params.USE_TEMP_FOLDER),
            strata_from_selection=reader.boolean(params.STRATA_FROM_SELECTION),
            include_styles=reader.boolean(params.INCLUDE_STYLES),
            style_categories=params.style_categories_flags(
                reader.enum_strings(params.STYLE_CATEGORIES)
            ),
            include_metadata=reader.boolean(params.INCLUDE_METADATA),
            keep_empty_layers=reader.boolean(params.KEEP_EMPTY_LAYERS),
            deduplicate=reader.boolean(params.DEDUPLICATE_SHARED_SOURCES),
            stage_providers=frozenset(reader.enum_strings(params.STAGE_PROVIDERS)),
            export_full=reader.boolean(params.EXPORT_FULL_PACKAGE),
            generate_report=reader.boolean(params.GENERATE_REPORT),
            write_checksums=reader.boolean(params.WRITE_CHECKSUMS),
            extra_dir=extra_dir,
            warm_dir=warm_dir,
            use_warm=warm_mode is params.WarmStartMode.USE,
            update_warm=warm_mode is params.WarmStartMode.UPDATE,
            full_package_path=reader.string(params.FULL_PACKAGE_PATH).strip(),
            dry_run=reader.boolean(params.DRY_RUN),
        )

    def _collect_layers(
        self,
        parameters: dict[str | None, Any],
        context: QgsProcessingContext,
        project: QgsProject,
        feedback: QgsProcessingFeedback,
    ) -> tuple[list[QgsVectorLayer], list[QgsMapLayer], list[QgsMapLayer]]:
        """
        Resolve ``LAYERS`` and classify the packaged layers by handling (§4 fixed-by-type).

        Plugin layers are excluded with a warning — they are reported here, not returned.

        :param parameters: Raw parameter values.
        :param context: The processing context.
        :param project: The run's project.
        :param feedback: Execution feedback channel.
        :return: ``(vector, payload (local raster/mesh/point-cloud), embedded-only
            (remote/annotation/live virtual))`` layers.
        :raise QgsProcessingException: If a layer's ``exclude`` variable cannot be coerced
            to bool while resolving an empty ``LAYERS`` (§5 strict regime).
        """
        raw_layers = (
            self.parameterAsLayerList(parameters, params.LAYERS, context)
            if not params.is_omitted(parameters, params.LAYERS)
            else None
        )
        if not raw_layers:
            try:
                eligible = params.eligible_layer_ids(project, strict=True)
            except ValueError as err:
                raise QgsProcessingException(
                    self.tr("Cannot determine eligible layers: {}").format(err)
                ) from err
            raw_layers = [
                layer for layer_id in eligible if (layer := project.mapLayer(layer_id)) is not None
            ]
        vectors: list[QgsVectorLayer] = []
        payloads: list[QgsMapLayer] = []
        embedded: list[QgsMapLayer] = []
        excluded: list[QgsMapLayer] = []
        virtuals: list[QgsVectorLayer] = []
        for layer in raw_layers:
            if isinstance(layer, QgsVectorLayer):
                # Virtual layers are resolved in a second pass: their live/materialize
                # decision depends on which other layers are packaged (SPEC §4/§13).
                (virtuals if layer.providerType() == "virtual" else vectors).append(layer)
            elif layer.type() == Qgis.LayerType.Plugin:
                excluded.append(layer)
            elif layer.type() in _LAYER_TYPE_TOKENS and local_source_path(layer) is not None:
                payloads.append(layer)
            else:
                embedded.append(layer)
        route_virtual_layers(virtuals, vectors, payloads, embedded, project, feedback)
        if excluded:
            feedback.pushWarning(
                self.tr("Plugin layers cannot be packaged; excluded: {}").format(
                    ", ".join(layer.name() for layer in excluded)
                )
            )
        if embedded:
            feedback.pushInfo(
                self.tr(
                    "Layers riding only in the embedded project (remote/annotation/live"
                    " virtual): {}"
                ).format(", ".join(layer.name() for layer in embedded))
            )
        return vectors, payloads, embedded

    def _resolve_strat_layer(
        self,
        parameters: dict[str | None, Any],
        context: QgsProcessingContext,
        project: QgsProject,
        reader: params.InputReader,
    ) -> QgsVectorLayer | None:
        """
        Resolve ``STRATIFICATION_LAYER`` (explicit, else the project variable's layer id).

        :param parameters: Raw parameter values.
        :param context: The processing context.
        :param project: The run's project.
        :param reader: The input reader.
        :return: The stratification layer, or :data:`None`.
        """
        strat_layer = self.parameterAsVectorLayer(parameters, params.STRATIFICATION_LAYER, context)
        if strat_layer is None and params.is_omitted(parameters, params.STRATIFICATION_LAYER):
            variable_value = str(reader.fallback(params.STRATIFICATION_LAYER) or "")
            if variable_value:
                candidate = project.mapLayer(variable_value)
                if isinstance(candidate, QgsVectorLayer):
                    strat_layer = candidate
        return strat_layer

    # ------------------------------------------------------------------
    # Run-start validation (§15)
    # ------------------------------------------------------------------

    def _resolve_strata_validated(
        self, inputs: _Inputs, project: QgsProject, feedback: QgsProcessingFeedback
    ) -> StrataResolution:
        """
        Validate the stratification layer and resolve the strata (§6, §15).

        :param inputs: The resolved inputs.
        :param project: The run's project.
        :param feedback: Execution feedback channel.
        :return: The strata resolution.
        :raise QgsProcessingException: Per the §6 strict rules (including the empty-selection
            fail-fast, raised by :func:`~.strata.resolve_strata`) and §3 footnote ¹.
        """
        if inputs.strat_layer is None:
            if inputs.export_full:
                return StrataResolution(strata=(), bundles={}, features=())
            raise QgsProcessingException(
                self.tr(
                    "STRATIFICATION_LAYER is required unless EXPORT_FULL_PACKAGE is"
                    " enabled (then only the full package is built)."
                )
            )
        resolution = resolve_strata(
            inputs.strat_layer,
            project=project,
            name_expression=inputs.name_expression,
            gpkg_path_expression=inputs.gpkg_expression,
            zip_path_expression=inputs.zip_expression,
            strata_from_selection=inputs.strata_from_selection,
        )
        if not resolution.strata:
            feedback.pushWarning(self.tr("The stratification layer yielded no strata."))
            if not inputs.export_full:
                raise QgsProcessingException(
                    self.tr("No strata to package (the stratification layer is empty).")
                )
        feedback.pushInfo(
            self.tr("Resolved %n strata ", n=len(resolution.strata))
            + self.tr("into %n zip(s).", n=len(resolution.bundles))
        )
        return resolution

    def _validate_warm_inputs(self, inputs: _Inputs) -> None:
        """
        Enforce the §11 warm-start requirements at run start.

        :param inputs: The resolved inputs.
        :raise QgsProcessingException: On a missing directory, an uncoercible
            ``warm_marked`` value, or an empty warm-marked layer set.
        """
        if not (inputs.use_warm or inputs.update_warm):
            return
        if inputs.warm_dir is None:
            raise QgsProcessingException(
                self.tr("WARM_START_DIR is required when warm start is enabled.")
            )
        if not any(_is_warm_marked(layer) for layer in inputs.layers):
            raise QgsProcessingException(
                self.tr(
                    "Warm start is enabled but no packaged layer is warm_marked —"
                    " a warm run with nothing warm is always a misconfiguration."
                )
            )

    def _collect_layer_name_expressions(self, layers: Sequence[QgsMapLayer]) -> dict[str, str]:
        """
        Snapshot and parse-validate the §4 ``layer_name`` expressions at run start.

        Consulted only when an embedded project is built. A parse error is the fail-fast;
        the per-stratum evaluation in :meth:`_project_plan` surfaces eval/NULL errors later.

        :param layers: Every layer that may appear in an embedded project.
        :return: Layer id -> non-empty expression text.
        :raise QgsProcessingException: If a layer's expression fails to parse.
        """
        expressions: dict[str, str] = {}
        for layer in layers:
            text = str(LayerVariables(layer).get(params.LAYER_VAR_LAYER_NAME) or "").strip()
            if not text:
                continue
            expression = QgsExpression(text)
            if expression.hasParserError():
                raise QgsProcessingException(
                    self.tr("Custom layer name expression for layer {} does not parse: {}").format(
                        layer.name(), expression.parserErrorString()
                    )
                )
            expressions[layer.id()] = text
        return expressions

    def _with_full_package(
        self, inputs: _Inputs, project: QgsProject, resolution: StrataResolution
    ) -> StrataResolution:
        """
        Append the ``<full>`` pseudo-stratum when ``EXPORT_FULL_PACKAGE`` is on (§3).

        :param inputs: The resolved inputs.
        :param project: The run's project (supplies the default basename).
        :param resolution: The strata resolution.
        :return: The resolution, possibly extended by the full package.
        :raise QgsProcessingException: On an invalid full-package path, or on any
            §6.5/§6.6 collision the re-bundling detects (case-variant zip paths,
            gpkg paths colliding inside a bundle the full package joins).
        """
        if not inputs.export_full:
            return resolution
        base = inputs.full_package_path or (
            sanitize_filename(project.baseName() or "project") + "_full"
        )
        try:
            components = split_archive_path(base)
        except ValueError as err:
            raise QgsProcessingException(
                self.tr("Invalid FULL_PACKAGE_PATH: {}").format(err)
            ) from err
        full_spec = StratumSpec(
            feature_id=-1,
            raw_name=FULL_PACKAGE_KEY,
            name=FULL_PACKAGE_KEY,
            gpkg_rel="/".join(components),
            zip_rel=components[-1],
        )
        # Re-bundle instead of hand-merging: bundling with an identical zip path is
        # legitimate, but the merged bundle must pass the same §6.6 gpkg-uniqueness
        # check as any other (two builds must never share one gpkg build path).
        strata = (*resolution.strata, full_spec)
        return StrataResolution(
            strata=strata,
            bundles=bundle_strata(strata),
            features=resolution.features,
        )

    def _apply_overwrite_mode(
        self,
        inputs: _Inputs,
        resolution: StrataResolution,
        report_rows: list[RunReportRow],
        feedback: QgsProcessingFeedback,
    ) -> dict[str, tuple[StratumSpec, ...]]:
        """
        Apply ``OVERWRITE_MODE`` to the bundle map (§10, §15).

        :param inputs: The resolved inputs.
        :param resolution: The strata resolution.
        :param report_rows: Mutable run-report rows (skip rows are appended).
        :param feedback: Execution feedback channel.
        :return: The surviving bundles.
        :raise QgsProcessingException: In ``error`` mode when any target exists.
        """
        existing = {
            zip_rel: inputs.output_dir / f"{zip_rel}.zip"
            for zip_rel in resolution.bundles
            if (inputs.output_dir / f"{zip_rel}.zip").exists()
        }
        if not existing or inputs.overwrite_mode is params.OverwriteMode.OVERWRITE:
            return dict(resolution.bundles)
        if inputs.overwrite_mode is params.OverwriteMode.ERROR:
            raise QgsProcessingException(
                self.tr("Existing outputs (OVERWRITE_MODE = error): {}").format(
                    ", ".join(str(path) for path in existing.values())
                )
            )
        surviving = {
            zip_rel: members
            for zip_rel, members in resolution.bundles.items()
            if zip_rel not in existing
        }
        for zip_rel in existing:
            # One row per (stratum, packaged layer) pair, like every other §9.1 path.
            report_rows.extend(
                RunReportRow(
                    stratum=member.name,
                    layer=layer.name(),
                    status=STATUS_SKIPPED_EXISTING,
                    detail=f"{zip_rel}.zip exists",
                )
                for member in resolution.bundles[zip_rel]
                for layer in (*inputs.layers, *inputs.payload_layers)
            )
            feedback.pushInfo(self.tr("Skipping existing output {}.zip").format(zip_rel))
        return surviving

    def _scan_extra_dir(
        self,
        inputs: _Inputs,
        bundles: Mapping[str, tuple[StratumSpec, ...]],
        feedback: QgsProcessingFeedback,
    ) -> None:
        """
        Reject EXTRA_DIR entries colliding with reserved zip content (§10, §15).

        :param inputs: The resolved inputs.
        :param bundles: The surviving bundles.
        :param feedback: Execution feedback channel.
        :raise QgsProcessingException: Listing every conflicting entry.
        """
        if inputs.extra_dir is None:
            return
        if not inputs.extra_dir.is_dir():
            raise QgsProcessingException(
                self.tr("EXTRA_DIR does not exist or is not a directory: {}").format(
                    inputs.extra_dir
                )
            )
        reserved: set[str] = {root.casefold() for root in _RESERVED_EXTRA_ROOTS}
        if inputs.generate_report:
            reserved.add("report.csv")
        for members in bundles.values():
            for member in members:
                first = member.gpkg_rel.partition("/")[0].casefold()
                reserved.add(f"{first}.gpkg" if "/" not in member.gpkg_rel else first)
                reserved.add(f"{first}.qgz" if "/" not in member.gpkg_rel else first)
        conflicts = sorted(
            entry.name for entry in inputs.extra_dir.iterdir() if entry.name.casefold() in reserved
        )
        if conflicts:
            raise QgsProcessingException(
                self.tr("EXTRA_DIR entries collide with reserved zip content: {}").format(
                    ", ".join(conflicts)
                )
            )
        feedback.pushDebugInfo(f"extra dir verified: {inputs.extra_dir}")

    def _make_workdir(self, inputs: _Inputs, feedback: QgsProcessingFeedback) -> Path:
        """
        Create the run-scoped build directory, sweeping stale leftovers first (§10).

        :param inputs: The resolved inputs.
        :param feedback: Execution feedback channel.
        :return: The build directory (under the Processing temp folder, or under the
            output directory when ``USE_TEMP_FOLDER`` is off).
        """
        if inputs.use_temp_folder:
            # No sweep here: the Processing temp folder is session-scoped (QGIS removes
            # it at exit), so residue from other sessions is unreachable from this run.
            return Path(
                tempfile.mkdtemp(prefix="stratified_", dir=QgsProcessingUtils.tempFolder())
            )
        inputs.output_dir.mkdir(parents=True, exist_ok=True)
        self._sweep_stale_workdirs(inputs.output_dir, feedback)
        return Path(tempfile.mkdtemp(prefix=".stratified_build_", dir=inputs.output_dir))

    def _sweep_stale_workdirs(self, output_dir: Path, feedback: QgsProcessingFeedback) -> None:
        """
        Best-effort removal of day-old build directories a crashed run left behind (§10).

        Only siblings past :data:`_STALE_WORKDIR_AGE` are touched — a younger
        ``.stratified_build_*`` directory could belong to a run still executing against
        the same output directory.

        :param output_dir: The run's output directory.
        :param feedback: Execution feedback channel.
        """
        now = time.time()
        for stale in output_dir.glob(".stratified_build_*"):
            try:
                is_stale = stale.is_dir() and now - stale.stat().st_mtime > _STALE_WORKDIR_AGE
            except OSError:
                continue
            if is_stale and remove_tree(stale, attempts=1):
                feedback.pushDebugInfo(self.tr("Removed stale build directory: {}").format(stale))

    def _discard_workdir(
        self, material: _Material, workdir: Path, feedback: QgsProcessingFeedback
    ) -> None:
        """
        Release the run's workdir-backed layer handles, then remove the build directory (§10).

        The preps' read layers sit over GeoPackages inside the workdir (staging copies,
        the whole-export template); while those layers are alive GDAL holds the files
        open and Windows refuses to delete them. Dropping the references (plus a GC pass
        for cycles) releases the handles so the removal can succeed. Residue surviving
        the retries — e.g. a handle a failed run's traceback still pins — is reported
        and left behind (best-effort, §17).

        :param material: The run material; its layer-holding fields are cleared in place.
        :param workdir: The run's build directory.
        :param feedback: Execution feedback channel.
        """
        material.preps.clear()
        material.payloads.clear()
        material.warm_prefetch.clear()
        gc.collect()
        if remove_tree(workdir):
            return
        message = self.tr("Could not fully remove the build directory: {}").format(workdir)
        if material.inputs.use_temp_folder:
            # Under the Processing temp folder, which QGIS removes at exit anyway.
            feedback.pushDebugInfo(message)
        else:
            feedback.pushWarning(message)

    # ------------------------------------------------------------------
    # Phase A (§8.1/§8.2 + §7 conditions + §14 bundling)
    # ------------------------------------------------------------------

    # pylint: disable-next=too-many-locals  # the §8.1 step sequence reads best flat
    def _phase_a(
        self,
        material: _Material,
        strata: Sequence[StratumSpec],
        features_by_name: Mapping[str, QgsFeature],
        workdir: Path,
        feedback: QgsProcessingFeedback,
    ) -> None:
        """
        Analysis & staging: methods, staging copies, conditions, payloads, build roots.

        :param material: The run material being filled.
        :param strata: The surviving strata.
        :param features_by_name: Stratum features keyed by sanitized name.
        :param workdir: The run's build directory.
        :param feedback: Execution feedback channel.
        :raise QgsProcessingException: Per §4/§7/§8.2 validation rules.
        """
        inputs = material.inputs
        project = material.project
        ordered = self._tree_ordered(project, inputs.layers)
        ordered_payloads = self._tree_ordered_any(project, inputs.payload_layers)
        plans = self._resolve_methods(inputs, project, ordered, feedback)

        tables = dedupe_names(
            [sql.safe_table_name(slugify(layer.name())) for layer in [*ordered, *ordered_payloads]]
        )
        vector_tables = tables[: len(ordered)]
        payload_tables = tables[len(ordered) :]
        for layer, table in zip([*ordered, *ordered_payloads], tables, strict=True):
            if table != sql.safe_table_name(slugify(layer.name())):
                feedback.pushWarning(
                    self.tr("Duplicate layer name; table renamed to {} for layer {}").format(
                        table, layer.name()
                    )
                )

        real_features = [
            features_by_name[stratum.name] for stratum in strata if stratum.feature_id >= 0
        ]
        for index, (layer, table) in enumerate(zip(ordered, vector_tables, strict=True), start=1):
            if feedback.isCanceled():
                raise QgsProcessingException(self.tr("Operation was canceled."))
            feedback.setProgressText(
                self.tr("Preparing layer {}/{}: {}").format(index, len(ordered), layer.name())
            )
            material.preps.append(
                self._prepare_vector_layer(layer, table, plans[layer.id()], inputs, feedback)
            )

        material.warm_marked_ids = {layer.id() for layer in ordered if _is_warm_marked(layer)}
        apply_dedup(material, feedback)
        promote_warm_groups(material, feedback)
        if not inputs.dry_run:
            # A dry run stops at analysis (§8.2): staging copies and the template are
            # build-side I/O that no dry-run output reads.
            self._stage_chain_hops(material, workdir / "staging", feedback)
            self._stage_preps(
                material,
                real_features,
                workdir / "staging",
                feedback,
                skip_warm_staged=self._warm_covers_all_builds(material, strata, feedback),
            )
            self._build_template(material, workdir, feedback)

        for layer, table in zip(ordered_payloads, payload_tables, strict=True):
            members = data_payload_members(layer, table, feedback)
            sharers = container_sharers(layer, project)
            if sharers:
                feedback.pushWarning(
                    self.tr(
                        "Layer {}: its copied source file also backs other layers"
                        " ({}) — the copy drags the whole container."
                    ).format(layer.name(), ", ".join(sharers))
                )
            material.payloads.append(
                _PayloadPrep(
                    layer=layer,
                    table=table,
                    members=tuple(members),
                    layer_type=_LAYER_TYPE_TOKENS.get(layer.type(), "raster"),
                    project_source=payload_source_arcname(layer, table),
                )
            )

        included: list[QgsMapLayer] = [*ordered, *ordered_payloads, *inputs.embedded_layers]
        if inputs.project_inclusion is not params.ProjectInclusion.NONE:
            material.layer_name_expressions = self._collect_layer_name_expressions(included)
        if inputs.include_styles:
            home = project.absolutePath()
            material.assets = style_asset_mapping(included, Path(home) if home else None, feedback)

        if not inputs.dry_run:  # placement is build-side I/O too (hardlinks/copies)
            self._place_shared_payloads(material)

    def _resolve_methods(
        self,
        inputs: _Inputs,
        project: QgsProject,
        ordered: Sequence[QgsVectorLayer],
        feedback: QgsProcessingFeedback,
    ) -> dict[str, LayerMatchPlan]:
        """
        Resolve every packaged layer's matching method (§4); a full-only run is all whole-export.

        :param inputs: The resolved inputs.
        :param project: The run's project.
        :param ordered: The packaged vector layers in tree order.
        :param feedback: Execution feedback channel.
        :return: One plan per layer id.
        :raise QgsProcessingException: Per the §4 rules, or if the relation manager is absent.
        """
        if inputs.strat_layer is None:
            # Full-only run (§3 footnote ¹): nothing is partitioned.
            return {
                layer.id(): LayerMatchPlan(
                    layer_id=layer.id(), method=params.MatchingMethod.WHOLE_EXPORT
                )
                for layer in ordered
            }
        manager = project.relationManager()
        if manager is None:
            raise QgsProcessingException(self.tr("The project has no relation manager."))
        graph = build_relation_graph(manager)
        return resolve_layer_methods(ordered, inputs.strat_layer, graph, feedback)

    def _build_template(
        self, material: _Material, workdir: Path, feedback: QgsProcessingFeedback
    ) -> None:
        """
        Write the §8.1.5 template gpkg once (non-warm-marked whole-export primaries).

        Each covered stratum is then seeded by a plain copy of the template; only its
        partitioned layers (and the per-stratum styles) are written afterwards. The
        template also becomes the covered layers' read source (§8.2): a warm-seeded
        stratum (§11) cannot take the template seed, so it writes these layers per
        stratum — from the local template copy, not the original source again.

        :param material: The run material.
        :param workdir: The run's build directory.
        :param feedback: Execution feedback channel.
        :raise QgsProcessingException: If the template writer fails or a written
            template table cannot be opened back as the read source.
        """
        covered = [
            prep
            for prep in material.preps
            if prep.plan.method is params.MatchingMethod.WHOLE_EXPORT
            and prep.layer.id() not in material.warm_marked_ids
            and prep.group_primary_id in (None, prep.layer.id())
        ]
        if not covered:
            return
        template = workdir / "template.gpkg"
        write_template(
            template,
            [self._layer_write(prep, material) for prep in covered],
            # The template build occupies the ≈ 20-25 % slice of Phase A (SPEC §8.4).
            feedback=_BandFeedback(feedback, 20, 25),
        )
        if feedback.isCanceled():  # write_template returns early then; the template is partial
            return
        material.template_path = template
        for prep in covered:
            prep.read_layer = self._open_local(template, prep.table, prep.layer.name())
            prep.kept_field_indexes = _field_indexes(prep.read_layer, prep.kept_fields)

    def _layer_write(
        self, prep: _LayerPrep, material: _Material, *, to_root: str = ""
    ) -> LayerWrite:
        """
        Build one (primary) prep's :class:`~.building.LayerWrite`.

        A dedup primary carries every group member's plan — membership is their union — and
        every member's style (the primary's loads by default). *to_root* sets the per-stratum
        ``resources/`` prefix used to rewrite the QML asset paths.

        :param prep: The (primary) layer prep.
        :param material: The run material.
        :param to_root: The stratum's relative prefix back to its zip root.
        :return: The layer write.
        """
        group = [
            other for other in material.preps if other.group_primary_id == prep.layer.id()
        ] or [prep]
        return LayerWrite(
            layer_id=prep.layer.id(),
            table=prep.table,
            read_layer=prep.read_layer,
            members=tuple(member.plan for member in group),
            kept_field_indexes=prep.kept_field_indexes,
            whole_export=prep.plan.method is params.MatchingMethod.WHOLE_EXPORT,
            warm_marked=prep.layer.id() in material.warm_marked_ids,
            keep_if_empty=material.inputs.keep_empty_layers,
            styles=tuple(
                StyleDoc(
                    name=member.layer.name(),
                    qml=rewrite_asset_paths(member.qml, material.assets, to_root),
                    sld=member.sld,
                    default=member is prep,
                )
                for member in group
                if member.qml
            ),
            metadata_xml=prep.metadata_xml,
        )

    def _prepare_vector_layer(
        self,
        layer: QgsVectorLayer,
        table: str,
        plan: LayerMatchPlan,
        inputs: _Inputs,
        feedback: QgsProcessingFeedback,
    ) -> _LayerPrep:
        """
        Build one vector layer's Phase-A prep over a plain clone (§8.1).

        The read source starts as a clone of *layer* (its subset string rides along; the
        user's layer is never read for data, so its selection and subset stay untouched).
        Staging happens later, per dedup *group*, in :meth:`_stage_preps` — after
        :func:`~.dedup.apply_dedup` has merged shared-source layers — so a group shares one
        staging copy instead of building one per member. Conditions are not materialized
        here; the per-stratum write computes them lazily against the read source.

        :param layer: The packaged vector layer.
        :param table: Its target table name.
        :param plan: Its matching plan.
        :param inputs: The resolved inputs.
        :param feedback: Execution feedback channel.
        :return: The prep.
        :raise QgsProcessingException: On a clone failure.
        """
        excluded = self._excluded_fields(layer)
        qml, sld = self._style_documents(layer, inputs, feedback)
        read_layer = self._clone(layer)
        kept = tuple(
            name
            for name in (field.name() for field in read_layer.fields().toList())
            if name not in excluded
        )
        return _LayerPrep(
            layer=layer,
            table=table,
            plan=plan,
            read_layer=read_layer,
            kept_fields=kept,
            kept_field_indexes=_field_indexes(read_layer, kept),
            excluded_fields=excluded,
            subset_sql=layer.subsetString(),
            qml=qml,
            sld=sld,
            metadata_xml=self._metadata_payload(layer, inputs),
        )

    def _warm_covers_all_builds(
        self,
        material: _Material,
        strata: Sequence[StratumSpec],
        feedback: QgsProcessingFeedback,
    ) -> bool:
        """
        Pre-scan the §11 warm caches to decide whether warm-covered staging is skippable.

        On a ``WARM_START_MODE=use`` run a fully-warm dedup group's staged copy is only ever read
        by a per-stratum cold fallback, so staging it is pure waste **unless** some stratum
        will actually fall back. Run the seed-time completeness check
        (:func:`~.building.warm_rejection`) against every build's cache file up front:
        all usable → staging of fully-warm groups is skipped (§8.2);
        any rejection → staging proceeds and the run is warned once.

        :param material: The run material (dedup applied, warm ids resolved).
        :param strata: The surviving strata (``<full>`` included when it is exported).
        :param feedback: Execution feedback channel.
        :return: Whether every build's warm cache passes the §11 completeness check.
        """
        inputs = material.inputs
        if not inputs.use_warm or inputs.warm_dir is None:
            return False
        expected = tuple(
            prep.table
            for prep in material.preps
            if prep.group_primary_id in (None, prep.layer.id())
            and prep.layer.id() in material.warm_marked_ids
        )
        rejections = [
            (spec.name, reason)
            for spec in strata
            if (
                reason := warm_rejection(
                    inputs.warm_dir / f"{_warm_file_name(spec.name)}.gpkg", expected
                )
            )
            is not None
        ]
        if not rejections:
            return True
        feedback.pushWarning(
            self.tr(
                "Warm cache unusable for %n stratum(s) ({}) — staging proceeds so cold"
                " fallbacks read local copies.",
                n=len(rejections),
            ).format("; ".join(f"{name}: {reason}" for name, reason in rejections[:3]))
        )
        return False

    def _stage_layer(
        self, layer: QgsVectorLayer, plan: LayerMatchPlan, stage_providers: Collection[str]
    ) -> bool:
        """
        Resolve a partitioned layer's staging decision (§8.2), wrapping the strict failure.

        :param layer: The packaged layer.
        :param plan: Its matching plan.
        :param stage_providers: The resolved ``STAGE_PROVIDERS`` provider keys.
        :return: Whether to stage the layer into a per-layer GeoPackage.
        :raise QgsProcessingException: If the stage variable is neither boolean nor ``auto``.
        """
        try:
            return effective_stage(layer, method=plan.method, stage_providers=stage_providers)
        except ValueError as err:
            raise QgsProcessingException(
                self.tr("layer {}: stage variable {}").format(layer.name(), err)
            ) from err

    def _stage_preps(
        self,
        material: _Material,
        real_features: Sequence[QgsFeature],
        staging_dir: Path,
        feedback: QgsProcessingFeedback,
        *,
        skip_warm_staged: bool,
    ) -> None:
        """
        Stage the read sources that resolve ``stage=true`` — once per dedup group (§8.2).

        Runs after :func:`~.dedup.apply_dedup`, so a group of shared-source layers stages a single
        copy through its primary (whose read layer already carries the merged field union and
        cleared subset); ungrouped layers stage individually. Whole-export preps are skipped —
        the §8.1.5 template is their staged form. With *skip_warm_staged*, a group whose every
        member is warm-marked is not staged either: on a ``WARM_START_MODE=use`` run whose caches
        all passed the §11 pre-scan, nothing ever reads such a group's staged copy.

        :param material: The run material (primary preps mutated in place).
        :param real_features: The real strata features (a staging copy unions across them).
        :param staging_dir: The directory holding per-layer staging GeoPackages.
        :param feedback: Execution feedback channel.
        :param skip_warm_staged: Whether fully-warm groups skip staging.
        :raise QgsProcessingException: On a bad stage variable, a staging write failure, or
            cancellation.
        """
        to_stage: list[tuple[_LayerPrep, list[_LayerPrep]]] = []
        skipped_warm = 0
        for prep in material.preps:
            if prep.plan.method is params.MatchingMethod.WHOLE_EXPORT:
                continue
            if prep.group_primary_id not in (None, prep.layer.id()):
                continue  # non-primary member: it reads through its primary's table
            group = [
                other for other in material.preps if other.group_primary_id == prep.layer.id()
            ] or [prep]
            if not any(
                self._stage_layer(member.layer, member.plan, material.inputs.stage_providers)
                for member in group
            ):
                continue
            if skip_warm_staged and all(
                member.layer.id() in material.warm_marked_ids for member in group
            ):
                skipped_warm += 1
                continue
            to_stage.append((prep, group))
        if skipped_warm:
            feedback.pushInfo(
                self.tr(
                    "Skipping staging for %n warm-seeded group(s) — the warm cache covers"
                    " every stratum.",
                    n=skipped_warm,
                )
            )
        if not to_stage:
            return
        # Staging occupies the ≈ 5-20 % slice of Phase A (SPEC §8.4): one equal step per
        # group, each write's own 0-100 sweep scaled into its step via the band proxy.
        band = _BandFeedback(feedback, 5, 20)
        steps = QgsProcessingMultiStepFeedback(len(to_stage), band)
        for index, (prep, group) in enumerate(to_stage, start=1):
            if feedback.isCanceled():
                raise QgsProcessingException(self.tr("Operation was canceled."))
            steps.setCurrentStep(index - 1)
            line = self.tr("Staging layer {}/{}: {}").format(
                index, len(to_stage), prep.layer.name()
            )
            feedback.setProgressText(line)
            feedback.pushInfo(line)
            self._stage_prep(prep, group, material, real_features, staging_dir, steps)

    def _stage_prep(
        self,
        prep: _LayerPrep,
        group: Sequence[_LayerPrep],
        material: _Material,
        real_features: Sequence[QgsFeature],
        staging_dir: Path,
        feedback: QgsProcessingFeedback,
    ) -> None:
        """
        Build one staging GeoPackage and swap *prep*'s read source onto it (§8.2).

        The staged copy must be a superset of every read taken against it: the union of every
        group member's matches across all strata — or **all** features when
        ``EXPORT_FULL_PACKAGE`` is on, since the ``<full>`` stratum reads the whole staged copy.

        :param prep: The group primary (or ungrouped) prep; mutated to read the staged copy.
        :param group: Every prep sharing the table (just *prep* when ungrouped).
        :param material: The run material.
        :param real_features: The real strata features.
        :param staging_dir: The directory holding per-layer staging GeoPackages.
        :param feedback: Execution feedback channel.
        :raise QgsProcessingException: On a staging write or transform failure.
        """
        # ponytail: a relation-hop key may be excluded from OUTPUT but still drives the
        # per-stratum match, so it must survive into the staged copy (§7.1) — for every member.
        protected = frozenset(
            field
            for member in group
            if member.plan.method is params.MatchingMethod.ATTRIBUTE and member.plan.chain
            for field in member.plan.chain[-1].to_fields
        )
        wanted = set(prep.kept_fields) | protected
        keep_for_copy = tuple(
            name
            for name in (field.name() for field in prep.read_layer.fields().toList())
            if name in wanted
        )
        staging_gpkg = staging_dir / f"{prep.table}.gpkg"
        staging_gpkg.parent.mkdir(parents=True, exist_ok=True)
        staged_indexes = _field_indexes(prep.read_layer, keep_for_copy)
        if material.inputs.export_full:
            # The <full> stratum writes the whole staged copy, so it must hold every feature —
            # not just the matched union — or orphans vanish from the full package (§8.2).
            prep.read_layer.removeSelection()
            write_vector_table(
                staging_gpkg,
                prep.read_layer,
                prep.table,
                kept_field_indexes=staged_indexes,
                only_selected=False,
                feedback=feedback,
            )
        else:
            stage_union(
                staging_gpkg,
                prep.read_layer,
                prep.table,
                tuple(member.plan for member in group),
                real_features,
                kept_field_indexes=staged_indexes,
                project=material.project,
                strat_layer=material.inputs.strat_layer,
                feedback=feedback,
                chain_context=material.chain_context,
            )
        # Index the key columns the N per-stratum IN filters scan (§8.2) — one index per
        # distinct member key set; the spatial path already rides the writer's r-tree.
        for key_fields in {
            member.plan.chain[-1].to_fields
            for member in group
            if member.plan.method is params.MatchingMethod.ATTRIBUTE and member.plan.chain
        }:
            try:
                gpkg.create_attribute_index(staging_gpkg, prep.table, key_fields)
            except sqlite3.Error as err:  # an index is an optimization, never block the run
                feedback.pushWarning(
                    self.tr("could not index staged key fields for {}: {}").format(
                        prep.layer.name(), err
                    )
                )
        prep.read_layer = self._open_local(staging_gpkg, prep.table, prep.layer.name())
        prep.kept_field_indexes = _field_indexes(prep.read_layer, prep.kept_fields)
        prep.staged = True

    def _chain_hop_fields(
        self, material: _Material
    ) -> dict[str, tuple[set[str], set[tuple[str, ...]]]]:
        """
        Collect the fields every relation chain queries on each **intermediate** hop layer (§7.1).

        The last hop of a chain is never queried — its far-side keys *are* the membership
        condition — so only the layers a chain passes *through* are collected. Each hop reads
        its own ``to_fields`` (matched against the incoming keys) and the next hop's
        ``from_fields`` (collected as the outgoing keys).

        :param material: The run material (its preps carry the resolved plans).
        :return: Hop layer id -> ``(queried field names, distinct match field sets)``.
        """
        collected: dict[str, tuple[set[str], set[tuple[str, ...]]]] = {}
        for prep in material.preps:
            chain = prep.plan.chain
            for index, hop in enumerate(chain[:-1]):
                names, match_sets = collected.setdefault(hop.to_layer_id, (set(), set()))
                names.update(hop.to_fields)
                names.update(chain[index + 1].from_fields)
                match_sets.add(tuple(hop.to_fields))
        return collected

    def _stage_chain_hops(
        self, material: _Material, staging_dir: Path, feedback: QgsProcessingFeedback
    ) -> None:
        """
        Stage the intermediate hop layers of a ``STAGE_PROVIDERS`` provider (SPEC §7.1/§8.2).

        Relation-chain intermediates are read straight from the project, once per ``IN`` chunk
        per member per stratum — the one read path per-layer staging never covered, because
        staging only replaces a *packaged* layer's read source. When such a hop sits on a
        provider the user declared slow, copy it once into a local GeoPackage holding just the
        fields the chain queries, index those, and resolve the chain against that copy instead.

        The copy holds **every** feature: a chain propagates keys through the whole
        intermediate, so the matched-union slice a packaged layer stages would silently drop
        rows. A layer that is both a packaged layer and a hop is therefore staged twice, once
        per role, which is redundant but correct.

        A failure here is contained: hop staging is a read-amortization optimization, so the
        run falls back to reading the project layer rather than aborting.

        :param material: The run material (its chain context receives the staged layers).
        :param staging_dir: The directory holding the staging GeoPackages.
        :param feedback: Execution feedback channel.
        :raise QgsProcessingException: On cancellation.
        """
        stage_providers = material.inputs.stage_providers
        if not stage_providers:
            return
        for index, (layer_id, (names, match_sets)) in enumerate(
            self._chain_hop_fields(material).items()
        ):
            if feedback.isCanceled():
                raise QgsProcessingException(self.tr("Operation was canceled."))
            layer = cast("QgsVectorLayer | None", material.project.mapLayer(layer_id))
            if layer is None or layer.providerType() not in stage_providers:
                continue
            feedback.setProgressText(
                self.tr("Staging relation-chain layer: {}").format(layer.name())
            )
            try:
                self._stage_chain_hop(
                    layer,
                    names,
                    match_sets,
                    staging_dir,
                    index,
                    material.chain_context,
                    feedback,
                )
            except QgsProcessingException as err:
                feedback.pushWarning(
                    self.tr(
                        "Could not stage relation-chain layer {} ({}); its hops will be"
                        " queried from the project instead."
                    ).format(layer.name(), err)
                )

    def _stage_chain_hop(
        self,
        layer: QgsVectorLayer,
        names: Collection[str],
        match_sets: Collection[tuple[str, ...]],
        staging_dir: Path,
        index: int,
        chain_context: ChainContext,
        feedback: QgsProcessingFeedback,
    ) -> None:
        """
        Copy one intermediate hop layer locally and register it on the chain context (§8.2).

        :param layer: The project's hop layer (cloned, never read for data nor mutated).
        :param names: The field names the chain queries on this layer.
        :param match_sets: Distinct key field sets to index (the ``IN`` filters scan them).
        :param staging_dir: The directory holding the staging GeoPackages.
        :param index: A per-run counter making the staging file name unique.
        :param chain_context: The run's chain context, which receives the staged layer.
        :param feedback: Execution feedback channel.
        :raise QgsProcessingException: If the copy cannot be written or re-opened.
        """
        staging_gpkg = staging_dir / f"__hop_{index}.gpkg"
        staging_gpkg.parent.mkdir(parents=True, exist_ok=True)
        clone = self._clone(layer)
        clone.removeSelection()
        write_vector_table(
            staging_gpkg,
            clone,
            _HOP_TABLE,
            kept_field_indexes=_field_indexes(clone, names),
            only_selected=False,
            feedback=feedback,
        )
        for key_fields in match_sets:
            try:
                gpkg.create_attribute_index(staging_gpkg, _HOP_TABLE, key_fields)
            except sqlite3.Error as err:  # an index is an optimization, never block the run
                feedback.pushWarning(
                    self.tr("could not index staged key fields for {}: {}").format(
                        layer.name(), err
                    )
                )
        staged = self._open_local(staging_gpkg, _HOP_TABLE, layer.name())
        chain_context.hop_layers[layer.id()] = staged
        count = staged.featureCount()
        feedback.pushInfo(
            self.tr("Staged relation-chain layer {}: %n feature(s) copied.", n=count).format(
                layer.name()
            )
        )

    def _clone(self, layer: QgsVectorLayer) -> QgsVectorLayer:
        """
        Clone *layer* into a standalone read layer (its subset string rides along, §8.2).

        :param layer: The user's layer (never mutated).
        :return: An independent clone whose selection may be freely changed.
        :raise QgsProcessingException: If the clone is invalid.
        """
        clone = layer.clone()
        if clone is None or not clone.isValid():
            raise QgsProcessingException(
                self.tr("Layer {} could not be cloned.").format(layer.name())
            )
        return clone

    def _open_local(self, gpkg_path: Path, table: str, label: str) -> QgsVectorLayer:
        """
        Open a staged GeoPackage table as a standalone read layer (§8.2).

        :param gpkg_path: The staging GeoPackage.
        :param table: The table name.
        :param label: A human label for error messages.
        :return: The opened layer.
        :raise QgsProcessingException: If the table cannot be opened.
        """
        opened = QgsVectorLayer(staged_layer_uri(gpkg_path, table), f"{label} (staged)", "ogr")
        if not opened.isValid():
            raise QgsProcessingException(
                self.tr("Staged copy of layer {} cannot be re-opened.").format(label)
            )
        return opened

    def _layout_zip_roots(self, material: _Material, workdir: Path) -> None:
        """
        Create one zip-mirror build root per bundle and map every member's build path (§10).

        Needs only the bundle layout, so it runs before Phase A — the §11 warm prefetch can
        then copy cache files straight to their final build paths while Phase A works.

        :param material: The run material (bundles in, roots/paths out).
        :param workdir: The run's build directory.
        """
        for index, (zip_rel, members) in enumerate(material.bundles.items()):
            root = workdir / f"zip_{index:03d}"
            root.mkdir(parents=True, exist_ok=True)
            material.zip_roots[zip_rel] = root
            for member in members:
                material.zip_of_stratum[member.name] = zip_rel
                material.gpkg_paths[member.name] = root / f"{member.gpkg_rel}.gpkg"

    def _submit_warm_prefetch(
        self,
        material: _Material,
        strata: Sequence[StratumSpec],
        pool: ThreadPoolExecutor,
        cancel: threading.Event,
    ) -> None:
        """
        Queue background copies of the §11 warm caches to their build paths (warm runs only).

        Submitted before Phase A, so a (possibly remote) cache file arrives while layers are
        prepared and staged; the deliverable pass then seeds in place instead of copying on
        the critical path. Best-effort: a failed or unfinished copy falls back to the normal
        seed-time copy from the original cache file.

        :param material: The run material (bundle layout already computed).
        :param strata: The surviving strata (``<full>`` included when it is exported).
        :param pool: The background pool.
        :param cancel: The run's cancellation event.
        """
        inputs = material.inputs
        if not inputs.use_warm or inputs.warm_dir is None or inputs.dry_run:
            return
        for spec in strata:
            material.warm_prefetch[spec.name] = pool.submit(
                run_prefetch,
                inputs.warm_dir / f"{_warm_file_name(spec.name)}.gpkg",
                material.gpkg_paths[spec.name],
                cancel,
            )

    def _place_shared_payloads(self, material: _Material) -> None:
        """
        Place each bundle's shared ``data/`` and ``resources/`` trees into its zip root (§13/§14).

        Hardlinked when the filesystem allows, copied otherwise, so embedded projects written
        beside the gpkgs resolve everything relatively. Runs at the end of Phase A (payloads
        and style assets are Phase-A products); the roots themselves are laid out earlier by
        :meth:`_layout_zip_roots`.

        :param material: The run material.
        """
        for root in material.zip_roots.values():
            for payload in material.payloads:
                for source, arcname in payload.members:
                    _place(source, root / arcname)
            for original, arcname in material.assets.items():
                _place(Path(original), root / arcname)

    def _tree_ordered(
        self, project: QgsProject, layers: Sequence[QgsVectorLayer]
    ) -> list[QgsVectorLayer]:
        """
        Order vector *layers* by layer-tree order (§12/§15 tie-breaking).

        :param project: The run's project.
        :param layers: The packaged vector layers.
        :return: The ordered layers (tree order; unlisted ones keep input order).
        """
        return cast("list[QgsVectorLayer]", self._tree_ordered_any(project, layers))

    def _tree_ordered_any(
        self, project: QgsProject, layers: Sequence[QgsMapLayer]
    ) -> list[QgsMapLayer]:
        """
        Order any *layers* by layer-tree order.

        :param project: The run's project.
        :param layers: The layers to order.
        :return: The ordered layers (tree order; unlisted ones keep input order).
        """
        root = project.layerTreeRoot()
        tree_order = [layer.id() for layer in root.layerOrder()] if root is not None else []
        position = {layer_id: index for index, layer_id in enumerate(tree_order)}
        return sorted(layers, key=lambda lyr: position.get(lyr.id(), len(position)))

    def _excluded_fields(self, layer: QgsVectorLayer) -> tuple[str, ...]:
        """
        Read the layer's ``excluded_fields`` variable (§4).

        :param layer: The packaged layer.
        :return: The excluded field names.
        :raise QgsProcessingException: If the variable is not a JSON list of strings.
        """
        raw = LayerVariables(layer).get(params.LAYER_VAR_EXCLUDED_FIELDS)
        if raw is None or str(raw) == "":
            return ()
        try:
            values = json.loads(str(raw))
        except json.JSONDecodeError as err:
            raise QgsProcessingException(
                self.tr("layer {}: excluded_fields is not a JSON list: {}").format(
                    layer.name(), err
                )
            ) from err
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            raise QgsProcessingException(
                self.tr("layer {}: excluded_fields must be a JSON list of names").format(
                    layer.name()
                )
            )
        return tuple(values)

    def _style_documents(
        self, layer: QgsMapLayer, inputs: _Inputs, feedback: QgsProcessingFeedback
    ) -> tuple[str, str]:
        """
        Serialize the layer's style: QML for the selected categories, SLD best-effort (§8.1).

        :param layer: The packaged layer.
        :param inputs: The resolved inputs.
        :param feedback: Execution feedback channel.
        :return: ``(qml, sld)`` — both empty when styles are excluded.
        """
        if not inputs.include_styles:
            return "", ""
        qml_doc = QDomDocument()
        layer.exportNamedStyle(qml_doc, categories=inputs.style_categories)
        sld_text = self._sld_text(layer)
        usable = "<StyledLayerDescriptor" in sld_text
        if not usable:
            # Acceptable: SLD is best-effort (§8.1); the category-scoped QML is the
            # authoritative style, so an unusable SLD is dropped rather than failing.
            feedback.pushDebugInfo(
                f"style[{layer.name()}]: SLD export produced no usable document; "
                "keeping the QML only"
            )
        return qml_doc.toString(), sld_text if usable else ""

    def _sld_text(self, layer: QgsMapLayer) -> str:
        """
        Serialize the layer's SLD, best-effort (§8.1).

        Prefer :meth:`~qgis.core.QgsMapLayer.exportSldStyleV3` (QGIS 3.44+; returns
        the document); below QGIS 3.44 it is absent, so ``except AttributeError`` falls
        back to the deprecated ``exportSldStyleV2`` (3.30). This guarded fallback is the
        sole sanctioned ``qgis.core`` behavioral fallback (SPEC §1.1); it keeps V3
        from raising the support floor.

        Unlike the QML (:meth:`~qgis.core.QgsMapLayer.exportNamedStyle`), the SLD is
        serialized **in full** — it is intentionally not scoped to ``STYLE_CATEGORIES``,
        because the SLD export API offers no category option and SLD represents only
        symbology and labeling. The category-filtered ``styleQML`` is the authoritative
        artifact (SPEC §13).

        :param layer: The packaged layer.
        :return: The SLD XML (possibly empty or invalid; the caller guards validity).
        """
        context = QgsSldExportContext()
        try:
            sld_doc = layer.exportSldStyleV3(context)
        except AttributeError:
            sld_doc = QDomDocument()
            layer.exportSldStyleV2(sld_doc, "", context)  # "" = unused errorMsg out-param
        return sld_doc.toString()

    def _metadata_payload(self, layer: QgsMapLayer, inputs: _Inputs) -> str:
        """
        Serialize the layer's QMD metadata (§8.1 step 4).

        :param layer: The packaged layer.
        :param inputs: The resolved inputs.
        :return: The QMD XML, or an empty string when metadata is excluded.
        """
        if not inputs.include_metadata:
            return ""
        document = QDomDocument()
        layer.exportNamedMetadata(document, "")
        return document.toString()

    # ------------------------------------------------------------------
    # Phases B & C (§8.3/§8.4/§10/§13)
    # ------------------------------------------------------------------

    def _phases_b_c(  # noqa: PLR0913  # keyword-only §8 hand-off inputs; a bag would rename them
        self,
        material: _Material,
        strata: Sequence[StratumSpec],
        *,
        warm_strata: Sequence[StratumSpec],
        features_by_name: Mapping[str, QgsFeature],
        workdir: Path,
        report_rows: list[RunReportRow],
        parameters: dict[str | None, Any],
        context: QgsProcessingContext,
        pool: ThreadPoolExecutor,
        cancel: threading.Event,
        feedback: QgsProcessingFeedback,
    ) -> StratifiedPackagerAlgorithmOutputDict:
        """
        Build the stratum gpkgs sequentially, embed projects, zip and publish per bundle.

        GeoPackage writing stays on this thread (only it may touch QGIS); the background pool
        zips each finished bundle while the next bundle's GeoPackages are built (SPEC §8).

        :param material: The run material.
        :param strata: The surviving strata (deliverables; ``OVERWRITE_MODE`` applied).
        :param warm_strata: Every resolved stratum — the §11 update pass refreshes all
            caches, including strata whose deliverable was skip-existing filtered.
        :param features_by_name: Stratum features keyed by sanitized name.
        :param workdir: The run's build directory.
        :param report_rows: Mutable run-report rows.
        :param parameters: Raw parameter values (carry the ``REPORT`` destination).
        :param context: The processing context.
        :param pool: The run-scoped background pool.
        :param cancel: The run's cancellation event.
        :param feedback: Execution feedback channel.
        :return: The §3 outputs map.
        :raise QgsProcessingException: On cancellation, or at the end when any stratum,
            zip, or warm-cache write failed (best-effort policy, §17).
        """
        inputs = material.inputs
        inputs.output_dir.mkdir(parents=True, exist_ok=True)
        remove_stale_parts(inputs.output_dir, [f"{rel}.zip" for rel in material.bundles])

        builds = {
            stratum.name: self._stratum_build(stratum, material, features_by_name)
            for stratum in strata
        }
        warm_builds = (
            [
                self._warm_cache_build(
                    stratum, material, features_by_name, workdir / "warm", inputs.warm_dir
                )
                for stratum in warm_strata
            ]
            if inputs.update_warm and inputs.warm_dir is not None
            else []
        )
        feedback.pushInfo(self.tr("Building %n strata.", n=len(builds)))
        state = self._build_and_zip(material, builds, warm_builds, workdir, pool, cancel, feedback)
        if feedback.isCanceled():
            raise QgsProcessingException(self.tr("Operation was canceled."))

        account_orphans(material, state, report_rows, feedback)
        collect_report_rows(strata, material, state, report_rows)
        report_id = self._emit_run_report(parameters, context, report_rows, feedback)
        feedback.setProgress(100)

        outputs: StratifiedPackagerAlgorithmOutputDict = {
            params.OUTPUT_DIRECTORY: str(inputs.output_dir),
            params.REPORT: report_id,
            params.ZIP_PATHS: json.dumps(sorted(state.published)),
            params.STRATA_COUNT: len(strata),
            params.ZIP_COUNT: len(state.published),
            params.FAILED_STRATA: json.dumps(sorted(state.failed)),
        }
        if state.failed or state.failed_zips or state.failed_warm:
            raise QgsProcessingException(
                self.tr(
                    "Run finished with failures — strata: [{}]; zips: [{}]; warm caches: [{}]"
                ).format(
                    ", ".join(sorted(state.failed)),
                    ", ".join(sorted(state.failed_zips)),
                    ", ".join(sorted(state.failed_warm)),
                )
            )
        return outputs

    # pylint: disable-next=too-many-locals  # sequential build + zip dispatch
    def _build_and_zip(
        self,
        material: _Material,
        builds: Mapping[str, StratumBuild],
        warm_builds: Sequence[StratumBuild],
        workdir: Path,
        pool: ThreadPoolExecutor,
        cancel: threading.Event,
        feedback: QgsProcessingFeedback,
    ) -> _BuildState:
        """
        Build every stratum gpkg on this thread, zipping finished bundles in the background.

        On ``WARM_START_MODE=update`` runs the §11 warm pass runs first: every stratum's warm
        cache is written and atomically published before any deliverable is built, so an
        interrupted run still leaves a complete, reusable cache. The deliverables then
        seed from the fresh cache; a stratum whose cache write failed builds cold. On
        ``WARM_START_MODE=use`` runs a member whose §11 prefetch landed seeds in place — its
        cache already sits at the build path.

        Bundles run in order and their strata in sequence (SPEC §8.4); a bundle's zip is
        submitted once its members are written, so the next bundle builds while this one
        compresses. Cancellation propagates into the in-flight zip jobs.

        :param material: The run material.
        :param builds: The stratum builds by sanitized name.
        :param warm_builds: The §11 warm-pass builds (empty unless ``WARM_START_MODE=update``).
        :param workdir: The run's build directory.
        :param pool: The run-scoped background pool.
        :param cancel: The run's cancellation event.
        :param feedback: Execution feedback channel.
        :return: The final build state.
        """
        inputs = material.inputs
        total = max(
            1,
            sum(len(build.layers) for build in builds.values())
            + sum(len(build.layers) for build in warm_builds)
            + len(material.bundles),
        )
        state = _BuildState(total_units=total)
        if warm_builds:
            feedback.pushInfo(
                self.tr("Updating %n warm cache(s) before the deliverables.", n=len(warm_builds))
            )
        for index, warm_build in enumerate(warm_builds, start=1):
            if feedback.isCanceled():
                return state
            line = self.tr("Warm cache {}/{}: {}").format(index, len(warm_builds), warm_build.name)
            feedback.pushInfo(line)
            result = write_stratum(
                warm_build,
                label=line,
                project=material.project,
                strat_layer=inputs.strat_layer,
                feedback=self._stratum_band(state, warm_build, feedback),
                chain_context=material.chain_context,
            )
            self._fold_warm_result(state, result, feedback)
            if result.ok:
                # The cache copy is published; the workdir build file would only hold the
                # same bytes for the rest of the run — drop it (Windows may keep it locked).
                try:
                    warm_build.gpkg_path.unlink(missing_ok=True)
                except OSError:
                    feedback.pushWarning(
                        self.tr("Failed to remove workdir copy of warm geopackage {}").format(
                            warm_build.gpkg_path
                        )
                    )
        stratum_index = 0
        for zip_rel, members in material.bundles.items():
            for member in members:
                if feedback.isCanceled():
                    cancel.set()
                    return state
                stratum_index += 1
                line = self.tr("Stratum {}/{}: {}").format(stratum_index, len(builds), member.name)
                feedback.pushInfo(line)
                build = builds[member.name]
                if build.warm_start is not None and member.name in state.failed_warm:
                    # A stale cache from an earlier run may still pass the §11 table
                    # check; never seed a deliverable from it after a failed refresh.
                    build = replace(build, warm_start=None)
                prefetch = material.warm_prefetch.get(member.name)
                if (
                    prefetch is not None
                    and build.warm_start is not None
                    and prefetch.result()  # the seed must exist before writing: wait for it
                ):
                    # The §11 prefetch already copied this cache to the build path; seed in
                    # place (a rejected copy still cold-falls-back inside _seed).
                    build = replace(build, warm_start=build.gpkg_path)
                result = write_stratum(
                    build,
                    label=line,
                    project=material.project,
                    strat_layer=inputs.strat_layer,
                    feedback=self._stratum_band(state, build, feedback),
                    chain_context=material.chain_context,
                )
                self._fold_result(state, result, feedback)
            self._maybe_submit_zip(
                pool, state, material, zip_rel, members, workdir, cancel, feedback
            )
        for future in state.zip_futures:
            self._fold_zip(state, future.result(), feedback)
        _report_chain_memo(material.chain_context, feedback)
        return state

    def _stratum_band(
        self, state: _BuildState, build: StratumBuild, feedback: QgsProcessingFeedback
    ) -> _BandFeedback:
        """
        Return the feedback band covering *build*'s slice of the 25-95 % B/C range (SPEC §8.4).

        The slice spans the build's per-layer units from the current unit count, so the
        writer sweeps inside it and the following ``_fold_*`` progress report lands exactly
        on the slice's upper bound.

        :param state: The build state (unit counters).
        :param build: The stratum build about to be written.
        :param feedback: The run feedback.
        :return: The band proxy to hand to :func:`~.building.write_stratum`.
        """
        low = 25 + 70 * state.done_units / state.total_units
        high = 25 + 70 * (state.done_units + len(build.layers)) / state.total_units
        return _BandFeedback(feedback, low, high)

    def _fold_result(
        self, state: _BuildState, result: StratumWriteResult, feedback: QgsProcessingFeedback
    ) -> None:
        """
        Fold one stratum's write outcome into the build state and the feedback (§9/§11).

        :param state: The build state.
        :param result: The stratum write result.
        :param feedback: Execution feedback channel.
        """
        if result.warm_reason:
            state.cold_fallbacks[result.name] = result.warm_reason
            feedback.pushWarning(
                self.tr("Stratum {}: cold fallback ({}).").format(result.name, result.warm_reason)
            )
        if result.ok:
            state.succeeded.add(result.name)
        else:
            state.failed[result.name] = result.error
            feedback.reportError(
                self.tr("Stratum {} failed: {}").format(result.name, result.error)
            )
        for layer_result in result.layers:
            state.layer_results[result.name, layer_result.layer_id] = layer_result
            if layer_result.matched_fids:
                state.matched_union.setdefault(layer_result.layer_id, set()).update(
                    layer_result.matched_fids
                )
            state.done_units += 1
        feedback.setProgress(25 + 70 * state.done_units / state.total_units)

    def _fold_warm_result(
        self, state: _BuildState, result: StratumWriteResult, feedback: QgsProcessingFeedback
    ) -> None:
        """
        Fold one §11 warm-pass outcome into the build state and the feedback.

        Deliverable accounting (``succeeded``/``failed``/``layer_results``) is untouched:
        the deliverable pass re-reports every layer (warm-seeded ones as ``warm``), and a
        failed cache write only costs that stratum its warm seed — it still builds and
        ships cold; the missing cache fails the run at the end. The matched fids do fold
        in: the warm-seeded deliverable reports none for those layers, so the §9.1 orphan
        union needs the warm pass's.

        :param state: The build state.
        :param result: The warm-cache write result.
        :param feedback: Execution feedback channel.
        """
        if not result.ok:
            state.failed_warm[result.name] = result.error
            # The deliverable pass skips the (possibly stale) seed for this stratum, so no
            # §11 rejection fires there — record the fallback here for the §9.1 rows.
            state.cold_fallbacks[result.name] = self.tr("warm cache not written: {}").format(
                result.error
            )
            feedback.pushWarning(
                self.tr("Stratum {}: warm cache not written ({}).").format(
                    result.name, result.error
                )
            )
        for layer_result in result.layers:
            if layer_result.matched_fids:
                state.matched_union.setdefault(layer_result.layer_id, set()).update(
                    layer_result.matched_fids
                )
            state.done_units += 1
        feedback.setProgress(25 + 70 * state.done_units / state.total_units)

    def _fold_zip(
        self, state: _BuildState, outcome: ZipOutcome, feedback: QgsProcessingFeedback
    ) -> None:
        """
        Fold one bundle's zip outcome into the build state and the feedback.

        :param state: The build state.
        :param outcome: The zip outcome.
        :param feedback: Execution feedback channel.
        """
        state.done_units += 1
        if outcome.ok:
            state.published.append(outcome.final_path)
            feedback.pushInfo(self.tr("Published {}").format(outcome.final_path))
        else:
            state.failed_zips[outcome.zip_rel] = outcome.error
            feedback.reportError(
                self.tr("Zip {} failed: {}").format(outcome.zip_rel, outcome.error)
            )
        feedback.setProgress(25 + 70 * state.done_units / state.total_units)

    def _maybe_submit_zip(
        self,
        pool: ThreadPoolExecutor,
        state: _BuildState,
        material: _Material,
        zip_rel: str,
        members: Sequence[StratumSpec],
        workdir: Path,
        cancel: threading.Event,
        feedback: QgsProcessingFeedback,
    ) -> None:
        """
        Finalize a finished bundle (Phase C) and submit its zip to the background pool.

        Embedded projects for the successful members, then the per-zip report, then the zip
        job. A bundle whose members all failed is recorded as a failed zip.

        :param pool: The background pool.
        :param state: The build state.
        :param material: The run material.
        :param zip_rel: The bundle's zip path (no extension).
        :param members: The bundle's member strata.
        :param workdir: The run's build directory.
        :param cancel: The run's cancellation event.
        :param feedback: Execution feedback channel.
        """
        ok_members = [member for member in members if member.name in state.succeeded]
        if ok_members:
            self._finalize_members(material, ok_members, state, feedback)
            # A §4 layer_name evaluation failure fails its member during finalization.
            ok_members = [member for member in ok_members if member.name in state.succeeded]
        if not ok_members:
            state.failed_zips[zip_rel] = "all member strata failed"
            state.done_units += 1
            feedback.pushWarning(
                self.tr("Zip {} skipped: every member stratum failed.").format(zip_rel)
            )
            return
        for member in ok_members:
            # The embedded-project build's OGR reads may have switched the gpkg to WAL journal
            # mode; fold the WAL back into the main file so the zip ships a complete database
            # (its ``-wal``/``-shm`` sidecars are excluded from the zip, SPEC §10).
            if not gpkg.checkpoint_wal(material.gpkg_paths[member.name]):
                feedback.pushWarning(
                    self.tr("Stratum {}: WAL checkpoint incomplete before zipping.").format(
                        member.name
                    )
                )
        if material.inputs.generate_report:
            write_zip_report(
                material.zip_roots[zip_rel] / "report.csv",
                zip_report_rows(material, ok_members, state),
            )
        job = self._zip_job(material, zip_rel, workdir)
        feedback.pushInfo(self.tr("Zipping {}.zip in the background.").format(zip_rel))
        state.zip_futures.append(pool.submit(run_zip, job, cancel))

    def _finalize_members(
        self,
        material: _Material,
        members: Sequence[StratumSpec],
        state: _BuildState,
        feedback: QgsProcessingFeedback,
    ) -> None:
        """
        Build the embedded project of each successful member (§13, Phase C).

        Two failure regimes (SPEC §4 vs §17): assembling the member's *plan* evaluates the
        ``layer_name`` expressions — a §4-strict eval error/NULL **fails the stratum** (the
        member leaves the succeeded set and its gpkg is discarded). Once the plan exists, an
        embedded-project *write* failure is non-fatal degraded delivery (§17): the member's
        data gpkg is intact and still ships — without the embedded project — and a warning is
        pushed. Genuine *data* failures are contained upstream in the worker pool, not here.

        :param material: The run material.
        :param members: The bundle's successful members.
        :param state: The pool state.
        :param feedback: Execution feedback channel.
        """
        if material.inputs.project_inclusion is params.ProjectInclusion.NONE:
            return
        for member in members:
            feedback.setProgressText(
                self.tr("Stratum {}: writing embedded project.").format(member.name)
            )
            try:
                plan = self._project_plan(material, member, state)
            except QgsProcessingException as err:
                # §4 strict regime: a layer_name eval error/NULL fails this stratum.
                state.succeeded.discard(member.name)
                state.failed[member.name] = str(err)
                if not discard_gpkg(material.gpkg_paths[member.name]):
                    feedback.pushWarning(
                        self.tr("Failed to remove gpkg of failed stratum {}.").format(member.name)
                    )
                feedback.reportError(self.tr("Stratum {} failed: {}").format(member.name, err))
                continue
            # Hold the gpkg in WAL with a live -wal sidecar for the whole build, so every
            # pooled open detects it and retries without nolock instead of breaking
            # mid-statement when a later write materializes the sidecar (§13); the
            # checkpoint in _maybe_submit_zip reverts it before zipping.
            try:
                with gpkg.wal_session(material.gpkg_paths[member.name]) as wal_ok:
                    if not wal_ok:
                        feedback.pushDebugInfo(
                            self.tr("Stratum {}: could not pre-enable WAL journaling.").format(
                                member.name
                            )
                        )
                    build_stratum_project(material.project, plan, feedback)
            except QgsProcessingException as err:
                # The data gpkg is intact (the stratum already succeeded); only the embedded
                # project failed. Ship the data without it rather than dropping the stratum
                # (§17 degraded delivery). The member stays in `succeeded`, so its gpkg is
                # still zipped; not unlinking it also avoids the Windows WinError 32 raised on
                # the gpkg handle the fresh project still holds open.
                feedback.pushWarning(
                    self.tr(
                        "Stratum {}: embedded project not written; shipping data without it ({})."
                    ).format(member.name, err)
                )

    def _project_plan(
        self, material: _Material, member: StratumSpec, state: _BuildState
    ) -> StratumProjectPlan:
        """
        Assemble one member's embedded-project plan (§13).

        :param material: The run material.
        :param member: The member stratum.
        :param state: The pool state (which tables were kept).
        :return: The plan.
        """
        gpkg_path = material.gpkg_paths[member.name]
        zip_root = material.zip_roots[material.zip_of_stratum[member.name]]
        to_root = "../" * member.gpkg_rel.count("/")
        vector_tables = {
            prep.layer.id(): prep.table
            for prep in material.preps
            if (outcome := state.layer_results.get((member.name, prep.layer.id()))) is not None
            and outcome.status != STATUS_EMPTY_SKIPPED
        }
        data_sources = {
            payload.layer.id(): zip_root / payload.project_source
            for payload in material.payloads
            if payload.project_source
        }
        styles = {
            prep.layer.id(): rewrite_asset_paths(prep.qml, material.assets, to_root)
            for prep in material.preps
            if prep.qml
        }
        display_names: dict[str, str] = {}
        for layer_id, text in material.layer_name_expressions.items():
            layer = material.project.mapLayer(layer_id)
            if layer is None:
                continue
            display_names[layer_id] = evaluate_layer_display_name(
                layer,
                material.project,
                text,
                stratum_name=member.raw_name,
                stratum_name_sanitized=member.name,
            )
        return StratumProjectPlan(
            title=member.name,
            mode=material.inputs.project_inclusion,
            gpkg_path=gpkg_path,
            qgz_path=gpkg_path.with_suffix(".qgz"),
            vector_tables=vector_tables,
            data_sources=data_sources,
            embedded_only=tuple(layer.id() for layer in material.inputs.embedded_layers),
            styles_qml=styles,
            subsets={
                prep.layer.id(): prep.subset_sql for prep in material.preps if prep.subset_sql
            },
            display_names=display_names,
        )

    def _stratum_build(
        self,
        stratum: StratumSpec,
        material: _Material,
        features_by_name: Mapping[str, QgsFeature],
    ) -> StratumBuild:
        """
        Assemble one stratum's deliverable build plan (§8.3 step-3 ordering).

        Layer order: warm-marked first, the whole-export template layers, then the
        partitioned layers. A dedup group contributes one layer (the primary's), carrying
        every member's plan and style. ``WARM_START_MODE=update`` deliverables seed from the
        warm cache the §11 warm pass just wrote, exactly like a ``WARM_START_MODE=use`` run.

        :param stratum: The stratum.
        :param material: The run material.
        :param features_by_name: Stratum features keyed by sanitized name (``<full>`` absent).
        :return: The build plan.
        """
        inputs = material.inputs
        to_root = "../" * stratum.gpkg_rel.count("/")
        primaries = [
            prep for prep in material.preps if prep.group_primary_id in (None, prep.layer.id())
        ]
        warm = [prep for prep in primaries if prep.layer.id() in material.warm_marked_ids]
        rest = [prep for prep in primaries if prep.layer.id() not in material.warm_marked_ids]
        whole = [prep for prep in rest if prep.plan.method is params.MatchingMethod.WHOLE_EXPORT]
        partitioned = [
            prep for prep in rest if prep.plan.method is not params.MatchingMethod.WHOLE_EXPORT
        ]
        layers = tuple(
            self._layer_write(prep, material, to_root=to_root)
            for prep in [*warm, *whole, *partitioned]
        )
        warm_file = (
            inputs.warm_dir / f"{_warm_file_name(stratum.name)}.gpkg"
            if inputs.warm_dir is not None
            else None
        )
        return StratumBuild(
            name=stratum.name,
            gpkg_path=material.gpkg_paths[stratum.name],
            layers=layers,
            stratum_feature=features_by_name.get(stratum.name),
            template=material.template_path,
            warm_start=warm_file if (inputs.use_warm or inputs.update_warm) else None,
            expected_warm_tables=tuple(prep.table for prep in warm),
        )

    def _warm_cache_build(
        self,
        stratum: StratumSpec,
        material: _Material,
        features_by_name: Mapping[str, QgsFeature],
        build_dir: Path,
        warm_dir: Path,
    ) -> StratumBuild:
        """
        Assemble one stratum's §11 warm-pass build plan (``WARM_START_MODE=update``).

        A fresh gpkg holding only the warm-marked primaries, assembled under *build_dir*
        and snapshot into the warm cache after its last layer lands. Empty warm tables
        are always kept — the cache stays complete regardless of ``KEEP_EMPTY_LAYERS``,
        which the deliverable pass applies when it seeds from the cache.

        :param stratum: The stratum.
        :param material: The run material.
        :param features_by_name: Stratum features keyed by sanitized name (``<full>`` absent).
        :param build_dir: The workdir subdirectory holding the warm-pass builds.
        :param warm_dir: The warm-cache directory (snapshot destination).
        :return: The build plan.
        """
        to_root = "../" * stratum.gpkg_rel.count("/")
        layers = tuple(
            replace(self._layer_write(prep, material, to_root=to_root), keep_if_empty=True)
            for prep in material.preps
            if prep.group_primary_id in (None, prep.layer.id())
            and prep.layer.id() in material.warm_marked_ids
        )
        return StratumBuild(
            name=stratum.name,
            gpkg_path=build_dir / f"{_warm_file_name(stratum.name)}.gpkg",
            layers=layers,
            stratum_feature=features_by_name.get(stratum.name),
            snapshot_to=warm_dir / f"{_warm_file_name(stratum.name)}.gpkg",
        )

    def _zip_job(self, material: _Material, zip_rel: str, workdir: Path) -> ZipJob:
        """
        Assemble one bundle's zip job from its build root (§10).

        :param material: The run material.
        :param zip_rel: The bundle's zip path (no extension).
        :param workdir: The run's build directory.
        :return: The zip job.
        """
        # SQLite sidecars must never ship: the gpkgs are checkpointed before this walk
        # (``_maybe_submit_zip``), so the main files are complete on their own (SPEC §10).
        members = [
            member
            for member in iter_file_members(material.zip_roots[zip_rel])
            if not member[0].name.endswith(_SQLITE_SIDECAR_SUFFIXES)
        ]
        if material.inputs.extra_dir is not None:
            members.extend(iter_file_members(material.inputs.extra_dir))
        return ZipJob(
            zip_rel=zip_rel,
            members=tuple(members),
            build_path=workdir / "zips" / f"{zip_rel}.zip",
            final_path=material.inputs.output_dir / f"{zip_rel}.zip",
            compression_level=material.inputs.compression_level,
            write_checksum=material.inputs.write_checksums,
        )

    # ------------------------------------------------------------------
    # Dry run (§3 DRY_RUN)
    # ------------------------------------------------------------------

    def _finish_dry_run(
        self,
        material: _Material,
        strata: Sequence[StratumSpec],
        report_rows: list[RunReportRow],
        parameters: dict[str | None, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> StratifiedPackagerAlgorithmOutputDict:
        """
        Conclude a dry run: report only, no packages (§9.1).

        :param material: The run material.
        :param strata: The surviving strata.
        :param report_rows: Mutable run-report rows.
        :param parameters: Raw parameter values (carry the ``REPORT`` destination).
        :param context: The processing context.
        :param feedback: Execution feedback channel.
        :return: The §3 outputs map (no zips).
        """
        inputs = material.inputs
        for stratum in strata:
            for prep in material.preps:
                # A dry run does not match; only the unconditional whole-export count is known.
                count: int | None = (
                    prep.read_layer.featureCount()
                    if prep.plan.method is params.MatchingMethod.WHOLE_EXPORT
                    else None
                )
                report_rows.append(
                    RunReportRow(
                        stratum=stratum.name,
                        layer=prep.layer.name(),
                        feature_count=count,
                        status=STATUS_DRY_RUN,
                    )
                )
            report_rows.extend(
                RunReportRow(
                    stratum=stratum.name,
                    layer=payload.layer.name(),
                    status=STATUS_DRY_RUN,
                )
                for payload in material.payloads
            )
        # Phase B/C (which creates the output dir) is skipped on a dry run, so ensure it
        # exists for a file-backed REPORT sink (a memory destination ignores it).
        inputs.output_dir.mkdir(parents=True, exist_ok=True)
        report_id = self._emit_run_report(parameters, context, report_rows, feedback)
        feedback.setProgress(100)
        return {
            params.OUTPUT_DIRECTORY: str(inputs.output_dir),
            params.REPORT: report_id,
            params.ZIP_PATHS: json.dumps([]),
            params.STRATA_COUNT: len(strata),
            params.ZIP_COUNT: 0,
            params.FAILED_STRATA: json.dumps([]),
        }

    def _emit_run_report(
        self,
        parameters: dict[str | None, Any],
        context: QgsProcessingContext,
        report_rows: Sequence[RunReportRow],
        feedback: QgsProcessingFeedback,
    ) -> str:
        """
        Write the run-level report (§9.1) into the ``REPORT`` feature sink.

        The destination is whatever ``REPORT`` resolves to: a memory table (loaded into
        the project by the GUI) when no path is given, or a file otherwise. Always
        produced — on ``DRY_RUN`` too — independent of ``GENERATE_REPORT``, which gates
        only the per-zip ``report.csv`` (§9.2). The sink's columns are the
        :class:`~.report.RunReportRow` fields.

        :param parameters: Raw parameter values (carry the ``REPORT`` destination).
        :param context: The processing context.
        :param report_rows: The run-report rows, in the intended order.
        :param feedback: Execution feedback channel.
        :return: The sink destination id (the memory layer id, or the written path).
        :raise QgsProcessingException: If QGIS cannot create the sink or accept a row.
        """
        column_names = [report_field.name for report_field in fields(RunReportRow)]
        report_fields = QgsFields()
        for name in column_names:
            kind = QMetaType.Type.Int if name == "feature_count" else QMetaType.Type.QString
            # The bundled QGIS stubs expose only QgsField's copy ctor; its (name, type)
            # ctor is runtime-valid on QGIS 4, so the checkers misread this call.
            report_fields.append(QgsField(name, kind))  # ty: ignore[invalid-argument-type, too-many-positional-arguments]
        sink, dest_id = self.parameterAsSink(
            parameters, params.REPORT, context, report_fields, Qgis.WkbType.NoGeometry
        )
        if sink is None:
            raise QgsProcessingException(self.tr("Could not create the run report output."))
        for row in report_rows:
            feature = QgsFeature(report_fields)
            feature.setAttributes([getattr(row, name) for name in column_names])
            if not sink.addFeature(feature):
                raise QgsProcessingException(self.tr("Could not write a run report row."))
        feedback.pushInfo(self.tr("Run report written to {}").format(dest_id))
        return dest_id

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @override
    def name(self) -> str:
        """Return the algorithm name, used for identifying the algorithm."""
        return "package"

    @override
    def displayName(self) -> str:
        """Return the translated user-facing algorithm name."""
        return self.tr("Package project")

    @override
    def shortDescription(self) -> str:
        """Return a translated one-line description."""
        return self.tr(
            "Partitions the project's layers against a stratification layer and emits"
            " one zipped GeoPackage per stratum."
        )

    @override
    def shortHelpString(self) -> str:
        """Return a localised HTML help string documenting every parameter (SPEC §20)."""
        variable_items = "".join(
            f"<li><code>{spec.name}</code> {self.tr(spec.description)}</li>"
            for spec in params.LAYER_VAR_SPECS
        )
        body = (
            self.tr(
                "<p>Partitions the open project's layers against a <b>stratification layer</b>"
                " (one stratum per feature) and writes <b>one zipped GeoPackage per stratum</b>"
                " into the output directory. Each layer's features are matched to strata either"
                " by <b>attribute</b> (following chains of project relations) or <b>spatially</b>"
                " (one or more predicates, including raw DE-9IM patterns, combined with OR),"
                " chosen per layer.</p>"
                "<h3>Key parameters</h3>"
                "<ul>"
                "<li><b>Layers to package</b> — leave empty to package every eligible layer not"
                " marked with the <code>stratified_packager_exclude</code> variable.</li>"
                "<li><b>Stratification layer</b> and <b>Stratum name expression</b> — the"
                " partition source and how each stratum is named (empty = feature id). Naming"
                " and path expressions can use <code>@stratum_name</code>,"
                " <code>@stratum_name_sanitized</code>, <code>@gpkg_path</code> and"
                " <code>@gpkg_name</code>.</li>"
                "<li><b>Output directory</b> — where zips are published (atomic .part"
                " rename).</li>"
                "<li><b>Existing outputs</b> — overwrite, error, or skip-existing.</li>"
                "<li><b>Embed a project per stratum</b> — none, gpkg (stored inside the"
                " package), or qgz (beside it); styles, metadata, relations and auxiliary files"
                " are bundled.</li>"
                "<li><b>Also export the full package</b> — additionally emit the unpartitioned"
                " dataset as a pseudo-stratum.</li>"
                "<li><b>Dry run</b> — validate and report without writing any packages.</li>"
                "</ul>"
                "<h3>Per-layer variables</h3>"
                "<p>Edit under <i>Layer Properties &gt; Variables</i>, the per-layer plugin"
                " page, or the plugin's <i>Configure layers for packaging</i> dialog:</p>"
            )
            + f"<ul>{variable_items}</ul>"
            + self.tr(
                "<h3>Defaults and precedence</h3>"
                "<p>Every omitted parameter resolves through <b>explicit input &gt; project"
                " variable (<code>stratified_packager_&lt;param&gt;</code>) &gt; plugin setting"
                " &gt; builtin default</b>. Project- and layer-scope values are editable from"
                " the plugin's Options page, the Project Properties page and the per-layer"
                " page.</p>"
                "<h3>Warm cache</h3>"
                "<p>With a warm-cache directory, <b>Use warm start</b> begins each stratum"
                " GeoPackage from a cached copy and appends only non-warm-marked layers;"
                " <b>Update warm cache</b> first writes every stratum's cache file, then builds"
                " the deliverables seeded from that fresh cache — an interrupted run still"
                " leaves a complete, reusable cache. A cached file that no longer matches its"
                " warm-marked tables falls back to a cold build for that stratum (reported as"
                " cold-fallback).</p>"
                "<h3>Running headless (qgis_process)</h3>"
                "<p>Pass <code>--project_path</code>: the algorithm requires a project. The"
                " Processing framework re-instantiates the algorithm after the project loads,"
                " so project-variable and plugin-setting defaults resolve correctly without a"
                " GUI. <code>QgsSettings</code> is per-profile, so qgis_process uses the"
                " default profile unless overridden.</p>"
            )
        )
        # QGIS's algorithm-help widget hardcodes dark-grey element colours
        # (``p,ul,li{color:#666}``, ``b{color:#333}``) that assume a light background and
        # vanish on a dark theme. Under a dark palette, prepend a document ``<style>`` —
        # which beats the widget's default stylesheet for the elements that follow it —
        # recolouring the help body to the palette text colour. Links keep their own colour;
        # light themes are left untouched (QGIS's greys are correct there).
        palette = QApplication.palette()
        text = palette.color(QPalette.ColorRole.WindowText)
        window = palette.color(QPalette.ColorRole.Window)
        if text.lightnessF() <= window.lightnessF():  # light theme: leave QGIS's colours
            return body
        return f"<style>h3,p,ul,li,b{{color:{text.name()};}}</style>{body}"

    @override
    def createInstance(self) -> StratifiedPackagerAlgorithm:
        """Create a new instance of the algorithm class."""
        return StratifiedPackagerAlgorithm()

    @classmethod
    def tr(
        cls,
        sourceText: str,  # noqa: N803  # Just to keep the same name as in QObject.tr
        disambiguation: str | None = None,
        n: int = -1,
    ) -> str:
        """
        Get the translation for a string using Qt translation API.

        :param sourceText: String for translation.
        :param disambiguation: Identifying string for when the same text is used
            in different roles within the context.
        :param n: Number to support plural forms.
            https://doc.qt.io/qt-6/i18n-source-translation.html#handle-plural-forms
        :return: Translated version of the source text.
        """
        return QCoreApplication.translate(cls.__name__, sourceText, disambiguation, n)


def _place(source: Path, destination: Path) -> None:
    """
    Materialize *source* at *destination* (hardlink when possible, copy otherwise).

    :param source: The existing file.
    :param destination: The target inside a zip-mirror build root.
    """
    if destination.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)
