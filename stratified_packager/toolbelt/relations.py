"""
Plugin-agnostic :class:`~qgis.core.QgsRelation` graph and pathfinding utilities.

Builds an undirected multigraph over a project's relation manager — nodes are layer ids,
edges are (non-polymorphic) relations with their ordered field pairs — and answers the
questions a partitioning engine asks of it: *all shortest* relation paths between two
layers (more than one ⇒ ambiguity the caller must surface) and validation of a
user-pinned relation chain.

Field pairs are read through :meth:`~qgis.core.QgsRelation.referencingFields` /
:meth:`~qgis.core.QgsRelation.referencedFields`, which preserve composite-key pair order
(``fieldPairs()`` does not — it is an unordered map).

Error messages raised here are plain (untranslated) strings; callers presenting them to
users are expected to wrap them into their own translated messages.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

from qgis.core import Qgis

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from qgis.core import QgsRelationManager

__all__: list[str] = [
    "RelationEdge",
    "RelationGraph",
    "RelationHop",
    "RelationPath",
    "all_shortest_paths",
    "build_relation_graph",
    "validate_pinned_path",
]


@dataclass(frozen=True)
class RelationEdge:
    """One usable relation, reduced to plain data."""

    relation_id: str
    """The relation's id in the relation manager."""

    name: str
    """The relation's display name."""

    referencing_layer_id: str
    """Layer id of the referencing (child) side."""

    referenced_layer_id: str
    """Layer id of the referenced (parent) side."""

    referencing_fields: tuple[str, ...]
    """Ordered key field names on the referencing side."""

    referenced_fields: tuple[str, ...]
    """Ordered key field names on the referenced side, pairwise with the referencing ones."""


@dataclass(frozen=True)
class RelationHop:
    """One traversal step over an edge, in a concrete direction."""

    edge: RelationEdge
    """The relation being traversed."""

    from_layer_id: str
    """Layer id the hop starts from."""

    to_layer_id: str
    """Layer id the hop arrives at."""

    @property
    def from_fields(self) -> tuple[str, ...]:
        """
        Key field names on the hop's start side.

        :return: The ordered key fields of the ``from`` layer.
        """
        if self.from_layer_id == self.edge.referencing_layer_id:
            return self.edge.referencing_fields
        return self.edge.referenced_fields

    @property
    def to_fields(self) -> tuple[str, ...]:
        """
        Key field names on the hop's arrival side.

        :return: The ordered key fields of the ``to`` layer.
        """
        if self.to_layer_id == self.edge.referencing_layer_id:
            return self.edge.referencing_fields
        return self.edge.referenced_fields

    def reversed(self) -> RelationHop:
        """
        Return the same edge traversed in the opposite direction.

        :return: The reversed hop.
        """
        return RelationHop(self.edge, self.to_layer_id, self.from_layer_id)


type RelationPath = tuple[RelationHop, ...]
"""An ordered chain of hops; empty when source and target are the same layer."""


class RelationGraph:
    """Undirected multigraph of layers (nodes) and relations (edges)."""

    def __init__(self, edges: Iterable[RelationEdge]) -> None:
        """
        Initialize the graph from plain edges.

        :param edges: The usable relation edges.
        """
        self._edges_by_id: dict[str, RelationEdge] = {}
        self._adjacency: defaultdict[str, list[RelationEdge]] = defaultdict(list)
        for edge in edges:
            self._edges_by_id[edge.relation_id] = edge
            self._adjacency[edge.referencing_layer_id].append(edge)
            self._adjacency[edge.referenced_layer_id].append(edge)

    @property
    def edges_by_id(self) -> Mapping[str, RelationEdge]:
        """
        All edges keyed by relation id.

        :return: A read-only view of the edge mapping.
        """
        return self._edges_by_id

    def edges_of(self, layer_id: str) -> tuple[RelationEdge, ...]:
        """
        Edges incident to *layer_id*.

        :param layer_id: The layer node.
        :return: The incident edges (empty for unknown layers).
        """
        return tuple(self._adjacency.get(layer_id, ()))

    def hops_from(self, layer_id: str) -> tuple[RelationHop, ...]:
        """
        Directed hops leaving *layer_id* (one per incident edge, both edge directions).

        A self-referencing relation (same layer on both sides) yields a single hop.

        :param layer_id: The layer node.
        :return: The outgoing hops.
        """
        hops: list[RelationHop] = []
        for edge in self.edges_of(layer_id):
            other = (
                edge.referenced_layer_id
                if edge.referencing_layer_id == layer_id
                else edge.referencing_layer_id
            )
            hops.append(RelationHop(edge, layer_id, other))
        return tuple(hops)


