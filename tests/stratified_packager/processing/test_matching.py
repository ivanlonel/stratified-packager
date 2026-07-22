"""
Tests for :mod:`stratified_packager.processing.matching`.

Builds in-memory attribute networks (states ← cities ← districts, composite keys on the
first hop) and spatial grids, then exercises §4 method resolution (auto rules, pins,
ambiguity, predicate tokens), §7.1 key propagation (fan-out, NULL keys, intermediate
subset strings, chunking) and §7.2 spatial fid sets (predicates, DE-9IM, CRS transform).
"""
# pylint: disable=redefined-outer-name

from __future__ import annotations

from dataclasses import dataclass

import pytest

pytest.importorskip("qgis", reason="The matching engine drives QgsFeatureRequest pushdown.")

# Imported only after the importorskip guard above confirms QGIS is available.
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsExpressionContextUtils,
    QgsFeature,
    QgsGeometry,
    QgsProcessingException,
    QgsProcessingFeedback,
    QgsProject,
    QgsRectangle,
    QgsVariantUtils,
    QgsVectorLayer,
)

from stratified_packager.processing.matching import (
    INTERIORS_INTERSECT,
    ChainContext,
    LayerMatchPlan,
    attribute_keys_for_stratum,
    in_filter_expressions,
    resolve_layer_methods,
    spatial_fids_for_stratum,
    stratum_geometry_in_layer_crs,
)
from stratified_packager.processing.params import MatchingMethod
from stratified_packager.toolbelt.relations import RelationGraph, build_relation_graph
from tests.stratified_packager._qgis_helpers import add_relation

pytestmark = pytest.mark.qgis
"""Marks the whole module as requiring a QGIS runtime."""


def _table(name: str, fields: str, rows: list[tuple[object, ...]]) -> QgsVectorLayer:
    """
    Build a geometryless memory layer.

    :param name: Layer name.
    :param fields: The ``field=a:integer&field=b:string`` URI fragment.
    :param rows: Attribute tuples.
    :return: The populated layer.
    """
    layer = QgsVectorLayer(f"NoGeometry?{fields}", name, "memory")
    provider = layer.dataProvider()
    assert provider is not None
    features = []
    for row in rows:
        feature = QgsFeature(layer.fields())
        for index, value in enumerate(row):
            feature.setAttribute(index, value)
        features.append(feature)
    assert provider.addFeatures(features)
    return layer


def _squares(
    name: str, cells: list[tuple[float, float, float]], crs: str = "EPSG:4326"
) -> QgsVectorLayer:
    """
    Build a polygon memory layer of axis-aligned squares with a ``tag`` field.

    :param name: Layer name.
    :param cells: ``(x0, y0, side)`` per square; ``tag`` is the index.
    :param crs: Authid of the layer CRS.
    :return: The populated layer.
    """
    layer = QgsVectorLayer(f"Polygon?crs={crs}&field=tag:integer", name, "memory")
    provider = layer.dataProvider()
    assert provider is not None
    features = []
    for index, (x0, y0, side) in enumerate(cells):
        feature = QgsFeature(layer.fields())
        feature.setAttribute(0, index)
        feature.setGeometry(QgsGeometry.fromRect(QgsRectangle(x0, y0, x0 + side, y0 + side)))
        features.append(feature)
    assert provider.addFeatures(features)
    return layer


@dataclass
class Network:
    """The attribute-matching fixture network."""

    project: QgsProject
    states: QgsVectorLayer
    cities: QgsVectorLayer
    districts: QgsVectorLayer

    def graph(self) -> RelationGraph:
        """Return a fresh relation graph over the current manager state."""
        manager = self.project.relationManager()
        assert manager is not None
        return build_relation_graph(manager)

    def state_feature(self, code: str) -> QgsFeature:
        """Return the states feature with the given ``code``."""
        for feature in self.states.getFeatures():  # type: ignore[union-attr]  # ty: ignore[not-iterable]  # stubs lag
            if feature.attribute("code") == code:
                return feature
        msg = f"no state {code!r}"
        raise AssertionError(msg)


