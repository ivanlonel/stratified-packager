"""
Tests for :mod:`stratified_packager.processing.building`.

Exercises the algorithm-thread write engine (SPEC §8.3): spatial and whole-export per-stratum
writes (with the clone-isolation guarantee — the user's layer is never touched), empty-table
handling, the field-subset writer, the whole-export template, and per-layer staging.
"""
# pylint: disable=redefined-outer-name

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

pytest.importorskip("qgis", reason="building.py wraps QgsVectorFileWriter and the QGIS provider.")

# Imported only after the importorskip guard above confirms QGIS is available.
from qgis.core import (
    QgsFeature,
    QgsGeometry,
    QgsProcessingException,
    QgsProcessingFeedback,
    QgsProject,
    QgsVectorLayer,
)

from stratified_packager.processing.building import (
    LayerWrite,
    StratumBuild,
    StyleDoc,
    discard_gpkg,
    stage_union,
    warm_rejection,
    write_stratum,
    write_template,
    write_vector_table,
)
from stratified_packager.processing.matching import LayerMatchPlan
from stratified_packager.processing.params import MatchingMethod
from stratified_packager.toolbelt import gpkg

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

pytestmark = pytest.mark.qgis
"""Marks the whole module as requiring a QGIS runtime."""


def _points(name: str, points: list[tuple[int, float, float]]) -> QgsVectorLayer:
    """
    Build a point memory layer with an integer ``pid`` and a string ``note``.

    :param name: Layer name.
    :param points: ``(pid, x, y)`` triples, one feature each.
    :return: The populated layer.
    """
    layer = QgsVectorLayer(
        "Point?crs=EPSG:4326&field=pid:integer&field=note:string", name, "memory"
    )
    provider = layer.dataProvider()
    assert provider is not None
    features = []
    for pid, x, y in points:
        feature = QgsFeature(layer.fields())
        feature.setAttributes([pid, f"n{pid}"])
        feature.setGeometry(QgsGeometry.fromWkt(f"POINT({x} {y})"))
        features.append(feature)
    assert provider.addFeatures(features)
    layer.updateExtents()
    return layer


def _stratum() -> tuple[QgsVectorLayer, QgsFeature]:
    """
    Build a one-feature polygon stratification layer covering ``0 0`` … ``5 5``.

    :return: ``(layer, the single stratum feature)``.
    """
    layer = QgsVectorLayer("Polygon?crs=EPSG:4326&field=sid:integer", "strat", "memory")
    provider = layer.dataProvider()
    assert provider is not None
    feature = QgsFeature(layer.fields())
    feature.setAttributes([1])
    feature.setGeometry(QgsGeometry.fromWkt("POLYGON((0 0,0 5,5 5,5 0,0 0))"))
    assert provider.addFeature(feature)
    layer.updateExtents()
    feature = next(iter(cast("Iterable[QgsFeature]", layer.getFeatures())))
    return layer, feature


def _spatial_plan(layer: QgsVectorLayer) -> LayerMatchPlan:
    """Return an ``intersects`` spatial plan for *layer*."""
    return LayerMatchPlan(
        layer_id=layer.id(), method=MatchingMethod.SPATIAL, predicates=("intersects",)
    )


def _clone(layer: QgsVectorLayer) -> QgsVectorLayer:
    """Return a non-None standalone clone (narrows the stub's ``QgsVectorLayer | None``)."""
    clone = layer.clone()
    assert clone is not None
    return clone


@pytest.fixture
def feedback() -> QgsProcessingFeedback:
    """Return a plain feedback sink."""
    return QgsProcessingFeedback()


@pytest.fixture
def project() -> QgsProject:
    """Return the QGIS project (supplies the transform context)."""
    instance = QgsProject.instance()
    assert instance is not None
    return instance


def test_write_stratum_spatial_selects_inside(
    tmp_path: Path, feedback: QgsProcessingFeedback, project: QgsProject
) -> None:
    """A spatial stratum writes only the matching features and never touches the user's layer."""
    strat, strat_feat = _stratum()
    points = _points("pts", [(10, 1, 1), (11, 2, 2), (12, 7, 2)])
    layer_write = LayerWrite(
        layer_id=points.id(),
        table="pts",
        read_layer=_clone(points),
        members=(_spatial_plan(points),),
        kept_field_indexes=(),
    )
    out = tmp_path / "s1.gpkg"
    result = write_stratum(
        StratumBuild(name="s1", gpkg_path=out, layers=(layer_write,), stratum_feature=strat_feat),
        project=project,
        strat_layer=strat,
        feedback=feedback,
    )
    assert result.ok, result.error
    (row,) = result.layers
    assert row.feature_count == 2
    assert row.status == "ok"
    assert points.selectedFeatureCount() == 0  # the user's layer is never selected on
    assert gpkg.feature_count(out, "pts") == 2


