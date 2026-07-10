"""
Tests for :mod:`stratified_packager.toolbelt.relations`.

Builds in-memory relation networks on the live :class:`~qgis.core.QgsProject` instance
(reset per test by pytest-qgis's ``qgis_new_project``) and exercises graph construction,
shortest-path enumeration (incl. ambiguity and cycles) and pin validation.
"""
# pylint: disable=redefined-outer-name

from __future__ import annotations

from dataclasses import dataclass

import pytest

pytest.importorskip("qgis", reason="The relation graph wraps QgsRelationManager.")

# Imported only after the importorskip guard above confirms QGIS is available.
from qgis.core import QgsProject, QgsRelation, QgsVectorLayer

from stratified_packager.toolbelt.relations import (
    RelationGraph,
    RelationHop,
    all_shortest_paths,
    build_relation_graph,
    validate_pinned_path,
)
from tests.stratified_packager._qgis_helpers import add_relation, relation_manager

pytestmark = pytest.mark.qgis
"""Marks the whole module as requiring a QGIS runtime."""


@dataclass
class RelationNetwork:
    """The layers and relation ids of the fixture network."""

    states: QgsVectorLayer
    cities: QgsVectorLayer
    districts: QgsVectorLayer
    graph: RelationGraph


@pytest.fixture
def network(qgis_new_project: QgsProject) -> RelationNetwork:
    """
    Build the canonical chain: districts → cities → states (composite keys on the
    cities→states hop), registered on the live project.

    :param qgis_new_project: pytest-qgis fixture resetting the project instance.
    :return: The populated network.
    """
    project = qgis_new_project
    states = QgsVectorLayer(
        "NoGeometry?field=code:string&field=country:string&field=label:string",
        "states",
        "memory",
    )
    cities = QgsVectorLayer(
        "NoGeometry?field=cid:integer&field=state_code:string&field=state_country:string",
        "cities",
        "memory",
    )
    districts = QgsVectorLayer(
        "NoGeometry?field=did:integer&field=city_id:integer", "districts", "memory"
    )
    assert project.addMapLayers([states, cities, districts], addToLegend=False)
    # Composite pair added in deliberate non-alphabetical order to pin ordering behavior.
    add_relation(
        "r_cities_states",
        cities,
        states,
        [("state_country", "country"), ("state_code", "code")],
    )
    add_relation("r_districts_cities", districts, cities, [("city_id", "cid")])
    manager = project.relationManager()
    assert manager is not None
    graph = build_relation_graph(manager)
    return RelationNetwork(states=states, cities=cities, districts=districts, graph=graph)


class TestBuildRelationGraph:
    """Tests for :func:`build_relation_graph`."""

    def test_edges_and_composite_field_order(self, network: RelationNetwork) -> None:
        """
        Both relations become edges; composite pairs keep their insertion order.

        :param network: The fixture network.
        """
        edge = network.graph.edges_by_id["r_cities_states"]
        assert edge.referencing_layer_id == network.cities.id()
        assert edge.referenced_layer_id == network.states.id()
        assert edge.referencing_fields == ("state_country", "state_code")
        assert edge.referenced_fields == ("country", "code")
        assert set(network.graph.edges_by_id) == {"r_cities_states", "r_districts_cities"}

    def test_invalid_relation_is_skipped(self, network: RelationNetwork) -> None:
        """
        A relation referencing a missing layer is invalid and never becomes an edge.

        :param network: The fixture network.
        """
        broken = QgsRelation()
        broken.setId("r_broken")
        broken.setName("r_broken")
        broken.setReferencingLayer("no_such_layer_id")
        broken.setReferencedLayer(network.states.id())
        broken.addFieldPair("x", "code")
        assert not broken.isValid()
        manager = relation_manager()
        manager.addRelation(broken)
        graph = build_relation_graph(manager)
        assert "r_broken" not in graph.edges_by_id

    def test_hops_from_both_endpoints(self, network: RelationNetwork) -> None:
        """
        Each edge is traversable from both of its endpoints.

        :param network: The fixture network.
        """
        from_cities = {h.to_layer_id for h in network.graph.hops_from(network.cities.id())}
        assert from_cities == {network.states.id(), network.districts.id()}
        from_states = {h.to_layer_id for h in network.graph.hops_from(network.states.id())}
        assert from_states == {network.cities.id()}


