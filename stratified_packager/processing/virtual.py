"""
Virtual-layer routing: materialize into the stratum gpkg vs. keep live (SPEC §4/§13).

A ``virtual`` provider layer is either materialized into its own packaged table (behaving like
any packaged vector) or kept live in the embedded project — re-pointed at this stratum's gpkg
tables — when every source it queries is already packaged. Runs on the algorithm thread during
Phase A layer classification.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from qgis.core import QgsProcessingException, QgsVirtualLayerDefinition
from qgis.PyQt.QtCore import QCoreApplication, QUrl

from stratified_packager.toolbelt.settings import LayerVariables
from stratified_packager.toolbelt.utils import coerce_bool

from . import params
from .dedup import normalized_source_key, source_group_key

if TYPE_CHECKING:
    from qgis.core import QgsMapLayer, QgsProcessingFeedback, QgsVectorLayer

__all__: list[str] = ["route_virtual_layers"]


def route_virtual_layers(
    virtuals: list[QgsVectorLayer],
    vectors: list[QgsVectorLayer],
    payloads: list[QgsMapLayer],
    embedded: list[QgsMapLayer],
    feedback: QgsProcessingFeedback,
) -> None:
    """
    Route virtual layers to packaged vectors (materialize) or embedded-only (live) (§4/§13).

    Mutates *vectors* / *embedded* in place; the coverage set is the already-classified
    packaged layers.

    :param virtuals: The collected ``virtual`` provider layers.
    :param vectors: Packaged vector layers (materialized virtuals are appended).
    :param payloads: Packaged payload layers (part of the coverage set).
    :param embedded: Embedded-only layers (live virtuals are appended).
    :param feedback: Execution feedback channel.
    """
    if not virtuals:
        return
    packaged_ids = frozenset(layer.id() for layer in (*vectors, *payloads))
    packaged_keys = frozenset(
        key for layer in vectors if (key := source_group_key(layer, feedback)) is not None
    )
    for layer in virtuals:
        target = (
            vectors
            if _virtual_should_materialize(layer, packaged_ids, packaged_keys, feedback)
            else embedded
        )
        target.append(layer)


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
