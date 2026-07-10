"""
Reusable scope-editor widgets and field tables for the defaults GUI (SPEC §19).

Three scopes edit the same families of value: the plugin **settings** (concrete base
values), the **project** variables and the per-**layer** variables. The **project** fields
are *inheritance-aware* — an empty editor means "inherit the effective value from the next
tier of the SPEC §5 chain", with that inherited value shown as an ``inherit (= X)``
placeholder. The **layer** fields have no higher tier to inherit from (only their builtin
default), so with ``inheriting=False`` the same editors present the unset state plainly
instead: 2-state booleans as checkboxes (checked = ``true``, unchecked = unset), a
sentinel-labelled combo for the tri-state ones, and plain placeholders. Plugin-scope fields
are concrete (the base of the chain, always a real value).

Three shared field tables (:func:`default_fields`, :func:`project_only_fields`,
:func:`layer_fields`) drive every page, so the GUI stays in step with the
parameter/variable schema. Editors are built programmatically from those tables; the host
pages supply the ``.ui`` skeleton.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, ClassVar, Final, cast, override

from qgis.core import Qgis, QgsProject, QgsVectorLayer
from qgis.gui import QgsCheckableComboBox, QgsExpressionLineEdit, QgsMapLayerComboBox
from qgis.PyQt.QtCore import QCoreApplication, QObject, Qt
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QWidget,
)

# _Kind is params-internal but deliberately consumed here: the field tables are derived
# views of the parameter table, so the two cannot drift.
from stratified_packager.processing.params import (
    DE9IM_PATTERN,
    LAYER_VAR_EXCLUDE,
    LAYER_VAR_EXCLUDED_FIELDS,
    LAYER_VAR_LAYER_NAME,
    LAYER_VAR_MATCHING_METHOD,
    LAYER_VAR_MATERIALIZE_VIRTUAL,
    LAYER_VAR_RELATION_PATH,
    LAYER_VAR_SPATIAL_PREDICATE,
    LAYER_VAR_SPECS,
    LAYER_VAR_STAGE,
    LAYER_VAR_WARM_MARKED,
    NAMED_SPATIAL_PREDICATES,
    PARAM_SPECS,
    STRATIFICATION_LAYER,
    STRATUM_NAME_EXPRESSION,
    STYLE_CATEGORY_OPTIONS,
    VARIABLE_PREFIX,
    MatchingMethod,
    OverwriteMode,
    ProjectInclusion,
    WarmStartMode,
    _Kind,
    provider_keys,
    translated_label,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, MutableMapping, Sequence

    from qgis.core import QgsMapLayer
    from qgis.PyQt.QtGui import QStandardItemModel


# Translated, user-facing labels for the token enums shown in the defaults-page combos
# (label displayed, token stored) — keyed by token. The Processing *run* dialog keeps the raw
# tokens (its static-string enum shows the stored value verbatim); these relabel only the
# custom defaults surfaces, where label ≠ token is fully controllable (as for MULTI_ENUM).
OVERWRITE_MODE_LABELS: Final[dict[str, str]] = {
    OverwriteMode.OVERWRITE.value: QCoreApplication.translate(
        "StratifiedPackagerWidgets", "Overwrite"
    ),
    OverwriteMode.ERROR.value: QCoreApplication.translate(
        "StratifiedPackagerWidgets", "Error if exists"
    ),
    OverwriteMode.SKIP_EXISTING.value: QCoreApplication.translate(
        "StratifiedPackagerWidgets", "Skip existing"
    ),
}
"""``OVERWRITE_MODE`` combo labels keyed by SPEC §10 token."""

PROJECT_INCLUSION_LABELS: Final[dict[str, str]] = {
    ProjectInclusion.NONE.value: QCoreApplication.translate("StratifiedPackagerWidgets", "None"),
    ProjectInclusion.GPKG.value: QCoreApplication.translate(
        "StratifiedPackagerWidgets", "Embedded in GeoPackage"
    ),
    ProjectInclusion.QGZ.value: QCoreApplication.translate(
        "StratifiedPackagerWidgets", "Standalone .qgz project"
    ),
}
"""``PROJECT_INCLUSION`` combo labels keyed by SPEC §13 token."""

WARM_START_MODE_LABELS: Final[dict[str, str]] = {
    WarmStartMode.OFF.value: QCoreApplication.translate("StratifiedPackagerWidgets", "Off"),
    WarmStartMode.USE.value: QCoreApplication.translate(
        "StratifiedPackagerWidgets", "Start from warm cache"
    ),
    WarmStartMode.UPDATE.value: QCoreApplication.translate(
        "StratifiedPackagerWidgets", "Refresh warm cache"
    ),
}
"""``WARM_START_MODE`` combo labels keyed by SPEC §11 token."""

MATCHING_METHOD_LABELS: Final[dict[str, str]] = {
    MatchingMethod.ATTRIBUTE.value: QCoreApplication.translate(
        "StratifiedPackagerWidgets", "By attribute (relations)"
    ),
    MatchingMethod.SPATIAL.value: QCoreApplication.translate(
        "StratifiedPackagerWidgets", "Spatial"
    ),
    MatchingMethod.WHOLE_EXPORT.value: QCoreApplication.translate(
        "StratifiedPackagerWidgets", "Whole export"
    ),
}
"""Per-layer matching-method combo labels keyed by SPEC §4 token (``auto`` is the sentinel,
not a selectable option)."""


def inherit_placeholder(effective: str) -> str:
    """
    Format the placeholder shown by an empty (inheriting) editor.

    :param effective: The inherited effective value, already stringified.
    :return: e.g. ``inherit (= true)``; just ``inherit`` when *effective* is empty.
    """
    effective = effective.strip()
    return (
        QCoreApplication.translate("StratifiedPackagerWidgets", "inherit (= {})").format(effective)
        if effective
        else QCoreApplication.translate("StratifiedPackagerWidgets", "inherit")
    )


def _populate_checkable(combo: QgsCheckableComboBox, choices: Sequence[tuple[str, str]]) -> None:
    """
    Add ``(label, token)`` items (initially unchecked) to a checkable combo.

    :param combo: The combo to populate.
    :param choices: ``(label, token)`` pairs in display order.
    """
    for label, token in choices:
        combo.addItem(label, token)


def _checkable_csv(combo: QgsCheckableComboBox) -> str:
    """
    Read a checkable combo's checked tokens as a comma-separated string (item order).

    :param combo: The checkable combo.
    :return: The checked tokens joined by ``,`` (empty when nothing is checked).
    """
    return ",".join(str(token) for token in combo.checkedItemsData())


def _set_checkable_csv(combo: QgsCheckableComboBox, csv: str) -> None:
    """
    Check exactly the items whose token appears in *csv*, unchecking the rest.

    :param combo: The checkable combo.
    :param csv: Comma-separated tokens to check.
    """
    wanted = {token.strip() for token in csv.split(",") if token.strip()}
    for index in range(combo.count()):
        checked = str(combo.itemData(index)) in wanted
        combo.setItemCheckState(
            index, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        )


class FieldKind(Enum):
    """How a field's value is edited and coerced (SPEC §3/§4 value types)."""

    BOOL = "bool"
    """Boolean, stored as the tokens ``true`` / ``false``."""

    INT = "int"
    """Non-negative integer."""

    STRING = "string"
    """Free text (also expressions and JSON lists)."""

    ENUM = "enum"
    """One of a fixed token set."""

    MULTI_ENUM = "multi_enum"
    """Any subset of a fixed token set, stored as comma-separated tokens."""

    FIELDS = "fields"
    """Multi-select of the layer's own field names, stored as a JSON list (SPEC §4)."""

    PREDICATES = "predicates"
    """Checkable named spatial predicates plus a validated free-text DE-9IM row (SPEC §4)."""

    EXPRESSION = "expression"
    """A QGIS expression string, edited with the expression-builder line edit (the project-only
    §3 fields; empty = unset)."""

    LAYER = "layer"
    """A project vector layer, stored as its layer **id** (the project-only §3 fields)."""


