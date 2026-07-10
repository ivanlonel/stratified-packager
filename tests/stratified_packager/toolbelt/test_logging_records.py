"""
Test suite for :mod:`stratified_packager.toolbelt.logging_records`.

Covers the record-level machinery split out of the logging suite: the level mapping
(:func:`level_to_qgis`, :data:`_QGIS_TO_QMSGBOX_ICON`, :func:`_qmsgbox_icon`), the
:class:`Target` flag, the :class:`QgisContextFilter` / :class:`TargetFilter` filters and the
:class:`MessageBarConfig` / :class:`MessageBoxConfig` dataclasses. The handler and wrapper that
build on these are exercised in :mod:`tests.stratified_packager.toolbelt.test_logging`.

All tests require a QGIS installation: the module-level :func:`pytest.importorskip` skips them
when QGIS is unavailable, and the module is marked ``qgis`` via :data:`pytestmark`.
"""
# pylint: disable=redefined-outer-name
# pylint: disable=duplicate-code  # trivial _make_record/_expected_* scaffolding shared with test_logging

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import hypothesis
import pytest
from hypothesis import strategies as st

pytest.importorskip("qgis", reason="The logging records bridge QGIS message APIs and need QGIS.")

# Imported only after the importorskip guard above confirms QGIS is available.
from qgis.core import Qgis, QgsApplication, QgsProject
from qgis.PyQt.QtWidgets import QMessageBox