@pytest.fixture
def network(qgis_new_project: QgsProject) -> Network:
    """Build states ← cities ← districts with data (composite keys on the first hop)."""
    states = _table(
        "states",
        "field=code:string&field=country:string",
        [("A", "X"), ("B", "X")],
    )
    cities = _table(
        "cities",
        "field=cid:integer&field=state_code:string&field=state_country:string",
        [(1, "A", "X"), (2, "A", "X"), (3, "B", "X"), (4, "A", "Y"), (5, None, "X")],
    )
    districts = _table(
        "districts",
        "field=did:integer&field=city_id:integer",
        [(10, 1), (11, 2), (12, 3), (13, 99)],
    )
    assert qgis_new_project.addMapLayers([states, cities, districts], addToLegend=False)
    add_relation(
        "r_cities_states",
        cities,
        states,
        [("state_code", "code"), ("state_country", "country")],
    )
    add_relation("r_districts_cities", districts, cities, [("city_id", "cid")])
    return Network(project=qgis_new_project, states=states, cities=cities, districts=districts)


@pytest.fixture
def feedback() -> QgsProcessingFeedback:
    """Return a plain feedback sink."""
    return QgsProcessingFeedback()


class TestResolveLayerMethods:
    """SPEC §4 method resolution."""

    def test_auto_prefers_attribute_over_spatial(
        self, network: Network, feedback: QgsProcessingFeedback
    ) -> None:
        """A relation path wins even for spatial-capable layers."""
        plans = resolve_layer_methods(
            [network.cities, network.districts], network.states, network.graph(), feedback
        )
        assert plans[network.cities.id()].method is MatchingMethod.ATTRIBUTE
        assert plans[network.districts.id()].method is MatchingMethod.ATTRIBUTE
        chain = plans[network.districts.id()].chain
        assert [hop.edge.relation_id for hop in chain] == [
            "r_cities_states",
            "r_districts_cities",
        ]
        assert chain[0].from_layer_id == network.states.id()

    def test_auto_falls_back_to_spatial(
        self, network: Network, feedback: QgsProcessingFeedback
    ) -> None:
        """Without a path, two spatial layers resolve to spatial + auto predicate."""
        strat = _squares("strat", [(0, 0, 10)])
        polys = _squares("polys", [(1, 1, 2)])
        assert network.project.addMapLayers([strat, polys], addToLegend=False)
        plans = resolve_layer_methods([polys], strat, network.graph(), feedback)
        assert plans[polys.id()].method is MatchingMethod.SPATIAL
        assert plans[polys.id()].predicates == (INTERIORS_INTERSECT,)

    def test_auto_dead_end_names_layer_and_remedies(
        self, network: Network, feedback: QgsProcessingFeedback
    ) -> None:
        """No path and no geometry aborts, naming the layer and the remedies."""
        loner = _table("loner", "field=a:integer", [(1,)])
        assert network.project.addMapLayer(loner, addToLegend=False)
        with pytest.raises(QgsProcessingException, match="loner") as excinfo:
            resolve_layer_methods([loner], network.states, network.graph(), feedback)
        assert "whole_export" in str(excinfo.value)

    def test_errors_aggregate_across_layers(
        self, network: Network, feedback: QgsProcessingFeedback
    ) -> None:
        """Every misconfigured layer is reported in one exception."""
        loner_a = _table("loner_a", "field=a:integer", [(1,)])
        loner_b = _table("loner_b", "field=a:integer", [(1,)])
        assert network.project.addMapLayers([loner_a, loner_b], addToLegend=False)
        with pytest.raises(QgsProcessingException) as excinfo:
            resolve_layer_methods([loner_a, loner_b], network.states, network.graph(), feedback)
        assert "loner_a" in str(excinfo.value)
        assert "loner_b" in str(excinfo.value)

    def test_explicit_whole_export(
        self, network: Network, feedback: QgsProcessingFeedback
    ) -> None:
        """An explicit whole_export passes through untouched."""
        QgsExpressionContextUtils.setLayerVariable(
            network.cities, "stratified_packager_matching_method", "whole_export"
        )
        plans = resolve_layer_methods([network.cities], network.states, network.graph(), feedback)
        assert plans[network.cities.id()].method is MatchingMethod.WHOLE_EXPORT

    def test_invalid_method_token_aborts(
        self, network: Network, feedback: QgsProcessingFeedback
    ) -> None:
        """An unknown matching_method token aborts."""
        QgsExpressionContextUtils.setLayerVariable(
            network.cities, "stratified_packager_matching_method", "sideways"
        )
        with pytest.raises(QgsProcessingException, match="invalid matching_method"):
            resolve_layer_methods([network.cities], network.states, network.graph(), feedback)

    def test_ambiguity_requires_pin_and_pin_resolves(
        self, network: Network, feedback: QgsProcessingFeedback
    ) -> None:
        """Parallel relations abort without a pin; a pin (layer → strat order) wins."""
        add_relation(
            "r_cities_states_alt", network.cities, network.states, [("state_code", "code")]
        )
        with pytest.raises(QgsProcessingException, match="relation_path"):
            resolve_layer_methods([network.cities], network.states, network.graph(), feedback)
        QgsExpressionContextUtils.setLayerVariable(
            network.cities,
            "stratified_packager_relation_path",
            '["r_cities_states_alt"]',
        )
        plans = resolve_layer_methods([network.cities], network.states, network.graph(), feedback)
        plan = plans[network.cities.id()]
        assert plan.pinned
        assert [hop.edge.relation_id for hop in plan.chain] == ["r_cities_states_alt"]
        assert plan.chain[0].from_layer_id == network.states.id()

    @pytest.mark.parametrize(
        ("pin", "fragment"),
        [
            ("not json", "not a JSON list"),
            ('{"a": 1}', "JSON list of relation ids"),
            ('["nope"]', "invalid relation_path pin"),
        ],
        ids=["unparsable", "not-a-list", "unknown-id"],
    )
    def test_broken_pins_abort(
        self, network: Network, feedback: QgsProcessingFeedback, pin: str, fragment: str
    ) -> None:
        """
        Broken pins abort with the §4 wording.

        :param network: Fixture network.
        :param feedback: Feedback sink.
        :param pin: The raw relation_path variable value.
        :param fragment: Expected message fragment.
        """
        QgsExpressionContextUtils.setLayerVariable(
            network.cities, "stratified_packager_relation_path", pin
        )
        with pytest.raises(QgsProcessingException, match=fragment):
            resolve_layer_methods([network.cities], network.states, network.graph(), feedback)

    def test_predicate_tokens(self, network: Network, feedback: QgsProcessingFeedback) -> None:
        """Named tokens, DE-9IM patterns, OR-lists and case/whitespace handling resolve."""
        strat = _squares("strat", [(0, 0, 10)])
        polys = _squares("polys2", [(0, 0, 1)])
        assert network.project.addMapLayers([strat, polys], addToLegend=False)

        # Named token, case-insensitive.
        QgsExpressionContextUtils.setLayerVariable(
            polys, "stratified_packager_spatial_predicate", "Touches"
        )
        plans = resolve_layer_methods([polys], strat, network.graph(), feedback)
        assert plans[polys.id()].predicates == ("touches",)

        # Comma-separated named OR-list (surrounding whitespace stripped, canonical case).
        QgsExpressionContextUtils.setLayerVariable(
            polys, "stratified_packager_spatial_predicate", "intersects,  Touches"
        )
        plans = resolve_layer_methods([polys], strat, network.graph(), feedback)
        assert plans[polys.id()].predicates == ("intersects", "touches")

        # Comma-separated DE-9IM list, lowercase t/f normalized to uppercase.
        QgsExpressionContextUtils.setLayerVariable(
            polys, "stratified_packager_spatial_predicate", "T*F**F***, t*f**f**1"
        )
        plans = resolve_layer_methods([polys], strat, network.graph(), feedback)
        assert plans[polys.id()].predicates == ("T*F**F***", "T*F**F**1")

        # `auto` cannot be combined with other tokens.
        QgsExpressionContextUtils.setLayerVariable(
            polys, "stratified_packager_spatial_predicate", "auto, touches"
        )
        with pytest.raises(QgsProcessingException, match="cannot be combined"):
            resolve_layer_methods([polys], strat, network.graph(), feedback)

        # Invalid DE-9IM token aborts.
        QgsExpressionContextUtils.setLayerVariable(
            polys, "stratified_packager_spatial_predicate", "TTTTTTTTTT"
        )
        with pytest.raises(QgsProcessingException, match="invalid spatial_predicate token"):
            resolve_layer_methods([polys], strat, network.graph(), feedback)

    def test_auto_predicate_by_geometry_type(
        self, network: Network, feedback: QgsProcessingFeedback
    ) -> None:
        """`auto` expands per the SPEC §4 geometry-type table."""
        poly_strat = _squares("poly_strat", [(0, 0, 10)])
        line_strat = QgsVectorLayer("LineString?crs=EPSG:4326", "line_strat", "memory")
        line_layer = QgsVectorLayer("LineString?crs=EPSG:4326", "line_layer", "memory")
        poly_layer = _squares("poly_layer", [(0, 0, 1)])
        point_layer = QgsVectorLayer("Point?crs=EPSG:4326", "point_layer", "memory")
        assert network.project.addMapLayers(
            [poly_strat, line_strat, line_layer, poly_layer, point_layer], addToLegend=False
        )
        graph = network.graph()
        # polygon stratum x line layer: interiors intersect OR line-along-boundary (dim 1).
        plans = resolve_layer_methods([line_layer], poly_strat, graph, feedback)
        assert plans[line_layer.id()].predicates == (INTERIORS_INTERSECT, "*1*******")
        # line stratum x polygon layer: interiors intersect OR boundary-along-line (dim 1).
        plans = resolve_layer_methods([poly_layer], line_strat, graph, feedback)
        assert plans[poly_layer.id()].predicates == (INTERIORS_INTERSECT, "***1*****")
        # point on either side -> intersects.
        plans = resolve_layer_methods([point_layer], poly_strat, graph, feedback)
        assert plans[point_layer.id()].predicates == ("intersects",)
        # polygon x polygon -> interiors intersect.
        plans = resolve_layer_methods([poly_layer], poly_strat, graph, feedback)
        assert plans[poly_layer.id()].predicates == (INTERIORS_INTERSECT,)


