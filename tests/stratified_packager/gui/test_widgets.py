"""
Tests for the reusable defaults-GUI scope editors (:mod:`stratified_packager.gui.widgets`).

Usage from the repo root folder:

.. code-block:: bash

    pytest tests/stratified_packager/gui/test_widgets.py
"""

from __future__ import annotations

import json
from typing import Never

import pytest

pytest.importorskip("qgis", reason="the editors are Qt widgets; need a QApplication.")

# Imported only after the importorskip guard above confirms QGIS is available.
from qgis.core import QgsProject, QgsVectorLayer
from qgis.gui import QgsCheckableComboBox
from qgis.PyQt.QtGui import QFontMetrics
from qgis.PyQt.QtWidgets import QComboBox

from stratified_packager.gui.widgets import (
    PROJECT_FIELD_STRATIFICATION_LAYER,
    PROJECT_FIELD_STRATUM_NAME_EXPRESSION,
    FieldKind,
    FieldSpec,
    OverrideCheckableCombo,
    OverrideCheckBox,
    OverrideComboBox,
    OverrideExpressionEdit,
    OverrideFieldsCombo,
    OverrideLayerCombo,
    OverrideLineEdit,
    OverridePredicateCombo,
    OverrideSpinBox,
    concrete_value,
    default_fields,
    inherit_placeholder,
    layer_fields,
    make_concrete_editor,
    make_override_editor,
    project_only_fields,
    set_concrete_value,
)
from stratified_packager.processing.params import (
    NAMED_SPATIAL_PREDICATES,
    PARAM_SPECS,
    STYLE_CATEGORY_OPTIONS,
    VARIABLE_PREFIX,
)
from stratified_packager.settings import StratifiedPackagerSettings

pytestmark = pytest.mark.qgis
"""Marks the whole module as requiring a Qt runtime."""


def _multi_enum_spec() -> FieldSpec:
    """Return a MULTI_ENUM field over the real style-category labels/tokens."""
    return FieldSpec(
        "style_categories",
        "Style categories",
        FieldKind.MULTI_ENUM,
        labeled_choices=tuple((option.label, option.token) for option in STYLE_CATEGORY_OPTIONS),
    )


def test_inherit_placeholder_formats_effective_value() -> None:
    """The placeholder names the inherited value, or just says ``inherit`` when empty."""
    assert inherit_placeholder("true") == "inherit (= true)"
    assert inherit_placeholder("  ") == "inherit"


def test_override_line_edit_empty_means_inherit() -> None:
    """An empty :class:`OverrideLineEdit` inherits; text is the explicit value."""
    editor = OverrideLineEdit()
    assert editor.scope_value() is None
    editor.set_scope_value("report.csv")
    assert editor.scope_value() == "report.csv"
    editor.set_scope_value(None)
    assert editor.scope_value() is None
    editor.set_effective("default.csv")
    assert editor.placeholderText() == "inherit (= default.csv)"


def test_override_combo_fixed_inherit_and_selection() -> None:
    """A fixed :class:`OverrideComboBox` starts on inherit and reports the chosen token."""
    editor = OverrideComboBox([("Enabled", "true"), ("Disabled", "false")])
    assert editor.scope_value() is None  # inherit item is current
    editor.set_scope_value("false")
    assert editor.scope_value() == "false"
    editor.set_scope_value(None)
    assert editor.scope_value() is None
    editor.set_effective("true")
    assert editor.itemText(0) == "inherit (= true)"


def _predicate_spec() -> FieldSpec:
    """Return the PREDICATES field over the real named-predicate tokens."""
    return FieldSpec(
        "stratified_packager_spatial_predicate",
        "Spatial predicate(s)",
        FieldKind.PREDICATES,
        NAMED_SPATIAL_PREDICATES,
    )


