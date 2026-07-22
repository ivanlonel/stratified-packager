"""
QGIS-side assembly of the §9 report rows (run-level and per-zip).

Folds the build outcomes held in :class:`~.material._BuildState` into the row dataclasses
of :mod:`~.report` (which stays ``qgis``-free — it only defines the rows and writes the
CSV). Orphan accounting (§9.1) also lives here. Runs on the algorithm thread; user-facing
warnings flow through the feedback.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from qgis.core import Qgis
from qgis.PyQt.QtCore import QCoreApplication

from . import params
from .report import (
    STATUS_COLD_FALLBACK,
    STATUS_EMPTY_SKIPPED,
    STATUS_FAILED,
    STATUS_OK,
    UNMATCHED_KEY,
    RunReportRow,
    ZipReportRow,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from qgis.core import QgsProcessingFeedback

    from .building import LayerWriteResult
    from .material import _BuildState, _LayerPrep, _Material
    from .strata import StratumSpec

__all__: list[str] = [
    "account_orphans",
    "collect_report_rows",
    "outcome_for",
    "zip_report_rows",
]


def outcome_for(
    state: _BuildState, stratum_name: str, prep: _LayerPrep
) -> LayerWriteResult | None:
    """
    Look up a layer's outcome, following the dedup-primary indirection (§12).

    :param state: The pool state.
    :param stratum_name: The stratum.
    :param prep: The (possibly non-primary) member prep.
    :return: The outcome of the prep's own job, or of its group primary's.
    """
    own = state.layer_results.get((stratum_name, prep.layer.id()))
    if own is not None or prep.group_primary_id is None:
        return own
    return state.layer_results.get((stratum_name, prep.group_primary_id))


def zip_report_rows(
    material: _Material,
    members: Sequence[StratumSpec],
    state: _BuildState,
) -> list[ZipReportRow]:
    """
    Build the §9.2 rows of one bundle (vector tables + payload entries).

    :param material: The run material.
    :param members: The bundle's successful members.
    :param state: The pool state.
    :return: The rows, member-major.
    """
    rows: list[ZipReportRow] = []
    for member in members:
        for prep in material.preps:
            outcome = outcome_for(state, member.name, prep)
            rows.append(
                ZipReportRow(
                    stratum=member.name,
                    layer_name=prep.layer.name(),
                    gpkg_table=outcome.table if outcome else "",
                    path_in_zip=f"{member.gpkg_rel}.gpkg" if outcome else "",
                    layer_type="vector",
                    geometry_type=(
                        Qgis.GeometryType(prep.layer.geometryType()).name
                        if prep.layer.isSpatial()
                        else ""
                    ),
                    feature_count=outcome.feature_count if outcome else None,
                    field_count=len(prep.kept_fields),
                    excluded_fields=";".join(prep.excluded_fields),
                    matching_method=prep.plan.method.value,
                    match_detail=(
                        " > ".join(h.edge.relation_id for h in prep.plan.chain)
                        if prep.plan.method is params.MatchingMethod.ATTRIBUTE
                        else ", ".join(prep.plan.predicates)
                    ),
                    source_crs=prep.layer.crs().authid(),
                    status=outcome.status if outcome else STATUS_OK,
                )
            )
        rows.extend(
            ZipReportRow(
                stratum=member.name,
                layer_name=payload.layer.name(),
                path_in_zip=payload.project_source,
                layer_type=payload.layer_type,
                matching_method=params.MatchingMethod.WHOLE_EXPORT.value,
                source_crs=payload.layer.crs().authid(),
            )
            for payload in material.payloads
        )
    return rows


def collect_report_rows(
    strata: Sequence[StratumSpec],
    material: _Material,
    state: _BuildState,
    report_rows: list[RunReportRow],
) -> None:
    """
    Fold worker outcomes into the §9.1 run-report rows.

    :param strata: The surviving strata.
    :param material: The run material.
    :param state: The pool state.
    :param report_rows: Mutable run-report rows.
    """
    for stratum in strata:
        for prep in material.preps:
            outcome = outcome_for(state, stratum.name, prep)
            if stratum.name in state.failed:
                report_rows.append(
                    RunReportRow(
                        stratum=stratum.name,
                        layer=prep.layer.name(),
                        status=STATUS_FAILED,
                        detail=state.failed[stratum.name],
                    )
                )
            elif outcome is not None:
                fallback = state.cold_fallbacks.get(stratum.name, "")
                cold = bool(fallback) and prep.layer.id() in material.warm_marked_ids
                report_rows.append(
                    RunReportRow(
                        stratum=stratum.name,
                        layer=prep.layer.name(),
                        feature_count=outcome.feature_count,
                        status=STATUS_COLD_FALLBACK if cold else outcome.status,
                        detail=fallback if cold else "",
                    )
                )
            else:
                report_rows.append(
                    RunReportRow(
                        stratum=stratum.name,
                        layer=prep.layer.name(),
                        feature_count=0,
                        status=STATUS_EMPTY_SKIPPED,
                    )
                )
        report_rows.extend(
            RunReportRow(
                stratum=stratum.name,
                layer=payload.layer.name(),
                status=(STATUS_FAILED if stratum.name in state.failed else STATUS_OK),
                detail=state.failed.get(stratum.name, ""),
            )
            for payload in material.payloads
        )


def account_orphans(
    material: _Material,
    state: _BuildState,
    report_rows: list[RunReportRow],
    feedback: QgsProcessingFeedback,
) -> None:
    """
    Count features matching no stratum, per partitioned (primary) layer (§9.1).

    Run after the build: the read source's feature count minus the union of every
    stratum's matched fids (accumulated during writing). A staged read source normally
    holds only the matched union, so it reports zero — correct for the data actually
    packaged; under ``EXPORT_FULL_PACKAGE`` it instead holds every feature (§8.2), so the
    true orphan count surfaces (those features ship in the ``<full>`` package).

    :param material: The run material.
    :param state: The build state (carries the per-layer matched-fid unions).
    :param report_rows: Mutable run-report rows.
    :param feedback: Execution feedback channel.
    """
    for prep in material.preps:
        if prep.plan.method is params.MatchingMethod.WHOLE_EXPORT or prep.group_primary_id not in (
            None,
            prep.layer.id(),
        ):
            continue
        if material.inputs.use_warm and prep.layer.id() in material.warm_marked_ids:
            # Warm-seeded strata report no matched fids (§11), so the union is
            # unknowable here — stay silent rather than counting every feature as an
            # orphan. (UPDATE runs are exact: the warm pass folds the fids in.)
            continue
        matched = state.matched_union.get(prep.layer.id(), set())
        orphans = prep.read_layer.featureCount() - len(matched)
        if orphans > 0:
            feedback.pushWarning(
                QCoreApplication.translate(
                    "StratifiedPackagerAlgorithm",
                    "Layer {}: %n feature(s) match no stratum.",
                    None,
                    orphans,
                ).format(prep.layer.name())
            )
            report_rows.append(
                RunReportRow(
                    stratum=UNMATCHED_KEY,
                    layer=prep.layer.name(),
                    feature_count=orphans,
                    status=STATUS_OK,
                    detail="features matching no stratum",
                )
            )
