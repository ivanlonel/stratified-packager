"""
Tests for :mod:`stratified_packager.processing.strata`.

Exercises the SPEC §6 strict regime on in-memory stratification layers: snapshot rules
(subset string, selection), naming (defaults, NULL/error/duplicate/collision aborts),
gpkg/zip path evaluation with the §6.4 variables, the §6.5 path rules and the §6.6
bundling rules.
"""
# pylint: disable=redefined-outer-name

from __future__ import annotations

import pytest

pytest.importorskip("qgis", reason="Strata resolution evaluates QGIS expressions.")

# Imported only after the importorskip guard above confirms QGIS is available.
from qgis.core import (
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsProcessingException,
    QgsProject,
    QgsVectorLayer,
)

from stratified_packager.processing.strata import (
    FULL_PACKAGE_KEY,
    evaluate_layer_display_name,
    resolve_strata,
)

pytestmark = pytest.mark.qgis
"""Marks the whole module as requiring a QGIS runtime."""


def _strat_layer(names: list[str], regions: list[str] | None = None) -> QgsVectorLayer:
    """
    Build a point stratification layer with ``name``/``region`` attributes.

    :param names: One feature per entry, ``name`` set to it.
    :param regions: Optional aligned ``region`` values (default ``r1``).
    :return: The memory layer (not yet added to the project).
    """
    layer = QgsVectorLayer(
        "Point?crs=EPSG:4326&field=name:string&field=region:string", "strata", "memory"
    )
    provider = layer.dataProvider()
    assert provider is not None
    features = []
    for index, name in enumerate(names):
        feature = QgsFeature(layer.fields())
        feature.setAttribute(0, name)
        feature.setAttribute(1, (regions or ["r1"] * len(names))[index])
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(index, 0)))
        features.append(feature)
    assert provider.addFeatures(features)
    return layer


@pytest.fixture
def project(qgis_new_project: QgsProject) -> QgsProject:
    """Return the clean per-test project provided by pytest-qgis."""
    return qgis_new_project