def test_predicate_combo_round_trips_names_and_de9im() -> None:
    """The predicate editor round-trips checked names plus the DE-9IM row, empty = inherit."""
    editor = make_override_editor(_predicate_spec())
    assert isinstance(editor, OverridePredicateCombo)
    assert editor.scope_value() is None  # nothing checked, blank DE-9IM row = inherit

    editor.set_scope_value("intersects,touches,T*F**F***")
    assert editor.scope_value() == "intersects,touches,T*F**F***"
    assert not editor.de9im_invalid

    editor.set_scope_value(None)
    assert editor.scope_value() is None
    editor.set_effective("auto")
    assert editor.defaultText() == "inherit (= auto)"


def test_predicate_combo_validates_de9im_patterns() -> None:
    """The DE-9IM row flags malformed patterns; lowercase t/f stay valid (SPEC §4)."""
    editor = make_override_editor(_predicate_spec())
    assert isinstance(editor, OverridePredicateCombo)

    editor.set_scope_value("t*f**f***")  # lowercase accepted (kept as typed in the editor)
    assert not editor.de9im_invalid
    assert editor.scope_value() == "t*f**f***"

    editor.set_scope_value("NOPE")  # not a named token, not a valid DE-9IM
    assert editor.de9im_invalid


def test_predicate_combo_de9im_row_width_hint_fits_placeholder() -> None:
    """The width hint exceeds the bare DE-9IM placeholder, leaving room for the label + chrome."""
    editor = make_override_editor(_predicate_spec())
    assert isinstance(editor, OverridePredicateCombo)
    hint = editor.de9im_row_width_hint()
    placeholder_only = QFontMetrics(editor.font()).horizontalAdvance("DE-9IM pattern(s)…")
    assert isinstance(hint, int)
    assert hint > placeholder_only > 0


@pytest.mark.parametrize(
    ("kind", "expected_type"),
    [
        (FieldKind.STRING, OverrideLineEdit),
        (FieldKind.INT, OverrideSpinBox),
        (FieldKind.BOOL, OverrideComboBox),
        (FieldKind.ENUM, OverrideComboBox),
        (FieldKind.MULTI_ENUM, OverrideCheckableCombo),
        (FieldKind.FIELDS, OverrideFieldsCombo),
        (FieldKind.PREDICATES, OverridePredicateCombo),
        (FieldKind.EXPRESSION, OverrideExpressionEdit),
        (FieldKind.LAYER, OverrideLayerCombo),
    ],
)
def test_make_override_editor_widget_type(kind: FieldKind, expected_type: type) -> None:
    """Each field kind maps to the expected inheritance-aware widget."""
    spec = FieldSpec("k", "L", kind, choices=("a", "b"))
    assert isinstance(make_override_editor(spec), expected_type)


@pytest.mark.parametrize(
    ("kind", "tristate", "expected_type"),
    [
        (FieldKind.BOOL, False, OverrideCheckBox),
        (FieldKind.BOOL, True, OverrideComboBox),
        (FieldKind.ENUM, False, OverrideComboBox),
        (FieldKind.STRING, False, OverrideLineEdit),
        (FieldKind.PREDICATES, False, OverridePredicateCombo),
        (FieldKind.FIELDS, False, OverrideFieldsCombo),
    ],
)
def test_make_override_editor_layer_widget_type(
    kind: FieldKind, tristate: bool, expected_type: type
) -> None:
    """Non-inheriting (layer) scope renders 2-state bools as checkboxes, tri-state as combos."""
    spec = FieldSpec("k", "L", kind, choices=("a", "b"), placeholder="auto", tristate=tristate)
    assert isinstance(make_override_editor(spec, inheriting=False), expected_type)


def test_override_expression_edit_empty_means_unset() -> None:
    """The expression editor reads empty as unset; explicit expressions round-trip."""
    editor = make_override_editor(FieldSpec("k", "L", FieldKind.EXPRESSION))
    assert isinstance(editor, OverrideExpressionEdit)
    assert editor.scope_value() is None
    editor.set_scope_value('"name"')
    assert editor.scope_value() == '"name"'
    editor.set_scope_value(None)
    assert editor.scope_value() is None
    editor.set_effective("ignored")  # no-op: no setting tier beneath (SPEC §19)
    layer = QgsVectorLayer("Point", "pts", "memory")
    editor.set_context_layer(layer)
    editor.set_context_layer(None)
    assert editor.scope_value() is None


