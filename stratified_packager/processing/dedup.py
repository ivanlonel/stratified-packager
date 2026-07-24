"""
Deduplication of packaged layers sharing one normalized data source (SPEC §12).

Groups packaged vector layers by their provider + normalized ``decodeUri`` components, merges
each group onto a primary member (whose table hosts the union of every member's matches and
kept fields), and extends warm marking across a shared table. Runs on the algorithm thread
during Phase A; all user-facing messaging flows through the passed feedback.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from qgis.core import QgsProviderRegistry
from qgis.PyQt.QtCore import QCoreApplication

from stratified_packager.toolbelt.sql import sqlite_where_error

from . import params
from .matching import LayerMatchPlan
from .material import _field_indexes

if TYPE_CHECKING:
    from qgis.core import QgsProcessingFeedback, QgsVectorLayer

    from .material import _LayerPrep, _Material

__all__: list[str] = [
    "apply_dedup",
    "normalized_source_key",
    "promote_warm_groups",
    "source_group_key",
]


def apply_dedup(material: _Material, feedback: QgsProcessingFeedback) -> None:
    """
    Fold layers sharing one normalized data source into dedup groups (§12).

    The first unfiltered member in tree order becomes the primary (the first member
    when every member is filtered): its table hosts the union of every member's match
    set and kept fields (always including the columns each member's subset references).
    Runs before staging, so a staged group builds **one** staging copy through its primary
    instead of one per member (§8.2). A member whose subset is not portable to the delivered
    GeoPackage (it references tables or functions absent from it) is excluded from grouping and
    staged standalone, so its filter is materialized on the source provider rather than
    re-applied against a shared table it could never evaluate.

    :param material: The run material (preps mutated in place).
    :param feedback: Execution feedback channel.
    """
    if not material.inputs.deduplicate:
        return
    groups: dict[tuple[str, frozenset[tuple[str, str]]], list[_LayerPrep]] = {}
    for prep in material.preps:
        if (
            prep.subset_sql
            and sqlite_where_error(
                [field.name() for field in prep.layer.fields().toList()], prep.subset_sql
            )
            is not None
        ):
            # A subset the delivered GeoPackage cannot evaluate (external tables, non-SQLite
            # functions like lpad) can never be re-applied there to recover this member's view
            # (§12), so folding it onto a shared table would strand it. Keep it standalone —
            # staging then materializes the filter on the source provider instead.
            feedback.pushInfo(
                QCoreApplication.translate(
                    "StratifiedPackagerAlgorithm",
                    "Layer {} is not deduplicated: its subset must run on the source provider,"
                    " not the GeoPackage, so it keeps its own staged copy.",
                ).format(prep.layer.name())
            )
            continue
        key = source_group_key(prep.layer, feedback)
        if key is not None:
            groups.setdefault(key, []).append(prep)
    for members in groups.values():
        if len(members) == 1:
            continue
        _merge_group(members, feedback)


def _merge_group(members: list[_LayerPrep], feedback: QgsProcessingFeedback) -> None:
    """
    Merge one dedup group onto its primary member (§12).

    :param members: The group, in tree order (the first unfiltered member — else the
        first — becomes the primary).
    :param feedback: Execution feedback channel.
    """
    # §12: prefer an unfiltered member's name for the shared table — it better
    # represents the whole union; fall back to first-in-tree-order when all are filtered.
    primary = next((m for m in members if not m.subset_sql), members[0])
    feedback.pushInfo(
        QCoreApplication.translate(
            "StratifiedPackagerAlgorithm", "Deduplicating shared source into table {}: {}"
        ).format(primary.table, ", ".join(m.layer.name() for m in members))
    )
    kept: list[str] = []
    for member in members:
        for name in (
            *member.kept_fields,
            *_subset_columns(member.subset_sql, member.layer),
        ):
            if name not in kept:
                kept.append(name)
    primary.kept_fields = tuple(kept)
    # The shared table holds the union of every member's match set, so the primary reads
    # the full source: clear its subset (the embedded project re-applies each member's
    # own subset to restore exact views, §12).
    if not primary.read_layer.setSubsetString(""):
        feedback.pushWarning(
            QCoreApplication.translate(
                "StratifiedPackagerAlgorithm", "Could not clear the subset of shared table {}."
            ).format(primary.table)
        )
    primary.kept_field_indexes = _field_indexes(primary.read_layer, kept)
    # Only the *read layer's* subset is dropped, never the prep's record of it: when every member
    # is filtered the primary is a filtered member too, and the embedded project has to restore
    # its own view from the union like any other member (§12).
    if any(member.plan.method is params.MatchingMethod.WHOLE_EXPORT for member in members):
        primary.plan = LayerMatchPlan(
            layer_id=primary.layer.id(), method=params.MatchingMethod.WHOLE_EXPORT
        )
    for member in members:
        member.table = primary.table
        member.group_primary_id = primary.layer.id()


def promote_warm_groups(material: _Material, feedback: QgsProcessingFeedback) -> None:
    """
    Extend warm marking to whole dedup groups (§11/§12).

    Warm marking is effectively per exported *table*, and a dedup group shares one
    table: either it rides the warm cache or it does not. The §11 machinery caches
    only group primaries, so a mark on a non-primary member alone would otherwise
    vanish silently — promote the whole group instead.

    :param material: The run material (dedup already applied).
    :param feedback: Execution feedback channel.
    """
    groups: dict[str, list[_LayerPrep]] = {}
    for prep in material.preps:
        if prep.group_primary_id is not None:
            groups.setdefault(prep.group_primary_id, []).append(prep)
    for members in groups.values():
        ids = {prep.layer.id() for prep in members}
        marked = ids & material.warm_marked_ids
        if marked and ids - material.warm_marked_ids:
            material.warm_marked_ids |= ids
            feedback.pushInfo(
                QCoreApplication.translate(
                    "StratifiedPackagerAlgorithm",
                    "Shared table {} is warm-marked through {}; every member of the"
                    " dedup group follows.",
                ).format(
                    members[0].table,
                    ", ".join(prep.layer.name() for prep in members if prep.layer.id() in marked),
                )
            )


def source_group_key(
    layer: QgsVectorLayer,
    feedback: QgsProcessingFeedback,
) -> tuple[str, frozenset[tuple[str, str]]] | None:
    """
    Build the §12 dedup group key: provider + normalized ``decodeUri`` components.

    :param layer: The packaged layer.
    :param feedback: Execution feedback channel.
    :return: The hashable key, or :data:`None` when the source cannot be decoded.
    """
    return normalized_source_key(layer.providerType(), layer.source(), layer.name(), feedback)


def normalized_source_key(
    provider_type: str,
    source: str,
    label: str,
    feedback: QgsProcessingFeedback,
) -> tuple[str, frozenset[tuple[str, str]]] | None:
    """
    Normalize a provider/source pair into the §12 dedup group key.

    Path-typed components are resolved and case-folded (``decodeUri`` does neither) and
    identifier quoting is stripped.

    :param provider_type: The provider key (e.g. ``ogr``, ``postgres``).
    :param source: The provider source uri.
    :param label: A human label for debug messages (typically the layer name).
    :param feedback: Execution feedback channel.
    :return: The hashable key, or :data:`None` when the source cannot be decoded.
    """
    registry = QgsProviderRegistry.instance()
    if registry is None:
        return None
    decoded = registry.decodeUri(provider_type, source)
    if not decoded:
        return None
    items: list[tuple[str, str]] = []
    for key, value in decoded.items():
        if value is None or value == "" or key == "subset":
            # A subset is a per-layer view over the same data source (§12 unions the
            # member views); it must not split the group.
            continue
        text = str(value)
        if key.lower().endswith("path") or key.lower() == "path":
            try:
                text = os.path.normcase(str(Path(text).resolve()))
            except (OSError, ValueError) as err:
                # Acceptable: an unresolvable path keys on its raw form, which can split a
                # dedup group (a layer written twice) but never corrupts output.
                feedback.pushDebugInfo(
                    f"dedup[{label}]: cannot resolve {text!r} ({err}); "
                    "grouping on the unresolved path"
                )
        items.append((key, text.strip('"')))
    return provider_type, frozenset(items)


def _subset_columns(subset_sql: str, layer: QgsVectorLayer) -> list[str]:
    """
    Name the layer fields referenced by a subset string (§12 kept-field rule).

    A pragmatic identifier scan: a field counts as referenced when it appears quoted
    or as a standalone word inside the subset SQL.

    :param subset_sql: The provider-native subset SQL (possibly empty).
    :param layer: The layer whose field names are scanned for.
    :return: The referenced field names, in field order.
    """
    if not subset_sql:
        return []
    import re  # noqa: PLC0415  # tiny, single-use

    found: list[str] = []
    for field_def in layer.fields().toList():
        name = field_def.name()
        pattern = rf'(?:"{re.escape(name)}"|\b{re.escape(name)}\b)'
        if re.search(pattern, subset_sql, flags=re.IGNORECASE):
            found.append(name)
    return found