class TestSnapshotAndNaming:
    """Snapshot rules and the strict naming regime (SPEC §6.1/§6.2)."""

    def test_default_names_are_feature_ids(self, project: QgsProject) -> None:
        """An empty name expression names strata by feature id."""
        layer = _strat_layer(["a", "b"])
        resolution = resolve_strata(layer, project=project)
        assert [s.raw_name for s in resolution.strata] == ["1", "2"]
        assert [s.gpkg_rel for s in resolution.strata] == ["1", "2"]
        assert [s.zip_rel for s in resolution.strata] == ["1", "2"]

    def test_expression_names(self, project: QgsProject) -> None:
        """A field-based expression names and sanitizes the strata."""
        layer = _strat_layer(["North Region", "South/Region"])
        resolution = resolve_strata(layer, project=project, name_expression='"name"')
        assert [s.raw_name for s in resolution.strata] == ["North Region", "South/Region"]
        assert [s.name for s in resolution.strata] == ["North Region", "SouthRegion"]

    def test_subset_string_is_honored(self, project: QgsProject) -> None:
        """The snapshot sees only the subset (SPEC §6.1)."""
        layer = _strat_layer(["a", "b", "c"])
        assert layer.setSubsetString("\"name\" != 'b'")
        resolution = resolve_strata(layer, project=project, name_expression='"name"')
        assert [s.raw_name for s in resolution.strata] == ["a", "c"]

    def test_selection_restricts_when_enabled(self, project: QgsProject) -> None:
        """strata_from_selection restricts to the selection; an empty selection aborts."""
        layer = _strat_layer(["a", "b", "c"])
        layer.selectByExpression("\"name\" = 'b'")
        with_selection = resolve_strata(
            layer, project=project, name_expression='"name"', strata_from_selection=True
        )
        assert [s.raw_name for s in with_selection.strata] == ["b"]
        layer.removeSelection()
        # Fail-fast (SPEC §6.1/§15): never a silent full run on an empty selection.
        with pytest.raises(QgsProcessingException, match=r"no\s+selected features"):
            resolve_strata(
                layer, project=project, name_expression='"name"', strata_from_selection=True
            )

    def test_empty_layer_resolves_to_nothing(self, project: QgsProject) -> None:
        """An empty (post-filter) layer yields zero strata (SPEC §6.7)."""
        layer = _strat_layer(["a"])
        assert layer.setSubsetString("\"name\" = 'nope'")
        resolution = resolve_strata(layer, project=project)
        assert not resolution.strata
        assert resolution.bundles == {}

    def test_null_name_aborts(self, project: QgsProject) -> None:
        """A NULL name names the feature and aborts (SPEC §6.2)."""
        layer = _strat_layer(["a", "b"])
        with pytest.raises(QgsProcessingException, match="NULL for feature 2"):
            resolve_strata(
                layer,
                project=project,
                name_expression="CASE WHEN \"name\" = 'a' THEN 'x' ELSE NULL END",
            )

    def test_parse_error_aborts(self, project: QgsProject) -> None:
        """An unparsable name expression aborts."""
        layer = _strat_layer(["a"])
        with pytest.raises(QgsProcessingException, match="failed to parse"):
            resolve_strata(layer, project=project, name_expression="(((")

    def test_duplicate_raw_names_abort(self, project: QgsProject) -> None:
        """Duplicate raw names list the collisions (SPEC §6.2)."""
        layer = _strat_layer(["dup", "dup", "ok"])
        with pytest.raises(QgsProcessingException, match="Duplicate stratum names: 'dup'"):
            resolve_strata(layer, project=project, name_expression='"name"')

    @pytest.mark.parametrize(
        ("first", "second"),
        [("x:y", "x*y"), ("AB", "ab")],
        ids=["sanitize-equal", "case-insensitive"],
    )
    def test_sanitization_collisions_abort(
        self, project: QgsProject, first: str, second: str
    ) -> None:
        """
        Distinct raw names colliding after sanitization (case-insensitively) abort.

        :param project: The project fixture.
        :param first: First raw name.
        :param second: Second raw name colliding with it post-sanitization.
        """
        layer = _strat_layer([first, second])
        with pytest.raises(QgsProcessingException, match="collide after sanitization"):
            resolve_strata(layer, project=project, name_expression='"name"')

    def test_full_package_key_cannot_collide(self, project: QgsProject) -> None:
        """A raw name of ``<full>`` sanitizes away its brackets (SPEC §15)."""
        layer = _strat_layer(["<full>"])
        resolution = resolve_strata(layer, project=project, name_expression='"name"')
        assert resolution.strata[0].name == "full"
        assert resolution.strata[0].name != FULL_PACKAGE_KEY


class TestPathEvaluation:
    """gpkg/zip path expressions and the §6.4/§6.5 rules."""

    def test_gpkg_subdirectories_and_zip_default_at_root(self, project: QgsProject) -> None:
        """A gpkg subpath stays inside the zip; the default zip lands at the root."""
        layer = _strat_layer(["alpha", "beta"], regions=["north", "south"])
        resolution = resolve_strata(
            layer,
            project=project,
            name_expression='"name"',
            gpkg_path_expression="\"region\" || '/' || @stratum_name_sanitized",
        )
        assert [s.gpkg_rel for s in resolution.strata] == ["north/alpha", "south/beta"]
        # §6.4: the gpkg subpath never leaks into the output directory layout.
        assert [s.zip_rel for s in resolution.strata] == ["alpha", "beta"]

    def test_zip_expression_sees_gpkg_variables(self, project: QgsProject) -> None:
        """``@gpkg_path`` and ``@gpkg_name`` are visible to the zip expression."""
        layer = _strat_layer(["alpha"], regions=["north"])
        resolution = resolve_strata(
            layer,
            project=project,
            name_expression='"name"',
            gpkg_path_expression="\"region\" || '/' || @stratum_name_sanitized",
            zip_path_expression="@gpkg_path || '_of_' || @gpkg_name",
        )
        assert resolution.strata[0].zip_rel == "north/alpha_of_alpha"

    @pytest.mark.parametrize(
        "expression",
        ["'../escape'", "'C:/abs'", "'a//b'", "'CON'"],
        ids=["dotdot", "absolute", "empty-component", "reserved"],
    )
    def test_invalid_gpkg_paths_abort(self, project: QgsProject, expression: str) -> None:
        """
        §6.5 violations are reported, never sanitized.

        :param project: The project fixture.
        :param expression: A gpkg path expression evaluating to an invalid path.
        """
        layer = _strat_layer(["alpha"])
        with pytest.raises(QgsProcessingException, match="Invalid GeoPackage path"):
            resolve_strata(
                layer,
                project=project,
                name_expression='"name"',
                gpkg_path_expression=expression,
            )

    def test_null_path_aborts(self, project: QgsProject) -> None:
        """A NULL path expression result aborts."""
        layer = _strat_layer(["alpha"])
        with pytest.raises(QgsProcessingException, match="returned NULL"):
            resolve_strata(
                layer,
                project=project,
                name_expression='"name"',
                zip_path_expression="NULL",
            )


