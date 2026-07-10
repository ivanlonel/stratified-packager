"""
Test suite for :mod:`stratified_packager.toolbelt.logging`.

Tooling
-------
* **pytest-qgis** — provides ``qgis_app`` (session-scoped, auto-use),
    ``qgis_iface``, ``qgis_new_project``, and ``qgis_bot`` fixtures.
* **pytest-qt** — provides ``qtbot`` for event-loop pumping and signal
    interception (``QApplication.instance()`` is already created by ``qgis_app``).

All tests in this module require a QGIS installation: the module-level
:func:`pytest.importorskip` skips it when QGIS is unavailable, and it is
marked ``qgis`` via :data:`pytestmark`.

Test organisation
-----------------
Each public symbol has its own test class. Cross-cutting concerns
(``__all__`` completeness) live in module-level functions. Thread-safety
and Qt-dispatch tests live in :class:`TestQgisHandlerThreadDispatch`.
Helper classes (:class:`_WorkerThread`, :class:`_CapturingHandler`) are
defined at the bottom of the module.
"""
# pylint: disable=too-many-lines
# pylint: disable=redefined-outer-name

from __future__ import annotations

import inspect
import logging
import threading
from typing import TYPE_CHECKING, Any, override
from unittest.mock import MagicMock, patch

import hypothesis
import pytest
from hypothesis import strategies as st

pytest.importorskip("qgis", reason="The logging wrapper bridges QGIS message APIs and needs QGIS.")

# Imported only after the importorskip guard above confirms QGIS is available.
from qgis.core import Qgis, QgsMessageLog
from qgis.PyQt.QtCore import QThread

import stratified_packager.toolbelt.logging as logging_module
from stratified_packager.toolbelt.logging import (
    _K_SETUP_OWNED,
    SUCCESS,
    EmitPayload,
    MessageBarConfig,
    MessageBoxConfig,
    QgisContextFilter,
    QgisHandler,
    QgisHandlerSignals,
    QgisLoggerWrapper,
    Target,
    TargetFilter,
    _is_main_thread,
)

# The per-call override sentinel keys now physically live in logging_records; mypy's
# no-implicit-reexport rule wants them imported from their defining module.
from stratified_packager.toolbelt.logging_records import _K_BAR_CFG, _K_BOX_CFG, _K_TARGETS

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping

pytestmark = pytest.mark.qgis
"""Marks the whole module as requiring a QGIS runtime."""

_SENTINEL_KEYS = {_K_TARGETS, _K_BAR_CFG, _K_BOX_CFG}
"""The private keys :meth:`QgisLoggerWrapper._pack_extra` reserves for overrides."""

