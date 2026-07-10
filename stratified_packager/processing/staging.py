"""
Per-layer staging decisions (SPEC §8.2).

Staging is no longer a correctness requirement. :class:`~qgis.core.QgsVectorFileWriter`
reads a layer through its QGIS provider, so memory providers, joins, virtual/expression
fields and unsaved edits are written directly, and per-stratum matching is computed against
the very layer that is written — the QGIS-fid ↔ OGR-FID equivalence problem that once forced
staging is gone. Staging is now a pure **read-amortization** optimization: a source read many
times (every ``whole_export`` layer, any layer of a ``STAGE_PROVIDERS`` provider, or any layer
the user marks) is copied once into a local GeoPackage holding only the features some stratum
uses (or every feature when ``EXPORT_FULL_PACKAGE`` is on, since the ``<full>`` stratum reads
the whole copy), and every stratum then reads its slice from that fast local copy instead of
re-fetching from a slow source.

The decision is the layer's tri-state ``stratified_packager_stage`` variable: ``true`` /
``false`` force it, unset (or ``auto``) stages iff the matching method is ``whole_export``
(the data that lands, identically, in every stratum) or the layer's data provider is in the
resolved ``STAGE_PROVIDERS`` set (a provider the user declared slow enough that every read
beyond the first must hit a local copy). The staging *write* itself reuses
:func:`~.building.write_vector_table`; this module only decides.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from stratified_packager.toolbelt.settings import LayerVariables
from stratified_packager.toolbelt.utils import coerce_bool

from .params import LAYER_VAR_STAGE, MatchingMethod

if TYPE_CHECKING:
    from collections.abc import Collection
    from pathlib import Path

    from qgis.core import QgsVectorLayer

__all__: list[str] = ["effective_stage", "staged_layer_uri"]


def effective_stage(
    layer: QgsVectorLayer, *, method: MatchingMethod, stage_providers: Collection[str]
) -> bool:
    """
    Resolve whether *layer*'s data is staged into a local GeoPackage (SPEC §8.2).

    The layer's ``stratified_packager_stage`` variable is tri-state: ``true``/``false`` force
    the decision; unset (or ``auto``) stages iff *method* is ``whole_export`` — the layer
    whose features land, identically, in every stratum — or the layer's data provider is in
    *stage_providers*, the resolved ``STAGE_PROVIDERS`` set of providers whose layers would
    otherwise be re-read from a slow source once per stratum.

    :param layer: The packaged vector layer.
    :param method: Its resolved matching method.
    :param stage_providers: The resolved ``STAGE_PROVIDERS`` provider keys.
    :return: Whether the layer is staged.
    :raise ValueError: If the variable holds a value that is neither boolean nor ``auto``.
    """
    raw = LayerVariables(layer).get(LAYER_VAR_STAGE)
    text = "" if raw is None else str(raw).strip().lower()
    if text in ("", "auto"):
        return method is MatchingMethod.WHOLE_EXPORT or layer.providerType() in stage_providers
    return coerce_bool(text)


def staged_layer_uri(staging_gpkg: Path, table: str, /) -> str:
    """
    Build the OGR uri of a staged table, for the algorithm thread's read layer.

    :param staging_gpkg: The staging GeoPackage.
    :param table: The staged table name.
    :return: The ``path|layername=table`` uri.
    """
    return f"{staging_gpkg}|layername={table}"