def test_override_layer_combo_round_trips_layer_ids(
    qgis_new_project: Never,  # noqa: ARG001  # clean project
) -> None:
    """The layer combo starts unset, stores layer ids, and treats unknown ids as unset."""
    project = QgsProject.instance()
    assert project is not None
    points = QgsVectorLayer("Point", "pts", "memory")
    table = QgsVectorLayer("None", "tbl", "memory")  # geometryless: must pass the filter
    assert project.addMapLayer(points) is not None
    assert project.addMapLayer(table) is not None

    editor = make_override_editor(FieldSpec("k", "L", FieldKind.LAYER))
    assert isinstance(editor, OverrideLayerCombo)
    assert editor.scope_value() is None  # a fresh combo must not auto-select a layer

    for layer in (points, table):
        editor.set_scope_value(layer.id())
        assert editor.scope_value() == layer.id()

    editor.set_scope_value("no-such-layer-id")
    assert editor.scope_value() is None
    editor.set_scope_value(None)
    assert editor.scope_value() is None
    assert editor.currentText() == "not set"


def test_override_check_box_checked_true_unchecked_unset() -> None:
    """The layer bool checkbox reads true when checked, unset (None) otherwise; false clears."""
    editor = make_override_editor(FieldSpec("b", "L", FieldKind.BOOL), inheriting=False)
    assert isinstance(editor, OverrideCheckBox)
    assert editor.scope_value() is None  # unchecked = unset
    editor.set_scope_value("true")
    assert editor.scope_value() == "true"
    editor.set_scope_value("false")  # explicit false collapses to unchecked = unset
    assert editor.scope_value() is None
    editor.set_scope_value(None)
    assert editor.scope_value() is None


def test_override_check_box_default_true_inverts() -> None:
    """A True-default bool checkbox starts checked (= unset); unchecking means explicit false."""
    editor = make_override_editor(
        FieldSpec("b", "L", FieldKind.BOOL, default_true=True), inheriting=False
    )
    assert isinstance(editor, OverrideCheckBox)
    assert editor.isChecked()  # default rendered as checked
    assert editor.scope_value() is None  # checked = matches default = unset
    editor.set_scope_value("false")  # the sole meaningful override of a True-default var
    assert not editor.isChecked()
    assert editor.scope_value() == "false"
    editor.set_scope_value("true")  # explicit true collapses to unset (== default)
    assert editor.scope_value() is None
    editor.set_scope_value(None)  # unset rests on the True default
    assert editor.isChecked()
    assert editor.scope_value() is None


def test_non_inheriting_enum_sentinel_is_unset_default() -> None:
    """A layer enum shows its plain sentinel label, defaults to unset, and round-trips tokens."""
    spec = FieldSpec(
        "matching_method",
        "Matching method",
        FieldKind.ENUM,
        ("attribute", "spatial", "whole_export"),
        placeholder="auto",
    )
    editor = make_override_editor(spec, inheriting=False)
    assert isinstance(editor, OverrideComboBox)
    assert editor.itemText(0) == "auto"  # plain sentinel, not "inherit (= auto)"
    assert editor.scope_value() is None  # sentinel selected = unset
    editor.set_scope_value("spatial")
    assert editor.scope_value() == "spatial"
    editor.set_scope_value(None)
    assert editor.scope_value() is None