def test_write_stratum_whole_export_writes_all(
    tmp_path: Path, feedback: QgsProcessingFeedback, project: QgsProject
) -> None:
    """A whole-export layer ignores the (absent) stratum feature and writes every feature."""
    points = _points("pts", [(10, 1, 1), (11, 9, 9)])
    layer_write = LayerWrite(
        layer_id=points.id(),
        table="pts",
        read_layer=_clone(points),
        members=(LayerMatchPlan(layer_id=points.id(), method=MatchingMethod.WHOLE_EXPORT),),
        kept_field_indexes=(),
        whole_export=True,
    )
    out = tmp_path / "full.gpkg"
    result = write_stratum(
        StratumBuild(name="full", gpkg_path=out, layers=(layer_write,), stratum_feature=None),
        project=project,
        strat_layer=None,
        feedback=feedback,
    )
    assert result.ok, result.error
    assert result.layers[0].feature_count == 2


def test_write_stratum_empty_match_dropped(
    tmp_path: Path, feedback: QgsProcessingFeedback, project: QgsProject
) -> None:
    """A stratum matching nothing yields an empty table, dropped when keep_if_empty is false."""
    strat, strat_feat = _stratum()
    points = _points("pts", [(12, 7, 2)])  # outside the stratum polygon
    layer_write = LayerWrite(
        layer_id=points.id(),
        table="pts",
        read_layer=_clone(points),
        members=(_spatial_plan(points),),
        kept_field_indexes=(),
        keep_if_empty=False,
    )
    out = tmp_path / "s1.gpkg"
    result = write_stratum(
        StratumBuild(name="s1", gpkg_path=out, layers=(layer_write,), stratum_feature=strat_feat),
        project=project,
        strat_layer=strat,
        feedback=feedback,
    )
    assert result.ok, result.error
    assert result.layers[0].status == "empty-skipped"
    assert "pts" not in gpkg.layer_names(out)


def test_write_vector_table_drops_excluded_fields(
    tmp_path: Path, feedback: QgsProcessingFeedback
) -> None:
    """``kept_field_indexes`` exports only the named columns."""
    points = _points("pts", [(10, 1, 1)])
    out = tmp_path / "t.gpkg"
    write_vector_table(
        out, _clone(points), "pts", kept_field_indexes=(0,), only_selected=False, feedback=feedback
    )
    reopened = QgsVectorLayer(f"{out}|layername=pts", "x", "ogr")
    assert reopened.isValid()
    names = [field.name() for field in reopened.fields().toList()]
    assert "pid" in names
    assert "note" not in names


def test_write_template_then_seed(
    tmp_path: Path, feedback: QgsProcessingFeedback, project: QgsProject
) -> None:
    """The template holds whole-export data; a template-seeded stratum carries it un-rewritten."""
    points = _points("base", [(10, 1, 1), (11, 2, 2)])
    layer_write = LayerWrite(
        layer_id=points.id(),
        table="base",
        read_layer=_clone(points),
        members=(LayerMatchPlan(layer_id=points.id(), method=MatchingMethod.WHOLE_EXPORT),),
        kept_field_indexes=(),
        whole_export=True,
        styles=(StyleDoc(name="base", qml="<qgis/>"),),
    )
    template = tmp_path / "template.gpkg"
    write_template(template, [layer_write], feedback=feedback)
    assert gpkg.feature_count(template, "base") == 2

    out = tmp_path / "s1.gpkg"
    result = write_stratum(
        StratumBuild(
            name="s1",
            gpkg_path=out,
            layers=(layer_write,),
            stratum_feature=None,
            template=template,
        ),
        project=project,
        strat_layer=None,
        feedback=feedback,
    )
    assert result.ok, result.error
    assert result.layers[0].feature_count == 2
    assert gpkg.feature_count(out, "base") == 2


@pytest.mark.parametrize(
    ("keep_if_empty", "status", "kept"),
    [(True, "warm", True), (False, "empty-skipped", False)],
)
def test_warm_seeded_empty_table_honors_keep_if_empty(
    tmp_path: Path,
    feedback: QgsProcessingFeedback,
    project: QgsProject,
    keep_if_empty: bool,
    status: str,
    kept: bool,
) -> None:
    """An empty warm-seeded table stays ``warm`` or is dropped, per the deliverable's policy."""
    strat, strat_feat = _stratum()
    points = _points("pts", [(12, 7, 2)])  # outside the stratum polygon
    seed_source = _clone(points)
    seed_source.removeSelection()
    warm = tmp_path / "warm.gpkg"
    # An empty selection writes an empty table: the §11 cache always keeps empty warm tables.
    write_vector_table(warm, seed_source, "pts", only_selected=True, feedback=feedback)
    layer_write = LayerWrite(
        layer_id=points.id(),
        table="pts",
        read_layer=_clone(points),
        members=(_spatial_plan(points),),
        kept_field_indexes=(),
        warm_marked=True,
        keep_if_empty=keep_if_empty,
    )
    out = tmp_path / "s1.gpkg"
    result = write_stratum(
        StratumBuild(
            name="s1",
            gpkg_path=out,
            layers=(layer_write,),
            stratum_feature=strat_feat,
            warm_start=warm,
            expected_warm_tables=("pts",),
        ),
        project=project,
        strat_layer=strat,
        feedback=feedback,
    )
    assert result.ok, result.error
    assert result.warm_used
    assert result.layers[0].status == status
    assert ("pts" in gpkg.layer_names(out)) is kept