# _pack_extra is pure, so property tests need no per-example fixture reset.
_PURE_PROPERTY = hypothesis.settings(
    suppress_health_check=[hypothesis.HealthCheck.function_scoped_fixture]
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def plugin_name() -> str:
    """
    Return a stable plugin name used as both logger name and handler tag.

    :return: The string ``"TestPlugin"``.
    """
    return "TestPlugin"


@pytest.fixture
def clean_logger(plugin_name: str) -> Generator[str, None, None]:
    """
    Yield *plugin_name* and remove the logger and all its children from
    the registry afterwards.

    Prevents handler accumulation and hierarchy pollution across tests.

    :param plugin_name: The logger name provided by the :func:`plugin_name`
        fixture.
    :yield: The plugin name string, for use in the test body.
    """
    yield plugin_name
    prefix = plugin_name + "."
    for name in list(logging.Logger.manager.loggerDict):
        if name == plugin_name or name.startswith(prefix):
            logger = logging.getLogger(name)
            for handler in logger.handlers[:]:
                logger.removeHandler(handler)
            logging.Logger.manager.loggerDict.pop(name, None)


@pytest.fixture
def mock_bar() -> MagicMock:
    """
    Return a :class:`MagicMock` standing in for :class:`QgsMessageBar`.

    :return: A configured :class:`MagicMock`.
    """
    msg_bar = MagicMock()
    msg_bar.createMessage.return_value = MagicMock()
    msg_bar.createMessage.return_value.layout.return_value = MagicMock()
    return msg_bar


@pytest.fixture
def basic_handler(plugin_name: str) -> QgisHandler:
    """
    Return a :class:`QgisHandler` targeting ``Target.LOG`` only.

    :param plugin_name: Injected from the :func:`plugin_name` fixture.
    :return: A :class:`QgisHandler` instance.
    """
    return QgisHandler(plugin_name=plugin_name, targets=Target.LOG)


@pytest.fixture
def bar_handler(plugin_name: str, mock_bar: MagicMock) -> QgisHandler:
    """
    Return a :class:`QgisHandler` targeting ``Target.BAR``, wired to *mock_bar*.

    :param plugin_name: Injected from the :func:`plugin_name` fixture.
    :param mock_bar: Injected from the :func:`mock_bar` fixture.
    :return: A :class:`QgisHandler` instance with ``Target.BAR`` active.
    """
    return QgisHandler(plugin_name=plugin_name, targets=Target.BAR, bar=mock_bar)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# __all__ completeness
# ---------------------------------------------------------------------------


def test_all_symbols_are_importable() -> None:
    """Every name in ``__all__`` must be importable from the module."""
    for name in logging_module.__all__:
        assert hasattr(logging_module, name), f"__all__ lists {name!r} but it's not in the module."


# ---------------------------------------------------------------------------
# Property-based tests (hypothesis)
# ---------------------------------------------------------------------------


class TestPackExtraProperties:
    """Property-based invariants for :meth:`QgisLoggerWrapper._pack_extra`."""

    @_PURE_PROPERTY
    @hypothesis.given(
        extra=st.dictionaries(
            st.text().filter(lambda key: key not in _SENTINEL_KEYS),
            st.integers(),
        ),
        targets=st.sampled_from(
            [None, Target.LOG, Target.BAR, Target.DIALOG, Target.LOG | Target.BAR]
        ),
        with_bar=st.booleans(),
        with_box=st.booleans(),
    )
    def test_pack_extra_invariants(
        self,
        extra: dict[str, int],
        targets: Target | None,
        with_bar: bool,
        with_box: bool,
    ) -> None:
        """
        Pack a copy of *extra*, preserve its items, and inject only the requested overrides.

        :param extra: User-supplied ``extra`` dict (free of sentinel keys).
        :param targets: Optional per-call target override.
        :param with_bar: Whether a bar-config override is supplied.
        :param with_box: Whether a box-config override is supplied.
        """
        bar_config = MessageBarConfig() if with_bar else None
        box_config = MessageBoxConfig() if with_box else None
        snapshot = dict(extra)
        result = QgisLoggerWrapper._pack_extra(
            extra, targets=targets, bar_config=bar_config, box_config=box_config
        )
        assert extra == snapshot  # the caller's dict is never mutated
        assert result is not extra  # a fresh copy is returned
        for key, value in snapshot.items():
            assert result[key] == value
        assert (_K_TARGETS in result) is (targets is not None)
        assert (_K_BAR_CFG in result) is with_bar
        assert (_K_BOX_CFG in result) is with_box


# ---------------------------------------------------------------------------
# QgisHandlerSignals
# ---------------------------------------------------------------------------


class TestQgisHandlerSignals:
    """Tests for :class:`QgisHandlerSignals` and :attr:`QgisHandler.signals`."""

    def test_signals_attribute_is_qgis_handler_signals(self, basic_handler: QgisHandler) -> None:
        """
        ``handler.signals`` must be a :class:`QgisHandlerSignals` instance.

        :param basic_handler: A handler targeting ``Target.LOG``.
        """
        assert isinstance(basic_handler.signals, QgisHandlerSignals)

    @pytest.mark.parametrize(
        ("level", "msg"),
        [
            (logging.INFO, "hello"),
            (logging.WARNING, "warn"),
        ],
        ids=["info", "warning"],
    )
    def test_message_emitted_fires(self, basic_handler: QgisHandler, level: int, msg: str) -> None:
        """
        :attr:`~QgisHandlerSignals.message_emitted` must fire once per record carrying the correct
        message and level, regardless of whether the level is INFO or WARNING.

        :param basic_handler: A handler targeting ``Target.LOG``.
        :param level: The logging level of the record.
        :param msg: The message text.
        """
        received: list[tuple[str, int]] = []
        basic_handler.signals.message_emitted.connect(lambda m, level: received.append((m, level)))
        basic_handler.setFormatter(logging.Formatter("%(message)s"))
        with patch("stratified_packager.toolbelt.logging.QgsMessageLog.logMessage"):
            basic_handler.emit(_make_record(msg=msg, level=level))
        assert received == [(msg, level)]

    @pytest.mark.parametrize(
        ("level", "should_fire"),
        [
            (logging.ERROR, True),
            (logging.CRITICAL, True),
            (logging.WARNING, False),
        ],
        ids=["error", "critical", "warning"],
    )
    def test_error_emitted_fires_above_error_threshold(
        self, basic_handler: QgisHandler, level: int, should_fire: bool
    ) -> None:
        """
        :attr:`~QgisHandlerSignals.error_emitted` must fire for ERROR and CRITICAL but not WARNING.

        :param basic_handler: A handler targeting ``Target.LOG``.
        :param level: The logging level of the record.
        :param should_fire: Whether :attr:`~QgisHandlerSignals.error_emitted` is expected to fire.
        """
        received: list[str] = []
        basic_handler.signals.error_emitted.connect(received.append)
        basic_handler.setFormatter(logging.Formatter("%(message)s"))
        with patch("stratified_packager.toolbelt.logging.QgsMessageLog.logMessage"):
            basic_handler.emit(_make_record(level=level))
        assert bool(received) is should_fire

    def test_message_emitted_carries_formatted_message(self, basic_handler: QgisHandler) -> None:
        """
        :attr:`~QgisHandlerSignals.message_emitted` must carry the formatter's output, not
        the raw msg.

        :param basic_handler: A handler targeting ``Target.LOG``.
        """
        received: list[str] = []
        basic_handler.signals.message_emitted.connect(lambda m, _level: received.append(m))
        basic_handler.setFormatter(logging.Formatter("PREFIX: %(message)s"))
        with patch("stratified_packager.toolbelt.logging.QgsMessageLog.logMessage"):
            basic_handler.emit(_make_record(msg="body"))
        assert received == ["PREFIX: body"]

    def test_message_emitted_fires_from_qthread(
        self, basic_handler: QgisHandler, qtbot: Any
    ) -> None:
        """
        :attr:`~QgisHandlerSignals.message_emitted` must be delivered on the GUI thread even when
        emitted from a :class:`QThread` worker.

        :param basic_handler: A handler targeting ``Target.LOG``.
        :param qtbot: pytest-qt fixture used to pump the event loop.
        """
        received_thread_ids: list[int] = []
        basic_handler.signals.message_emitted.connect(
            lambda _m, _level: received_thread_ids.append(threading.get_ident())
        )
        basic_handler.setFormatter(logging.Formatter("%(message)s"))

        def worker() -> None:
            """Call emit from a QThread worker."""
            with patch("stratified_packager.toolbelt.logging.QgsMessageLog.logMessage"):
                basic_handler.emit(_make_record(level=logging.INFO))

        thread = _WorkerThread(target=worker)
        thread.start()
        thread.wait(2_000)
        assert thread.exception is None
        qtbot.wait(50)
        assert len(received_thread_ids) == 1
        assert received_thread_ids[0] == threading.get_ident()


# ---------------------------------------------------------------------------
# QgisHandler — construction
# ---------------------------------------------------------------------------


class TestQgisHandlerConstruction:
    """Tests for :class:`QgisHandler` construction-time behaviour."""

    def test_basic_construction(self, plugin_name: str) -> None:
        """
        Must expose plugin name and default to ``Target.LOG``.

        :param plugin_name: The plugin name string.
        """
        handler = QgisHandler(plugin_name=plugin_name)
        assert handler.plugin_name == plugin_name
        assert handler.targets is Target.LOG

    @pytest.mark.parametrize(
        ("tag", "expected"),
        [(None, "TestPlugin"), ("CustomTag", "CustomTag")],
        ids=["default", "custom"],
    )
    def test_tag(self, plugin_name: str, tag: str | None, expected: str) -> None:
        """
        When ``tag=None`` the internal tag must equal the plugin name;
        a custom tag must be stored verbatim.

        :param plugin_name: The plugin name string.
        :param tag: The ``tag`` argument passed to the constructor.
        :param expected: The expected value of ``handler._tag``.
        """
        handler = QgisHandler(plugin_name=plugin_name, tag=tag)
        assert handler._tag == expected

    @pytest.mark.parametrize(
        ("bar", "should_raise"),
        [(None, True), ("mock", False)],
        ids=["no_bar_raises", "with_bar_ok"],
    )
    def test_bar_target_validation(
        self,
        plugin_name: str,
        mock_bar: MagicMock,
        bar: str | None,  # pylint: disable=disallowed-name  # domain-meaningful name (message bar)
        should_raise: bool,
    ) -> None:
        """
        Requesting ``Target.BAR`` without a bar must raise :exc:`ValueError`;
        providing one must succeed and store the bar.

        :param plugin_name: The plugin name string.
        :param mock_bar: The mock bar fixture (used when *bar* is ``"mock"``).
        :param bar: :data:`None` to omit the bar, or ``"mock"`` to pass *mock_bar*.
        :param should_raise: Whether a :exc:`ValueError` is expected.
        """
        bar_arg = None if bar is None else mock_bar
        if should_raise:
            with pytest.raises(ValueError, match="QgsMessageBar"):
                QgisHandler(plugin_name=plugin_name, targets=Target.BAR, bar=bar_arg)
        else:
            handler = QgisHandler(plugin_name=plugin_name, targets=Target.BAR, bar=bar_arg)
            assert handler._bar is mock_bar

    @pytest.mark.parametrize(
        "pass_parent",
        [False, True],
        ids=["default_none", "explicit_parent"],
    )
    def test_box_parent_stored(self, plugin_name: str, pass_parent: bool) -> None:
        """
        The ``box_parent`` argument must be stored verbatim, defaulting to
        :data:`None` when omitted.

        :param plugin_name: The plugin name string.
        :param pass_parent: Whether to pass an explicit ``box_parent``.
        """
        parent = MagicMock() if pass_parent else None
        handler = QgisHandler(plugin_name=plugin_name, box_parent=parent)
        assert handler._box_parent is parent


# ---------------------------------------------------------------------------
# QgisHandler — runtime reconfiguration
# ---------------------------------------------------------------------------


class TestQgisHandlerReconfiguration:
    """Tests for runtime property setters on :class:`QgisHandler`."""

    @pytest.mark.parametrize(
        ("new_targets", "should_raise"),
        [
            (Target.LOG | Target.DIALOG, False),
            (Target.BAR, True),
        ],
        ids=["valid_combo", "bar_without_bar"],
    )
    def test_targets_setter(
        self,
        basic_handler: QgisHandler,
        new_targets: Target,
        should_raise: bool,
    ) -> None:
        """
        Assigning a valid :class:`Target` combination must take effect; assigning
        ``Target.BAR`` on a handler without a bar must raise :exc:`ValueError`.

        :param basic_handler: A handler targeting ``Target.LOG`` (no bar).
        :param new_targets: The new target combination to assign.
        :param should_raise: Whether a :exc:`ValueError` is expected.
        """
        if should_raise:
            with pytest.raises(ValueError, match="QgsMessageBar"):
                basic_handler.targets = new_targets
        else:
            basic_handler.targets = new_targets
            assert new_targets in basic_handler.targets


# ---------------------------------------------------------------------------
# QgisHandler — emit routing to QgsMessageLog
# ---------------------------------------------------------------------------


class TestQgisHandlerEmitLog:
    """Tests for :meth:`QgisHandler.emit` routing to :class:`QgsMessageLog`."""

    def test_emit_calls_qgs_message_log(self, basic_handler: QgisHandler) -> None:
        """
        Emitting a record must call :meth:`qgis.core.QgsMessageLog.logMessage` once with
        the formatted message.

        :param basic_handler: A handler targeting ``Target.LOG``.
        """
        basic_handler.setFormatter(logging.Formatter("%(message)s"))
        with patch("stratified_packager.toolbelt.logging.QgsMessageLog.logMessage") as mock_log:
            basic_handler.emit(_make_record(msg="Hello log"))
            mock_log.assert_called_once()
            args, kwargs = mock_log.call_args
            assert "Hello log" in (kwargs.get("message") or args[0])

    @pytest.mark.parametrize(
        ("level", "expected_qgis_level"),
        [
            (logging.CRITICAL, Qgis.MessageLevel.Critical),
            (logging.ERROR, Qgis.MessageLevel.Critical),
            (logging.WARNING, Qgis.MessageLevel.Warning),
            (SUCCESS, Qgis.MessageLevel.Success),
            (logging.INFO, Qgis.MessageLevel.Info),
            (logging.DEBUG, Qgis.MessageLevel.Info),
            (logging.NOTSET, Qgis.MessageLevel.NoLevel),
        ],
        ids=[
            "critical",
            "error",
            "warning",
            "success",
            "info",
            "debug",
            "notset",
        ],
    )
    def test_emit_level_mapping(
        self,
        basic_handler: QgisHandler,
        level: int,
        expected_qgis_level: Qgis.MessageLevel,
    ) -> None:
        """
        The record level must be translated to the correct :class:`~qgis.core.Qgis.MessageLevel`
        when calling :meth:`~qgis.core.QgsMessageLog.logMessage`.

        :param basic_handler: A handler targeting ``Target.LOG``.
        :param level: The stdlib level of the record.
        :param expected_qgis_level: The expected :class:`~qgis.core.Qgis.MessageLevel` argument.
        """
        basic_handler.setFormatter(logging.Formatter("%(message)s"))
        with patch("stratified_packager.toolbelt.logging.QgsMessageLog.logMessage") as mock_log:
            basic_handler.emit(_make_record(level=level))
            assert mock_log.call_args[1]["level"] == expected_qgis_level

    def test_emit_uses_tag(self, plugin_name: str) -> None:
        """
        A custom ``tag`` must be forwarded to :meth:`~qgis.core.QgsMessageLog.logMessage`.

        :param plugin_name: The plugin name string.
        """
        handler = QgisHandler(plugin_name=plugin_name, tag="MyTag")
        handler.setFormatter(logging.Formatter("%(message)s"))
        with patch("stratified_packager.toolbelt.logging.QgsMessageLog.logMessage") as mock_log:
            handler.emit(_make_record())
            assert mock_log.call_args[1]["tag"] == "MyTag"

    def test_emit_does_not_call_log_when_not_in_targets(
        self, plugin_name: str, mock_bar: MagicMock
    ) -> None:
        """
        :meth:`~qgis.core.QgsMessageLog.logMessage` must not be called if ``Target.LOG`` is absent.

        :param plugin_name: The plugin name string.
        :param mock_bar: A mock bar required for ``Target.BAR``.
        """
        handler = QgisHandler(plugin_name=plugin_name, targets=Target.BAR, bar=mock_bar)
        handler.setFormatter(logging.Formatter("%(message)s"))
        with patch("stratified_packager.toolbelt.logging.QgsMessageLog.logMessage") as mock_log:
            handler.emit(_make_record())
            mock_log.assert_not_called()


# ---------------------------------------------------------------------------
# QgisHandler — emit routing to QgsMessageBar
# ---------------------------------------------------------------------------


class TestQgisHandlerEmitBar:
    """Tests for :meth:`QgisHandler.emit` routing to :class:`QgsMessageBar`."""

    def test_emit_calls_push_item(self, bar_handler: QgisHandler, mock_bar: MagicMock) -> None:
        """
        ``bar.pushItem`` must be called once per emitted record.

        :param bar_handler: A handler targeting ``Target.BAR``.
        :param mock_bar: The mocked message bar.
        """
        bar_handler.setFormatter(logging.Formatter("%(message)s"))
        bar_handler.emit(_make_record(level=logging.WARNING))
        mock_bar.pushItem.assert_called_once()

    def test_emit_creates_message_with_plugin_name(
        self, bar_handler: QgisHandler, mock_bar: MagicMock, plugin_name: str
    ) -> None:
        """
        ``bar.createMessage`` must receive the plugin name and formatted message.

        :param bar_handler: A handler targeting ``Target.BAR``.
        :param mock_bar: The mocked message bar.
        :param plugin_name: The expected first argument to
            :meth:`~qgis.gui.QgsMessageBar.createMessage`.
        """
        bar_handler.setFormatter(logging.Formatter("%(message)s"))
        bar_handler.emit(_make_record(msg="bar msg"))
        mock_bar.createMessage.assert_called_once_with(plugin_name, "bar msg")

    def test_bar_target_without_bar_in_payload_skips_silently(self, plugin_name: str) -> None:
        """
        A per-call BAR override on a handler without a bar must not raise.

        :param plugin_name: The plugin name string.
        """
        handler = QgisHandler(plugin_name=plugin_name, targets=Target.LOG)
        handler.setFormatter(logging.Formatter("%(message)s"))
        record = _make_record(extra={_K_TARGETS: Target.BAR | Target.LOG})
        with patch("stratified_packager.toolbelt.logging.QgsMessageLog.logMessage"):
            handler.emit(record)

    def test_progress_bar_added_when_show_progress_true(
        self, plugin_name: str, mock_bar: MagicMock
    ) -> None:
        """
        ``show_progress=True`` must cause a widget to be added via
        :meth:`~qgis.PyQt.QtWidgets.QLayout.addWidget`.

        :param plugin_name: The plugin name string.
        :param mock_bar: A mock bar.
        """
        handler = QgisHandler(
            plugin_name=plugin_name,
            targets=Target.BAR,
            bar=mock_bar,
            bar_config=MessageBarConfig(show_progress=True),
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.emit(_make_record())
        assert mock_bar.createMessage.return_value.layout.return_value.addWidget.called

    def test_buttons_added_to_bar_item(self, plugin_name: str, mock_bar: MagicMock) -> None:
        """
        Every button in :attr:`MessageBarConfig.buttons` must be added via
        :meth:`~qgis.PyQt.QtWidgets.QLayout.addWidget`.

        :param plugin_name: The plugin name string.
        :param mock_bar: A mock bar.
        """
        btn = MagicMock()
        handler = QgisHandler(
            plugin_name=plugin_name,
            targets=Target.BAR,
            bar=mock_bar,
            bar_config=MessageBarConfig(buttons=[btn]),
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.emit(_make_record())
        mock_bar.createMessage.return_value.layout.return_value.addWidget.assert_any_call(btn)

    @pytest.mark.parametrize(
        "duration",
        [0, 5],
        ids=["permanent", "timed"],
    )
    def test_duration_set_correctly(
        self,
        plugin_name: str,
        mock_bar: MagicMock,
        duration: int,
    ) -> None:
        """
        :meth:`~qgis.gui.QgsMessageBarItem.setDuration` must be called with ``0`` for
        permanent messages and with the duration in seconds for timed ones.

        :param plugin_name: The plugin name string.
        :param mock_bar: A mock bar.
        :param duration: The ``duration`` field value in seconds.
        """
        handler = QgisHandler(
            plugin_name=plugin_name,
            targets=Target.BAR,
            bar=mock_bar,
            bar_config=MessageBarConfig(duration=duration),
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.emit(_make_record())
        mock_bar.createMessage.return_value.setDuration.assert_called_once_with(duration)

    def test_render_bar_without_bar_raises(self, plugin_name: str) -> None:
        """
        Calling ``_render_bar`` on a handler with no :class:`~qgis.gui.QgsMessageBar` must
        raise :exc:`RuntimeError` rather than rendering silently.

        :param plugin_name: The plugin name string.
        """
        handler = QgisHandler(plugin_name=plugin_name, targets=Target.LOG)
        payload = EmitPayload(
            targets=Target.BAR,
            plugin_name=plugin_name,
            tag=plugin_name,
            message="msg",
            level=logging.INFO,
            bar_config=MessageBarConfig(),
            box_config=MessageBoxConfig(),
        )
        with pytest.raises(RuntimeError, match="QgsMessageBar"):
            handler._render_bar(payload)


# ---------------------------------------------------------------------------
# QgisHandler — emit routing to QMessageBox
# ---------------------------------------------------------------------------


class TestQgisHandlerEmitDialog:
    """Tests for :meth:`QgisHandler.emit` routing to :class:`QMessageBox`."""

    def test_dialog_parented_to_box_parent(self, plugin_name: str) -> None:
        """
        The modal :class:`QMessageBox` must be constructed with the handler's
        ``box_parent`` as its parent widget.

        :param plugin_name: The plugin name string.
        """
        parent = MagicMock()
        handler = QgisHandler(plugin_name=plugin_name, targets=Target.DIALOG, box_parent=parent)
        handler.setFormatter(logging.Formatter("%(message)s"))
        with patch("stratified_packager.toolbelt.logging.QMessageBox") as mock_box:
            handler.emit(_make_record())
            mock_box.assert_called_once_with(parent=parent)

    def test_dialog_parent_defaults_to_none(self, plugin_name: str) -> None:
        """
        When no ``box_parent`` is supplied, the dialog is created parentless.

        :param plugin_name: The plugin name string.
        """
        handler = QgisHandler(plugin_name=plugin_name, targets=Target.DIALOG)
        handler.setFormatter(logging.Formatter("%(message)s"))
        with patch("stratified_packager.toolbelt.logging.QMessageBox") as mock_box:
            handler.emit(_make_record())
            mock_box.assert_called_once_with(parent=None)


# ---------------------------------------------------------------------------
# QgisHandler — per-call overrides resolved in emit
# ---------------------------------------------------------------------------


class TestQgisHandlerPerCallOverrides:
    """Tests for per-call override resolution in :meth:`QgisHandler.emit`."""

    def test_per_call_target_overrides_handler_default(self, basic_handler: QgisHandler) -> None:
        """
        ``_K_TARGETS=Target.DIALOG`` must reroute the record away from LOG.

        :param basic_handler: A handler targeting ``Target.LOG``.
        """
        basic_handler.setFormatter(logging.Formatter("%(message)s"))
        record = _make_record(extra={_K_TARGETS: Target.DIALOG})
        with (
            patch("stratified_packager.toolbelt.logging.QgsMessageLog.logMessage") as mock_log,
            patch.object(basic_handler, "_render_dialog") as mock_dialog,
        ):
            basic_handler.emit(record)
            mock_log.assert_not_called()
            mock_dialog.assert_called_once()

    def test_per_call_bar_config_override(
        self, bar_handler: QgisHandler, mock_bar: MagicMock
    ) -> None:
        """
        ``_K_BAR_CFG`` override must replace the handler's default duration.

        :param bar_handler: A handler targeting ``Target.BAR``.
        :param mock_bar: The mocked message bar.
        """
        bar_handler.setFormatter(logging.Formatter("%(message)s"))
        record = _make_record(extra={_K_BAR_CFG: MessageBarConfig(duration=99)})
        bar_handler.emit(record)
        mock_bar.createMessage.return_value.setDuration.assert_called_once_with(99)

    def test_per_call_box_config_override(self, plugin_name: str) -> None:
        """
        ``_K_BOX_CFG`` override must appear in the payload passed to
        ``_render_dialog``.

        :param plugin_name: The plugin name string.
        """
        handler = QgisHandler(plugin_name=plugin_name, targets=Target.DIALOG)
        handler.setFormatter(logging.Formatter("%(message)s"))
        record = _make_record(
            level=logging.ERROR,
            extra={_K_TARGETS: Target.DIALOG, _K_BOX_CFG: MessageBoxConfig(title="Override")},
        )
        with patch.object(handler, "_render_dialog") as mock_render:
            handler.emit(record)
            payload: EmitPayload = mock_render.call_args[0][0]
            assert payload.box_config.title == "Override"

    def test_handler_defaults_used_when_no_override(self, basic_handler: QgisHandler) -> None:
        """
        When no override keys are present, the payload must reflect the
        handler's own default targets.

        :param basic_handler: A handler targeting ``Target.LOG``.
        """
        basic_handler.setFormatter(logging.Formatter("%(message)s"))
        with patch.object(basic_handler, "_render") as mock_render:
            basic_handler.emit(_make_record())
            payload: EmitPayload = mock_render.call_args[0][0]
            assert payload.targets is basic_handler.targets


# ---------------------------------------------------------------------------
# QgisHandler — thread safety / main-thread dispatch
# ---------------------------------------------------------------------------


class TestQgisHandlerThreadDispatch:
    """Tests for the cross-thread dispatch mechanism in :class:`QgisHandler`."""

    def test_emit_from_main_thread_calls_render_directly(self, basic_handler: QgisHandler) -> None:
        """
        ``_render`` must be called synchronously when on the GUI thread.

        :param basic_handler: A handler targeting ``Target.LOG``.
        """
        basic_handler.setFormatter(logging.Formatter("%(message)s"))
        with (
            patch("stratified_packager.toolbelt.logging._is_main_thread", return_value=True),
            patch.object(basic_handler, "_render") as mock_render,
        ):
            basic_handler.emit(_make_record())
            mock_render.assert_called_once()

    def test_emit_from_qthread_defers_to_gui_thread(
        self, basic_handler: QgisHandler, qtbot: Any
    ) -> None:
        """
        :attr:`~QgisHandlerSignals.message_emitted` must be delivered on the GUI thread when
        ``emit`` is called from a :class:`QThread` worker.

        :param basic_handler: A handler targeting ``Target.LOG``.
        :param qtbot: pytest-qt fixture used to pump the event loop.
        """
        received_thread_ids: list[int] = []
        basic_handler.signals.message_emitted.connect(
            lambda _m, _level: received_thread_ids.append(threading.get_ident())
        )
        basic_handler.setFormatter(logging.Formatter("%(message)s"))

        fired_before_loop: list[bool] = []

        def worker() -> None:
            """Call emit from a QThread worker."""
            with patch("stratified_packager.toolbelt.logging.QgsMessageLog.logMessage"):
                basic_handler.emit(_make_record())
            fired_before_loop.append(len(received_thread_ids) == 0)

        thread = _WorkerThread(target=worker)
        thread.start()
        thread.wait(2_000)
        assert thread.exception is None
        assert fired_before_loop == [True]
        qtbot.wait(50)
        assert len(received_thread_ids) == 1
        assert received_thread_ids[0] == threading.get_ident()

    @pytest.mark.usefixtures("qtbot")
    def test_is_main_thread_returns_false_inside_qthread(self) -> None:
        """``_is_main_thread()`` must return :data:`False` inside a :class:`QThread`."""
        results: list[bool | None] = []

        def worker() -> None:
            """Record _is_main_thread() from the worker."""
            results.append(_is_main_thread())

        thread = _WorkerThread(target=worker)
        thread.start()
        thread.wait(2_000)
        assert thread.exception is None
        assert results == [False]

    def test_concurrent_qthread_emits_do_not_raise(
        self, basic_handler: QgisHandler, qtbot: Any
    ) -> None:
        """
        Five QThread workers x 20 emits must not raise any exception.

        :param basic_handler: A handler targeting ``Target.LOG``.
        :param qtbot: pytest-qt fixture used to drain the event loop.
        """
        basic_handler.setFormatter(logging.Formatter("%(message)s"))

        def worker() -> None:
            """Emit 20 records from a QThread worker."""
            for _ in range(20):
                with patch("stratified_packager.toolbelt.logging.QgsMessageLog.logMessage"):
                    basic_handler.emit(_make_record())

        threads = [_WorkerThread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.wait(5_000)

        exceptions = [t.exception for t in threads if t.exception is not None]
        assert exceptions == []
        qtbot.wait(50)


# ---------------------------------------------------------------------------
# QgisHandler — handleError fallback
# ---------------------------------------------------------------------------


class TestQgisHandlerHandleError:
    """Tests for the :meth:`QgisHandler.emit` error-handling fallback."""

    def test_format_exception_calls_handle_error(self, basic_handler: QgisHandler) -> None:
        """
        A formatter that raises must trigger :meth:`~logging.Handler.handleError`, not propagate.

        :param basic_handler: A handler targeting ``Target.LOG``.
        """
        broken = MagicMock()
        broken.format.side_effect = RuntimeError("formatter broke")
        basic_handler.setFormatter(broken)
        with patch.object(basic_handler, "handleError") as mock_he:
            basic_handler.emit(_make_record())
            mock_he.assert_called_once()


# ---------------------------------------------------------------------------
# QgisLoggerWrapper — _pack_extra and per-call kwarg injection
# ---------------------------------------------------------------------------


class TestQgisLoggerWrapperLog:
    """
    Tests for :meth:`QgisLoggerWrapper._pack_extra` and the per-call
    keyword argument injection across all logging methods.
    """

    # --- _pack_extra unit tests ---

    def test_pack_extra_returns_none_when_no_overrides_and_no_extra(
        self,
    ) -> None:
        """
        When all override args are :data:`None` and *extra* is :data:`None`,
        :meth:`_pack_extra` must return :data:`None` unchanged.
        """
        result: object = QgisLoggerWrapper._pack_extra(
            None, targets=None, bar_config=None, box_config=None
        )
        assert result is None

    def test_pack_extra_returns_equal_dict_when_no_overrides(self) -> None:
        """
        When all override args are :data:`None`, :meth:`_pack_extra` must
        return an unchanged copy of the original *extra* dict object.
        """
        original = {"key": "val"}
        returned = QgisLoggerWrapper._pack_extra(
            original, targets=None, bar_config=None, box_config=None
        )
        assert original == returned
        assert original is not returned

    @pytest.mark.parametrize(
        ("targets", "bar_config", "box_config", "sentinel_key"),
        [
            (Target.DIALOG, None, None, _K_TARGETS),
            (None, MessageBarConfig(duration=3), None, _K_BAR_CFG),
            (None, None, MessageBoxConfig(title="T"), _K_BOX_CFG),
        ],
        ids=["targets", "bar_config", "box_config"],
    )
    def test_pack_extra_injects_override(
        self,
        targets: Target | None,
        bar_config: MessageBarConfig | None,
        box_config: MessageBoxConfig | None,
        sentinel_key: str,
    ) -> None:
        """
        Each override argument must be stored under its sentinel key in the
        returned dict.

        :param targets: Per-call target override.
        :param bar_config: Per-call bar config override.
        :param box_config: Per-call box config override.
        :param sentinel_key: The dict key expected in the result.
        """
        result = QgisLoggerWrapper._pack_extra(
            None, targets=targets, bar_config=bar_config, box_config=box_config
        )
        assert result is not None
        assert sentinel_key in result

    def test_pack_extra_preserves_existing_keys(self) -> None:
        """Existing keys in *extra* must survive alongside the injected QGIS key."""
        result = QgisLoggerWrapper._pack_extra(
            {"feature_id": 42}, targets=Target.LOG, bar_config=None, box_config=None
        )
        assert result["feature_id"] == 42
        assert result[_K_TARGETS] is Target.LOG

    def test_pack_extra_does_not_mutate_caller_dict(self) -> None:
        """The caller's *extra* dict must not be modified in place."""
        original: dict[str, Any] = {"a": 1}
        copy = dict(original)
        QgisLoggerWrapper._pack_extra(
            original, targets=Target.LOG, bar_config=None, box_config=None
        )
        assert original == copy

    # --- Integration: kwargs arrive on the emitted record ---

    def test_no_qgis_kwargs_leaves_no_sentinel_keys(self, clean_logger: str) -> None:
        """
        A plain log call must produce a record with no sentinel keys set.

        :param clean_logger: Logger name with a clean registry entry.
        """
        log = QgisLoggerWrapper.setup(clean_logger)
        captured: list[logging.LogRecord] = []
        log.logger.addHandler(_CapturingHandler(captured))
        log.info("plain")
        record = captured[0]
        assert not hasattr(record, _K_TARGETS)
        assert not hasattr(record, _K_BAR_CFG)
        assert not hasattr(record, _K_BOX_CFG)

    @pytest.mark.parametrize(
        "method_name",
        ["debug", "info", "success", "warning", "error", "critical"],
    )
    def test_all_level_methods_accept_targets_kwarg(
        self, clean_logger: str, method_name: str
    ) -> None:
        """
        Every level-specific method must accept and forward ``targets=``.

        :param clean_logger: Logger name with a clean registry entry.
        :param method_name: The logging method name under test.
        """
        log = QgisLoggerWrapper.setup(clean_logger, level=logging.DEBUG)
        captured: list[logging.LogRecord] = []
        log.logger.addHandler(_CapturingHandler(captured))
        getattr(log, method_name)("msg", targets=Target.DIALOG)
        assert len(captured) == 1
        assert getattr(captured[0], _K_TARGETS) is Target.DIALOG

    def test_log_method_accepts_explicit_level(self, clean_logger: str) -> None:
        """
        The ``log(level, msg, ...)`` method must forward records at the
        supplied level and inject QGIS kwargs correctly.

        :param clean_logger: Logger name with a clean registry entry.
        """
        log = QgisLoggerWrapper.setup(clean_logger, level=logging.DEBUG)
        captured: list[logging.LogRecord] = []
        log.logger.addHandler(_CapturingHandler(captured))
        log.log(logging.WARNING, "msg", targets=Target.LOG)
        assert len(captured) == 1
        assert captured[0].levelno == logging.WARNING
        assert getattr(captured[0], _K_TARGETS) is Target.LOG

    # --- Caller location (stacklevel) ---

    @pytest.mark.parametrize(
        "method_name",
        ["debug", "info", "success", "warning", "error", "critical", "exception"],
    )
    def test_caller_location_reported_not_wrapper(
        self, clean_logger: str, method_name: str
    ) -> None:
        """
        The record's :attr:`~logging.LogRecord.lineno` and :attr:`~logging.LogRecord.funcName`
        must point at the caller.

        It must not point at the wrapper method that forwards to
        :meth:`logging.Logger._log`.

        Guards against the wrapper frame leaking into :meth:`logging.Logger.findCaller`,
        which would otherwise report the line inside the wrapper where ``_log``
        is invoked.

        :param clean_logger: Logger name with a clean registry entry.
        :param method_name: The logging method under test.
        """
        log = QgisLoggerWrapper.setup(clean_logger, level=logging.DEBUG)
        captured: list[logging.LogRecord] = []
        log.logger.addHandler(_CapturingHandler(captured))

        frame = inspect.currentframe()
        assert frame is not None
        expected_lineno = frame.f_lineno + 1
        getattr(log, method_name)("msg")

        assert captured[0].lineno == expected_lineno
        assert captured[0].funcName == "test_caller_location_reported_not_wrapper"

    def test_log_method_reports_caller_location(self, clean_logger: str) -> None:
        """
        The generic :meth:`QgisLoggerWrapper.log` must also report the caller's
        location rather than the wrapper's internal forwarding line.

        :param clean_logger: Logger name with a clean registry entry.
        """
        log = QgisLoggerWrapper.setup(clean_logger, level=logging.DEBUG)
        captured: list[logging.LogRecord] = []
        log.logger.addHandler(_CapturingHandler(captured))

        frame = inspect.currentframe()
        assert frame is not None
        expected_lineno = frame.f_lineno + 1
        log.log(logging.INFO, "msg")

        assert captured[0].lineno == expected_lineno
        assert captured[0].funcName == "test_log_method_reports_caller_location"

    def test_explicit_stacklevel_reports_grandcaller(self, clean_logger: str) -> None:
        """
        A user-supplied ``stacklevel=2`` must report the caller's caller,
        confirming the wrapper's internal frame offset composes with the
        caller-facing ``stacklevel`` contract.

        :param clean_logger: Logger name with a clean registry entry.
        """
        log = QgisLoggerWrapper.setup(clean_logger, level=logging.DEBUG)
        captured: list[logging.LogRecord] = []
        log.logger.addHandler(_CapturingHandler(captured))

        def helper() -> None:
            """Log with ``stacklevel=2`` so this frame is skipped."""
            log.info("msg", stacklevel=2)

        frame = inspect.currentframe()
        assert frame is not None
        expected_lineno = frame.f_lineno + 1
        helper()

        assert captured[0].lineno == expected_lineno
        assert captured[0].funcName == "test_explicit_stacklevel_reports_grandcaller"


# ---------------------------------------------------------------------------
# QgisLoggerWrapper.setup
# ---------------------------------------------------------------------------


class TestQgisLoggerWrapperSetup:
    """Tests for :meth:`QgisLoggerWrapper.setup`."""

    def test_returns_wrapper_instance(self, clean_logger: str) -> None:
        """
        Must return a :class:`QgisLoggerWrapper`.

        :param clean_logger: Logger name with a clean registry entry.
        """
        assert isinstance(QgisLoggerWrapper.setup(clean_logger), QgisLoggerWrapper)

    def test_attaches_qgis_handler(self, clean_logger: str) -> None:
        """
        The underlying logger must have a :class:`QgisHandler` attached.

        :param clean_logger: Logger name with a clean registry entry.
        """
        log = QgisLoggerWrapper.setup(clean_logger)
        assert any(isinstance(h, QgisHandler) for h in log.logger.handlers)

    def test_idempotent_on_repeated_calls(self, clean_logger: str) -> None:
        """
        Repeated calls must return wrappers around the same underlying
        logger and must not accumulate duplicate handlers.

        :param clean_logger: Logger name with a clean registry entry.
        """
        log1 = QgisLoggerWrapper.setup(clean_logger)
        first_handler = next(h for h in log1.logger.handlers if isinstance(h, QgisHandler))
        log2 = QgisLoggerWrapper.setup(clean_logger)
        assert log1.logger is log2.logger
        assert sum(1 for h in log2.logger.handlers if isinstance(h, QgisHandler)) == 1
        assert first_handler not in log2.logger.handlers  # replaced, not retained

    def test_replaces_stale_handler_from_previous_load(self, clean_logger: str) -> None:
        """
        A handler left attached by a previous plugin load must be replaced.

        QGIS purges plugin modules on reload, so such a handler is an instance of a
        re-created class object that defeats ``isinstance`` checks. Each leftover used to
        render every record one extra time per reload.

        :param clean_logger: Logger name with a clean registry entry.
        """

        class StaleHandler(logging.Handler):
            """Stand-in for a ``QgisHandler`` class created by a previous module load."""

            @override
            def emit(self, record: logging.LogRecord) -> None:
                """Render like the real handler would, so duplicates are observable."""
                QgsMessageLog.logMessage(record.getMessage())

        StaleHandler.__module__ = QgisHandler.__module__
        StaleHandler.__qualname__ = QgisHandler.__qualname__
        stale = StaleHandler()
        logging.getLogger(clean_logger).addHandler(stale)

        log = QgisLoggerWrapper.setup(clean_logger)

        assert stale not in log.logger.handlers
        assert sum(1 for h in log.logger.handlers if isinstance(h, QgisHandler)) == 1
        with patch("stratified_packager.toolbelt.logging.QgsMessageLog.logMessage") as mock_log:
            log.info("must be rendered exactly once")
        assert mock_log.call_count == 1

    def test_removes_marked_handler_keeps_foreign(self, clean_logger: str) -> None:
        """
        Handlers carrying the ownership marker must be detached; unmarked foreign
        handlers must be left alone.

        :param clean_logger: Logger name with a clean registry entry.
        """
        logger = logging.getLogger(clean_logger)
        marked = logging.NullHandler()
        setattr(marked, _K_SETUP_OWNED, True)
        foreign = logging.NullHandler()
        logger.addHandler(marked)
        logger.addHandler(foreign)

        QgisLoggerWrapper.setup(clean_logger)

        assert marked not in logger.handlers
        assert foreign in logger.handlers

    def test_filters_do_not_accumulate_across_calls(self, clean_logger: str) -> None:
        """
        Filters attached by a previous call must be replaced, not accumulated.

        :param clean_logger: Logger name with a clean registry entry.
        """
        QgisLoggerWrapper.setup(clean_logger, filters=(QgisContextFilter(),))
        log = QgisLoggerWrapper.setup(clean_logger, filters=(QgisContextFilter(),))
        assert sum(1 for f in log.logger.filters if isinstance(f, QgisContextFilter)) == 1

    def test_replaces_unmarked_filter_of_incoming_type(self, clean_logger: str) -> None:
        """
        An unmarked leftover filter must be replaced when a filter of the same type is
        passed in (heals filters attached by a build predating the ownership marker).

        :param clean_logger: Logger name with a clean registry entry.
        """
        stale_filter = QgisContextFilter(static_fields={"plugin_version": "old"})
        logging.getLogger(clean_logger).addFilter(stale_filter)

        log = QgisLoggerWrapper.setup(clean_logger, filters=(QgisContextFilter(),))

        assert stale_filter not in log.logger.filters
        assert sum(1 for f in log.logger.filters if isinstance(f, QgisContextFilter)) == 1

    def test_tolerates_unmarkable_filter(self, clean_logger: str) -> None:
        """
        A slotted filter that rejects the ownership marker must still be attached.

        :param clean_logger: Logger name with a clean registry entry.
        """

        class SlottedFilter:
            """A filter object that cannot take new attributes."""

            __slots__ = ()

            def filter(self, _record: logging.LogRecord) -> bool:
                """Let every record through."""
                return True

        slotted = SlottedFilter()
        log = QgisLoggerWrapper.setup(clean_logger, filters=(slotted,))
        assert slotted in log.logger.filters

    def test_propagate_false_by_default(self, clean_logger: str) -> None:
        """
        :attr:`~logging.Logger.propagate` must default to :data:`False`.

        :param clean_logger: Logger name with a clean registry entry.
        """
        assert QgisLoggerWrapper.setup(clean_logger).logger.propagate is False

    def test_custom_level_applied(self, clean_logger: str) -> None:
        """
        The ``level=`` parameter must set the effective level on the logger.

        :param clean_logger: Logger name with a clean registry entry.
        """
        assert (
            QgisLoggerWrapper.setup(clean_logger, level=logging.WARNING).logger.level
            == logging.WARNING
        )

    def test_box_parent_taken_from_iface_main_window(self, clean_logger: str) -> None:
        """
        When an ``iface`` is supplied, the handler's box parent must be
        ``iface.mainWindow()``.

        :param clean_logger: Logger name with a clean registry entry.
        """
        mock_iface = MagicMock()
        log = QgisLoggerWrapper.setup(clean_logger, iface=mock_iface)
        handler = next(h for h in log.logger.handlers if isinstance(h, QgisHandler))
        assert handler._box_parent is mock_iface.mainWindow.return_value

    def test_box_parent_none_without_iface(self, clean_logger: str) -> None:
        """
        Without an ``iface``, the handler's box parent must be :data:`None`.

        :param clean_logger: Logger name with a clean registry entry.
        """
        log = QgisLoggerWrapper.setup(clean_logger)
        handler = next(h for h in log.logger.handlers if isinstance(h, QgisHandler))
        assert handler._box_parent is None

    def test_wraps_standard_logging_logger(self, clean_logger: str) -> None:
        """
        The underlying logger must be a plain :class:`logging.Logger`,
        confirming composition rather than subclassing.

        :param clean_logger: Logger name with a clean registry entry.
        """
        log = QgisLoggerWrapper.setup(clean_logger)
        assert log.logger.__class__ is logging.Logger

    @pytest.mark.parametrize(
        "use_custom",
        [False, True],
        ids=["default_formatter", "custom_formatter"],
    )
    def test_formatter_attached(self, clean_logger: str, use_custom: bool) -> None:
        """
        A formatter must always be attached to the handler — either the
        custom one supplied or the built-in default.

        :param clean_logger: Logger name with a clean registry entry.
        :param use_custom: Whether to pass a custom :class:`~logging.Formatter`.
        """
        fmt = logging.Formatter("CUSTOM: %(message)s") if use_custom else None
        log = QgisLoggerWrapper.setup(clean_logger, formatter=fmt)
        handler = next(h for h in log.logger.handlers if isinstance(h, QgisHandler))
        assert handler.formatter is not None
        if use_custom:
            assert handler.formatter is fmt


# ---------------------------------------------------------------------------
# QgisLoggerWrapper.teardown
# ---------------------------------------------------------------------------


class TestQgisLoggerWrapperTeardown:
    """Tests for :meth:`QgisLoggerWrapper.teardown`."""

    def test_detaches_handler(self, clean_logger: str) -> None:
        """
        The handler attached by ``setup`` must be gone after teardown.

        :param clean_logger: Logger name with a clean registry entry.
        """
        log = QgisLoggerWrapper.setup(clean_logger)
        QgisLoggerWrapper.teardown(clean_logger)
        assert not any(isinstance(h, QgisHandler) for h in log.logger.handlers)

    def test_closes_handler_and_disposes_signals_carrier(self, clean_logger: str) -> None:
        """
        Teardown must close the handler and schedule its signals carrier for deletion.

        :param clean_logger: Logger name with a clean registry entry.
        """
        log = QgisLoggerWrapper.setup(clean_logger)
        handler = next(h for h in log.logger.handlers if isinstance(h, QgisHandler))
        with (
            patch.object(handler, "close", wraps=handler.close) as mock_close,
            patch.object(handler.signals, "deleteLater") as mock_delete_later,
        ):
            QgisLoggerWrapper.teardown(clean_logger)
        mock_close.assert_called_once()
        mock_delete_later.assert_called_once()

    def test_removes_marked_filters_keeps_foreign(self, clean_logger: str) -> None:
        """
        Filters attached by ``setup`` must be removed; foreign filters must stay.

        :param clean_logger: Logger name with a clean registry entry.
        """
        log = QgisLoggerWrapper.setup(clean_logger, filters=(QgisContextFilter(),))
        foreign = logging.Filter()
        log.logger.addFilter(foreign)

        QgisLoggerWrapper.teardown(clean_logger)

        assert not any(isinstance(f, QgisContextFilter) for f in log.logger.filters)
        assert foreign in log.logger.filters

    def test_noop_without_setup_and_idempotent(self, clean_logger: str) -> None:
        """
        Teardown must be safe without a prior ``setup`` and when called repeatedly.

        :param clean_logger: Logger name with a clean registry entry.
        """
        QgisLoggerWrapper.teardown(clean_logger)
        QgisLoggerWrapper.setup(clean_logger)
        QgisLoggerWrapper.teardown(clean_logger)
        QgisLoggerWrapper.teardown(clean_logger)
        assert not logging.getLogger(clean_logger).handlers


# ---------------------------------------------------------------------------
# QgisLoggerWrapper.get_logger
# ---------------------------------------------------------------------------


class TestQgisLoggerWrapperGetLogger:
    """Tests for :meth:`QgisLoggerWrapper.get_logger`."""

    def test_returns_wrapper_instance(self, clean_logger: str) -> None:
        """
        Must return a :class:`QgisLoggerWrapper`.

        :param clean_logger: Logger name.
        """
        assert isinstance(QgisLoggerWrapper.get_logger(clean_logger), QgisLoggerWrapper)

    def test_no_handler_attached(self, clean_logger: str) -> None:
        """
        A child logger must have no handlers — it propagates to the root.

        :param clean_logger: Logger name.
        """
        log = QgisLoggerWrapper.get_logger(clean_logger)
        assert not any(isinstance(h, QgisHandler) for h in log.logger.handlers)

    def test_propagate_true_by_default(self, clean_logger: str) -> None:
        """
        :attr:`~logging.Logger.propagate` must be :data:`True` so records flow to the root logger.

        :param clean_logger: Logger name.
        """
        assert QgisLoggerWrapper.get_logger(clean_logger).logger.propagate is True

    def test_idempotent_on_repeated_calls(self, clean_logger: str) -> None:
        """
        Repeated calls must return wrappers around the same underlying logger.

        :param clean_logger: Logger name.
        """
        assert (
            QgisLoggerWrapper.get_logger(clean_logger).logger
            is QgisLoggerWrapper.get_logger(clean_logger).logger
        )

    def test_wraps_standard_logging_logger(self, clean_logger: str) -> None:
        """
        The underlying logger must be a plain :class:`logging.Logger`.

        :param clean_logger: Logger name.
        """
        assert QgisLoggerWrapper.get_logger(clean_logger).logger.__class__ is logging.Logger

    def test_does_not_modify_global_logger_class(self, clean_logger: str) -> None:
        """
        :meth:`QgisLoggerWrapper.get_logger` must never call :func:`logging.setLoggerClass`.

        :param clean_logger: Logger name.
        """
        previous = logging.getLoggerClass()
        with patch("logging.setLoggerClass") as mock_set:
            QgisLoggerWrapper.get_logger(clean_logger)
            mock_set.assert_not_called()
        assert logging.getLoggerClass() is previous

    def test_child_records_propagate_to_root_handler(self, clean_logger: str) -> None:
        """
        Records on a child logger must reach the root handler via propagation.

        :param clean_logger: Root logger name.
        """
        root = QgisLoggerWrapper.setup(clean_logger)
        captured: list[logging.LogRecord] = []
        root.logger.addHandler(_CapturingHandler(captured))

        child = QgisLoggerWrapper.get_logger(f"{clean_logger}.sub")
        child.info("from child")

        assert len(captured) == 1
        assert captured[0].name == f"{clean_logger}.sub"

    def test_child_logger_name_appears_in_record(self, clean_logger: str) -> None:
        """
        The :attr:`~logging.LogRecord.name` attribute on propagated records must be the
        child's name.

        :param clean_logger: Root logger name.
        """
        QgisLoggerWrapper.setup(clean_logger)
        captured: list[logging.LogRecord] = []
        logging.getLogger(clean_logger).addHandler(_CapturingHandler(captured))

        child_name = f"{clean_logger}.network.http"
        QgisLoggerWrapper.get_logger(child_name).warning("deep child")

        assert captured[0].name == child_name

    def test_multiple_children_share_root_handler(self, clean_logger: str) -> None:
        """
        Multiple child loggers must all route through the single root handler.

        :param clean_logger: Root logger name.
        """
        root = QgisLoggerWrapper.setup(clean_logger)
        captured: list[logging.LogRecord] = []
        root.logger.addHandler(_CapturingHandler(captured))

        for suffix in ("a", "b", "c"):
            QgisLoggerWrapper.get_logger(f"{clean_logger}.{suffix}").info(suffix)

        assert len(captured) == 3
        assert {r.name for r in captured} == {
            f"{clean_logger}.a",
            f"{clean_logger}.b",
            f"{clean_logger}.c",
        }


# ---------------------------------------------------------------------------
# QgisLoggerWrapper._default_formatter
# ---------------------------------------------------------------------------


class TestQgisLoggerWrapperDefaultFormatter:
    """Tests for :meth:`QgisLoggerWrapper._default_formatter`."""

    def test_returns_formatter_instance(self) -> None:
        """Must return a :class:`logging.Formatter`."""
        assert isinstance(QgisLoggerWrapper._default_formatter(), logging.Formatter)

    @pytest.mark.parametrize(
        ("kwargs", "expected_substring"),
        [
            ({"level": logging.WARNING}, "WARNING"),
            ({"msg": "sentinel_text"}, "sentinel_text"),
        ],
        ids=["levelname", "message"],
    )
    def test_format_output_contains(self, kwargs: dict[str, Any], expected_substring: str) -> None:
        """
        The formatted string must contain the level name and message text.

        :param kwargs: Arguments forwarded to :func:`_make_record`.
        :param expected_substring: The substring expected in the output.
        """
        output = QgisLoggerWrapper._default_formatter().format(_make_record(**kwargs))
        assert expected_substring in output


# ---------------------------------------------------------------------------
# _is_main_thread
# ---------------------------------------------------------------------------


class TestIsMainThread:
    """Tests for :func:`_is_main_thread`."""

    def test_returns_true_on_gui_thread(self) -> None:
        """Must return :data:`True` when called from the Qt GUI thread."""
        assert _is_main_thread() is True

    def test_returns_false_inside_qthread(self) -> None:
        """Must return :data:`False` when called from a :class:`QThread` worker."""
        results: list[bool | None] = []

        def worker() -> None:
            """Append result from the worker thread."""
            results.append(_is_main_thread())

        thread = _WorkerThread(target=worker)
        thread.start()
        thread.wait(2_000)
        assert thread.exception is None
        assert results == [False]


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------


class TestIntegration:
    """End-to-end integration tests."""

    def test_context_filter_fields_available_in_handler(self, clean_logger: str) -> None:
        """
        Fields from :class:`QgisContextFilter` must reach downstream handlers.

        :param clean_logger: Logger name with a clean registry entry.
        """
        log = QgisLoggerWrapper.setup(clean_logger)
        log.logger.addFilter(QgisContextFilter())
        captured: list[logging.LogRecord] = []
        log.logger.addHandler(_CapturingHandler(captured))
        log.info("integration test")
        assert hasattr(captured[0], "qgis_version")
        assert captured[0].qgis_version == Qgis.version()

    def test_target_filter_on_handler_blocks_low_level(self, clean_logger: str) -> None:
        """
        A :class:`TargetFilter` with ``min_level=WARNING`` must block all
        records below :data:`~logging.WARNING`.

        :param clean_logger: Logger name with a clean registry entry.
        """
        log = QgisLoggerWrapper.setup(clean_logger, level=logging.DEBUG)
        captured: list[logging.LogRecord] = []
        capturing = _CapturingHandler(captured)
        capturing.addFilter(TargetFilter(allowed_targets=Target.LOG, min_level=logging.WARNING))
        log.logger.addHandler(capturing)

        log.debug("blocked")
        log.info("blocked")
        log.success("blocked")
        log.warning("passes")
        log.error("passes")

        assert len(captured) == 2
        assert captured[0].getMessage() == "passes"
        assert captured[1].getMessage() == "passes"

    def test_per_call_target_override_with_target_filter(self, clean_logger: str) -> None:
        """
        A DIALOG-filtered handler must not receive LOG-targeted records.

        :param clean_logger: Logger name with a clean registry entry.
        """
        log = QgisLoggerWrapper.setup(clean_logger)
        captured: list[logging.LogRecord] = []
        capturing = _CapturingHandler(captured)
        capturing.addFilter(TargetFilter(allowed_targets=Target.DIALOG))
        log.logger.addHandler(capturing)

        log.info("to log", targets=Target.LOG)
        assert not captured

        log.error("to dialog", targets=Target.DIALOG)
        assert len(captured) == 1

    def test_static_fields_in_formatted_output(self, clean_logger: str) -> None:
        """
        Static fields from :class:`QgisContextFilter` must reach handlers.

        :param clean_logger: Logger name with a clean registry entry.
        """
        log = QgisLoggerWrapper.setup(clean_logger)
        log.logger.addFilter(QgisContextFilter(static_fields={"plugin_version": "9.9.9"}))
        captured: list[logging.LogRecord] = []
        log.logger.addHandler(_CapturingHandler(captured))
        log.info("msg")
        assert captured[0].__dict__["plugin_version"] == "9.9.9"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class _WorkerThread(QThread):
    """
    A :class:`QThread` subclass that runs a callable and captures exceptions.

    :param target: Callable to invoke on the worker thread.
    """

    def __init__(self, target: Any) -> None:
        super().__init__()
        self._target: Any = target
        self.exception: BaseException | None = None

    @override
    def run(self) -> None:
        """Execute *target* and store any raised exception."""
        try:
            self._target()
        except BaseException as exc:  # noqa: BLE001
            self.exception = exc


class _CapturingHandler(logging.Handler):
    """
    A :class:`logging.Handler` that appends every record to a list.

    :param records: The list to which records are appended.
    """

    def __init__(self, records: list[logging.LogRecord]) -> None:
        super().__init__(logging.NOTSET)
        self._records: list[logging.LogRecord] = records

    @override
    def emit(self, record: logging.LogRecord) -> None:
        """
        Append *record* to the internal list.

        :param record: The record to store.
        """
        self._records.append(record)