class TestAttributeKeys:
    """SPEC §7.1 key propagation."""

    def _plan(self, network: Network, layer: QgsVectorLayer) -> LayerMatchPlan:
        """Resolve the attribute plan of one layer."""
        plans = resolve_layer_methods(
            [layer], network.states, network.graph(), QgsProcessingFeedback()
        )
        return plans[layer.id()]

    def test_direct_hop_uses_stratum_keys_without_querying(
        self, network: Network, feedback: QgsProcessingFeedback
    ) -> None:
        """One-hop chains take the stratum's composite key directly."""
        condition = attribute_keys_for_stratum(
            self._plan(network, network.cities),
            network.state_feature("A"),
            "A",
            network.project,
            feedback,
        )
        assert condition.key_fields == ("state_code", "state_country")
        assert condition.keys == (("A", "X"),)
        assert not condition.by_fid

    def test_two_hop_fan_out(self, network: Network, feedback: QgsProcessingFeedback) -> None:
        """State A fans out to cities 1+2, then to the district key set {1, 2}."""
        condition = attribute_keys_for_stratum(
            self._plan(network, network.districts),
            network.state_feature("A"),
            "A",
            network.project,
            feedback,
        )
        assert condition.key_fields == ("city_id",)
        assert set(condition.keys) == {(1,), (2,)}

    def test_intermediate_subset_string_is_honored(
        self, network: Network, feedback: QgsProcessingFeedback
    ) -> None:
        """A subset on the intermediate layer narrows the propagation."""
        assert network.cities.setSubsetString('"cid" != 2')
        condition = attribute_keys_for_stratum(
            self._plan(network, network.districts),
            network.state_feature("A"),
            "A",
            network.project,
            feedback,
        )
        assert set(condition.keys) == {(1,)}

    def test_null_keys_never_match(
        self, network: Network, feedback: QgsProcessingFeedback
    ) -> None:
        """A NULL stratum key yields an empty (never-matching) condition."""
        provider = network.states.dataProvider()
        assert provider is not None
        feature = QgsFeature(network.states.fields())
        feature.setAttribute(0, None)
        feature.setAttribute(1, "X")
        assert provider.addFeatures([feature])
        null_state = next(
            f
            for f in network.states.getFeatures()  # type: ignore[union-attr]  # ty: ignore[not-iterable]  # stubs lag
            if QgsVariantUtils.isNull(f.attribute("code"))
        )
        condition = attribute_keys_for_stratum(
            self._plan(network, network.cities), null_state, "null", network.project, feedback
        )
        assert not condition.keys
        assert condition.key_fields == ("state_code", "state_country")

    def test_same_layer_matches_by_fid(
        self, network: Network, feedback: QgsProcessingFeedback
    ) -> None:
        """The stratification layer itself matches exactly its own feature."""
        plan = LayerMatchPlan(
            layer_id=network.states.id(), method=MatchingMethod.ATTRIBUTE, chain=()
        )
        stratum = network.state_feature("B")
        condition = attribute_keys_for_stratum(plan, stratum, "B", network.project, feedback)
        assert condition.by_fid
        assert condition.fids == (stratum.id(),)

    def test_in_expression_chunking(self) -> None:
        """Key chunks split at 1 000 per expression, composite keys as OR-of-AND."""
        single = in_filter_expressions(["k"], [(value,) for value in range(2500)])
        assert len(single) == 3
        assert single[0].startswith('"k" IN (')
        composite = in_filter_expressions(["a", "b"], [(1, "x")])
        assert composite == ['(("a" = 1 AND "b" = \'x\'))']
        assert not in_filter_expressions(["a"], [])