@dataclass(frozen=True)
class FieldSpec:
    """One editable field on a defaults page (one §3 setting or §4 layer variable)."""

    key: str
    """Storage key: always the bare variable/setting **suffix** (e.g. ``compression_level``,
    ``exclude``) — a valid :class:`~stratified_packager.settings.StratifiedPackagerSettings`
    attribute name for the ✓ inputs. The full ``stratified_packager_<key>`` variable name is
    :attr:`variable`."""

    label: str
    """Translated, user-facing label."""

    kind: FieldKind
    """The field's value kind."""

    choices: tuple[str, ...] = ()
    """Allowed tokens for :attr:`FieldKind.ENUM`."""

    labeled_choices: tuple[tuple[str, str], ...] = ()
    """``(label, token)`` pairs for :attr:`FieldKind.MULTI_ENUM` (label shown, token stored)."""

    max_value: int = 9
    """Upper bound for :attr:`FieldKind.INT` editors (lower bound is always 0)."""

    placeholder: str = ""
    """Plain placeholder shown for the unset state in non-inheriting (layer) scope, and the
    sentinel item's label for a non-inheriting combo (e.g. ``auto``). Ignored when the form is
    inheriting (the Project Properties page shows an ``inherit (= X)`` placeholder instead)."""

    tristate: bool = False
    """Whether a :attr:`FieldKind.BOOL` field is genuinely tri-state (``true``/``false``/unset,
    like ``stage``). In non-inheriting scope such a field renders as a sentinel-labelled combo
    rather than a 2-state checkbox, so the explicit ``false`` (force-off) state stays
    expressible."""

    default_true: bool = False
    """The builtin default of a 2-state :attr:`FieldKind.BOOL` field. Only consulted for a
    non-inheriting field rendered as an :class:`OverrideCheckBox`: when :data:`True` the checkbox
    renders inverted (checked by default = unset, unchecking = explicit ``false``), so the sole
    meaningful override of a True-default variable stays expressible."""

    @property
    def variable(self) -> str:
        """
        The full project/layer variable name backing this field.

        :attr:`key` is always the bare suffix (a settings attribute name for the ✓ inputs);
        this prepends the ``stratified_packager_`` prefix in exactly one place, so a host
        never hand-builds the variable name.

        :return: ``stratified_packager_<key>``.
        """
        return f"{VARIABLE_PREFIX}{self.key}"


# ---------------------------------------------------------------------------
# Inheritance-aware editors (project & layer scope)
# ---------------------------------------------------------------------------


class OverrideLineEdit(QLineEdit):
    """A line edit whose empty state means "inherit"."""

    @override
    def __init__(self, parent: QWidget | None = None) -> None:
        """
        Initialize the editor.

        :param parent: Optional parent widget.
        """
        super().__init__(parent)

    def scope_value(self) -> str | None:
        """
        Return the explicit value, or :data:`None` when the field inherits.

        :return: The trimmed text, or :data:`None` if empty.
        """
        text = self.text().strip()
        return text or None

    def set_scope_value(self, value: str | None) -> None:
        """
        Set the explicit value (or clear it to inherit).

        :param value: The value to show, or :data:`None`/empty to inherit.
        """
        self.setText(value or "")

    def set_effective(self, effective: str) -> None:
        """
        Show the inherited effective value as the placeholder.

        :param effective: The inherited effective value, stringified.
        """
        self.setPlaceholderText(inherit_placeholder(effective))


