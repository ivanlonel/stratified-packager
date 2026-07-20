"""
Virtual-layer routing: materialize into the stratum gpkg vs. keep live (SPEC §4/§13).

A ``virtual`` provider layer is either materialized into its own packaged table (behaving like
any packaged vector) or kept live in the embedded project — re-pointed at this stratum's gpkg
tables — when every source it queries is already packaged. Runs on the algorithm thread during
Phase A layer classification.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from qgis.core import QgsProcessingException, QgsVirtualLayerDefinition
from qgis.PyQt.QtCore import QCoreApplication, QUrl

from stratified_packager.toolbelt.settings import LayerVariables
from stratified_packager.toolbelt.utils import coerce_bool

from . import params
from .dedup import normalized_source_key, source_group_key

if TYPE_CHECKING:
    from qgis.core import QgsMapLayer, QgsProcessingFeedback, QgsProject, QgsVectorLayer

__all__: list[str] = ["route_virtual_layers"]

_LOCAL_PROVIDERS: Final[frozenset[str]] = frozenset(
    {"ogr", "gdal", "gpkg", "spatialite", "memory", "delimitedtext", "gpx", "mdal"}
)
"""Provider keys a virtual layer can query without leaving the machine.

Anything else — a database provider, a web service, or a nested ``virtual`` layer that may
itself reach one — makes the virtual query a remote round-trip generator when materialized."""


def route_virtual_layers(
    virtuals: list[QgsVectorLayer],
    vectors: list[QgsVectorLayer],
    payloads: list[QgsMapLayer],
    embedded: list[QgsMapLayer],
    project: QgsProject,
    feedback: QgsProcessingFeedback,
) -> None:
    """
    Route virtual layers to packaged vectors (materialize) or embedded-only (live) (§4/§13).

    Mutates *vectors* / *embedded* in place; the coverage set is the already-classified
    packaged layers. A layer routed to materialize is additionally checked for remote sources,
    which cost a warning but never change the routing.

    :param virtuals: The collected ``virtual`` provider layers.
    :param vectors: Packaged vector layers (materialized virtuals are appended).
    :param payloads: Packaged payload layers (part of the coverage set).
    :param embedded: Embedded-only layers (live virtuals are appended).
    :param project: The run's project (resolves referenced sources to their provider).
    :param feedback: Execution feedback channel.
    """
    if not virtuals:
        return
    packaged_ids = frozenset(layer.id() for layer in (*vectors, *payloads))
    packaged_keys = frozenset(
        key for layer in vectors if (key := source_group_key(layer, feedback)) is not None
    )
    for layer in virtuals:
        if _virtual_should_materialize(layer, packaged_ids, packaged_keys, feedback):
            _warn_remote_sources(layer, project, feedback)
            vectors.append(layer)
        else:
            embedded.append(layer)


def _warn_remote_sources(
    layer: QgsVectorLayer, project: QgsProject, feedback: QgsProcessingFeedback
) -> None:
    """
    Warn when a materialized virtual layer queries sources off the local machine (§4/§8.2).

    A materialized virtual layer is packaged like any vector, so its SQLite query is
    re-executed for every stratum — once to select the stratum's features and once more while
    the writer reads them. When a source is a database or service provider, each execution is a
    round-trip generator: SQLite cannot push a correlated subquery down, so it pulls the source
    through QGIS row by row, and concurrent scans can exhaust the provider's connection pool and
    wedge the run. Pushing the join into the source (a subset filter, view, or materialized
    view) turns the whole thing into one set-based query.

    Detection only — the layer is materialized exactly as it would have been.

    :param layer: The virtual layer being materialized.
    :param project: The run's project (resolves referenced sources to their provider).
    :param feedback: Execution feedback channel.
    """
    definition = QgsVirtualLayerDefinition.fromUrl(QUrl(layer.source()))
    remote: list[str] = []
    for source in definition.sourceLayers():
        if source.isReferenced():
            referenced = project.mapLayer(source.reference())
            provider = "" if referenced is None else referenced.providerType()
        else:
            provider = source.provider()
        if provider and provider not in _LOCAL_PROVIDERS:
            remote.append(f"{source.name()} ({provider})")
    if not remote:
        return
    feedback.pushWarning(
        QCoreApplication.translate(
            "StratifiedPackagerAlgorithm",
            "Virtual layer {} is materialized but queries non-local source(s) ({}). Its query"
            " re-runs against them for every stratum, which on a database provider means many"
            " round-trips and may exhaust the provider's connection pool. Consider pushing the"
            " join into the source — a subset filter, a view, or a materialized view — and"
            " packaging that layer instead.",
        ).format(layer.name(), ", ".join(remote))
    )


def _virtual_should_materialize(
    layer: QgsVectorLayer,
    packaged_ids: frozenset[str],
    packaged_keys: frozenset[tuple[str, frozenset[tuple[str, str]]]],
    feedback: QgsProcessingFeedback,
) -> bool:
    """
    Decide whether a ``virtual`` layer is materialized vs. kept live (SPEC §4/§13).

    The ``materialize_virtual_layer`` variable forces materialization when true. Otherwise
    the layer is kept live only when **every** source it queries is already packaged into the
    stratum gpkg (referenced by id to a packaged layer, or an embedded source normalizing to
    a packaged layer's source); any uncovered source would require adding new data, so the
    layer is materialized and an info message is pushed.

    :param layer: The ``virtual`` provider layer.
    :param packaged_ids: Layer ids of the packaged (vector + payload) layers.
    :param packaged_keys: Dedup source keys of the packaged vector layers.
    :param feedback: Execution feedback channel.
    :return: :data:`True` to materialize (route to packaged vectors), :data:`False` to keep
        the layer live (route to embedded-only).
    :raise qgis.core.QgsProcessingException: If the ``materialize_virtual_layer`` value
        cannot be coerced to bool (the §6 strict regime).
    """
    raw = LayerVariables(layer).get(params.LAYER_VAR_MATERIALIZE_VIRTUAL)
    if raw is not None:
        try:
            if coerce_bool(raw):
                return True
        except ValueError as err:
            raise QgsProcessingException(
                QCoreApplication.translate(
                    "StratifiedPackagerAlgorithm",
                    "layer {}: materialize_virtual_layer {} is not a boolean: {}",
                ).format(layer.name(), raw, err)
            ) from err
    definition = QgsVirtualLayerDefinition.fromUrl(QUrl(layer.source()))
    uncovered: list[str] = []
    for source in definition.sourceLayers():
        if source.isReferenced():
            covered = source.reference() in packaged_ids
        else:
            key = normalized_source_key(source.provider(), source.source(), layer.name(), feedback)
            covered = key is not None and key in packaged_keys
        if not covered:
            uncovered.append(source.name())
    if uncovered:
        feedback.pushInfo(
            QCoreApplication.translate(
                "StratifiedPackagerAlgorithm",
                "Virtual layer {} references sources not packaged ({}); materializing it"
                " instead of keeping it live in the embedded project.",
            ).format(layer.name(), ", ".join(uncovered))
        )
        return True
    return False