class TestChainContext:
    """SPEC §7.1 chain memo + staged-hop resolution."""

    def _plan(self, network: Network, layer: QgsVectorLayer) -> LayerMatchPlan:
        """Resolve the attribute plan of one layer."""
        plans = resolve_layer_methods(
            [layer], network.states, network.graph(), QgsProcessingFeedback()
        )
        return plans[layer.id()]

    def _resolve(
        self,
        network: Network,
        plan: LayerMatchPlan,
        code: str,
        feedback: QgsProcessingFeedback,
        context: ChainContext | None,
    ) -> object:
        """Resolve one stratum's condition through *context*."""
        return attribute_keys_for_stratum(
            plan,
            network.state_feature(code),
            code,
            network.project,
            feedback,
            chain_context=context,
        )

    def test_repeated_resolution_is_memoized(
        self, network: Network, feedback: QgsProcessingFeedback
    ) -> None:
        """The second resolution of the same (chain, keys) pair is served from the memo."""
        plan = self._plan(network, network.districts)  # two hops: queries the cities intermediate
        context = ChainContext()
        first = self._resolve(network, plan, "A", feedback, context)
        assert (context.hits, context.misses) == (0, 1)
        second = self._resolve(network, plan, "A", feedback, context)
        assert (context.hits, context.misses) == (1, 1)
        assert first == second

    def _leaf_off_cities(
        self,
        network: Network,
        name: str,
        cities_field: str,
        rows: list[tuple[object, ...]],
    ) -> QgsVectorLayer:
        """Hang a new layer off ``cities``, so its chain shares the first hop with districts."""
        field_type = network.cities.fields().field(cities_field).typeName().lower()
        leaf = _table(name, f"field=lid:integer&field=ref:{field_type}", rows)
        assert network.project.addMapLayer(leaf, addToLegend=False)
        add_relation(f"r_{name}_cities", leaf, network.cities, [("ref", cities_field)])
        return leaf

    def test_layers_sharing_a_chain_prefix_share_the_memo(
        self, network: Network, feedback: QgsProcessingFeedback
    ) -> None:
        """
        Chains that diverge only at their last hop still reuse the hops they share.

        The regression this guards: keying the memo on the *whole* chain made it useless in
        practice, because packaged layers overwhelmingly share a prefix and differ at the final,
        layer-specific relation.
        """
        leaf = self._leaf_off_cities(network, "blocks", "cid", [(20, 1), (21, 2)])
        districts_plan = self._plan(network, network.districts)
        leaf_plan = self._plan(network, leaf)
        assert districts_plan.chain[:1] == leaf_plan.chain[:1]  # shared prefix
        assert districts_plan.chain[1:] != leaf_plan.chain[1:]  # divergent tail

        context = ChainContext()
        self._resolve(network, districts_plan, "A", feedback, context)
        assert (context.hits, context.misses) == (0, 1)
        self._resolve(network, leaf_plan, "A", feedback, context)
        assert (context.hits, context.misses) == (1, 1)

    def test_a_shared_hop_read_for_other_keys_is_not_shared(
        self, network: Network, feedback: QgsProcessingFeedback
    ) -> None:
        """The same relation traversed for a different onward key is a different question."""
        leaf = self._leaf_off_cities(network, "zones", "state_code", [(30, "A"), (31, "B")])
        districts_plan = self._plan(network, network.districts)
        leaf_plan = self._plan(network, leaf)
        assert districts_plan.chain[:1] == leaf_plan.chain[:1]
        assert districts_plan.chain[1].from_fields != leaf_plan.chain[1].from_fields

        context = ChainContext()
        self._resolve(network, districts_plan, "A", feedback, context)
        self._resolve(network, leaf_plan, "A", feedback, context)
        assert (context.hits, context.misses) == (0, 2)

    def test_memo_never_changes_the_result(
        self, network: Network, feedback: QgsProcessingFeedback
    ) -> None:
        """Memoized and unmemoized resolutions agree — the memo is invisible to outputs."""
        plan = self._plan(network, network.districts)
        context = ChainContext()
        for code in ("A", "B", "A", "B"):
            assert self._resolve(network, plan, code, feedback, context) == self._resolve(
                network, plan, code, feedback, None
            )

    def test_capacity_zero_disables_memoization(
        self, network: Network, feedback: QgsProcessingFeedback
    ) -> None:
        """A zero capacity keeps every resolution a miss, still returning the same answer."""
        plan = self._plan(network, network.districts)
        context = ChainContext(capacity=0)
        first = self._resolve(network, plan, "A", feedback, context)
        second = self._resolve(network, plan, "A", feedback, context)
        assert (context.hits, context.misses) == (0, 2)
        assert first == second

    def test_evicts_least_recently_used(
        self, network: Network, feedback: QgsProcessingFeedback
    ) -> None:
        """Past capacity the oldest entry goes, so the memo cannot grow without bound."""
        plan = self._plan(network, network.districts)
        context = ChainContext(capacity=1)
        self._resolve(network, plan, "A", feedback, context)
        self._resolve(network, plan, "B", feedback, context)  # evicts A
        self._resolve(network, plan, "A", feedback, context)
        assert (context.hits, context.misses) == (0, 3)

    def test_empty_chain_is_never_memoized(
        self, network: Network, feedback: QgsProcessingFeedback
    ) -> None:
        """A layer that *is* the stratification layer resolves by fid without touching the memo."""
        context = ChainContext()
        condition = attribute_keys_for_stratum(
            LayerMatchPlan(layer_id=network.states.id(), method=MatchingMethod.ATTRIBUTE),
            network.state_feature("A"),
            "A",
            network.project,
            feedback,
            chain_context=context,
        )
        assert condition.by_fid
        assert (context.hits, context.misses) == (0, 0)

    def test_hop_layer_prefers_the_staged_copy(self, network: Network) -> None:
        """A registered hop layer wins over the project lookup; others still resolve normally."""
        staged = QgsVectorLayer("Point?crs=EPSG:4326", "staged cities", "memory")
        assert staged.isValid()
        context = ChainContext(hop_layers={network.cities.id(): staged})
        assert context.hop_layer(network.cities.id(), network.project) is staged
        assert context.hop_layer(network.districts.id(), network.project) is network.districts
        assert context.hop_layer("no-such-layer", network.project) is None


