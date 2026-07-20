"""
Tests for :mod:`stratified_packager.processing.params`.

Exercises the SPEC §3 table: variable naming, the §5 resolution chain (variable >
setting > builtin, strict vs prefill modes), eligibility for the ``LAYERS`` prefill,
the automatic worker formula, and declaration of all parameters/outputs on a real
:class:`~qgis.core.QgsProcessingAlgorithm`.
"""
# pylint: disable=redefined-outer-name

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast, override

import pytest

pytest.importorskip("qgis", reason="Parameter declaration wraps the Processing framework.")

# Imported only after the importorskip guard above confirms QGIS is available.
from qgis.core import (
    Qgis,
    QgsExpressionContextUtils,
    QgsMapLayer,
    QgsProcessingAlgorithm,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsProject,
    QgsVectorLayer,
)

from stratified_packager.processing import params
from stratified_packager.processing.params import (
    MatchingMethod,
    OverwriteMode,
    ParamSpec,
    ProjectInclusion,
    StratifiedPackagerAlgorithmInputDict,
    StratifiedPackagerAlgorithmOutputDict,
    declare_outputs,
    declare_parameters,
    eligible_layer_ids,
    is_omitted,
    resolve_default,
    variable_name,
)

if TYPE_CHECKING:
    from qgis.core import QgsProcessingParameterEnum

    from stratified_packager.settings import StratifiedPackagerSettings

pytestmark = pytest.mark.qgis
"""Marks the whole module as requiring a QGIS runtime."""


def test_layer_variable_defaults_cover_layer_name() -> None:
    """The §4 ``layer_name`` variable is registered with an empty (inherit) default."""
    assert f"{params.VARIABLE_PREFIX}layer_name" == params.LAYER_VAR_LAYER_NAME
    assert params.LAYER_VARIABLE_DEFAULTS[params.LAYER_VAR_LAYER_NAME] == ""


@pytest.fixture
def project(qgis_new_project: QgsProject) -> QgsProject:
    """Return the clean per-test project provided by pytest-qgis."""
    return qgis_new_project


@pytest.fixture
def fake_settings() -> StratifiedPackagerSettings:
    """Return a duck-typed settings double carrying every ✓-row attribute."""
    # The resolver only getattr()s the ✓-row names, so a namespace suffices at runtime.
    return cast(
        "StratifiedPackagerSettings",
        SimpleNamespace(
            gpkg_path_expression="",
            zip_path_expression="",
            compression_level=3,
            overwrite_mode="error",
            project_inclusion="qgz",
            use_temp_folder=True,
            include_styles=True,
            style_categories="symbology,labeling",
            include_metadata=True,
            keep_empty_layers=True,
            deduplicate_shared_sources=True,
            stage_providers="",
            export_full_package=False,
            generate_report=True,
            warm_start_mode="off",
            write_checksums=False,
        ),
    )