def test_tristate_bool_keeps_force_off_expressible() -> None:
    """Tri-state ``stage`` stays a sentinel combo, so an explicit false (force-off) survives."""
    spec = FieldSpec("stage", "Stage", FieldKind.BOOL, placeholder="auto", tristate=True)
    editor = make_override_editor(spec, inheriting=False)
    assert isinstance(editor, OverrideComboBox)
    assert editor.itemText(0) == "auto"
    assert editor.scope_value() is None  # auto = unset
    editor.set_scope_value("false")  # force-off
    assert editor.scope_value() == "false"
    editor.set_scope_value("true")  # force-on
    assert editor.scope_value() == "true"


def test_non_inheriting_placeholders_are_plain() -> None:
    """Layer text/predicate/fields editors use plain placeholders, never the 'inherit' idiom."""
    line = make_override_editor(
        FieldSpec("layer_name", "L", FieldKind.STRING, placeholder="keep original"),
        inheriting=False,
    )
    assert isinstance(line, OverrideLineEdit)
    assert line.placeholderText() == "keep original"

    predicate = make_override_editor(
        FieldSpec("sp", "L", FieldKind.PREDICATES, NAMED_SPATIAL_PREDICATES, placeholder="auto"),
        inheriting=False,
    )
    assert isinstance(predicate, OverridePredicateCombo)
    assert predicate.defaultText() == "auto"

    fields = make_override_editor(
        FieldSpec("ef", "L", FieldKind.FIELDS), field_names=("id", "name"), inheriting=False
    )
    assert isinstance(fields, OverrideFieldsCombo)
    assert "inherit" not in fields.defaultText().lower()


def test_override_spin_box_inherit_and_range() -> None:
    """The spin box rests on inherit, round-trips values, and clamps to ``0..max_value``."""
    editor = make_override_editor(FieldSpec("compression_level", "L", FieldKind.INT, max_value=9))
    assert isinstance(editor, OverrideSpinBox)
    assert editor.scope_value() is None  # below-range sentinel = inherit
    editor.set_scope_value("6")
    assert editor.scope_value() == "6"
    editor.set_scope_value(None)
    assert editor.scope_value() is None
    editor.set_effective("6")
    assert editor.specialValueText() == "inherit (= 6)"
    editor.set_scope_value("999")  # above max_value
    assert editor.scope_value() == "9"


def test_override_fields_combo_json_round_trips_field_names() -> None:
    """The fields combo inherits when empty and serialises checked names as a JSON list."""
    editor = make_override_editor(
        FieldSpec("stratified_packager_excluded_fields", "L", FieldKind.FIELDS),
        field_names=("id", "name", "geom"),
    )
    assert isinstance(editor, OverrideFieldsCombo)
    assert editor.scope_value() is None  # nothing checked = inherit
    editor.set_scope_value('["name", "id"]')
    assert json.loads(str(editor.scope_value())) == ["id", "name"]  # item (canonical) order
    editor.set_scope_value(None)
    assert editor.scope_value() is None
    editor.set_scope_value('["absent"]')  # name not in the layer drops silently
    assert editor.scope_value() is None


def test_override_checkable_combo_empty_means_inherit() -> None:
    """An all-unchecked combo inherits; checked tokens report as canonical-order CSV."""
    editor = make_override_editor(_multi_enum_spec())
    assert isinstance(editor, OverrideCheckableCombo)
    assert editor.scope_value() is None
    editor.set_scope_value("labeling,symbology")  # input order ignored
    assert editor.scope_value() == "symbology,labeling"
    editor.set_scope_value(None)
    assert editor.scope_value() is None
    editor.set_effective("symbology,labeling")
    assert editor.defaultText() == "inherit (= symbology,labeling)"


def test_override_checkable_combo_collapses_full_selection_to_all() -> None:
    """A full inherited selection renders as 'all', not the whole token list."""
    spec = _multi_enum_spec()
    editor = make_override_editor(spec)
    assert isinstance(editor, OverrideCheckableCombo)
    every = ",".join(token for _label, token in spec.labeled_choices)
    editor.set_effective(every)
    assert editor.defaultText() == "inherit (= all)"


