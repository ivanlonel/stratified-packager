"""
Tests for :mod:`stratified_packager.processing.material` shared helpers.

The dataclasses are plain records exercised end-to-end in ``test_algorithm``; here we cover
the pure helpers (:func:`_field_indexes`, :func:`_warm_file_name`, :func:`_is_warm_marked`).
"""

from __future__ import annotations

import pytest

pytest.importorskip("qgis", reason="The helpers read QGIS layers and variables.")

# Imported only after the importorskip guard above confirms QGIS is available.
from qgis.core import QgsExpressionContextUtils, QgsProcessingException, QgsVectorLayer

from stratified_packager.processing import params as p
from stratified_packager.processing.material import (
    _field_indexes,
    _is_warm_marked,
    _warm_file_name,
)
from stratified_packager.processing.strata import FULL_PACKAGE_KEY

pytestmark = pytest.mark.qgis
"""Marks the whole module as requiring a QGIS runtime."""


def _layer() -> QgsVectorLayer:
    """Return a memory layer with fields ``a``, ``b``, ``c``."""
    layer = QgsVectorLayer(
        "Point?crs=EPSG:4326&field=a:integer&field=b:string&field=c:double", "pts", "memory"
    )
    assert layer.isValid()
    return layer


class TestFieldIndexes:
    """`_field_indexes` resolves names to schema indexes in field order."""

    def test_returns_indexes_in_field_order(self) -> None:
        """Requested names resolve to their indexes, ordered by the layer schema."""
        assert _field_indexes(_layer(), {"c", "a"}) == (0, 2)

    def test_unknown_names_are_ignored(self) -> None:
        """Names absent from the schema contribute no index."""
        assert _field_indexes(_layer(), {"a", "nope"}) == (0,)

    def test_empty_names_keep_every_field(self) -> None:
        """An empty name set yields an empty tuple (the writer keeps every field)."""
        assert not _field_indexes(_layer(), set())


class TestWarmFileName:
    """`_warm_file_name` maps the stratum key to its cache basename."""

    def test_full_package_uses_filename_safe_key(self) -> None:
        """``<full>`` maps to ``__full__`` (its bracket chars are illegal in filenames)."""
        assert _warm_file_name(FULL_PACKAGE_KEY) == "__full__"

    def test_plain_name_passes_through(self) -> None:
        """A sanitized stratum name is its own cache basename."""
        assert _warm_file_name("north") == "north"


class TestIsWarmMarked:
    """`_is_warm_marked` reads the layer variable with strict bool coercion (§4/§6)."""

    def test_unset_is_false(self) -> None:
        """A layer with no ``warm_marked`` variable is not warm."""
        assert _is_warm_marked(_layer()) is False

    @pytest.mark.parametrize("token", ["true", "t", "1", "yes"])
    def test_truthy_tokens_are_warm(self, token: str) -> None:
        """
        Every strict-truthy token marks the layer warm.

        :param token: A truthy variable value.
        """
        layer = _layer()
        QgsExpressionContextUtils.setLayerVariable(layer, p.LAYER_VAR_WARM_MARKED, token)
        assert _is_warm_marked(layer) is True

    def test_uncoercible_value_aborts(self) -> None:
        """A non-boolean value raises, matching every other boolean layer variable."""
        layer = _layer()
        QgsExpressionContextUtils.setLayerVariable(layer, p.LAYER_VAR_WARM_MARKED, "maybe")
        with pytest.raises(QgsProcessingException, match="warm_marked"):
            _is_warm_marked(layer)
