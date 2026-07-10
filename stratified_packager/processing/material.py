"""
Phase-A → Phase-B/C hand-off records and their shared helpers (SPEC §8).

The plain dataclasses the algorithm fills during Phase A and consumes while building and
zipping (:class:`_Inputs`, :class:`_LayerPrep`, :class:`_PayloadPrep`, :class:`_Material`,
:class:`_BuildState`), plus the small helpers that several phase modules share
(:func:`_field_indexes`, :func:`_warm_file_name`, :func:`_is_warm_marked`). Kept here so
the extracted phase modules (:mod:`~.dedup`, :mod:`~.reporting`) and the orchestrator all
depend on one lower-layer module rather than on each other.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from qgis.core import QgsProcessingException
from qgis.PyQt.QtCore import QCoreApplication

from stratified_packager.toolbelt.settings import LayerVariables
from stratified_packager.toolbelt.utils import coerce_bool

from . import params
from .strata import FULL_PACKAGE_KEY

if TYPE_CHECKING:
    from collections.abc import Collection
    from concurrent.futures import Future
    from pathlib import Path

    from qgis.core import QgsMapLayer, QgsProject, QgsVectorLayer

    from .building import LayerWriteResult
    from .matching import LayerMatchPlan
    from .strata import StratumSpec
    from .workers import ZipOutcome

__all__: list[str] = [
    "_BuildState",
    "_Inputs",
    "_LayerPrep",
    "_Material",
    "_PayloadPrep",
    "_field_indexes",
    "_is_warm_marked",
    "_warm_file_name",
]


@dataclass
# pylint: disable-next=too-many-instance-attributes  # plain record mirroring SPEC §3
class _Inputs:
    """Every input of SPEC §3, resolved through the §5 chain to typed values."""

    layers: list[QgsVectorLayer]
    payload_layers: list[QgsMapLayer]
    embedded_layers: list[QgsMapLayer]
    strat_layer: QgsVectorLayer | None
    name_expression: str
    gpkg_expression: str
    zip_expression: str
    output_dir: Path
    compression_level: int
    overwrite_mode: params.OverwriteMode
    project_inclusion: params.ProjectInclusion
    use_temp_folder: bool
    strata_from_selection: bool
    include_styles: bool
    style_categories: QgsMapLayer.StyleCategory
    include_metadata: bool
    keep_empty_layers: bool
    deduplicate: bool
    stage_providers: frozenset[str]
    export_full: bool
    generate_report: bool
    write_checksums: bool
    extra_dir: Path | None
    warm_dir: Path | None
    use_warm: bool
    update_warm: bool
    full_package_path: str
    dry_run: bool


@dataclass
class _LayerPrep:
    """Phase-A material of one packaged vector layer."""

    layer: QgsVectorLayer
    """The user's layer (styles, names, the embedded-project source); never read for data."""

    table: str
    plan: LayerMatchPlan
    read_layer: QgsVectorLayer
    """The standalone layer the per-stratum write reads and selects from — a clone of
    :attr:`layer`, or a layer over the staging/full-package gpkg. Never a project layer, so
    its selection is mutated freely."""

    kept_fields: tuple[str, ...]
    """Exported field names after exclusions (and the §12 dedup union on a primary)."""

    kept_field_indexes: tuple[int, ...]
    """:attr:`kept_fields` resolved to indexes into ``read_layer.fields()`` (the writer
    drops the rest); empty exports every field."""

    excluded_fields: tuple[str, ...]
    subset_sql: str = ""
    """The original ``subsetString``, re-applied in the embedded project (§12); no longer a
    data filter — per-stratum filtering is the read layer's selection."""

    qml: str = ""
    sld: str = ""
    metadata_xml: str = ""

    staged: bool = False
    """Whether :attr:`read_layer` is a staging copy (§8.2) — set on the group primary (or an
    ungrouped layer); non-primary members read through their primary's staged table."""

    group_primary_id: str | None = None
    """Dedup groups (§12): the primary member's layer id when this prep rides a
    shared table (the primary points at itself); None outside any group."""


@dataclass
class _PayloadPrep:
    """Phase-A material of one whole-export raster/mesh/point-cloud layer (SPEC §14)."""

    layer: QgsMapLayer
    table: str
    members: tuple[tuple[Path, str], ...]
    """``(source file, arcname)`` pairs under ``data/<table>/``."""

    layer_type: str
    """§9.2 token: ``raster`` | ``mesh`` | ``point-cloud``."""

    project_source: str = ""
    """Arcname the embedded project re-points this layer at (§13) and the §9.2
    ``path_in_zip``: the main file, or the copied directory for directory-based sources."""