def test_concrete_multi_enum_round_trip() -> None:
    """The concrete MULTI_ENUM editor round-trips checked tokens in canonical order."""
    spec = _multi_enum_spec()
    editor = make_concrete_editor(spec)
    assert isinstance(editor, QgsCheckableComboBox)
    set_concrete_value(spec, editor, "notes,symbology")
    assert concrete_value(spec, editor) == "symbology,notes"
    set_concrete_value(spec, editor, "")
    assert concrete_value(spec, editor) == ""


@pytest.mark.parametrize(
    ("spec", "set_to", "expected"),
    [
        (FieldSpec("b", "L", FieldKind.BOOL), "true", "true"),
        (FieldSpec("b", "L", FieldKind.BOOL), "false", "false"),
        (FieldSpec("i", "L", FieldKind.INT, max_value=9), "7", "7"),
        (FieldSpec("s", "L", FieldKind.STRING), "hello", "hello"),
        (FieldSpec("e", "L", FieldKind.ENUM, ("x", "y")), "y", "y"),
    ],
)
def test_concrete_editor_round_trip(spec: FieldSpec, set_to: str, expected: str) -> None:
    """Concrete editors round-trip their stored string tokens."""
    editor = make_concrete_editor(spec)
    set_concrete_value(spec, editor, set_to)
    assert concrete_value(spec, editor) == expected


def test_enum_combo_shows_labels_but_stores_tokens() -> None:
    """An ENUM with ``labeled_choices`` displays the label yet reads/writes the token."""
    spec = FieldSpec(
        "e", "L", FieldKind.ENUM, labeled_choices=(("Label X", "x"), ("Label Y", "y"))
    )

    concrete = make_concrete_editor(spec)
    assert isinstance(concrete, QComboBox)
    assert [concrete.itemText(i) for i in range(concrete.count())] == ["Label X", "Label Y"]
    set_concrete_value(spec, concrete, "y")
    assert concrete.currentText() == "Label Y"  # the label is what the user sees
    assert concrete_value(spec, concrete) == "y"  # the token is what gets stored

    override = make_override_editor(spec)
    assert isinstance(override, OverrideComboBox)
    override.set_scope_value("y")
    assert override.scope_value() == "y"


def test_concrete_value_rejects_mismatched_editor() -> None:
    """Reading with the wrong editor type is a programming error, surfaced loudly."""
    spec = FieldSpec("b", "L", FieldKind.BOOL)
    wrong = make_concrete_editor(FieldSpec("s", "L", FieldKind.STRING))
    with pytest.raises(TypeError):
        concrete_value(spec, wrong)


def test_default_fields_match_settings_and_specs() -> None:
    """Every default field names a real setting attribute and a §3 parameter."""
    setting_attrs = {spec.setting for spec in PARAM_SPECS.values() if spec.setting is not None}
    keys = {field.key for field in default_fields()}
    assert keys == setting_attrs
    for key in keys:
        assert hasattr(StratifiedPackagerSettings, key)


def test_project_only_fields_are_variable_only_params() -> None:
    """Every project-only field is a §3 parameter with a variable but no setting tier."""
    fields = project_only_fields()
    assert [field.key for field in fields] == [
        PROJECT_FIELD_STRATIFICATION_LAYER,
        PROJECT_FIELD_STRATUM_NAME_EXPRESSION,
    ]
    for field in fields:
        spec = PARAM_SPECS[field.key.upper()]
        assert spec.setting is None
        assert spec.variable == VARIABLE_PREFIX + field.key
        assert not hasattr(StratifiedPackagerSettings, field.key)


def test_layer_fields_are_suffix_keyed_variables() -> None:
    """Every layer field's key is a bare suffix; ``.variable`` is the full prefixed name."""
    fields = layer_fields()
    assert len(fields) == 9
    for spec in fields:
        assert not spec.key.startswith(VARIABLE_PREFIX)
        assert spec.variable == f"{VARIABLE_PREFIX}{spec.key}"