class TestAllShortestPaths:
    """Tests for :func:`all_shortest_paths`."""

    def test_direct_hop_child_to_parent(self, network: RelationNetwork) -> None:
        """
        The cities→states path is one hop with child-side fields at the start.

        :param network: The fixture network.
        """
        paths = all_shortest_paths(network.graph, network.cities.id(), network.states.id())
        assert len(paths) == 1
        (hop,) = paths[0]
        assert hop.from_layer_id == network.cities.id()
        assert hop.from_fields == ("state_country", "state_code")
        assert hop.to_fields == ("country", "code")

    def test_two_hop_traversal(self, network: RelationNetwork) -> None:
        """
        districts→states runs through cities, hops in order.

        :param network: The fixture network.
        """
        paths = all_shortest_paths(network.graph, network.districts.id(), network.states.id())
        assert len(paths) == 1
        hops = paths[0]
        assert [h.edge.relation_id for h in hops] == ["r_districts_cities", "r_cities_states"]
        assert hops[0].to_layer_id == hops[1].from_layer_id == network.cities.id()

    def test_parallel_relations_are_ambiguous(self, network: RelationNetwork) -> None:
        """
        A second relation between cities and states yields two shortest paths.

        :param network: The fixture network.
        """
        add_relation(
            "r_cities_states_alt", network.cities, network.states, [("state_code", "code")]
        )
        graph = build_relation_graph(relation_manager())
        paths = all_shortest_paths(graph, network.cities.id(), network.states.id())
        assert {p[0].edge.relation_id for p in paths} == {
            "r_cities_states",
            "r_cities_states_alt",
        }

    def test_cycle_terminates_and_prefers_direct_edge(self, network: RelationNetwork) -> None:
        """
        Closing the triangle districts→states keeps termination and shortens the path.

        :param network: The fixture network.
        """
        add_relation("r_districts_states", network.districts, network.states, [("did", "code")])
        graph = build_relation_graph(relation_manager())
        paths = all_shortest_paths(graph, network.districts.id(), network.states.id())
        assert len(paths) == 1
        assert [h.edge.relation_id for h in paths[0]] == ["r_districts_states"]

    def test_no_path_and_same_layer(self, network: RelationNetwork) -> None:
        """
        An unconnected layer yields no path; identical endpoints yield the empty path.

        :param network: The fixture network.
        """
        loner = QgsVectorLayer("NoGeometry?field=a:integer", "loner", "memory")
        project = QgsProject.instance()
        assert project is not None
        assert project.addMapLayer(loner, addToLegend=False)
        assert not all_shortest_paths(network.graph, loner.id(), network.states.id())
        assert all_shortest_paths(network.graph, loner.id(), loner.id()) == [()]

    def test_max_paths_caps_enumeration(self, network: RelationNetwork) -> None:
        """
        The enumeration cap bounds the number of returned paths.

        :param network: The fixture network.
        """
        for index in range(3):
            add_relation(
                f"r_extra_{index}", network.cities, network.states, [("state_code", "code")]
            )
        graph = build_relation_graph(relation_manager())
        paths = all_shortest_paths(graph, network.cities.id(), network.states.id(), max_paths=2)
        assert len(paths) == 2


class TestValidatePinnedPath:
    """Tests for :func:`validate_pinned_path`."""

    def test_valid_pin(self, network: RelationNetwork) -> None:
        """
        The two-hop pin from districts to states validates into ordered hops.

        :param network: The fixture network.
        """
        hops = validate_pinned_path(
            network.graph,
            network.districts.id(),
            network.states.id(),
            ["r_districts_cities", "r_cities_states"],
        )
        assert [h.edge.relation_id for h in hops] == ["r_districts_cities", "r_cities_states"]
        assert hops[-1].to_layer_id == network.states.id()

    @pytest.mark.parametrize(
        ("relation_ids", "fragment"),
        [
            (["nope"], "unknown relation id"),
            (["r_cities_states"], "does not connect"),
            (["r_districts_cities"], "ends at layer"),
            ([], "empty"),
        ],
        ids=["unknown-id", "disconnected", "short-chain", "empty-pin"],
    )
    def test_invalid_pins(
        self, network: RelationNetwork, relation_ids: list[str], fragment: str
    ) -> None:
        """
        Broken pins raise :exc:`ValueError` naming the violation.

        :param network: The fixture network.
        :param relation_ids: The pinned chain under test.
        :param fragment: Substring expected in the error message.
        """
        with pytest.raises(ValueError, match=fragment):
            validate_pinned_path(
                network.graph, network.districts.id(), network.states.id(), relation_ids
            )

    def test_empty_pin_for_same_layer(self, network: RelationNetwork) -> None:
        """
        An empty pin is valid when source and target coincide.

        :param network: The fixture network.
        """
        assert not validate_pinned_path(
            network.graph, network.states.id(), network.states.id(), []
        )

    def test_hop_reversal_round_trip(self, network: RelationNetwork) -> None:
        """
        Reversing a hop twice restores it; fields swap sides in between.

        :param network: The fixture network.
        """
        (hop,) = all_shortest_paths(network.graph, network.cities.id(), network.states.id())[0]
        reverse = hop.reversed()
        assert isinstance(reverse, RelationHop)
        assert reverse.from_fields == hop.to_fields
        assert reverse.to_fields == hop.from_fields
        assert reverse.reversed() == hop
