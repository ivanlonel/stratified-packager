"""
The matching engine: method resolution, relation-chain keys, spatial fid sets (SPEC §4/§7).

Runs on the algorithm thread during Phase A. Provider pushdown where it pays: relation hops
query intermediates with C++-evaluated ``IN`` filter expressions (chunked, NULL keys never
match); spatial candidates pass through the provider's spatial index (``setFilterRect``), then a
prepared :class:`~qgis.core.QgsGeometryEngine` over the stratum geometry tests each candidate
(prepared once per pair, so the polygon is never re-analysed per feature; never inlined WKT).

All user-facing messaging flows through the :class:`~qgis.core.QgsProcessingFeedback`
passed by the caller; fatal conditions raise :exc:`~qgis.core.QgsProcessingException`.
"""

from __future__ import annotations

import json
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, cast

from qgis.core import (
    Qgis,
    QgsCoordinateTransform,
    QgsExpression,
    QgsFeatureRequest,
    QgsGeometry,
    QgsProcessingException,
    QgsVariantUtils,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QCoreApplication

from stratified_packager.toolbelt.relations import (
    RelationGraph,
    all_shortest_paths,
    validate_pinned_path,
)
from stratified_packager.toolbelt.settings import LayerVariables

from .params import (
    DE9IM_PATTERN,
    LAYER_VAR_MATCHING_METHOD,
    LAYER_VAR_RELATION_PATH,
    LAYER_VAR_SPATIAL_PREDICATE,
    NAMED_SPATIAL_PREDICATES,
    MatchingMethod,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

    from qgis.core import (
        QgsFeature,
        QgsGeometryEngine,
        QgsProcessingFeedback,
        QgsProject,
        QgsVectorLayer,
    )

    from stratified_packager.toolbelt.relations import RelationPath

__all__: list[str] = [
    "DE9IM_PATTERN",
    "INTERIORS_INTERSECT",
    "ChainContext",
    "LayerMatchPlan",
    "MatchCondition",
    "attribute_keys_for_stratum",
    "in_filter_expressions",
    "resolve_layer_methods",
    "spatial_fids_for_stratum",
    "stratum_geometry_in_layer_crs",
]

INTERIORS_INTERSECT: Final = "T********"
"""The ``spatial_predicate = auto`` pattern when neither side is point- or line-like."""

_NAMED_PREDICATES: Final[frozenset[str]] = frozenset(NAMED_SPATIAL_PREDICATES)
"""Named predicates mapping 1:1 onto QGIS expression functions (SPEC §4)."""

_KEY_CHUNK: Final = 1_000
"""Values (or key tuples) per ``IN`` chunk in intermediate hop queries (SPEC §7.1)."""


def _check_canceled(feedback: QgsProcessingFeedback) -> None:
    """
    Raise the standard cancellation error when the run was canceled.

    Called at the top of the hot per-feature loops (hop queries, spatial candidate
    tests) so a cancellation interrupts a large layer mid-scan.

    :param feedback: Execution feedback channel.
    :raise QgsProcessingException: If cancellation was requested.
    """
    if feedback.isCanceled():
        raise QgsProcessingException(
            QCoreApplication.translate("MatchingEngine", "Operation was canceled.")
        )


# ---------------------------------------------------------------------------
# Plans & conditions (plain data)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LayerMatchPlan:
    """The resolved matching strategy of one packaged, partitioned vector layer."""

    layer_id: str
    """The layer's id."""

    method: MatchingMethod
    """The resolved method — never :attr:`~.params.MatchingMethod.AUTO`."""

    chain: RelationPath = ()
    """Attribute matching: hops ordered **stratification layer → packaged layer**."""

    predicates: tuple[str, ...] = ()
    """Spatial matching: the resolved predicate tokens (named or DE-9IM), combined with OR."""

    pinned: bool = False
    """Whether the chain came from a ``relation_path`` pin."""


@dataclass(frozen=True)
class MatchCondition:
    """What one (layer, stratum) pair must satisfy — plain data for worker payloads."""

    key_fields: tuple[str, ...] = ()
    """Attribute matching: the target layer's key fields."""

    keys: tuple[tuple[object, ...], ...] = ()
    """Attribute matching: the matching key tuples (NULL-free)."""

    fids: tuple[int, ...] = ()
    """Spatial (or self) matching: the matching feature ids."""

    by_fid: bool = False
    """Whether :attr:`fids` (rather than the key columns) define membership."""


type HopMemoKey = tuple[RelationPath, tuple[str, ...], tuple[object, ...]]
"""A memoized hop's identity: the chain prefix walked so far, the fields the arrival hop
collects, and the stratum's starting key tuple (SPEC §7.1)."""

_CHAIN_MEMO_CAPACITY: Final = 64
"""Hop resolutions :class:`ChainContext` keeps (SPEC §7.1). Phase B resolves one stratum against
every layer before moving on, and layers sharing a chain prefix share these entries, so a small
memo captures nearly every hit while holding far less than every stratum's key sets.
ponytail: Phase A calls :func:`~.building.stage_union` once per staged *group*, sweeping all
strata inside each — so its cross-group reuse would need one entry per prefix per stratum and
does not fit here. Raise the cap only if a profile shows Phase A's hop queries actually
dominate."""


@dataclass
class ChainContext:
    """
    Per-run relation-chain resolution context: staged hop layers plus a bounded key memo (§7.1).

    Resolving a chain is a pure function of the hops walked and the stratum's starting key values
    — the run never reads a project layer for anything else and never mutates one (§8.1) — so the
    same :data:`HopMemoKey` always yields the same key set. Memoizing per **hop prefix** rather
    than per whole chain is what makes that pay: packaged layers rarely share a chain outright,
    but many share its leading hops and diverge only at the final, layer-specific relation, so a
    whole-chain key collides for none of them while a prefix key collides for all.

    Held per run and passed explicitly down the build call chain, never module-side, so nothing
    shares mutable state between runs.
    """

    hop_layers: dict[str, QgsVectorLayer] = field(default_factory=dict)
    """Intermediate hop layer id -> its staged local copy (§8.2); ids absent from the map
    resolve against the project, as they always did."""

    capacity: int = _CHAIN_MEMO_CAPACITY
    """Memo entries kept before the least-recently-used one is evicted; ``0`` disables
    memoization (every resolution queries the hops)."""

    hits: int = field(default=0, init=False)
    """Hop resolutions served from the memo."""

    misses: int = field(default=0, init=False)
    """Hop resolutions that had to query the arrival layer."""

    _memo: OrderedDict[HopMemoKey, frozenset[tuple[object, ...]]] = field(
        default_factory=OrderedDict, init=False, repr=False
    )

    def hop_layer(self, layer_id: str, project: QgsProject) -> QgsVectorLayer | None:
        """
        Resolve one hop's target layer, preferring its staged local copy (§8.2).

        :param layer_id: The hop's arrival layer id.
        :param project: The run's project (the fallback lookup).
        :return: The staged copy, the project layer, or :data:`None` when neither exists.
        """
        staged = self.hop_layers.get(layer_id)
        if staged is not None:
            return staged
        return cast("QgsVectorLayer | None", project.mapLayer(layer_id))

    def get(self, key: HopMemoKey) -> frozenset[tuple[object, ...]] | None:
        """
        Look one hop resolution up, refreshing its recency on a hit.

        :param key: The hop's identity.
        :return: The memoized key set, or :data:`None` when not memoized.
        """
        keys = self._memo.get(key)
        if keys is None:
            self.misses += 1
            return None
        self._memo.move_to_end(key)
        self.hits += 1
        return keys

    def put(self, key: HopMemoKey, keys: frozenset[tuple[object, ...]]) -> None:
        """
        Memoize one hop resolution, evicting the least recently used entries past capacity.

        :param key: The hop's identity.
        :param keys: The key set the hop's query produced.
        """
        self._memo[key] = keys
        self._memo.move_to_end(key)
        while len(self._memo) > self.capacity:
            self._memo.popitem(last=False)


# ---------------------------------------------------------------------------
# §4 — per-layer method resolution
# ---------------------------------------------------------------------------


def resolve_layer_methods(
    layers: Sequence[QgsVectorLayer],
    strat_layer: QgsVectorLayer,
    graph: RelationGraph,
    feedback: QgsProcessingFeedback,
) -> dict[str, LayerMatchPlan]:
    """
    Resolve every partitioned vector layer's matching method (SPEC §4).

    Errors are aggregated so the user sees every misconfigured layer at once.

    :param layers: The packaged, partitioned vector layers.
    :param strat_layer: The stratification layer.
    :param graph: The project relation graph.
    :param feedback: Execution feedback channel.
    :return: One plan per layer id.
    :raise QgsProcessingException: Listing every layer whose method cannot be resolved
        (no path and no geometry, ambiguous chains without a pin, invalid pins or
        predicate tokens).
    """
    plans: dict[str, LayerMatchPlan] = {}
    errors: list[str] = []
    for layer in layers:
        try:
            plans[layer.id()] = _resolve_one(layer, strat_layer, graph, feedback)
        except QgsProcessingException as err:  # aggregation is the point
            errors.append(str(err))
    if errors:
        raise QgsProcessingException(
            QCoreApplication.translate(
                "MatchingEngine", "Matching cannot be resolved:\n- {}"
            ).format("\n- ".join(errors))
        )
    return plans


def _resolve_one(
    layer: QgsVectorLayer,
    strat_layer: QgsVectorLayer,
    graph: RelationGraph,
    feedback: QgsProcessingFeedback,
) -> LayerMatchPlan:
    """
    Resolve one layer's plan.

    :param layer: The packaged layer.
    :param strat_layer: The stratification layer.
    :param graph: The relation graph.
    :param feedback: Execution feedback channel.
    :return: The plan.
    :raise QgsProcessingException: Per the §4 rules.
    """
    variables = LayerVariables(layer)
    raw_method = str(variables.get(LAYER_VAR_MATCHING_METHOD) or MatchingMethod.AUTO.value)
    try:
        method = MatchingMethod(raw_method.strip().lower())
    except ValueError as err:
        raise QgsProcessingException(
            QCoreApplication.translate(
                "MatchingEngine", "layer {}: invalid matching_method {}"
            ).format(layer.name(), raw_method)
        ) from err

    if method is MatchingMethod.WHOLE_EXPORT:
        return LayerMatchPlan(layer_id=layer.id(), method=method)

    pin_raw = variables.get(LAYER_VAR_RELATION_PATH)
    paths = all_shortest_paths(graph, layer.id(), strat_layer.id())

    if method is MatchingMethod.AUTO:
        if paths:
            method = MatchingMethod.ATTRIBUTE
        elif layer.isSpatial() and strat_layer.isSpatial():
            method = MatchingMethod.SPATIAL
        else:
            raise QgsProcessingException(
                QCoreApplication.translate(
                    "MatchingEngine",
                    "layer {}: no relation path to the stratification layer and no"
                    " geometry on both sides; add a relation, set matching_method ="
                    " whole_export, exclude the layer, or give the stratification"
                    " layer geometry",
                ).format(layer.name())
            )

    if method is MatchingMethod.ATTRIBUTE:
        chain = _resolve_chain(layer, strat_layer, graph, paths, pin_raw)
        feedback.pushDebugInfo(
            f"matching[{layer.name()}]: attribute via "
            + (" > ".join(hop.edge.relation_id for hop in chain) or "<same layer>")
        )
        return LayerMatchPlan(
            layer_id=layer.id(),
            method=method,
            chain=chain,
            pinned=pin_raw is not None and str(pin_raw) != "",
        )

    # Spatial.
    if not layer.isSpatial() or not strat_layer.isSpatial():
        raise QgsProcessingException(
            QCoreApplication.translate(
                "MatchingEngine",
                "layer {}: matching_method = spatial requires geometry on both the"
                " layer and the stratification layer",
            ).format(layer.name())
        )
    predicates = _resolve_predicates(
        layer, strat_layer, str(variables.get(LAYER_VAR_SPATIAL_PREDICATE) or "auto")
    )
    feedback.pushDebugInfo(f"matching[{layer.name()}]: spatial via {' OR '.join(predicates)}")
    return LayerMatchPlan(layer_id=layer.id(), method=method, predicates=predicates)


def _resolve_chain(
    layer: QgsVectorLayer,
    strat_layer: QgsVectorLayer,
    graph: RelationGraph,
    paths: list[RelationPath],
    pin_raw: object,
) -> RelationPath:
    """
    Pick the relation chain: a valid pin wins; else the unique shortest path.

    The returned hops run **stratification layer → packaged layer** (propagation order);
    pins are given in the opposite, layer-→-strat order (SPEC §4) and are reversed here.

    :param layer: The packaged layer.
    :param strat_layer: The stratification layer.
    :param graph: The relation graph.
    :param paths: The precomputed shortest paths (layer → strat direction).
    :param pin_raw: The raw ``relation_path`` variable value (JSON list or unset).
    :return: The chain in propagation order.
    :raise QgsProcessingException: On invalid pins, no path, or unpinned ambiguity.
    """
    if pin_raw is not None and str(pin_raw) != "":
        try:
            pinned_ids = json.loads(str(pin_raw))
        except json.JSONDecodeError as err:
            raise QgsProcessingException(
                QCoreApplication.translate(
                    "MatchingEngine", "layer {}: relation_path is not a JSON list: {}"
                ).format(layer.name(), err)
            ) from err
        if not isinstance(pinned_ids, list) or not all(
            isinstance(item, str) for item in pinned_ids
        ):
            raise QgsProcessingException(
                QCoreApplication.translate(
                    "MatchingEngine", "layer {}: relation_path must be a JSON list of relation ids"
                ).format(layer.name())
            )
        try:
            pinned = validate_pinned_path(graph, layer.id(), strat_layer.id(), pinned_ids)
        except ValueError as err:
            raise QgsProcessingException(
                QCoreApplication.translate(
                    "MatchingEngine", "layer {}: invalid relation_path pin: {}"
                ).format(layer.name(), err)
            ) from err
        return tuple(hop.reversed() for hop in reversed(pinned))

    if not paths:
        raise QgsProcessingException(
            QCoreApplication.translate(
                "MatchingEngine",
                "layer {}: matching_method = attribute but no relation path reaches"
                " the stratification layer",
            ).format(layer.name())
        )
    if len(paths) > 1:
        rendered = "; ".join(" > ".join(hop.edge.relation_id for hop in path) for path in paths)
        raise QgsProcessingException(
            QCoreApplication.translate(
                "MatchingEngine",
                "layer {}: multiple shortest relation paths ({}); set the layer's"
                " relation_path variable to pin one",
            ).format(layer.name(), rendered)
        )
    return tuple(hop.reversed() for hop in reversed(paths[0]))


def _resolve_predicates(
    layer: QgsVectorLayer, strat_layer: QgsVectorLayer, raw: str
) -> tuple[str, ...]:
    """
    Resolve the ``spatial_predicate`` value to a tuple of predicates (SPEC §4).

    The value is a comma-separated list whose tokens combine additively (OR). Each token is a
    named predicate or a 9-character DE-9IM pattern (the T/F case-insensitive, normalized to
    uppercase). The sole token ``auto`` expands by geometry type (:func:`_auto_predicates`) and
    cannot be combined with other tokens.

    :param layer: The packaged layer.
    :param strat_layer: The stratification layer.
    :param raw: The raw value (``auto``, or a comma-separated list of named predicates and
        DE-9IM patterns).
    :return: The resolved predicates, de-duplicated in input order.
    :raise QgsProcessingException: On an unrecognized token, or ``auto`` combined with others.
    """
    tokens = [token.strip() for token in raw.split(",") if token.strip()]
    if not tokens:
        return _auto_predicates(layer, strat_layer)
    if any(token.lower() == "auto" for token in tokens):
        if len(tokens) > 1:
            raise QgsProcessingException(
                QCoreApplication.translate(
                    "MatchingEngine",
                    "layer {}: spatial_predicate 'auto' cannot be combined with other predicates",
                ).format(layer.name())
            )
        return _auto_predicates(layer, strat_layer)
    resolved: list[str] = []
    for token in tokens:
        if token.lower() in _NAMED_PREDICATES:
            resolved.append(token.lower())
        elif DE9IM_PATTERN.match(token):
            resolved.append(token.upper())
        else:
            raise QgsProcessingException(
                QCoreApplication.translate(
                    "MatchingEngine", "layer {}: invalid spatial_predicate token {!r}"
                ).format(layer.name(), token)
            )
    return tuple(dict.fromkeys(resolved))


def _auto_predicates(layer: QgsVectorLayer, strat_layer: QgsVectorLayer) -> tuple[str, ...]:
    """
    Expand ``spatial_predicate = auto`` to its predicate tuple by geometry type (SPEC §4).

    With the layer feature as geometry *a* and the stratum as geometry *b*: a polygon stratum
    against a line layer (or the reverse) defaults to "interiors intersect, OR the line runs
    along the polygon boundary (dimension 1)"; a point on either side falls back to plain
    ``intersects``; otherwise the interiors must intersect.

    :param layer: The packaged layer (geometry *a*).
    :param strat_layer: The stratification layer (geometry *b*).
    :return: One or two resolved tokens (a named predicate or a DE-9IM pattern).
    """
    layer_type = QgsWkbTypes.geometryType(layer.wkbType())
    strat_type = QgsWkbTypes.geometryType(strat_layer.wkbType())
    if Qgis.GeometryType.Point in (layer_type, strat_type):
        return ("intersects",)
    if strat_type is Qgis.GeometryType.Polygon and layer_type is Qgis.GeometryType.Line:
        return (INTERIORS_INTERSECT, "*1*******")
    if strat_type is Qgis.GeometryType.Line and layer_type is Qgis.GeometryType.Polygon:
        return (INTERIORS_INTERSECT, "***1*****")
    if Qgis.GeometryType.Line in (layer_type, strat_type):
        return ("intersects",)
    return (INTERIORS_INTERSECT,)


# ---------------------------------------------------------------------------
# §7.1 — attribute key propagation
# ---------------------------------------------------------------------------


def attribute_keys_for_stratum(
    plan: LayerMatchPlan,
    stratum_feature: QgsFeature,
    stratum_name: str,
    project: QgsProject,
    feedback: QgsProcessingFeedback,
    *,
    chain_context: ChainContext | None = None,
) -> MatchCondition:
    """
    Propagate the stratum's keys along the chain to the target layer (SPEC §7.1).

    Each hop queries the next layer with chunked, C++-evaluated ``IN`` filters,
    honoring that layer's ``subsetString`` (selections on intermediates are ignored
    by construction — the request reads the layer, not its selection). NULL keys never
    match. The final hop's far-side key set becomes the membership condition.

    With a *chain_context*, a hop already walked for this stratum under the same chain prefix is
    answered from its memo instead of re-queried, and hops whose layer was staged read the local
    copy.

    :param plan: The layer's attribute plan (chain in strat → layer order).
    :param stratum_feature: The stratum feature.
    :param stratum_name: The resolved stratum name (for feedback only).
    :param project: The project (resolves intermediate layers by id).
    :param feedback: Execution feedback channel.
    :param chain_context: The run's chain context (staged hop layers + memo); :data:`None`
        resolves every chain from the project, unmemoized.
    :return: The membership condition; for an empty chain (the layer *is* the
        stratification layer) a single-fid condition.
    :raise QgsProcessingException: If an intermediate layer of the chain is missing,
        or on cancellation during a hop query.
    """
    if not plan.chain:
        return MatchCondition(fids=(stratum_feature.id(),), by_fid=True)

    start = tuple(stratum_feature.attribute(name) for name in plan.chain[0].from_fields)
    return _propagate_chain(plan, start, stratum_name, project, feedback, chain_context)


def _propagate_chain(
    plan: LayerMatchPlan,
    start: tuple[object, ...],
    stratum_name: str,
    project: QgsProject,
    feedback: QgsProcessingFeedback,
    chain_context: ChainContext | None,
) -> MatchCondition:
    """
    Walk the chain's hops, propagating *start* to the target layer's key set (SPEC §7.1).

    Each intermediate hop's outgoing key set is memoized on *chain_context* under the prefix that
    produced it, so a later chain sharing those leading hops walks them for free.

    :param plan: The layer's attribute plan (non-empty chain).
    :param start: The stratum's starting key tuple.
    :param stratum_name: The resolved stratum name (for feedback only).
    :param project: The project (resolves intermediate layers by id).
    :param feedback: Execution feedback channel.
    :param chain_context: The run's chain context, or :data:`None`.
    :return: The membership condition.
    :raise QgsProcessingException: If an intermediate layer of the chain is missing,
        or on cancellation during a hop query.
    """
    keys: set[tuple[object, ...]] = set()
    # NULL keys never match (SPEC §7). feature.attribute() returns Python None on PyQt6 but a
    # QVariant null on PyQt5, so detect both via QgsVariantUtils.isNull rather than `is None`.
    if all(not QgsVariantUtils.isNull(value) for value in start):
        keys.add(start)

    for hop_index, hop in enumerate(plan.chain):
        if not keys:
            return MatchCondition(key_fields=tuple(plan.chain[-1].to_fields))
        target = (
            chain_context.hop_layer(hop.to_layer_id, project)
            if chain_context is not None
            else project.mapLayer(hop.to_layer_id)
        )
        if target is None:
            raise QgsProcessingException(
                QCoreApplication.translate(
                    "MatchingEngine", "relation chain layer {} is not in the project"
                ).format(hop.to_layer_id)
            )
        if hop_index == len(plan.chain) - 1:  # last hop
            # The far-side keys ARE the membership condition; no query needed.
            return MatchCondition(
                key_fields=tuple(hop.to_fields), keys=tuple(sorted(keys, key=repr))
            )
        # What this hop yields depends on the hops already walked, the fields the *next* hop
        # reads back, and the stratum's starting keys — nothing else (§7.1). Two chains that
        # share these share the answer even when their remaining hops differ.
        collect_fields = tuple(plan.chain[hop_index + 1].from_fields)
        memo_key: HopMemoKey = (plan.chain[: hop_index + 1], collect_fields, start)
        memoized = chain_context.get(memo_key) if chain_context is not None else None
        if memoized is not None:
            keys = set(memoized)
            continue
        chain_target_layer = project.mapLayer(plan.layer_id)
        prefix = f"attribute[{chain_target_layer.name()}]: " if chain_target_layer else ""
        hop_target_layer = cast("QgsVectorLayer", target)
        keys = _query_far_keys(hop_target_layer, hop.to_fields, keys, collect_fields, feedback)
        if chain_context is not None:
            chain_context.put(memo_key, frozenset(keys))
        feedback.pushDebugInfo(
            f"{prefix}chain hop {hop.edge.relation_id} ({stratum_name}): "
            f"{len(keys)} key(s) at {hop_target_layer.name()}"
        )
    # Unreachable: the loop always returns at the last hop.
    raise QgsProcessingException(
        QCoreApplication.translate(
            "MatchingEngine", "relation chain produced no terminal condition"
        )
    )


def _query_far_keys(
    layer: QgsVectorLayer,
    match_fields: Sequence[str],
    keys: Iterable[tuple[object, ...]],
    collect_fields: Sequence[str],
    feedback: QgsProcessingFeedback,
) -> set[tuple[object, ...]]:
    """
    Query *layer* for features whose *match_fields* are in *keys*; collect new keys.

    :param layer: The intermediate layer (its ``subsetString`` applies implicitly).
    :param match_fields: Fields matched against the incoming keys.
    :param keys: Incoming key tuples (NULL-free).
    :param collect_fields: Fields whose values form the outgoing keys.
    :param feedback: Execution feedback channel (cancellation).
    :return: The outgoing key tuples, NULL-bearing ones dropped.
    :raise QgsProcessingException: On cancellation.
    """
    needed = [*match_fields, *collect_fields]
    indexes = [layer.fields().indexOf(name) for name in needed]
    collected: set[tuple[object, ...]] = set()
    for expression in in_filter_expressions(match_fields, keys):
        _check_canceled(feedback)
        request = QgsFeatureRequest()
        request.setFilterExpression(expression)
        request.setSubsetOfAttributes(indexes)
        request.setFlags(Qgis.FeatureRequestFlag.NoGeometry)
        for feature in cast("Iterable[QgsFeature]", layer.getFeatures(request)):
            _check_canceled(feedback)
            values = tuple(feature.attribute(name) for name in collect_fields)
            # NULL keys never match (SPEC §7); QgsVariantUtils.isNull covers PyQt6 None and
            # the PyQt5 QVariant null alike.
            if all(not QgsVariantUtils.isNull(value) for value in values):
                collected.add(values)
    return collected


def in_filter_expressions(fields: Sequence[str], keys: Iterable[tuple[object, ...]]) -> list[str]:
    """
    Build chunked QGIS filter expressions matching *fields* against *keys*.

    Single fields render as ``"f" IN (...)``; composite keys as chunked
    ``OR``-of-``AND`` groups (SPEC §7.1).

    :param fields: The key field names.
    :param keys: The key tuples (already NULL-free).
    :return: One C++-evaluable expression per chunk (empty when there are no keys).
    """
    key_list = list(keys)
    if not key_list:
        return []
    expressions: list[str] = []
    if len(fields) == 1:
        column = QgsExpression.quotedColumnRef(fields[0])
        for start in range(0, len(key_list), _KEY_CHUNK):
            chunk = key_list[start : start + _KEY_CHUNK]
            values = ", ".join(QgsExpression.quotedValue(key[0]) for key in chunk)
            expressions.append(f"{column} IN ({values})")
        return expressions
    columns = [QgsExpression.quotedColumnRef(name) for name in fields]
    for start in range(0, len(key_list), _KEY_CHUNK):
        chunk = key_list[start : start + _KEY_CHUNK]
        groups = " OR ".join(
            "("
            + " AND ".join(
                f"{column} = {QgsExpression.quotedValue(value)}"
                for column, value in zip(columns, key, strict=True)
            )
            + ")"
            for key in chunk
        )
        expressions.append(f"({groups})")
    return expressions


# ---------------------------------------------------------------------------
# §7.2 — spatial fid sets
# ---------------------------------------------------------------------------


def stratum_geometry_in_layer_crs(
    geometry: QgsGeometry,
    strat_layer: QgsVectorLayer,
    layer: QgsVectorLayer,
    project: QgsProject,
    feedback: QgsProcessingFeedback,
) -> QgsGeometry:
    """
    Transform one stratum geometry into the layer's CRS (once per pair, SPEC §7.2).

    Whether a transform is needed is decided by the
    :class:`~qgis.core.QgsCoordinateTransform` itself: a short-circuited transform
    (equivalent or invalid CRSs) returns the geometry unchanged. Every real transform
    is reported with source and target authids.

    :param geometry: The stratum geometry (a copy is returned either way).
    :param strat_layer: The stratification layer (source CRS).
    :param layer: The packaged layer (target CRS).
    :param project: Supplies the transform context.
    :param feedback: Execution feedback channel.
    :return: The geometry in the layer's CRS.
    :raise QgsProcessingException: If the coordinate transform fails (the §7.2
        best-effort containment happens in the caller).
    """
    source = strat_layer.crs()
    target = layer.crs()
    transformed = QgsGeometry(geometry)
    ctx = project.transformContext()
    # The bundled stubs miss the (source, target, context) constructor overload.
    transform = QgsCoordinateTransform(source, target, ctx)  # ty: ignore[invalid-argument-type, too-many-positional-arguments]
    if transform.isShortCircuited():
        return transformed
    feedback.pushDebugInfo(
        f"transforming stratum geometry {source.authid()} -> {target.authid()}"
        f" for layer {layer.name()}"
    )
    if transformed.transform(transform) != Qgis.GeometryOperationResult.Success:
        raise QgsProcessingException(
            QCoreApplication.translate(
                "MatchingEngine", "coordinate transform {} -> {} failed for layer {}"
            ).format(source.authid(), target.authid(), layer.name())
        )
    return transformed


_NAMED_ENGINE_METHOD: Final[dict[str, str]] = {
    "intersects": "intersects",
    "overlaps": "overlaps",
    "crosses": "crosses",
    "touches": "touches",
    # The predicate reads ``predicate(feature, stratum)`` but the engine is prepared on the
    # stratum, so the directional pair flips: feature contains stratum ⟺ stratum within feature.
    "contains": "within",
    "within": "contains",
}
"""
Resolved named predicate → the prepared-engine method testing it against a candidate (§7.2).

Keys mirror :data:`~.params.NAMED_SPATIAL_PREDICATES`.
"""


def _transpose_de9im(pattern: str, /) -> str:
    """
    Transpose a row-major DE-9IM pattern (swap the intersection matrix's rows and columns).

    The prepared engine computes ``IM(stratum, feature)`` while the predicate is written
    ``relate(feature, stratum, pattern)`` — the transpose of that matrix — so the pattern is
    transposed to match. Self-transpose patterns (e.g. the ``auto`` ``T********``) are unchanged.

    :param pattern: A nine-character DE-9IM pattern.
    :return: The transposed pattern.
    """
    return "".join(pattern[i] for i in (0, 3, 6, 1, 4, 7, 2, 5, 8))


def _requires_intersection(pattern: str, /) -> bool:
    """
    Report whether *pattern* is unsatisfiable by disjoint geometries (§7.2 prefilter gate).

    Two geometries intersect iff at least one of their interior-interior, interior-boundary,
    boundary-interior or boundary-boundary cells is non-empty. A pattern that demands a dimension
    (not ``F``, not the wildcard ``*``) in any of those four cells can only match intersecting
    geometries, so a cheap prepared ``intersects`` test can pre-reject candidates before the
    fuller ``relatePattern``. The test is symmetric, so pattern orientation is irrelevant here.

    :param pattern: A nine-character DE-9IM pattern.
    :return: Whether every match must intersect.
    """
    return any(pattern[i] not in "F*" for i in (0, 1, 3, 4))


def _implied_by_containment(pattern: str, /) -> bool:
    """
    Report whether a DE-9IM *pattern* is guaranteed by the stratum containing the candidate.

    When the prepared engine (built on stratum ``S``) reports ``contains(C)``, the transposed
    matrix ``IM(C, S)`` is guaranteed ``II`` non-empty, ``IE = F`` and ``BE = F`` — nothing
    else. *pattern* is therefore implied iff cell 0 accepts any non-empty intersection
    (``T``/``*`` — a dimension digit is **not** guaranteed), cells 2 and 5 accept ``F``, and
    every other cell is a wildcard. True for the ``auto`` ``T********`` (§4), letting the
    interior majority short-circuit on a prepared ``contains`` instead of a full relate.

    :param pattern: A nine-character DE-9IM pattern (feature-vs-stratum orientation).
    :return: Whether ``contains`` alone proves the pattern.
    """
    if pattern[0] not in "T*" or pattern[2] not in "F*" or pattern[5] not in "F*":
        return False
    return all(pattern[i] == "*" for i in (1, 3, 4, 6, 7, 8))


def _compile_matcher(
    engine: QgsGeometryEngine, predicates: Sequence[str]
) -> Callable[[QgsGeometry], bool]:
    """
    Compile the per-candidate membership test for one prepared stratum engine (§7.2).

    Everything derivable from the predicates alone — engine-method binding, DE-9IM
    transposition, the intersection/containment implications — is resolved here, once per
    (layer, stratum), so the returned closure does only prepared GEOS calls per candidate.
    DE-9IM candidates take a prepared ``contains`` fast-accept (when the pattern is implied
    by containment), then a prepared ``intersects`` fast-reject (when the pattern requires
    intersection), and only the remaining boundary shell pays ``relatePattern`` — which has
    no prepared fast path in GEOS.

    :param engine: A geometry engine prepared on the stratum geometry.
    :param predicates: The OR-combined resolved predicates (named or DE-9IM).
    :return: A callable testing one candidate geometry (a null geometry never matches).
    """
    intersects = engine.intersects
    contains = engine.contains
    relate = engine.relatePattern
    named = [
        getattr(engine, _NAMED_ENGINE_METHOD[p]) for p in predicates if p in _NAMED_ENGINE_METHOD
    ]
    de9im = [
        (_transpose_de9im(p), _requires_intersection(p), _implied_by_containment(p))
        for p in predicates
        if p not in _NAMED_ENGINE_METHOD
    ]

    def matches(geometry: QgsGeometry) -> bool:
        abstract = geometry.constGet()
        if abstract is None:  # a null geometry never matches
            return False
        for test in named:
            if test(abstract):
                return True
        for pattern, needs_intersection, containment_implies in de9im:
            if containment_implies and contains(abstract):
                return True
            if needs_intersection and not intersects(abstract):
                continue
            if relate(abstract, pattern):
                return True
        return False

    return matches


def spatial_fids_for_stratum(
    layer: QgsVectorLayer,
    stratum_geometry: QgsGeometry,
    stratum_name: str,
    predicates: Sequence[str],
    feedback: QgsProcessingFeedback,
) -> MatchCondition:
    """
    Materialize the matching fid set for one (layer, stratum) pair (SPEC §7.2).

    The candidate filter is the provider's spatial index (``setFilterRect`` with the stratum's
    bbox, already in the layer's CRS); the exact test is a **prepared**
    :class:`~qgis.core.QgsGeometryEngine` over the stratum geometry — prepared once per pair, then
    each candidate is tested against the OR of the resolved predicates. Preparing the (often
    complex, admin-boundary) stratum polygon turns each test from ``O(vertices)`` into roughly
    ``O(log vertices)``, the dominant cost on large layers. No attributes are fetched.

    :param layer: The packaged layer (its ``subsetString`` applies implicitly).
    :param stratum_geometry: The stratum geometry in the layer's CRS.
    :param stratum_name: The resolved stratum name (for feedback only).
    :param predicates: The resolved predicates (named or DE-9IM) from the layer's plan,
        combined with OR.
    :param feedback: Execution feedback channel (messages and cancellation).
    :return: The fid-set condition.
    :raise QgsProcessingException: On cancellation during the candidate scan.
    """
    abstract = stratum_geometry.constGet()
    engine = None if abstract is None else QgsGeometry.createGeometryEngine(abstract)
    if engine is None:  # an empty/unpreparable stratum geometry matches nothing
        fids: tuple[int, ...] = ()
    else:
        engine.prepareGeometry()
        matches = _compile_matcher(engine, predicates)
        request = QgsFeatureRequest()
        request.setFilterRect(stratum_geometry.boundingBox())
        request.setNoAttributes()
        matched: list[int] = []
        for feature in cast("Iterable[QgsFeature]", layer.getFeatures(request)):
            _check_canceled(feedback)
            if matches(feature.geometry()):
                matched.append(feature.id())
        fids = tuple(matched)
    feedback.pushDebugInfo(f"spatial[{layer.name()}]: {len(fids)} feature(s) match {stratum_name}")
    return MatchCondition(fids=fids, by_fid=True)