class TestLayerDisplayName:
    """Per-layer display-name expressions (SPEC §4/§13)."""

    def test_sees_stratum_and_layer_variables(self, project: QgsProject) -> None:
        """The expression resolves @stratum_name, @stratum_name_sanitized and @layer_name."""
        layer = _strat_layer(["ignored"])  # the helper names the layer "strata"
        name = evaluate_layer_display_name(
            layer,
            project,
            "@stratum_name || ' / ' || @stratum_name_sanitized || ' / ' || @layer_name",
            stratum_name="North/Region",
            stratum_name_sanitized="NorthRegion",
        )
        assert name == "North/Region / NorthRegion / strata"

    def test_parse_error_raises(self, project: QgsProject) -> None:
        """An unparsable expression aborts."""
        layer = _strat_layer(["x"])
        with pytest.raises(QgsProcessingException, match="failed to parse"):
            evaluate_layer_display_name(
                layer, project, "(((", stratum_name="s", stratum_name_sanitized="s"
            )

    def test_null_result_raises(self, project: QgsProject) -> None:
        """A NULL result names the layer and aborts."""
        layer = _strat_layer(["x"])
        with pytest.raises(QgsProcessingException, match="returned NULL for layer strata"):
            evaluate_layer_display_name(
                layer, project, "NULL", stratum_name="s", stratum_name_sanitized="s"
            )


class TestBundling:
    """Zip bundling and its uniqueness rules (SPEC §6.6)."""

    def test_strata_bundle_into_one_zip(self, project: QgsProject) -> None:
        """Identical zip paths bundle, member order preserved."""
        layer = _strat_layer(["a", "b", "c"])
        resolution = resolve_strata(
            layer,
            project=project,
            name_expression='"name"',
            zip_path_expression="'all_strata'",
        )
        assert set(resolution.bundles) == {"all_strata"}
        assert [s.raw_name for s in resolution.bundles["all_strata"]] == ["a", "b", "c"]

    def test_same_basename_in_different_subdirs_is_valid(self, project: QgsProject) -> None:
        """Identical gpkg basenames in different subdirectories may share a zip."""
        layer = _strat_layer(["a", "b"], regions=["north", "south"])
        resolution = resolve_strata(
            layer,
            project=project,
            name_expression='"name"',
            gpkg_path_expression="\"region\" || '/data'",
            zip_path_expression="'bundle'",
        )
        assert [s.gpkg_rel for s in resolution.bundles["bundle"]] == [
            "north/data",
            "south/data",
        ]

    def test_gpkg_collision_inside_bundle_aborts(self, project: QgsProject) -> None:
        """Case-insensitively equal gpkg paths in one zip abort."""
        layer = _strat_layer(["a", "b"])
        with pytest.raises(QgsProcessingException, match="collide inside zip"):
            resolve_strata(
                layer,
                project=project,
                name_expression='"name"',
                gpkg_path_expression=(
                    "CASE WHEN \"name\" = 'a' THEN 'sub/Pack' ELSE 'sub/pack' END"
                ),
                zip_path_expression="'bundle'",
            )

    def test_case_variant_zip_paths_abort(self, project: QgsProject) -> None:
        """Distinct zip paths differing only by case abort (Windows rule)."""
        layer = _strat_layer(["a", "b"])
        with pytest.raises(QgsProcessingException, match="differ only by letter case"):
            resolve_strata(
                layer,
                project=project,
                name_expression='"name"',
                zip_path_expression="CASE WHEN \"name\" = 'a' THEN 'Pack' ELSE 'pack' END",
            )