class _DummyAlgorithm(QgsProcessingAlgorithm):
    """Minimal concrete algorithm hosting declared parameters in tests."""

    @override
    def name(self) -> str:
        """Return the algorithm name."""
        return "dummy"

    @override
    def displayName(self) -> str:
        """Return the display name."""
        return "dummy"

    @override
    def createInstance(self) -> _DummyAlgorithm:
        """Return a fresh instance."""
        return _DummyAlgorithm()

    @override
    def initAlgorithm(self, configuration: dict[str | None, Any] | None = None) -> None:
        """Declare nothing; tests call the declaration helpers explicitly."""

    @override
    def processAlgorithm(
        self,
        parameters: dict[str | None, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback | None,
    ) -> dict[str, Any]:
        """Return nothing; never executed in these tests."""
        return {}


class TestNamingAndContracts:
    """Tests for the naming rule and the typed contracts."""

    def test_variable_naming_rule(self) -> None:
        """Input X maps to stratified_packager_<x_lower>."""
        assert variable_name("COMPRESSION_LEVEL") == "stratified_packager_compression_level"

    def test_every_input_except_layers_has_a_variable(self) -> None:
        """Every non-multiple-layers input carries a project variable."""
        for name, spec in params.PARAM_SPECS.items():
            if name == params.LAYERS:
                assert spec.variable is None
            else:
                assert spec.variable == f"stratified_packager_{name.lower()}"

    def test_typed_dict_keys_match_the_spec_table(self) -> None:
        """The input/output TypedDicts mirror the SPEC §3 contracts."""
        # REPORT is a feature-sink destination — an input a caller passes, but not a
        # resolution-chain row, so it is in the InputDict yet absent from PARAM_SPECS.
        assert set(StratifiedPackagerAlgorithmInputDict.__annotations__) == (
            set(params.PARAM_SPECS) | {params.REPORT}
        )
        assert set(StratifiedPackagerAlgorithmOutputDict.__annotations__) == {
            params.OUTPUT_DIRECTORY,
            params.REPORT,
            params.ZIP_PATHS,
            params.STRATA_COUNT,
            params.ZIP_COUNT,
            params.FAILED_STRATA,
        }

    def test_enum_tokens(self) -> None:
        """The token enums carry exactly the SPEC §3/§4 tokens."""
        assert [m.value for m in OverwriteMode] == ["overwrite", "error", "skip-existing"]
        assert [m.value for m in ProjectInclusion] == ["none", "gpkg", "qgz"]
        assert [m.value for m in MatchingMethod] == [
            "auto",
            "attribute",
            "spatial",
            "whole_export",
        ]


class TestResolveDefault:
    """Tests for :func:`resolve_default` (the §5 chain tail)."""

    def test_builtin_tier(self) -> None:
        """With no project and no settings the builtin applies."""
        assert resolve_default(params.COMPRESSION_LEVEL) == 6
        assert resolve_default(params.OVERWRITE_MODE) == "overwrite"

    def test_setting_tier_overrides_builtin(
        self, fake_settings: StratifiedPackagerSettings
    ) -> None:
        """A plugin setting beats the builtin."""
        assert resolve_default(params.COMPRESSION_LEVEL, settings=fake_settings) == 3
        assert resolve_default(params.OVERWRITE_MODE, settings=fake_settings) == "error"
        assert resolve_default(params.PROJECT_INCLUSION, settings=fake_settings) == "qgz"

    def test_variable_tier_overrides_setting(
        self, project: QgsProject, fake_settings: StratifiedPackagerSettings
    ) -> None:
        """A project variable beats the setting; string coercions apply."""
        QgsExpressionContextUtils.setProjectVariable(
            project, "stratified_packager_compression_level", "9"
        )
        QgsExpressionContextUtils.setProjectVariable(
            project, "stratified_packager_keep_empty_layers", "false"
        )
        assert (
            resolve_default(params.COMPRESSION_LEVEL, project=project, settings=fake_settings) == 9
        )
        assert (
            resolve_default(params.KEEP_EMPTY_LAYERS, project=project, settings=fake_settings)
            is False
        )

    def test_strict_raises_on_bad_stored_values(
        self, project: QgsProject, fake_settings: StratifiedPackagerSettings
    ) -> None:
        """Strict mode names the offending tier instead of guessing."""
        QgsExpressionContextUtils.setProjectVariable(
            project, "stratified_packager_overwrite_mode", "nonsense"
        )
        with pytest.raises(ValueError, match="project variable"):
            resolve_default(params.OVERWRITE_MODE, project=project)
        fake_settings.project_inclusion = "garbage"
        with pytest.raises(ValueError, match="plugin setting"):
            resolve_default(params.PROJECT_INCLUSION, settings=fake_settings)

    def test_prefill_mode_falls_through_bad_values(
        self, project: QgsProject, fake_settings: StratifiedPackagerSettings
    ) -> None:
        """Non-strict (declaration) mode falls through to the next usable tier."""
        QgsExpressionContextUtils.setProjectVariable(
            project, "stratified_packager_overwrite_mode", "nonsense"
        )
        assert (
            resolve_default(
                params.OVERWRITE_MODE, project=project, settings=fake_settings, strict=False
            )
            == "error"
        )
        fake_settings.overwrite_mode = "also-garbage"
        assert (
            resolve_default(
                params.OVERWRITE_MODE, project=project, settings=fake_settings, strict=False
            )
            == "overwrite"
        )

    def test_empty_variable_is_ignored(self, project: QgsProject) -> None:
        """An empty-string variable falls through (unset semantics)."""
        QgsExpressionContextUtils.setProjectVariable(
            project, "stratified_packager_compression_level", ""
        )
        assert resolve_default(params.COMPRESSION_LEVEL, project=project) == 6

    def test_is_omitted(self) -> None:
        """Absent or None parameters count as omitted."""
        assert is_omitted({}, params.DRY_RUN)
        assert is_omitted({params.DRY_RUN: None}, params.DRY_RUN)
        assert not is_omitted({params.DRY_RUN: False}, params.DRY_RUN)


class TestStyleCategories:
    """Tests for the STYLE_CATEGORIES table, flag mapping and resolution (SPEC §8.1)."""

    def test_tokens_match_options_in_canonical_order(self) -> None:
        """The token tuple mirrors the option table, in bit order, without duplicates."""
        tokens = [option.token for option in params.STYLE_CATEGORY_OPTIONS]
        assert tuple(tokens) == params.STYLE_CATEGORY_TOKENS
        assert len(set(tokens)) == len(tokens) == 18
        assert list(params.STYLE_CATEGORY_TOKENS) == params.DEFAULT_STYLE_CATEGORIES

    def test_label_is_translated_on_access(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The label resolves at access, not at import: the translator installs afterwards."""
        option = params.STYLE_CATEGORY_OPTIONS[1]
        assert option.source_label == "Symbology"
        monkeypatch.setattr(
            params,
            "QCoreApplication",
            SimpleNamespace(translate=lambda ctx, text: f"{ctx}|{text}"),
        )
        # The runtime context must equal the QT_TRANSLATE_NOOP one, or the lookup misses.
        assert option.label == "StratifiedPackagerAlgorithm|Symbology"

    def test_empty_selection_means_all(self) -> None:
        """No (or all-unknown) tokens resolve to AllStyleCategories (select-none = select-all)."""
        every = QgsMapLayer.StyleCategory.AllStyleCategories
        assert params.style_categories_flags([]) == every
        assert params.style_categories_flags(["nope"]) == every

    def test_subset_ors_the_matching_flags(self) -> None:
        """A token subset ORs exactly the matching single-bit flags."""
        flags = params.style_categories_flags(["symbology", "labeling"])
        assert flags == (QgsMapLayer.StyleCategory.Symbology | QgsMapLayer.StyleCategory.Labeling)

    def test_setting_tier_coerces_csv_to_canonical_list(
        self, fake_settings: StratifiedPackagerSettings
    ) -> None:
        """A CSV setting resolves to the tokens in canonical order (input order ignored)."""
        fake_settings.style_categories = "labeling,symbology"
        assert resolve_default(params.STYLE_CATEGORIES, settings=fake_settings) == [
            "symbology",
            "labeling",
        ]

    def test_builtin_tier_is_every_category(self) -> None:
        """With nothing stored the builtin is every category."""
        assert resolve_default(params.STYLE_CATEGORIES) == list(params.STYLE_CATEGORY_TOKENS)

    def test_unknown_token_raises_in_strict_mode(
        self, fake_settings: StratifiedPackagerSettings
    ) -> None:
        """An unknown stored token aborts the run (fail-fast)."""
        fake_settings.style_categories = "symbology,bogus"
        with pytest.raises(ValueError, match="bogus"):
            resolve_default(params.STYLE_CATEGORIES, settings=fake_settings)

    def test_declared_as_optional_advanced_multi_static_enum(self) -> None:
        """STYLE_CATEGORIES is an optional, advanced, multi-select static-strings enum."""
        algorithm = _DummyAlgorithm()
        declare_parameters(algorithm)
        definition = cast(
            "QgsProcessingParameterEnum",
            next(
                d for d in algorithm.parameterDefinitions() if d.name() == params.STYLE_CATEGORIES
            ),
        )
        assert definition.usesStaticStrings()
        assert definition.allowMultiple()
        assert definition.options() == list(params.STYLE_CATEGORY_TOKENS)
        assert definition.defaultValue() == list(params.STYLE_CATEGORY_TOKENS)
        assert definition.flags() & Qgis.ProcessingParameterFlag.Advanced
        assert definition.flags() & Qgis.ProcessingParameterFlag.Optional


class TestStageProviders:
    """Tests for the ``STAGE_PROVIDERS`` multi-select and its coercion (SPEC §3/§8.2)."""

    def test_builtin_tier_is_empty(self) -> None:
        """With nothing stored, no provider is staged implicitly."""
        assert resolve_default(params.STAGE_PROVIDERS) == []

    def test_provider_keys_are_the_sorted_registry(self) -> None:
        """The multi-select options are the registry's provider keys, sorted."""
        keys = params.provider_keys()
        assert keys == sorted(keys)
        assert {"memory", "ogr"} <= set(keys)

    def test_setting_tier_coerces_csv_sorted_deduplicated(
        self, fake_settings: StratifiedPackagerSettings
    ) -> None:
        """A CSV setting resolves to sorted, deduplicated keys; blanks are dropped."""
        fake_settings.stage_providers = "ogr, memory,ogr,"
        assert resolve_default(params.STAGE_PROVIDERS, settings=fake_settings) == [
            "memory",
            "ogr",
        ]

    def test_variable_tier_overrides_setting(
        self, project: QgsProject, fake_settings: StratifiedPackagerSettings
    ) -> None:
        """A project variable beats the plugin setting."""
        fake_settings.stage_providers = "ogr"
        QgsExpressionContextUtils.setProjectVariable(
            project, "stratified_packager_stage_providers", "memory"
        )
        assert resolve_default(
            params.STAGE_PROVIDERS, project=project, settings=fake_settings
        ) == ["memory"]

    def test_unknown_key_raises_in_strict_mode(
        self, fake_settings: StratifiedPackagerSettings
    ) -> None:
        """A key outside the provider registry aborts the run (fail-fast)."""
        fake_settings.stage_providers = "memory,postgress"
        with pytest.raises(ValueError, match="postgress"):
            resolve_default(params.STAGE_PROVIDERS, settings=fake_settings)

    def test_declared_as_optional_advanced_multi_static_enum(self) -> None:
        """STAGE_PROVIDERS is an optional, advanced, multi-select static-strings enum."""
        algorithm = _DummyAlgorithm()
        declare_parameters(algorithm)
        definition = cast(
            "QgsProcessingParameterEnum",
            next(
                d for d in algorithm.parameterDefinitions() if d.name() == params.STAGE_PROVIDERS
            ),
        )
        assert definition.usesStaticStrings()
        assert definition.allowMultiple()
        assert definition.options() == params.provider_keys()
        assert definition.defaultValue() in ([], None)
        assert definition.flags() & Qgis.ProcessingParameterFlag.Advanced
        assert definition.flags() & Qgis.ProcessingParameterFlag.Optional


class TestEligibleLayers:
    """Tests for :func:`eligible_layer_ids`."""

    def test_exclude_variable_gates_membership(self, project: QgsProject) -> None:
        """Layers default to included; an explicit ``exclude=true`` drops them."""
        kept = QgsVectorLayer("Point?crs=EPSG:4326", "kept", "memory")
        excluded = QgsVectorLayer("Point?crs=EPSG:4326", "excluded", "memory")
        also_kept = QgsVectorLayer("NoGeometry?field=a:integer", "table", "memory")
        assert project.addMapLayers([kept, excluded, also_kept], addToLegend=False)
        QgsExpressionContextUtils.setLayerVariable(excluded, "stratified_packager_exclude", "true")
        QgsExpressionContextUtils.setLayerVariable(
            also_kept, "stratified_packager_exclude", "false"
        )
        assert set(eligible_layer_ids(project)) == {kept.id(), also_kept.id()}

    def test_raises_on_uncoercible_exclude(self, project: QgsProject) -> None:
        """A non-bool ``exclude`` aborts the run instead of guessing inclusion."""
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "bad", "memory")
        assert project.addMapLayers([layer], addToLegend=False)
        QgsExpressionContextUtils.setLayerVariable(layer, "stratified_packager_exclude", "maybe")
        with pytest.raises(ValueError, match="exclude variable"):
            eligible_layer_ids(project)


class TestDeclaration:
    """Tests for :func:`declare_parameters` and :func:`declare_outputs`."""

    @pytest.fixture
    def algorithm(
        self, project: QgsProject, fake_settings: StratifiedPackagerSettings
    ) -> _DummyAlgorithm:
        """Return a dummy algorithm with everything declared against the live project."""
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "eligible", "memory")
        assert project.addMapLayer(layer, addToLegend=False)
        algorithm = _DummyAlgorithm()
        declare_parameters(
            algorithm,
            project=project,
            settings=fake_settings,
        )
        declare_outputs(algorithm)
        return algorithm

    def test_all_inputs_declared_in_spec_order(self, algorithm: _DummyAlgorithm) -> None:
        """Every SPEC §3 input is declared in table order, plus the REPORT sink."""
        names = [d.name() for d in algorithm.parameterDefinitions()]
        assert params.REPORT in names
        assert [name for name in names if name != params.REPORT] == list(params.PARAM_SPECS)

    def test_defaults_flow_through_the_chain(self, algorithm: _DummyAlgorithm) -> None:
        """Declared defaults reflect the setting tier; ``LAYERS`` carries none."""
        definitions = {d.name(): d for d in algorithm.parameterDefinitions()}
        assert definitions[params.COMPRESSION_LEVEL].defaultValue() == 3
        assert definitions[params.OVERWRITE_MODE].defaultValue() == "error"
        assert definitions[params.PROJECT_INCLUSION].defaultValue() == "qgz"

    def test_layers_declares_no_default(
        self, algorithm: _DummyAlgorithm, project: QgsProject
    ) -> None:
        """
        ``LAYERS`` must stay defaultless even with a project (SPEC §5).

        Regression: an id-list default was rewritten by the multiple-layers widget wrapper
        into one *source* string per layer, and source-keyed resolution answered every
        string of a shared source with the same layer — silently dropping every §12
        shared-source sibling from a GUI run.
        """
        assert eligible_layer_ids(project)  # the project would have prefilled something
        definitions = {d.name(): d for d in algorithm.parameterDefinitions()}
        assert definitions[params.LAYERS].defaultValue() in ([], None)

    def test_enum_parameters_use_static_tokens(self, algorithm: _DummyAlgorithm) -> None:
        """Enum parameters run in static-strings mode with the SPEC tokens."""
        definition = cast(
            "QgsProcessingParameterEnum",
            next(d for d in algorithm.parameterDefinitions() if d.name() == params.OVERWRITE_MODE),
        )
        assert definition.usesStaticStrings()
        assert definition.options() == [m.value for m in OverwriteMode]

    def test_advanced_flags(self, algorithm: _DummyAlgorithm) -> None:
        """Tuning parameters are flagged advanced; headline ones are not."""
        definitions = {d.name(): d for d in algorithm.parameterDefinitions()}
        assert definitions[params.USE_TEMP_FOLDER].flags() & Qgis.ProcessingParameterFlag.Advanced
        assert not (
            definitions[params.OUTPUT_DIRECTORY].flags() & Qgis.ProcessingParameterFlag.Advanced
        )

    def test_outputs_declared(self, algorithm: _DummyAlgorithm) -> None:
        """All six SPEC §3 outputs are declared."""
        names = {o.name() for o in algorithm.outputDefinitions()}
        assert names == {
            params.OUTPUT_DIRECTORY,
            params.REPORT,
            params.ZIP_PATHS,
            params.STRATA_COUNT,
            params.ZIP_COUNT,
            params.FAILED_STRATA,
        }

    def test_param_spec_is_frozen(self) -> None:
        """The spec table rows are immutable value objects."""
        spec = params.PARAM_SPECS[params.DRY_RUN]
        assert isinstance(spec, ParamSpec)
        with pytest.raises(AttributeError):
            spec.builtin = True  # type: ignore[misc]  # ty: ignore[invalid-assignment]  # frozen probe


def test_resolve_default_empty_setting_falls_through_to_builtin(
    fake_settings: StratifiedPackagerSettings,
) -> None:
    """An empty stored setting means unset: the builtin applies, mirroring the variable tier."""
    fake_settings.style_categories = ""
    assert (
        resolve_default(params.STYLE_CATEGORIES, settings=fake_settings)
        == params.PARAM_SPECS[params.STYLE_CATEGORIES].builtin
    )