class TestSpatialFids:
    """SPEC §7.2 spatial fid sets."""

    @pytest.fixture
    def grid(self, qgis_new_project: QgsProject) -> QgsVectorLayer:
        """Four squares: inside, edge-touching, overlapping and far from the stratum."""
        layer = _squares(
            "grid",
            [
                (2, 2, 2),  # tag 0: fully inside the stratum (0..10)
                (10, 0, 2),  # tag 1: touches the stratum's right edge only
                (9, 9, 4),  # tag 2: overlaps the stratum's corner
                (50, 50, 2),  # tag 3: far away
            ],
        )
        assert qgis_new_project.addMapLayer(layer, addToLegend=False)
        return layer

    @pytest.fixture
    def stratum_name(self) -> str:
        """Return the stratum name."""
        return "stratum_1"

    @pytest.fixture
    def stratum_geometry(self) -> QgsGeometry:
        """Return the stratum square (0..10)."""
        return QgsGeometry.fromRect(QgsRectangle(0, 0, 10, 10))

    def _tags(self, layer: QgsVectorLayer, fids: tuple[int, ...]) -> set[int]:
        """Map matched fids back to the ``tag`` attribute."""
        return {
            feature.attribute("tag")
            for feature in layer.getFeatures()  # type: ignore[union-attr]  # ty: ignore[not-iterable]  # stubs lag
            if feature.id() in fids
        }

    def test_intersects_includes_boundary_touch(
        self,
        grid: QgsVectorLayer,
        stratum_name: str,
        stratum_geometry: QgsGeometry,
        feedback: QgsProcessingFeedback,
    ) -> None:
        """``intersects`` matches inside, touching and overlapping squares."""
        condition = spatial_fids_for_stratum(
            grid, stratum_geometry, stratum_name, ("intersects",), feedback
        )
        assert self._tags(grid, condition.fids) == {0, 1, 2}
        assert condition.by_fid

    def test_interiors_intersect_excludes_boundary_touch(
        self,
        grid: QgsVectorLayer,
        stratum_name: str,
        stratum_geometry: QgsGeometry,
        feedback: QgsProcessingFeedback,
    ) -> None:
        """``T********`` drops the square that only shares an edge (SPEC §4)."""
        condition = spatial_fids_for_stratum(
            grid, stratum_geometry, stratum_name, (INTERIORS_INTERSECT,), feedback
        )
        assert self._tags(grid, condition.fids) == {0, 2}

    def test_interiors_intersect_matches_enclosing_candidate(
        self,
        qgis_new_project: QgsProject,
        stratum_name: str,
        stratum_geometry: QgsGeometry,
        feedback: QgsProcessingFeedback,
    ) -> None:
        """
        A candidate square enclosing the whole stratum matches ``T********``.

        The stratum does not *contain* this candidate (the relation is inverted), so the
        containment fast-accept must fall through to the full relate — this guards against
        misreading ``contains`` as a rejection test.
        """
        enclosing = _squares("enclosing", [(-5, -5, 30)])  # covers the 0..10 stratum entirely
        assert qgis_new_project.addMapLayer(enclosing, addToLegend=False)
        condition = spatial_fids_for_stratum(
            enclosing, stratum_geometry, stratum_name, (INTERIORS_INTERSECT,), feedback
        )
        assert self._tags(enclosing, condition.fids) == {0}

    def test_named_predicates(
        self,
        grid: QgsVectorLayer,
        stratum_name: str,
        stratum_geometry: QgsGeometry,
        feedback: QgsProcessingFeedback,
    ) -> None:
        """``touches`` and ``within`` map onto their expression functions."""
        touches = spatial_fids_for_stratum(
            grid, stratum_geometry, stratum_name, ("touches",), feedback
        )
        assert self._tags(grid, touches.fids) == {1}
        within = spatial_fids_for_stratum(
            grid, stratum_geometry, stratum_name, ("within",), feedback
        )
        assert self._tags(grid, within.fids) == {0}

    def test_de9im_pattern_orientation_matches_named_within(
        self,
        grid: QgsVectorLayer,
        stratum_name: str,
        stratum_geometry: QgsGeometry,
        feedback: QgsProcessingFeedback,
    ) -> None:
        """
        A non-symmetric DE-9IM 'within' pattern matches the same fids as the named predicate.

        ``T*F**F***`` is not transpose-invariant (unlike ``T********``), so it pins the
        feature-vs-stratum orientation of the prepared-engine ``relatePattern`` — a missing or
        wrong transpose would select a different set.
        """
        named = spatial_fids_for_stratum(
            grid, stratum_geometry, stratum_name, ("within",), feedback
        )
        de9im = spatial_fids_for_stratum(
            grid, stratum_geometry, stratum_name, ("T*F**F***",), feedback
        )
        assert self._tags(grid, de9im.fids) == self._tags(grid, named.fids) == {0}

    def test_or_combines_predicates(
        self,
        grid: QgsVectorLayer,
        stratum_name: str,
        stratum_geometry: QgsGeometry,
        feedback: QgsProcessingFeedback,
    ) -> None:
        """An OR-list matches the union of its predicates' fid sets (SPEC §7.2)."""
        condition = spatial_fids_for_stratum(
            grid, stratum_geometry, stratum_name, ("within", "touches"), feedback
        )
        assert self._tags(grid, condition.fids) == {0, 1}

    def test_subset_string_applies(
        self,
        grid: QgsVectorLayer,
        stratum_name: str,
        stratum_geometry: QgsGeometry,
        feedback: QgsProcessingFeedback,
    ) -> None:
        """The layer's subset narrows the candidates."""
        assert grid.setSubsetString('"tag" != 0')
        condition = spatial_fids_for_stratum(
            grid, stratum_geometry, stratum_name, ("intersects",), feedback
        )
        assert self._tags(grid, condition.fids) == {1, 2}

    def test_crs_transform_once_per_pair(
        self, stratum_name: str, qgis_new_project: QgsProject, feedback: QgsProcessingFeedback
    ) -> None:
        """A 3857 stratum geometry transforms into the 4326 layer's CRS and matches."""
        layer = _squares("grid4326", [(2, 2, 2), (50, 50, 2)])
        strat = _squares("strat3857", [(0, 0, 1)], crs="EPSG:3857")
        assert qgis_new_project.addMapLayers([layer, strat], addToLegend=False)
        geometry = QgsGeometry.fromRect(QgsRectangle(0, 0, 10, 10))
        transform = QgsCoordinateTransform(
            QgsCoordinateReferenceSystem("EPSG:4326"),  # ty: ignore  # stub lacks ctor
            QgsCoordinateReferenceSystem("EPSG:3857"),  # ty: ignore  # stub lacks ctor
            qgis_new_project.transformContext(),
        )
        assert geometry.transform(transform) == 0  # build the 3857 stratum rectangle
        transformed = stratum_geometry_in_layer_crs(
            geometry, strat, layer, qgis_new_project, feedback
        )
        condition = spatial_fids_for_stratum(
            layer, transformed, stratum_name, ("intersects",), feedback
        )
        assert self._tags(layer, condition.fids) == {0}

    def test_equal_crs_skips_transform(
        self,
        qgis_new_project: QgsProject,
        grid: QgsVectorLayer,
        stratum_geometry: QgsGeometry,
        feedback: QgsProcessingFeedback,
    ) -> None:
        """Equal CRSs short-circuit the transform and return the geometry unchanged."""
        strat = _squares("strat_same", [(0, 0, 10)])
        assert qgis_new_project.addMapLayer(strat, addToLegend=False)
        result = stratum_geometry_in_layer_crs(
            stratum_geometry, strat, grid, qgis_new_project, feedback
        )
        assert result.equals(stratum_geometry)


def test_spatial_scan_aborts_on_cancellation(feedback: QgsProcessingFeedback) -> None:
    """The candidate loop honors cancellation mid-scan (SPEC 7.1: per-feature checks)."""
    layer = _squares("cancel_grid", [(0.0, 0.0, 1.0)])
    feedback.cancel()
    with pytest.raises(QgsProcessingException, match="canceled"):
        spatial_fids_for_stratum(
            layer,
            QgsGeometry.fromRect(QgsRectangle(0.0, 0.0, 10.0, 10.0)),
            "s",
            ("intersects",),
            feedback,
        )