@dataclass
class _Material:
    """Everything Phase A hands to Phases B/C (one object instead of long params)."""

    project: QgsProject
    inputs: _Inputs
    preps: list[_LayerPrep] = field(default_factory=list)
    payloads: list[_PayloadPrep] = field(default_factory=list)
    assets: dict[str, str] = field(default_factory=dict)
    """Style-asset path -> ``resources/...`` arcname (SPEC §14)."""

    bundles: dict[str, tuple[StratumSpec, ...]] = field(default_factory=dict)
    zip_roots: dict[str, Path] = field(default_factory=dict)
    """Zip path -> its zip-mirror build root."""

    gpkg_paths: dict[str, Path] = field(default_factory=dict)
    """Stratum name -> its gpkg build path (inside its zip root)."""

    zip_of_stratum: dict[str, str] = field(default_factory=dict)
    """Stratum name -> its zip path."""

    warm_marked_ids: set[str] = field(default_factory=set)
    """Layer ids carrying ``warm_marked = true`` (§11)."""

    warm_prefetch: dict[str, Future[bool]] = field(default_factory=dict)
    """Stratum name -> its §11 warm-cache prefetch future (``WARM_START_MODE=use`` runs only):
    ``True`` = the cache already sits at the stratum's build path and the build seeds in
    place; ``False``/absent = seed-time copy from the original cache file."""

    layer_name_expressions: dict[str, str] = field(default_factory=dict)
    """Layer id -> non-empty ``stratified_packager_layer_name`` expression text (SPEC §4),
    snapshotted and parse-validated in Phase A; empty unless an embedded project is built."""

    template_path: Path | None = None
    """The §8.1.5 template gpkg (non-warm-marked whole-export layers), if built."""


@dataclass
class _BuildState:
    """Mutable bookkeeping of the sequential build and the background zip pool."""

    total_units: int
    """Progress units: one per (stratum, layer) write plus one per bundle zip."""

    done_units: int = 0
    succeeded: set[str] = field(default_factory=set)
    failed: dict[str, str] = field(default_factory=dict)
    published: list[str] = field(default_factory=list)
    failed_zips: dict[str, str] = field(default_factory=dict)
    layer_results: dict[tuple[str, str], LayerWriteResult] = field(default_factory=dict)
    """``(stratum name, layer id)`` -> the layer's write outcome (the dedup primary's id)."""

    zip_futures: list[Future[ZipOutcome]] = field(default_factory=list)
    cold_fallbacks: dict[str, str] = field(default_factory=dict)
    matched_union: dict[str, set[int]] = field(default_factory=dict)
    """Dedup-primary layer id -> union of matched fids across strata (§9.1 orphans)."""

    failed_warm: dict[str, str] = field(default_factory=dict)
    """Stratum name -> error of its failed §11 warm-cache write (the deliverable still
    builds — cold — but a requested-yet-unwritten cache fails the run at the end)."""


def _is_warm_marked(layer: QgsMapLayer) -> bool:
    """
    Report whether a layer carries ``stratified_packager_warm_marked = true`` (§11).

    Coerced with the same strict :func:`~stratified_packager.toolbelt.utils.coerce_bool`
    every other boolean layer variable uses (§4/§6 strict regime).

    :param layer: The packaged layer.
    :return: Whether the layer belongs to the warm cache.
    :raise QgsProcessingException: If the variable holds an uncoercible value.
    """
    raw = LayerVariables(layer).get(params.LAYER_VAR_WARM_MARKED)
    text = "" if raw is None else str(raw).strip()
    if not text:
        return False
    try:
        return coerce_bool(text)
    except ValueError as err:
        raise QgsProcessingException(
            QCoreApplication.translate(
                "StratifiedPackagerAlgorithm", "layer {}: warm_marked variable {}"
            ).format(layer.name(), err)
        ) from err


def _field_indexes(layer: QgsVectorLayer, names: Collection[str]) -> tuple[int, ...]:
    """
    Resolve field *names* to their indexes in *layer*, in field order.

    :param layer: The layer whose schema is indexed.
    :param names: The field names to keep.
    :return: The matching indexes in field order (an empty tuple keeps every field).
    """
    wanted = set(names)
    return tuple(
        index
        for index, field_def in enumerate(layer.fields().toList())
        if field_def.name() in wanted
    )


def _warm_file_name(stratum_name: str) -> str:
    """
    Map a stratum key to its warm-cache file basename (§11).

    :param stratum_name: The sanitized stratum name, or ``<full>``.
    :return: The basename without extension (``__full__`` for the full package, whose
        key contains characters that are not legal in filenames).
    """
    return "__full__" if stratum_name == FULL_PACKAGE_KEY else stratum_name