import stratified_packager.toolbelt.logging_records as records_module
from stratified_packager.toolbelt.logging_records import (
    _K_TARGETS,
    _QGIS_TO_QMSGBOX_ICON,
    SUCCESS,
    MessageBarConfig,
    MessageBoxConfig,
    QgisContextFilter,
    Target,
    TargetFilter,
    _qmsgbox_icon,
    level_to_qgis,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

pytestmark = pytest.mark.qgis
"""Marks the whole module as requiring a QGIS runtime."""

# Severity rank for Qgis.MessageLevel, lowest to highest. QGIS' own enum values are
# not ordered by severity, so an explicit ranking is needed for the monotonicity check.
_SEVERITY_ORDER = [
    Qgis.MessageLevel.NoLevel,
    Qgis.MessageLevel.Info,
    Qgis.MessageLevel.Success,
    Qgis.MessageLevel.Warning,
    Qgis.MessageLevel.Critical,
]

# level_to_qgis and _qmsgbox_icon are pure, so property tests need no per-example fixture reset.
_PURE_PROPERTY = hypothesis.settings(
    suppress_health_check=[hypothesis.HealthCheck.function_scoped_fixture]
)


def _make_record(
    msg: str = "test message",
    level: int = logging.INFO,
    name: str = "TestPlugin",
    extra: Mapping[str, object] | None = None,
) -> logging.LogRecord:
    """
    Create a minimal :class:`logging.LogRecord` for use in tests.

    :param msg: The log message string.
    :param level: The numeric logging level.
    :param name: The logger name embedded in the record.
    :param extra: Additional attributes to set on the record.
    :return: A populated :class:`logging.LogRecord`.
    """
    record = logging.LogRecord(
        name=name,
        level=level,
        pathname=__file__,
        lineno=0,
        msg=msg,
        args=(),
        exc_info=None,
    )
    for key, value in (extra or {}).items():
        setattr(record, key, value)
    return record


def _expected_locale() -> str:
    """Return the running application's locale, asserting an application exists."""
    app = QgsApplication.instance()
    assert app is not None
    return app.locale()


def _expected_project_path() -> str:
    """Return the current project's absolute file path, asserting a project exists."""
    project = QgsProject.instance()
    assert project is not None
    return project.absoluteFilePath()


def test_all_symbols_are_importable() -> None:
    """Every name in ``__all__`` must be importable from the module."""
    for name in records_module.__all__:
        assert hasattr(records_module, name), f"__all__ lists {name!r} but it's not in the module."


class TestLevelToQgis:
    """
    Tests for :func:`level_to_qgis`.

    Parametrized over every distinct branch in the function.
    """

    @pytest.mark.parametrize(
        ("level", "expected"),
        [
            (logging.CRITICAL + 10, Qgis.MessageLevel.Critical),
            (logging.CRITICAL, Qgis.MessageLevel.Critical),
            (logging.ERROR, Qgis.MessageLevel.Critical),
            (logging.WARNING, Qgis.MessageLevel.Warning),
            (SUCCESS, Qgis.MessageLevel.Success),
            (logging.INFO, Qgis.MessageLevel.Info),
            (logging.DEBUG, Qgis.MessageLevel.Info),
            (logging.NOTSET, Qgis.MessageLevel.NoLevel),
        ],
        ids=[
            "above_critical",
            "critical",
            "error",
            "warning",
            "success",
            "info",
            "debug",
            "notset",
        ],
    )
    def test_level_mapping(self, level: int, expected: Qgis.MessageLevel) -> None:
        """
        Each stdlib level must map to the documented :class:`~qgis.core.Qgis.MessageLevel`.

        :param level: Numeric stdlib level under test.
        :param expected: The expected :class:`~qgis.core.Qgis.MessageLevel` result.
        """
        assert level_to_qgis(level) == expected


class TestQgisToQmsgboxIcon:
    """Tests for the :data:`_QGIS_TO_QMSGBOX_ICON` mapping and :func:`_qmsgbox_icon`."""

    def test_all_message_levels_are_mapped(self) -> None:
        """
        Every :class:`~qgis.core.Qgis.MessageLevel` member must have an entry in
        :data:`_QGIS_TO_QMSGBOX_ICON` — catches newly added enum members
        before they cause a :exc:`KeyError` at runtime.
        """
        try:
            members = tuple(Qgis.MessageLevel)
        except TypeError:  # Qgis.MessageLevel is a non-iterable sip enum on PyQt5 (QGIS 3.x).
            members = tuple(
                v for v in vars(Qgis.MessageLevel).values() if isinstance(v, Qgis.MessageLevel)
            )
        for member in members:
            assert member in _QGIS_TO_QMSGBOX_ICON, (
                f"Qgis.MessageLevel.{member.name} missing from _QGIS_TO_QMSGBOX_ICON"
            )

    @pytest.mark.parametrize(
        ("msg_level", "expected_icon"),
        [
            (Qgis.MessageLevel.Info, QMessageBox.Icon.Information),
            (Qgis.MessageLevel.Warning, QMessageBox.Icon.Warning),
            (Qgis.MessageLevel.Critical, QMessageBox.Icon.Critical),
            (Qgis.MessageLevel.Success, QMessageBox.Icon.Information),
            (Qgis.MessageLevel.NoLevel, QMessageBox.Icon.NoIcon),
        ],
        ids=["info", "warning", "critical", "success", "nolevel"],
    )
    def test_mapping_values(
        self,
        msg_level: Qgis.MessageLevel,
        expected_icon: QMessageBox.Icon,
    ) -> None:
        """
        Each :class:`~qgis.core.Qgis.MessageLevel` must map to the expected
        :class:`~qgis.PyQt.QtWidgets.QMessageBox.Icon`.

        :param msg_level: The :class:`~qgis.core.Qgis.MessageLevel` key under test.
        :param expected_icon: The expected :class:`~qgis.PyQt.QtWidgets.QMessageBox.Icon` value.
        """
        assert _QGIS_TO_QMSGBOX_ICON[msg_level] == expected_icon

    def test_qmsgbox_icon_consistent_with_mapping(self) -> None:
        """
        ``_qmsgbox_icon(level)`` must equal
        ``_QGIS_TO_QMSGBOX_ICON[level_to_qgis(level)]`` for every stdlib
        level — verifies the two mappings stay in sync.
        """
        for level in (
            logging.DEBUG,
            logging.INFO,
            SUCCESS,
            logging.WARNING,
            logging.ERROR,
            logging.CRITICAL,
            logging.NOTSET,
        ):
            assert _qmsgbox_icon(level) is _QGIS_TO_QMSGBOX_ICON[level_to_qgis(level)]


class TestLevelMappingProperties:
    """Property-based checks for :func:`level_to_qgis` and :func:`_qmsgbox_icon`."""

    @_PURE_PROPERTY
    @hypothesis.given(level=st.integers())
    def test_level_to_qgis_total(self, level: int) -> None:
        """
        Any integer level must map to a known :class:`~qgis.core.Qgis.MessageLevel`.

        :param level: An arbitrary stdlib logging level.
        """
        assert level_to_qgis(level) in _SEVERITY_ORDER

    @_PURE_PROPERTY
    @hypothesis.given(a=st.integers(), b=st.integers())
    def test_level_to_qgis_monotonic(self, a: int, b: int) -> None:
        """
        A higher numeric level must never map to a lower severity.

        :param a: One arbitrary level.
        :param b: Another arbitrary level.
        """
        lower, higher = sorted((a, b))
        assert _SEVERITY_ORDER.index(level_to_qgis(lower)) <= _SEVERITY_ORDER.index(
            level_to_qgis(higher)
        )

    @_PURE_PROPERTY
    @hypothesis.given(level=st.integers())
    def test_qmsgbox_icon_matches_mapping(self, level: int) -> None:
        """
        ``_qmsgbox_icon`` must agree with the level-to-icon mapping for any level.

        :param level: An arbitrary stdlib logging level.
        """
        assert _qmsgbox_icon(level) is _QGIS_TO_QMSGBOX_ICON[level_to_qgis(level)]


class TestTarget:
    """Tests for the :class:`Target` flag enum."""

    def test_combination_contains_both(self) -> None:
        """Combining two flags must produce a value containing both and excluding others."""
        combo = Target.LOG | Target.BAR
        assert Target.LOG in combo
        assert Target.BAR in combo
        assert Target.DIALOG not in combo

    def test_strip_flag(self) -> None:
        """``& ~flag`` must remove one flag without affecting the others."""
        stripped = (Target.LOG | Target.BAR) & ~Target.BAR
        assert Target.BAR not in stripped
        assert Target.LOG in stripped


class TestMessageBarConfig:
    """Tests for the :class:`MessageBarConfig` dataclass."""

    def test_defaults(self) -> None:
        """Default-constructed instance must have the documented field values."""
        cfg = MessageBarConfig()
        assert cfg.duration == 5
        assert cfg.buttons == []
        assert cfg.show_progress is False
        assert cfg.progress_value == 0
        assert cfg.progress_format == "%p%"

    def test_custom_values(self) -> None:
        """Keyword arguments must override the corresponding defaults."""
        cfg = MessageBarConfig(duration=10, show_progress=True, progress_value=42)
        assert cfg.duration == 10
        assert cfg.show_progress is True
        assert cfg.progress_value == 42

    def test_buttons_default_is_independent_per_instance(self) -> None:
        """
        The default :attr:`~MessageBarConfig.buttons` list must not be shared between
        instances.
        """
        cfg1 = MessageBarConfig()
        cfg2 = MessageBarConfig()
        cfg1.buttons.append(MagicMock())
        assert cfg2.buttons == []


class TestMessageBoxConfig:
    """Tests for the :class:`MessageBoxConfig` dataclass."""

    def test_defaults(self) -> None:
        """Default-constructed instance must have the documented field values."""
        cfg = MessageBoxConfig()
        assert cfg.title is None
        assert cfg.standard_buttons == QMessageBox.StandardButton.Ok
        assert cfg.default_button == QMessageBox.StandardButton.Ok
        assert cfg.detailed_text is None

    def test_custom_title(self) -> None:
        """``title=`` must be stored in :attr:`title`."""
        assert MessageBoxConfig(title="My Error").title == "My Error"


class TestQgisContextFilter:
    """Tests for :class:`QgisContextFilter`."""

    def test_always_returns_true(self) -> None:
        """``filter()`` must always return :data:`True`."""
        assert QgisContextFilter().filter(_make_record()) is True

    @pytest.mark.parametrize(
        ("attr", "get_expected"),
        [
            ("qgis_version", Qgis.version),
            ("qgis_locale", _expected_locale),
            ("qgis_project_path", _expected_project_path),
        ],
        ids=["version", "locale", "project_path"],
    )
    @pytest.mark.usefixtures("qgis_new_project")
    def test_stamps_dynamic_field(self, attr: str, get_expected: Callable[[], object]) -> None:
        """
        Each dynamic QGIS field must equal the live value at filter time.

        :param attr: The record attribute name to check.
        :param get_expected: Zero-argument callable returning the expected value.
        """
        record = _make_record()
        QgisContextFilter().filter(record)
        assert getattr(record, attr) == get_expected()

    def test_stamps_active_layer_id(self) -> None:
        """
        ``qgis_active_layer_id`` must equal the active layer's ID when
        ``iface.activeLayer()`` returns a layer.
        """
        mock_layer = MagicMock()
        mock_layer.id.return_value = "layer_abc"
        mock_iface = MagicMock()
        mock_iface.activeLayer.return_value = mock_layer
        record = _make_record()
        QgisContextFilter(iface=mock_iface).filter(record)
        assert record.__dict__["qgis_active_layer_id"] == "layer_abc"

    def test_active_layer_id_absent_when_iface_is_none(self) -> None:
        """
        ``qgis_active_layer_id`` must be absent from the record when
        ``iface=None`` is passed — the filter skips the attribute entirely.
        """
        record = _make_record()
        QgisContextFilter(iface=None).filter(record)
        assert not hasattr(record, "qgis_active_layer_id")

    def test_active_layer_id_empty_when_no_active_layer(self) -> None:
        """
        ``qgis_active_layer_id`` must be an empty string when
        ``iface.activeLayer()`` returns :data:`None`.
        """
        mock_iface = MagicMock()
        mock_iface.activeLayer.return_value = None
        record = _make_record()
        QgisContextFilter(iface=mock_iface).filter(record)
        assert record.__dict__["qgis_active_layer_id"] == ""

    def test_static_fields_stamped_on_record(self) -> None:
        """Every ``static_fields`` key must appear as a record attribute."""
        record = _make_record()
        QgisContextFilter(static_fields={"plugin_version": "2.0.0", "task": "import"}).filter(
            record
        )
        assert record.__dict__["plugin_version"] == "2.0.0"
        assert record.__dict__["task"] == "import"

    def test_dynamic_fields_overwrite_static_on_collision(self) -> None:
        """Dynamic QGIS fields must overwrite static fields on key collision."""
        record = _make_record()
        QgisContextFilter(static_fields={"qgis_version": "0.0.0-fake"}).filter(record)
        assert record.__dict__["qgis_version"] == Qgis.version()

    @pytest.mark.parametrize(
        "kwargs",
        [{}, {"static_fields": None}],
        ids=["omitted", "explicit_none"],
    )
    def test_static_fields_empty_when_not_provided(self, kwargs: dict[str, Any]) -> None:
        """
        ``_static_fields`` must be an empty dict when ``static_fields`` is
        omitted or explicitly :data:`None`.

        :param kwargs: Constructor kwargs for :class:`QgisContextFilter`.
        """
        assert QgisContextFilter(**kwargs)._static_fields == {}


class TestTargetFilter:
    """Tests for :class:`TargetFilter`."""

    @pytest.mark.parametrize(
        ("record_level", "min_level", "expected"),
        [
            (logging.DEBUG, logging.WARNING, False),
            (logging.WARNING, logging.WARNING, True),
            (logging.ERROR, logging.WARNING, True),
            (logging.DEBUG, logging.NOTSET, True),
        ],
        ids=["below", "at", "above", "notset_passes_all"],
    )
    def test_level_gate(self, record_level: int, min_level: int, expected: bool) -> None:
        """
        The level gate must drop records below ``min_level`` and pass
        those at or above it.

        :param record_level: The level of the record under test.
        :param min_level: The ``min_level`` configured on the filter.
        :param expected: Whether :meth:`filter` should return :data:`True`.
        """
        f = TargetFilter(allowed_targets=Target.LOG, min_level=min_level)
        assert f.filter(_make_record(level=record_level)) is expected

    @pytest.mark.parametrize(
        ("override", "expected"),
        [
            (None, True),
            (Target.DIALOG, True),
            (Target.BAR | Target.DIALOG, True),
            (Target.LOG | Target.BAR, False),
        ],
        ids=[
            "no_override_passes",
            "exact_match_passes",
            "shared_flag_passes",
            "no_shared_flag_dropped",
        ],
    )
    def test_target_gate(self, override: Target | None, expected: bool) -> None:
        """
        The target gate must pass records whose override shares a flag with
        ``allowed_targets`` and drop those with no overlap. Records with no
        override always pass.

        :param override: The ``_K_TARGETS`` value to set on the record, or
            :data:`None` to omit the attribute entirely.
        :param expected: Whether :meth:`filter` should return :data:`True`.
        """
        f = TargetFilter(allowed_targets=Target.DIALOG)
        extra = {_K_TARGETS: override} if override is not None else {}
        assert f.filter(_make_record(extra=extra)) is expected

    def test_level_gate_checked_before_target_gate(self) -> None:
        """
        A record failing the level gate must be dropped even if the target
        gate would pass it.
        """
        f = TargetFilter(allowed_targets=Target.LOG, min_level=logging.ERROR)
        assert f.filter(_make_record(level=logging.DEBUG, extra={_K_TARGETS: Target.LOG})) is False

    def test_allowed_targets_setter(self) -> None:
        """Assigning to ``allowed_targets`` must replace the stored value."""
        f = TargetFilter(allowed_targets=Target.LOG)
        f.allowed_targets = Target.BAR | Target.DIALOG
        assert f.allowed_targets == Target.BAR | Target.DIALOG

    def test_min_level_setter(self) -> None:
        """Assigning to ``min_level`` must take effect on the next call."""
        f = TargetFilter(allowed_targets=Target.LOG)
        f.min_level = logging.CRITICAL
        assert f.min_level == logging.CRITICAL
        assert f.filter(_make_record(level=logging.ERROR)) is False
