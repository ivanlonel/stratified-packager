"""
Tests for :mod:`stratified_packager.processing.staging`.

Staging is now a per-layer read-amortization decision (SPEC §8.2): the tri-state
``stratified_packager_stage`` variable plus the ``STAGE_PROVIDERS`` provider set and the
staged-uri helper. The staging *write* itself is covered by ``test_building.py`` (it reuses
``building.write_vector_table``).
"""
# pylint: disable=redefined-outer-name

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

pytest.importorskip("qgis", reason="effective_stage reads a layer variable via the QGIS API.")

# Imported only after the importorskip guard above confirms QGIS is available.
from qgis.core import QgsVectorLayer

from stratified_packager.processing.params import LAYER_VAR_STAGE, MatchingMethod
from stratified_packager.processing.staging import effective_stage, staged_layer_uri
from stratified_packager.toolbelt.settings import LayerVariables

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.qgis
"""Marks the whole module as requiring a QGIS runtime."""


@pytest.fixture
def layer() -> QgsVectorLayer:
    """Return a tiny point memory layer with the stage variable unset."""
    return QgsVectorLayer("Point?crs=EPSG:4326&field=a:integer", "L", "memory")


class TestEffectiveStage:
    """The tri-state ``stage`` decision (SPEC §8.2/§4)."""

    @pytest.mark.parametrize(
        ("method", "expected"),
        [
            (MatchingMethod.WHOLE_EXPORT, True),
            (MatchingMethod.SPATIAL, False),
            (MatchingMethod.ATTRIBUTE, False),
        ],
    )
    def test_auto_stages_only_whole_export(
        self, layer: QgsVectorLayer, method: MatchingMethod, expected: bool
    ) -> None:
        """
        Unset/auto with an empty provider set stages iff the method is ``whole_export``.

        :param layer: The packaged layer (stage variable unset).
        :param method: The resolved matching method.
        :param expected: Whether the layer is staged.
        """
        assert effective_stage(layer, method=method, stage_providers=frozenset()) is expected

    @pytest.mark.parametrize(
        ("providers", "expected"),
        [
            (frozenset({"memory"}), True),
            (frozenset({"memory", "postgres"}), True),
            (frozenset({"postgres"}), False),
            (frozenset(), False),
        ],
    )
    def test_auto_stages_the_selected_providers(
        self, layer: QgsVectorLayer, providers: frozenset[str], expected: bool
    ) -> None:
        """
        Unset/auto stages a partitioned layer iff its provider is in ``STAGE_PROVIDERS``.

        :param layer: The packaged layer (a ``memory``-provider layer, stage unset).
        :param providers: The resolved ``STAGE_PROVIDERS`` set.
        :param expected: Whether the layer is staged.
        """
        assert (
            effective_stage(layer, method=MatchingMethod.SPATIAL, stage_providers=providers)
            is expected
        )

    def test_provider_type_survives_an_unconnectable_layer(self) -> None:
        """
        The provider check reads ``providerType()``, which an invalid layer still reports.

        A ``postgres`` layer without a reachable database is exactly the situation on a CI
        machine; the decision must not require a live connection.
        """
        remote = QgsVectorLayer('dbname=\'x\' table="s"."t" (geom)', "P", "postgres")
        assert not remote.isValid()
        assert (
            effective_stage(
                remote, method=MatchingMethod.ATTRIBUTE, stage_providers=frozenset({"postgres"})
            )
            is True
        )

    @pytest.mark.parametrize(
        ("value", "expected"), [("true", True), ("false", False), ("auto", True)]
    )
    def test_explicit_override_beats_the_provider_set(
        self, layer: QgsVectorLayer, value: str, expected: bool
    ) -> None:
        """
        An explicit ``true``/``false`` overrides the provider set; ``auto`` defers to it.

        :param layer: The packaged layer (its ``memory`` provider is in the set).
        :param value: The stored stage value.
        :param expected: The decision for a spatial (partitioned) layer.
        """
        LayerVariables(layer)[LAYER_VAR_STAGE] = value
        assert (
            effective_stage(
                layer, method=MatchingMethod.SPATIAL, stage_providers=frozenset({"memory"})
            )
            is expected
        )

    def test_invalid_value_raises(self, layer: QgsVectorLayer) -> None:
        """A non-boolean, non-``auto`` value fails fast."""
        LayerVariables(layer)[LAYER_VAR_STAGE] = "maybe"
        with pytest.raises(ValueError):  # noqa: PT011  # coerce_bool's message is the detail
            effective_stage(layer, method=MatchingMethod.SPATIAL, stage_providers=frozenset())


def test_staged_layer_uri(tmp_path: Path) -> None:
    """The staged uri is ``path|layername=table``."""
    gpkg = tmp_path / "s.gpkg"
    assert staged_layer_uri(gpkg, "t") == f"{gpkg}|layername=t"
