"""
Tests for :mod:`stratified_packager.processing.reporting` (SPEC §9 row assembly).

The run-level and per-zip row builders are asserted end-to-end (on the produced REPORT layer
and the golden CSV) in ``test_algorithm``; here we cover the dedup-primary outcome indirection
in isolation with lightweight fakes.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

pytest.importorskip("qgis", reason="reporting imports qgis.core at module load.")

# Imported only after the importorskip guard above confirms QGIS is available.
from stratified_packager.processing.reporting import outcome_for

if TYPE_CHECKING:
    from stratified_packager.processing.building import LayerWriteResult
    from stratified_packager.processing.material import _BuildState, _LayerPrep

pytestmark = pytest.mark.qgis
"""Marks the whole module as requiring a QGIS runtime."""


def _prep(layer_id: str, primary_id: str | None) -> _LayerPrep:
    """Return a fake prep exposing only ``layer.id()`` and ``group_primary_id``."""
    fake = SimpleNamespace(layer=SimpleNamespace(id=lambda: layer_id), group_primary_id=primary_id)
    return cast("_LayerPrep", fake)


def _state(results: dict[tuple[str, str], LayerWriteResult]) -> _BuildState:
    """Return a fake build state carrying only ``layer_results``."""
    return cast("_BuildState", SimpleNamespace(layer_results=results))


class TestOutcomeFor:
    """`outcome_for` follows the §12 dedup-primary indirection."""

    def test_own_outcome_wins(self) -> None:
        """A layer with its own recorded outcome returns it directly."""
        outcome = cast("LayerWriteResult", object())
        state = _state({("north", "own"): outcome})
        assert outcome_for(state, "north", _prep("own", None)) is outcome

    def test_falls_back_to_group_primary(self) -> None:
        """A non-primary member with no own outcome reads its primary's."""
        outcome = cast("LayerWriteResult", object())
        state = _state({("north", "primary"): outcome})
        assert outcome_for(state, "north", _prep("member", "primary")) is outcome

    def test_missing_outcome_is_none(self) -> None:
        """An ungrouped layer with no recorded outcome returns None."""
        assert outcome_for(_state({}), "north", _prep("x", None)) is None