class OverrideComboBox(QComboBox):
    """A combo whose "inherit" choice (or empty edit text) means inherit."""

    @override
    def __init__(
        self,
        choices: Sequence[tuple[str, str]],
        *,
        sentinel_label: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """
        Build the combo with an unset affordance plus *choices*.

        :param choices: ``(label, token)`` pairs in display order.
        :param sentinel_label: Fixed label for the unset/sentinel item (data :data:`None`),
            used by non-inheriting (layer) scope, e.g. ``auto``. When :data:`None` the item shows
            the inheriting ``inherit (= X)`` placeholder instead (set via :meth:`set_effective`).
        :param parent: Optional parent widget.
        """
        super().__init__(parent)
        self._sentinel_label = sentinel_label
        # A dedicated unset item (data None) precedes the choices.
        self.addItem(
            sentinel_label if sentinel_label is not None else inherit_placeholder(""), None
        )
        for label, token in choices:
            self.addItem(label, token)

    def scope_value(self) -> str | None:
        """
        Return the selected token, or :data:`None` when inheriting.

        :return: The token, or :data:`None` if the inherit choice is active.
        """
        data = self.currentData()
        return None if data is None else str(data)

    def set_scope_value(self, value: str | None) -> None:
        """
        Select the item matching *value* (or the inherit state).

        :param value: The token to select, or :data:`None`/empty to inherit.
        """
        if value is None or value == "":
            self.setCurrentIndex(0)
            return
        self.setCurrentIndex(max(self.findData(value), 0))

    def set_effective(self, effective: str) -> None:
        """
        Show the inherited effective value (placeholder, or the unset item's label).

        A combo built with a fixed ``sentinel_label`` (non-inheriting scope) keeps that label.

        :param effective: The inherited effective value, stringified.
        """
        if self._sentinel_label is not None:
            return
        self.setItemText(0, inherit_placeholder(effective))


class OverrideCheckableCombo(QgsCheckableComboBox):
    """A checkable multi-select whose empty (nothing-checked) state means inherit."""

    @override
    def __init__(self, choices: Sequence[tuple[str, str]], parent: QWidget | None = None) -> None:
        """
        Build the checkable combo with *choices* (all unchecked = inherit).

        :param choices: ``(label, token)`` pairs in display order.
        :param parent: Optional parent widget.
        """
        super().__init__(parent)
        _populate_checkable(self, choices)

    def scope_value(self) -> str | None:
        """
        Return the checked tokens as CSV, or :data:`None` when nothing is checked.

        :return: Comma-separated checked tokens, or :data:`None` to inherit.
        """
        return _checkable_csv(self) or None

    def set_scope_value(self, value: str | None) -> None:
        """
        Check the items named by *value* (or clear all to inherit).

        :param value: Comma-separated tokens, or :data:`None`/empty to inherit.
        """
        _set_checkable_csv(self, value or "")

    def set_effective(self, effective: str) -> None:
        """
        Show the inherited effective value as the no-selection placeholder.

        A full selection (every category, the common default) collapses to ``all`` so the
        placeholder stays short; partial selections show their tokens verbatim.

        :param effective: The inherited effective value (comma-separated tokens).
        """
        tokens = {token.strip() for token in effective.split(",") if token.strip()}
        self.setDefaultText(
            inherit_placeholder(
                QCoreApplication.translate("StratifiedPackagerWidgets", "all")
                if tokens
                and tokens == {str(self.itemData(index)) for index in range(self.count())}
                else effective
            )
        )


class OverrideFieldsCombo(OverrideCheckableCombo):
    """
    A multi-select of the layer's field names whose value is a JSON list.

    Like :class:`OverrideCheckableCombo` (nothing checked = inherit) but the checked names are
    serialised as a JSON list rather than CSV, because field names may contain commas and the
    matching engine reads ``excluded_fields`` as JSON. The only inheritable value is the builtin
    ``[]`` (exclude nothing), so the empty state simply reads ``inherit``.
    """

    @override
    def __init__(self, field_names: Sequence[str], parent: QWidget | None = None) -> None:
        """
        Build the combo with one checkable item per field name (all unchecked = inherit).

        :param field_names: The layer's field names, in display order.
        :param parent: Optional parent widget.
        """
        super().__init__(tuple((name, name) for name in field_names), parent)

    @override
    def scope_value(self) -> str | None:
        """
        Return the checked field names as a JSON list, or :data:`None` when nothing is checked.

        :return: A JSON array of the checked names, or :data:`None` to inherit.
        """
        names = [str(data) for data in self.checkedItemsData()]
        return json.dumps(names) if names else None

    @override
    def set_scope_value(self, value: str | None) -> None:
        """
        Check the items named by the JSON list in *value* (or clear all to inherit).

        A name no longer present in the layer is silently dropped (the combo can only
        represent current fields).

        :param value: A JSON list of field names, or :data:`None`/empty to inherit.
        """
        wanted = {str(name) for name in json.loads(value)} if value else set()
        for index in range(self.count()):
            checked = str(self.itemData(index)) in wanted
            self.setItemCheckState(
                index, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
            )

    @override
    def set_effective(self, effective: str) -> None:
        """
        Show the inherited (always-empty) state as the no-selection placeholder.

        :param effective: The inherited effective value (the builtin ``[]``); unused beyond
            yielding the plain ``inherit`` placeholder.
        """
        self.setDefaultText(inherit_placeholder(""))


class OverridePredicateCombo(QgsCheckableComboBox):
    """
    Spatial-predicate editor: checkable named predicates + a validated DE-9IM free-text row.

    The named predicates (SPEC §4) are checkable items; the last, non-checkable popup row hosts
    a line edit for one or more comma-separated DE-9IM patterns, validated live against
    :data:`~stratified_packager.processing.params.DE9IM_PATTERN`. The empty state (nothing
    checked, blank text) means inherit. The value read and written is the comma-joined
    token list the matching engine parses.
    """

    _DE9IM_ROW_PADDING: ClassVar[int] = 48
    """Pixels for the popup row's checkbox indent, item margins and the combo arrow/frame."""

    @override
    def __init__(self, named: Sequence[str], parent: QWidget | None = None) -> None:
        """
        Build the combo with the *named* predicates and the DE-9IM row.

        :param named: The named-predicate tokens, in display order.
        :param parent: Optional parent widget.
        """
        super().__init__(parent)
        self._named: tuple[str, ...] = tuple(named)
        self.de9im_invalid: bool = False
        """Whether the DE-9IM row holds an invalid pattern (advisory; the run-start validation
        is authoritative)."""
        self._default_text: str = ""
        for token in self._named:
            self.addItem(token, token)
        self._de9im_edit = QLineEdit()
        self._de9im_edit.setPlaceholderText(
            QCoreApplication.translate("StratifiedPackagerWidgets", "DE-9IM pattern(s)…")
        )
        self._de9im_edit.textChanged.connect(self._on_de9im_changed)
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(2, 0, 2, 0)
        self._de9im_label = QLabel(
            QCoreApplication.translate("StratifiedPackagerWidgets", "DE-9IM:")
        )
        row_layout.addWidget(self._de9im_label)
        row_layout.addWidget(self._de9im_edit)
        self.addItem("", None)
        de9im_row = self.count() - 1
        model = cast("QStandardItemModel", self.model())
        if item := model.item(de9im_row):
            # The DE-9IM row hosts a line edit, not a checkbox: make it non-checkable.
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
        if view := self.view():
            view.setIndexWidget(model.index(de9im_row, 0), row)
        self.checkedItemsChanged.connect(self._refresh_display)

    def de9im_row_width_hint(self) -> int:
        """
        Return the pixel width needed to show the DE-9IM popup row's full placeholder.

        :return: Width of the ``DE-9IM:`` label plus the ``DE-9IM pattern(s)…`` placeholder
            plus popup chrome, so the column (hence the popup) shows the placeholder in full.
        """
        metrics = self._de9im_edit.fontMetrics()
        return (
            metrics.horizontalAdvance(self._de9im_label.text())
            + metrics.horizontalAdvance(self._de9im_edit.placeholderText())
            + self._DE9IM_ROW_PADDING
        )

    def scope_value(self) -> str | None:
        """
        Return the checked named predicates plus DE-9IM patterns as CSV, or :data:`None`.

        :return: Comma-joined tokens, or :data:`None` when nothing is checked and the DE-9IM
            row is blank (inherit).
        """
        named = [str(data) for data in self.checkedItemsData() if data is not None]
        de9im = [token.strip() for token in self._de9im_edit.text().split(",") if token.strip()]
        return ",".join(named + de9im) or None

    def set_scope_value(self, value: str | None) -> None:
        """
        Check the named tokens in *value* and route the remaining tokens to the DE-9IM row.

        :param value: Comma-separated tokens, or :data:`None`/empty to inherit.
        """
        tokens = [token.strip() for token in (value or "").split(",") if token.strip()]
        for index in range(self.count()):
            data = self.itemData(index)
            if data is None:
                continue  # the DE-9IM host row
            checked = str(data).lower() in {token.lower() for token in tokens}
            self.setItemCheckState(
                index, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
            )
        named_lower = {token.lower() for token in self._named}
        de9im = [
            token
            for token in tokens
            if token.lower() not in named_lower and token.lower() != "auto"
        ]
        self._de9im_edit.setText(", ".join(de9im))

    def set_placeholder(self, text: str) -> None:
        """
        Set the no-selection placeholder text verbatim (non-inheriting scope).

        :param text: The placeholder to show when nothing is checked.
        """
        self._default_text = text
        self.setDefaultText(self._default_text)
        self._refresh_display()

    def set_effective(self, effective: str) -> None:
        """
        Show the inherited effective value as the no-selection placeholder.

        :param effective: The inherited effective value, stringified.
        """
        self.set_placeholder(inherit_placeholder(effective))

    def _on_de9im_changed(self, text: str) -> None:
        """
        Validate the DE-9IM row live, flagging invalid patterns with a red border.

        :param text: The current DE-9IM row text.
        """
        patterns = [token.strip() for token in text.split(",") if token.strip()]
        invalid = [pattern for pattern in patterns if not DE9IM_PATTERN.match(pattern)]
        self.de9im_invalid = bool(invalid)
        if invalid:
            self._de9im_edit.setStyleSheet("QLineEdit { border: 1px solid red; }")
            self._de9im_edit.setToolTip(
                QCoreApplication.translate(
                    "StratifiedPackagerWidgets", "Invalid DE-9IM pattern(s): {}"
                ).format(", ".join(invalid))
            )
        else:
            self._de9im_edit.setStyleSheet("")
            self._de9im_edit.setToolTip("")
        self._refresh_display()

    def _refresh_display(self) -> None:
        """Mirror the checked names and DE-9IM patterns into the collapsed display bar."""
        line_edit = self.lineEdit()
        if line_edit is None:
            return
        named = [str(data) for data in self.checkedItemsData() if data is not None]
        de9im = [token.strip() for token in self._de9im_edit.text().split(",") if token.strip()]
        parts = named + de9im
        line_edit.setText(", ".join(parts) if parts else self._default_text)


class OverrideSpinBox(QSpinBox):
    """A range-bound integer spin box whose below-range value means "inherit"."""

    @override
    def __init__(self, max_value: int, parent: QWidget | None = None) -> None:
        """
        Build the spin box over ``0..max_value`` with a below-range inherit sentinel.

        The minimum is ``-1`` (one step below the valid range); resting there shows the
        inherit placeholder via :meth:`~qgis.PyQt.QtWidgets.QAbstractSpinBox.setSpecialValueText`
        and reads back as inherit. The valid override range stays ``0..max_value``.

        :param max_value: The inclusive upper bound (lower bound is always 0).
        :param parent: Optional parent widget.
        """
        super().__init__(parent)
        self.setRange(-1, max_value)
        self.setValue(-1)  # noqa: QGS202  # QSpinBox, not a QGIS data provider
        self.setSpecialValueText(inherit_placeholder(""))

    def scope_value(self) -> str | None:
        """
        Return the explicit value, or :data:`None` when the field inherits.

        :return: The value as a string, or :data:`None` when below the valid range.
        """
        return None if self.value() < 0 else str(self.value())

    def set_scope_value(self, value: str | None) -> None:
        """
        Set the explicit value (or rest on the inherit sentinel).

        :param value: The value to show, or :data:`None`/empty to inherit.
        """
        # QGS202 targets QgsRasterBlock/QgsRasterAttributeTable; this is a plain QSpinBox.
        self.setValue(int(value) if value else -1)  # noqa: QGS202

    def set_effective(self, effective: str) -> None:
        """
        Show the inherited effective value as the inherit-sentinel label.

        :param effective: The inherited effective value, stringified.
        """
        self.setSpecialValueText(inherit_placeholder(effective))


class OverrideCheckBox(QCheckBox):
    """
    A default-aware 2-state boolean editor whose unset state mirrors the builtin default.

    Used in non-inheriting (layer) scope, where a boolean variable has no higher tier to inherit
    from — only a builtin default that applies while the variable is unset. The box's
    *checked* state mirrors the **effective** boolean, so an unset field rests on its default; an
    override is stored only when the box differs from that default. With a ``False`` default
    (the common case) that means checked = ``true`` and unchecked = unset; with a ``True`` default
    it inverts — checked = unset and unchecking = explicit ``false`` — keeping the sole meaningful
    override of a True-default variable expressible. Tri-state booleans (``stage``) use a sentinel
    combo instead, so all three of ``true``/``false``/unset stay distinct.
    """

    @override
    def __init__(self, default_value: bool = False, parent: QWidget | None = None) -> None:
        """
        Build the checkbox resting on its builtin default (so an unset field shows that state).

        :param default_value: The field's builtin default; the box starts in this state and
            reads back as unset whenever it matches it.
        :param parent: Optional parent widget.
        """
        super().__init__(parent)
        self._default = default_value
        self.setChecked(default_value)

    def scope_value(self) -> str | None:
        """
        Return the explicit override, or :data:`None` (unset) when the box matches the default.

        :return: ``"true"``/``"false"`` when the box differs from the builtin default, else
            :data:`None`.
        """
        if self.isChecked() == self._default:
            return None
        return "true" if self.isChecked() else "false"

    def set_scope_value(self, value: str | None) -> None:
        """
        Set the box from an explicit token, or rest it on the default when unset.

        :param value: A boolean token, or :data:`None`/empty to rest on the builtin default.
        """
        if value is None or str(value).strip() == "":
            self.setChecked(self._default)
        else:
            self.setChecked(str(value).strip().lower() in {"true", "1", "yes", "on"})

    def set_effective(self, effective: str) -> None:
        """
        No-op: a layer boolean has no inherited tier to surface.

        :param effective: Ignored.
        """


class OverrideExpressionEdit(QgsExpressionLineEdit):
    """An expression line edit whose empty state means "unset" (project-only rows)."""

    @override
    def __init__(self, parent: QWidget | None = None) -> None:
        """
        Initialize the editor.

        :param parent: Optional parent widget.
        """
        super().__init__(parent)

    def scope_value(self) -> str | None:
        """
        Return the explicit expression, or :data:`None` when the field is unset.

        :return: The trimmed expression, or :data:`None` if empty.
        """
        return self.expression().strip() or None

    def set_scope_value(self, value: str | None) -> None:
        """
        Set the explicit expression (or clear it to unset).

        :param value: The expression to show, or :data:`None`/empty to unset.
        """
        self.setExpression(value or "")

    def set_effective(self, effective: str) -> None:
        """
        No-op: a project-only field has no plugin-setting tier to surface.

        The builtin fallback (feature id) is already stated in the field label.

        :param effective: Ignored.
        """

    def set_context_layer(self, layer: QgsMapLayer | None) -> None:
        """
        Give the expression builder *layer*'s fields as context (a non-vector layer clears it).

        :param layer: The layer to take fields from, or :data:`None` to clear.
        """
        self.setLayer(layer if isinstance(layer, QgsVectorLayer) else None)


class OverrideLayerCombo(QgsMapLayerComboBox):
    """
    A project-layer combo whose labeled empty row means "unset" (project-only rows).

    Stores the selected layer's **id** — the format the runtime resolver feeds to
    :meth:`~qgis.core.QgsProject.mapLayer` (SPEC §5). The filter admits geometryless tables,
    matching ``STRATIFICATION_LAYER``'s ``TypeVector`` (SPEC §3). A stale/unknown id loads as
    unset, so applying the page clears it (fail-fast).
    """

    @override
    def __init__(self, parent: QWidget | None = None) -> None:
        """
        Initialize the combo (vector layers incl. geometryless tables, empty row first).

        :param parent: Optional parent widget.
        """
        super().__init__(parent)
        self.setFilters(Qgis.LayerFilter.VectorLayer)
        self.setAllowEmptyLayer(
            True,  # noqa: FBT003  # QGIS API positional bool
            QCoreApplication.translate("StratifiedPackagerWidgets", "not set"),
        )
        # The combo auto-selects the first real layer; start on the empty row instead.
        self.setCurrentIndex(0)

    def scope_value(self) -> str | None:
        """
        Return the selected layer's id, or :data:`None` when the empty row is selected.

        :return: The layer id, or :data:`None`.
        """
        layer = self.currentLayer()
        return layer.id() if layer is not None else None

    def set_scope_value(self, value: str | None) -> None:
        """
        Select the layer with id *value*, or the empty row when unset/unknown.

        :param value: The layer id, or :data:`None`/empty to unset.
        """
        project = QgsProject.instance()
        layer = project.mapLayer(value) if project is not None and value else None
        if isinstance(layer, QgsVectorLayer):
            self.setLayer(layer)
        else:
            # setLayer(None) blanks the display (index -1); select the labeled empty row.
            self.setCurrentIndex(0)

    def set_effective(self, effective: str) -> None:
        """
        No-op: a project-only field has no plugin-setting tier to surface.

        :param effective: Ignored.
        """


ScopeEditor = (
    OverrideLineEdit
    | OverrideComboBox
    | OverrideCheckBox
    | OverrideCheckableCombo
    | OverrideFieldsCombo
    | OverridePredicateCombo
    | OverrideSpinBox
    | OverrideExpressionEdit
    | OverrideLayerCombo
)
"""Any scope editor; all expose ``scope_value`` / ``set_scope_value`` / ``set_effective`` and
are :class:`~qgis.PyQt.QtWidgets.QWidget` subclasses."""


def make_override_editor(
    spec: FieldSpec,
    parent: QWidget | None = None,
    field_names: Sequence[str] = (),
    *,
    inheriting: bool = True,
) -> ScopeEditor:
    """
    Build the scope editor for *spec* (project or layer scope).

    With ``inheriting=True`` (project scope) the editor surfaces the next-tier value as an
    ``inherit (= X)`` placeholder. With ``inheriting=False`` (layer scope, no tier to inherit
    from) it presents the unset state plainly: a :class:`OverrideCheckBox` for a 2-state boolean,
    a ``sentinel_label`` combo for a tri-state boolean or enum, and the field's
    :attr:`FieldSpec.placeholder` for the text/predicate editors.

    :param spec: The field to edit.
    :param parent: Optional parent widget.
    :param field_names: The host layer's field names, used to populate a
        :attr:`FieldKind.FIELDS` editor; ignored for every other kind.
    :param inheriting: Whether the field inherits from a higher tier (project scope) or falls
        back only to its builtin default (layer scope). The project-only
        :attr:`FieldKind.EXPRESSION` / :attr:`FieldKind.LAYER` kinds ignore it (no tier below
        them either way).
    :return: An :class:`OverrideLineEdit`, :class:`OverrideComboBox`, :class:`OverrideCheckBox`,
        :class:`OverrideCheckableCombo`, :class:`OverrideFieldsCombo`,
        :class:`OverridePredicateCombo`, :class:`OverrideSpinBox`,
        :class:`OverrideExpressionEdit` or :class:`OverrideLayerCombo`.
    """
    editor: ScopeEditor
    match spec.kind:
        case FieldKind.BOOL if not inheriting and not spec.tristate:
            editor = OverrideCheckBox(spec.default_true, parent)
        case FieldKind.BOOL:
            editor = OverrideComboBox(
                [
                    (QCoreApplication.translate("StratifiedPackagerWidgets", "Enabled"), "true"),
                    (QCoreApplication.translate("StratifiedPackagerWidgets", "Disabled"), "false"),
                ],
                sentinel_label=(spec.placeholder or None) if not inheriting else None,
                parent=parent,
            )
        case FieldKind.INT:
            editor = OverrideSpinBox(spec.max_value, parent)
        case FieldKind.ENUM:
            editor = OverrideComboBox(
                spec.labeled_choices or tuple((token, token) for token in spec.choices),
                sentinel_label=(spec.placeholder or None) if not inheriting else None,
                parent=parent,
            )
        case FieldKind.MULTI_ENUM:
            editor = OverrideCheckableCombo(spec.labeled_choices, parent)
        case FieldKind.FIELDS:
            # Non-inheriting: keep QgsCheckableComboBox's own default text (no inherit label).
            editor = OverrideFieldsCombo(field_names, parent)
        case FieldKind.PREDICATES:
            predicate = OverridePredicateCombo(spec.choices, parent)
            if not inheriting:
                predicate.set_placeholder(spec.placeholder)
            editor = predicate
        case FieldKind.EXPRESSION:
            editor = OverrideExpressionEdit(parent)
        case FieldKind.LAYER:
            editor = OverrideLayerCombo(parent)
        case _:
            line = OverrideLineEdit(parent)
            if not inheriting and spec.placeholder:
                line.setPlaceholderText(spec.placeholder)
            editor = line
    return editor


def apply_overrides(target: MutableMapping[str, object], values: Mapping[str, str | None]) -> None:
    """
    Write explicit *values* to *target*, removing keys whose value is ``None`` (inherit).

    Shared by every defaults page so the write-back rule lives in one place.

    :param target: The settings/variable proxy to update.
    :param values: ``{key: explicit value or None}``; a ``None`` value clears the key.
    """
    for key, value in values.items():
        if value is None:
            target.pop(key, None)
        else:
            target[key] = value


class OverrideForm:
    """
    A form of inheritance-aware editors for a set of fields (project/layer scope).

    Builds one labelled editor per :class:`FieldSpec` into a caller-supplied
    :class:`~qgis.PyQt.QtWidgets.QFormLayout`, then loads/dumps the explicit values
    keyed by field key. Used by the Project Properties page and the per-layer page so
    the inherit-vs-override behaviour lives in one place.
    """

    def __init__(self, fields: Sequence[FieldSpec], *, inheriting: bool = True) -> None:
        """
        Initialize the form for *fields* (call :meth:`build` to create the editors).

        :param fields: The fields to edit, in display order.
        :param inheriting: Whether the fields inherit from a higher tier (project scope) or fall
            back only to their builtin defaults (layer scope); forwarded to every editor.
        """
        self.fields: tuple[FieldSpec, ...] = tuple(fields)
        self._inheriting = inheriting
        self._editors: dict[str, ScopeEditor] = {}

    def build(
        self,
        form_layout: QFormLayout,
        parent: QObject | None = None,
        field_names: Sequence[str] = (),
    ) -> None:
        """
        Create the editors and add them as labelled rows to *form_layout*.

        :param form_layout: The layout to populate (one row per field).
        :param parent: Optional parent for the editors.
        :param field_names: The host layer's field names, forwarded to any
            :attr:`FieldKind.FIELDS` editor; ignored for every other kind.
        """
        widget_parent = parent if isinstance(parent, QWidget) else None
        for spec in self.fields:
            editor = make_override_editor(
                spec, widget_parent, field_names, inheriting=self._inheriting
            )
            self._editors[spec.key] = editor
            form_layout.addRow(spec.label, editor)

    def load(self, current: Mapping[str, str | None], effective: Mapping[str, str]) -> None:
        """
        Populate the editors from the current explicit values and inherited values.

        :param current: Explicit values per field key (missing/``None`` = unset).
        :param effective: Inherited effective value per field key (for the placeholder); unused in
            non-inheriting scope, where the placeholder is fixed at build time.
        """
        for spec in self.fields:
            editor = self._editors[spec.key]
            if self._inheriting:
                editor.set_effective(str(effective.get(spec.key, "")))
            editor.set_scope_value(current.get(spec.key))

    def dump(self) -> dict[str, str | None]:
        """
        Read the explicit value of every field, keyed by its bare :attr:`FieldSpec.key`.

        :return: ``{field key: explicit value or None}`` (``None`` means inherit).
        """
        return {key: editor.scope_value() for key, editor in self._editors.items()}

    def dump_variables(self) -> dict[str, str | None]:
        """
        Read the explicit value of every field, keyed by its full variable name.

        The single place the ``stratified_packager_`` prefix is applied on write, so a host
        never hand-builds variable names from :meth:`dump` keys.

        :return: ``{stratified_packager_<key>: explicit value or None}`` (``None`` = inherit).
        """
        return {spec.variable: self._editors[spec.key].scope_value() for spec in self.fields}

    def set_value(self, key: str, value: str | None) -> None:
        """
        Set one field's explicit value (or clear it to inherit).

        :param key: The field key.
        :param value: The explicit value, or :data:`None` to inherit.
        :raise KeyError: If *key* is not a field of this form.
        """
        self._editors[key].set_scope_value(value)

    def editor(self, key: str) -> ScopeEditor:
        """
        Return one field's editor (e.g. to wire cross-field signals).

        :param key: The field key.
        :return: The field's scope editor.
        :raise KeyError: If *key* is not a field of this form.
        """
        return self._editors[key]

    def set_enabled(self, key: str, *, enabled: bool) -> None:
        """
        Enable or disable one field's editor (e.g. gate an inapplicable field).

        :param key: The field key.
        :param enabled: Whether the editor accepts edits.
        :raise KeyError: If *key* is not a field of this form.
        """
        self._editors[key].setEnabled(enabled)


# ---------------------------------------------------------------------------
# Concrete editors (plugin-settings scope — always a real value)
# ---------------------------------------------------------------------------


def make_concrete_editor(spec: FieldSpec, parent: QWidget | None = None) -> QWidget:
    """
    Build the concrete editor for *spec* (plugin-settings scope).

    :param spec: The field to edit.
    :param parent: Optional parent widget.
    :return: A plain ``QCheckBox`` / ``QSpinBox`` / ``QComboBox`` / ``QLineEdit``.
    """
    match spec.kind:
        case FieldKind.BOOL:
            return QCheckBox(parent)
        case FieldKind.INT:
            spin = QSpinBox(parent)
            spin.setRange(0, spec.max_value)
            return spin
        case FieldKind.ENUM:
            combo = QComboBox(parent)
            for label, token in spec.labeled_choices or tuple(
                (token, token) for token in spec.choices
            ):
                combo.addItem(label, token)
            return combo
        case FieldKind.MULTI_ENUM:
            checkable = QgsCheckableComboBox(parent)
            _populate_checkable(checkable, spec.labeled_choices)
            return checkable
        case _:
            return QLineEdit(parent)


def concrete_value(spec: FieldSpec, editor: QWidget) -> str:
    """
    Read a concrete editor's value as its stored string token.

    :param spec: The field being read.
    :param editor: The editor built by :func:`make_concrete_editor`.
    :return: The value as a string token (``true``/``false`` for booleans).
    :raise TypeError: If *editor* is not the widget type *spec* implies.
    """
    match spec.kind:
        case FieldKind.BOOL:
            if not isinstance(editor, QCheckBox):
                raise TypeError(_unexpected_editor(spec, editor))
            return "true" if editor.isChecked() else "false"
        case FieldKind.INT:
            if not isinstance(editor, QSpinBox):
                raise TypeError(_unexpected_editor(spec, editor))
            return str(editor.value())
        case FieldKind.MULTI_ENUM:
            if not isinstance(editor, QgsCheckableComboBox):
                raise TypeError(_unexpected_editor(spec, editor))
            return _checkable_csv(editor)
        case FieldKind.ENUM:
            if not isinstance(editor, QComboBox):
                raise TypeError(_unexpected_editor(spec, editor))
            # currentData holds the stored token (label ≠ token once combos are relabelled).
            return str(editor.currentData()).strip()
        case _:
            if not isinstance(editor, QLineEdit):
                raise TypeError(_unexpected_editor(spec, editor))
            return editor.text().strip()


def set_concrete_value(spec: FieldSpec, editor: QWidget, value: str) -> None:
    """
    Set a concrete editor's value from its stored string token.

    :param spec: The field being set.
    :param editor: The editor built by :func:`make_concrete_editor`.
    :param value: The stored string token.
    :raise TypeError: If *editor* is not the widget type *spec* implies.
    """
    match spec.kind:
        case FieldKind.BOOL:
            if not isinstance(editor, QCheckBox):
                raise TypeError(_unexpected_editor(spec, editor))
            editor.setChecked(str(value).strip().lower() in {"true", "1", "yes", "on"})
        case FieldKind.INT:
            if not isinstance(editor, QSpinBox):
                raise TypeError(_unexpected_editor(spec, editor))
            editor.setValue(int(value or 0))  # noqa: QGS202  # QSpinBox, not a QGIS data provider
        case FieldKind.MULTI_ENUM:
            if not isinstance(editor, QgsCheckableComboBox):
                raise TypeError(_unexpected_editor(spec, editor))
            _set_checkable_csv(editor, value)
        case FieldKind.ENUM:
            if not isinstance(editor, QComboBox):
                raise TypeError(_unexpected_editor(spec, editor))
            index = editor.findData(value)
            if index >= 0:
                editor.setCurrentIndex(index)
        case _:
            if not isinstance(editor, QLineEdit):
                raise TypeError(_unexpected_editor(spec, editor))
            editor.setText(value)


def _unexpected_editor(spec: FieldSpec, editor: QWidget) -> str:
    """
    Build the message for an editor that does not match its field kind.

    :param spec: The field whose editor was wrong.
    :param editor: The mismatched editor.
    :return: A diagnostic message.
    """
    return f"field {spec.key!r} ({spec.kind.value}) got a {type(editor).__name__}"


# ---------------------------------------------------------------------------
# Field tables (single source of truth for every page)
# ---------------------------------------------------------------------------


def _default_field(key: str, label: str, kind: _Kind) -> FieldSpec:
    """
    Build one settings-backed field from its parameter-table facts.

    :param key: The settings attribute name (the parameter id lowercased).
    :param label: The translated label.
    :param kind: The parameter's coercion kind, mapped to the matching editor kind.
    :return: The field spec.
    """
    result: FieldSpec
    match kind:
        case _Kind.BOOL:
            result = FieldSpec(key, label, FieldKind.BOOL)
        case _Kind.INT:
            result = FieldSpec(key, label, FieldKind.INT, max_value=9)
        case _Kind.OVERWRITE:
            result = FieldSpec(
                key,
                label,
                FieldKind.ENUM,
                labeled_choices=tuple(
                    (OVERWRITE_MODE_LABELS[member.value], member.value) for member in OverwriteMode
                ),
            )
        case _Kind.INCLUSION:
            result = FieldSpec(
                key,
                label,
                FieldKind.ENUM,
                labeled_choices=tuple(
                    (PROJECT_INCLUSION_LABELS[member.value], member.value)
                    for member in ProjectInclusion
                ),
            )
        case _Kind.WARM:
            result = FieldSpec(
                key,
                label,
                FieldKind.ENUM,
                labeled_choices=tuple(
                    (WARM_START_MODE_LABELS[member.value], member.value)
                    for member in WarmStartMode
                ),
            )
        case _Kind.STYLE_CATEGORIES:
            result = FieldSpec(
                key,
                label,
                FieldKind.MULTI_ENUM,
                labeled_choices=tuple(
                    (option.label, option.token) for option in STYLE_CATEGORY_OPTIONS
                ),
            )
        case _Kind.PROVIDER_LIST:
            result = FieldSpec(
                key,
                label,
                FieldKind.MULTI_ENUM,
                labeled_choices=tuple((token, token) for token in provider_keys()),
            )
        case _:
            result = FieldSpec(key, label, FieldKind.STRING)
    return result


def default_fields() -> tuple[FieldSpec, ...]:
    """
    Return the settings-backed default fields (the ✓ rows of SPEC §3, in table order).

    Derived from the parameter table: each ``key`` is the attribute name on
    :class:`~stratified_packager.settings.StratifiedPackagerSettings` (the input id
    lowercased) and the suffix of the matching ``stratified_packager_<x>`` project
    variable; the label is the input's canonical translated label. A new settings-backed
    input therefore appears on the Options and Project pages without touching this module.

    :return: The default fields in display order.
    """
    return tuple(
        _default_field(str(spec.setting), translated_label(spec.name), spec.kind)
        for spec in PARAM_SPECS.values()
        if spec.setting is not None
    )


PROJECT_FIELD_STRATIFICATION_LAYER: Final = "stratification_layer"
"""Key of the stratification-layer project-only field (its project-variable suffix)."""

PROJECT_FIELD_STRATUM_NAME_EXPRESSION: Final = "stratum_name_expression"
"""Key of the stratum-name-expression project-only field (its project-variable suffix)."""


def project_only_fields() -> tuple[FieldSpec, ...]:
    """
    Return the project-only default fields (the SPEC §3 inputs with a variable but no setting).

    These inputs hold project-dependent values (a layer id, an expression over that layer's
    fields), so they have no global plugin-setting tier: the Project Properties page is their
    only defaults surface. Each ``key`` is the input's project-variable suffix (the SPEC §5
    ``variable_name`` rule).

    :return: The project-only fields in SPEC §3 declaration order.
    """
    return (
        FieldSpec(
            PROJECT_FIELD_STRATIFICATION_LAYER,
            translated_label(STRATIFICATION_LAYER),
            FieldKind.LAYER,
        ),
        FieldSpec(
            PROJECT_FIELD_STRATUM_NAME_EXPRESSION,
            translated_label(STRATUM_NAME_EXPRESSION),
            FieldKind.EXPRESSION,
        ),
    )


def layer_fields() -> tuple[FieldSpec, ...]:
    """
    Return the per-layer variable fields (SPEC §4, in table order).

    Derived from :data:`~stratified_packager.processing.params.LAYER_VAR_SPECS`: keys,
    labels and order come from the table; only the presentation (editor kind, choices,
    placeholders) is decided here. Each ``key`` is the layer variable's bare suffix (as
    with :func:`default_fields`); the full ``stratified_packager_<x>`` name is
    :attr:`FieldSpec.variable`. These variables have no project/plugin tier to inherit
    from, so the pages build them with ``inheriting=False``
    (:func:`make_override_editor`): the :attr:`FieldSpec.placeholder` is the plain unset
    affordance, ``auto`` doubling as the sentinel-item label for the tri-state fields.

    :return: The layer-variable fields in display order.
    """
    auto = QCoreApplication.translate("StratifiedPackagerWidgets", "auto")
    non_auto_methods = tuple(
        member.value for member in MatchingMethod if member is not MatchingMethod.AUTO
    )
    # (kind, choices, placeholder, tristate) per variable — a new LAYER_VAR_SPECS entry
    # fails loudly here until its presentation is decided.
    presentation: dict[str, tuple[FieldKind, tuple[str, ...], str, bool]] = {
        LAYER_VAR_EXCLUDE: (FieldKind.BOOL, (), "", False),
        LAYER_VAR_LAYER_NAME: (
            FieldKind.STRING,
            (),
            QCoreApplication.translate("StratifiedPackagerWidgets", "keep original"),
            False,
        ),
        LAYER_VAR_MATCHING_METHOD: (FieldKind.ENUM, non_auto_methods, auto, False),
        LAYER_VAR_SPATIAL_PREDICATE: (
            FieldKind.PREDICATES,
            NAMED_SPATIAL_PREDICATES,
            auto,
            False,
        ),
        LAYER_VAR_EXCLUDED_FIELDS: (FieldKind.FIELDS, (), "", False),
        LAYER_VAR_STAGE: (FieldKind.BOOL, (), auto, True),
        LAYER_VAR_WARM_MARKED: (FieldKind.BOOL, (), "", False),
        LAYER_VAR_MATERIALIZE_VIRTUAL: (FieldKind.BOOL, (), "", False),
        LAYER_VAR_RELATION_PATH: (FieldKind.STRING, (), auto, False),
    }
    fields: list[FieldSpec] = []
    for spec in LAYER_VAR_SPECS:
        kind, choices, placeholder, tristate = presentation[spec.name]
        # ENUM carries translated (label, token) pairs; every other kind stores raw tokens.
        labeled_choices = (
            tuple((MATCHING_METHOD_LABELS[token], token) for token in choices)
            if kind is FieldKind.ENUM
            else ()
        )
        fields.append(
            FieldSpec(
                spec.suffix,
                QCoreApplication.translate("StratifiedPackagerWidgets", spec.label),
                kind,
                () if kind is FieldKind.ENUM else choices,
                labeled_choices=labeled_choices,
                placeholder=placeholder,
                tristate=tristate,
            )
        )
    return tuple(fields)