def build_relation_graph(manager: QgsRelationManager) -> RelationGraph:
    """
    Build the relation graph from a project's relation manager.

    Invalid relations are skipped. Generated relations (the children of polymorphic
    relations) are skipped as well — polymorphic relations are not traversable as
    plain key chains.

    :param manager: The project's relation manager.
    :return: The graph over all usable relations.
    """
    edges: list[RelationEdge] = []
    for relation in manager.relations().values():
        if not relation.isValid():
            continue
        if relation.type() == Qgis.RelationshipType.Generated:
            continue
        referencing = relation.referencingLayer()
        referenced = relation.referencedLayer()
        if referencing is None or referenced is None:
            continue  # cannot happen for a valid relation, but the API types are Optional
        referencing_fields = relation.referencingFields()
        referenced_fields = relation.referencedFields()
        edges.append(
            RelationEdge(
                relation_id=relation.id(),
                name=relation.name(),
                referencing_layer_id=relation.referencingLayerId(),
                referenced_layer_id=relation.referencedLayerId(),
                referencing_fields=tuple(
                    referencing.fields()[index].name() for index in referencing_fields
                ),
                referenced_fields=tuple(
                    referenced.fields()[index].name() for index in referenced_fields
                ),
            )
        )
    return RelationGraph(edges)


def all_shortest_paths(
    graph: RelationGraph, start: str, end: str, *, max_paths: int = 16
) -> list[RelationPath]:
    """
    Enumerate every shortest relation path from *start* to *end*.

    Cycles cannot extend a shortest path, so traversal terminates on any graph. More
    than one result means the choice is ambiguous and the caller must require a pin.

    :param graph: The relation graph.
    :param start: Source layer id.
    :param end: Target layer id.
    :param max_paths: Enumeration cap (ambiguity reporting needs only a few examples).
    :return: All shortest paths (capped), shortest first by construction; empty when no
        path exists; ``[()]`` when *start* equals *end*.
    """
    if start == end:
        return [()]
    distance: dict[str, int] = {start: 0}
    predecessors: defaultdict[str, list[RelationHop]] = defaultdict(list)
    queue: deque[str] = deque([start])
    while queue:
        node = queue.popleft()
        if node == end:
            continue  # hops beyond the target cannot lie on a shortest path to it
        for hop in graph.hops_from(node):
            successor = hop.to_layer_id
            if successor not in distance:
                distance[successor] = distance[node] + 1
                queue.append(successor)
            if distance[successor] == distance[node] + 1:
                predecessors[successor].append(hop)
    if end not in distance:
        return []

    paths: list[RelationPath] = []

    def backtrack(node: str, suffix: tuple[RelationHop, ...]) -> None:
        if len(paths) >= max_paths:
            return
        if node == start:
            paths.append(suffix)
            return
        for hop in predecessors[node]:
            backtrack(hop.from_layer_id, (hop, *suffix))

    backtrack(end, ())
    return paths


def validate_pinned_path(
    graph: RelationGraph, start: str, end: str, relation_ids: Sequence[str]
) -> RelationPath:
    """
    Validate a user-pinned relation chain from *start* to *end*.

    :param graph: The relation graph.
    :param start: Source layer id (the packaged layer).
    :param end: Target layer id (the stratification layer).
    :param relation_ids: Ordered relation ids, from *start* towards *end*.
    :return: The validated hops.
    :raise ValueError: If the pin is empty while the endpoints differ, names an unknown
        relation id, does not form a connected chain from *start*, or ends elsewhere
        than *end*.
    """
    if not relation_ids:
        if start == end:
            return ()
        msg = "pinned relation path is empty"
        raise ValueError(msg)
    hops: list[RelationHop] = []
    current = start
    for relation_id in relation_ids:
        edge = graph.edges_by_id.get(relation_id)
        if edge is None:
            msg = f"unknown relation id {relation_id!r} in pinned path"
            raise ValueError(msg)
        if edge.referencing_layer_id == current:
            successor = edge.referenced_layer_id
        elif edge.referenced_layer_id == current:
            successor = edge.referencing_layer_id
        else:
            msg = f"relation {relation_id!r} does not connect to layer {current!r}"
            raise ValueError(msg)
        hops.append(RelationHop(edge, current, successor))
        current = successor
    if current != end:
        msg = f"pinned path ends at layer {current!r} instead of {end!r}"
        raise ValueError(msg)
    return tuple(hops)