def test_template_seed_still_writes_warm_marked_whole_export(
    tmp_path: Path, feedback: QgsProcessingFeedback, project: QgsProject
) -> None:
    """A warm-marked whole-export layer never rides the template, so a template seed writes it."""
    base = _points("base", [(10, 1, 1), (11, 2, 2)])
    warm_points = _points("roads", [(20, 3, 3)])
    base_write = LayerWrite(
        layer_id=base.id(),
        table="base",
        read_layer=_clone(base),
        members=(LayerMatchPlan(layer_id=base.id(), method=MatchingMethod.WHOLE_EXPORT),),
        kept_field_indexes=(),
        whole_export=True,
    )
    warm_write = LayerWrite(
        layer_id=warm_points.id(),
        table="roads",
        read_layer=_clone(warm_points),
        members=(LayerMatchPlan(layer_id=warm_points.id(), method=MatchingMethod.WHOLE_EXPORT),),
        kept_field_indexes=(),
        whole_export=True,
        warm_marked=True,
    )
    template = tmp_path / "template.gpkg"
    write_template(template, [base_write], feedback=feedback)  # warm-marked excluded (§8.1.5)

    out = tmp_path / "s1.gpkg"
    result = write_stratum(
        StratumBuild(
            name="s1",
            gpkg_path=out,
            layers=(warm_write, base_write),  # §8.3 order: warm-marked first
            stratum_feature=None,
            template=template,
        ),
        project=project,
        strat_layer=None,
        feedback=feedback,
    )
    assert result.ok, result.error
    assert gpkg.feature_count(out, "roads") == 1  # silently missing before the fix
    assert gpkg.feature_count(out, "base") == 2
    statuses = {row.table: row.status for row in result.layers}
    assert statuses["roads"] == "ok"


def test_warm_rejection_names_the_cold_fallback_trigger(tmp_path: Path) -> None:
    """The §11 completeness check flags a missing file and table drift, else passes."""
    feedback = QgsProcessingFeedback()
    warm = tmp_path / "warm.gpkg"
    write_vector_table(
        warm, _points("pts", [(1, 0.0, 0.0)]), "pts", only_selected=False, feedback=feedback
    )

    assert warm_rejection(None, ("pts",)) == "warm file is missing"
    assert warm_rejection(tmp_path / "absent.gpkg", ("pts",)) == "warm file is missing"
    assert warm_rejection(warm, ("pts",)) is None
    assert "lacks expected" in (warm_rejection(warm, ("pts", "more")) or "")
    assert "non-warm-marked" in (warm_rejection(warm, ()) or "")


def test_stage_union_holds_only_matched(
    tmp_path: Path, feedback: QgsProcessingFeedback, project: QgsProject
) -> None:
    """A per-layer staging copy holds the union of every stratum's matches, nothing else."""
    strat, strat_feat = _stratum()
    points = _points("pts", [(10, 1, 1), (11, 2, 2), (12, 7, 2)])  # 12 is outside every stratum
    staging = tmp_path / "pts_staging.gpkg"
    stage_union(
        staging,
        _clone(points),
        "pts",
        (_spatial_plan(points),),
        [strat_feat],
        project=project,
        strat_layer=strat,
        feedback=feedback,
    )
    # Only the two points inside the stratum are staged; the orphan (12) is not.
    assert gpkg.feature_count(staging, "pts") == 2


def test_discard_swallows_the_oserror_a_locked_gpkg_raises(tmp_path: Path) -> None:
    """Cleanup of a partial gpkg never raises, so a failed/canceled write can't crash the run."""
    # A directory can't be unlinked (PermissionError on Windows, IsADirectoryError on POSIX) — a
    # portable stand-in for the Windows case where the aborted writer still holds the file open.
    discarded = discard_gpkg(tmp_path)
    assert not discarded
    assert tmp_path.is_dir()  # the undeletable path is left for the workdir teardown / the OS


def test_write_vector_table_maps_a_canceled_writer_error_to_cancellation(tmp_path: Path) -> None:
    """A writer error while the feedback is canceled reports as cancellation, not a failure."""
    layer = _points("pts", [(1, 1.0, 1.0)])
    feedback = QgsProcessingFeedback()
    feedback.cancel()
    bad_path = tmp_path / "missing" / "out.gpkg"  # no parent dir ⇒ the writer errors
    with pytest.raises(QgsProcessingException, match="canceled"):
        write_vector_table(bad_path, layer, "pts", only_selected=False, feedback=feedback)


def test_write_vector_table_reports_a_genuine_write_failure(tmp_path: Path) -> None:
    """A writer error without cancellation surfaces as a table-write failure."""
    layer = _points("pts", [(1, 1.0, 1.0)])
    feedback = QgsProcessingFeedback()
    bad_path = tmp_path / "missing" / "out.gpkg"
    with pytest.raises(QgsProcessingException, match="failed"):
        write_vector_table(bad_path, layer, "pts", only_selected=False, feedback=feedback)
