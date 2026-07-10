"""
A thread-safe, structured logging suite for QGIS 4.0+ plugins.

This module provides a :class:`QgisHandler` — a :class:`logging.Handler`
subclass — that routes standard-library log records to any combination of:

* :class:`qgis.core.QgsMessageLog` (the QGIS application log panel)
* :class:`qgis.gui.QgsMessageBar` (the in-canvas notification bar)
* :class:`~qgis.PyQt.QtWidgets.QMessageBox` (modal dialogs)

Plugin developers call :meth:`QgisLoggerWrapper.setup` once per plugin to
create the root logger wired to a :class:`QgisHandler`, then call
:meth:`QgisLoggerWrapper.get_logger` in each sub-module to obtain a named
child wrapper that propagates records up to the root handler automatically:

.. code-block:: python

    # In the plugin's __init__.py — once per plugin:
    root = QgisLoggerWrapper.setup(
        name="MyPlugin",
        targets=Target.LOG | Target.BAR,
    )

    # In any sub-module — no handler needed:
    log = QgisLoggerWrapper.get_logger("MyPlugin.utils")
    log = QgisLoggerWrapper.get_logger("MyPlugin.network.http")

    # Per-call overrides work on any wrapper regardless of hierarchy level.
    log.warning(
        "No features selected.",
        targets=Target.DIALOG,
        box_config=MessageBoxConfig(title="Selection warning"),
    )

On plugin unload, call :meth:`QgisLoggerWrapper.teardown` to detach and dispose everything
:meth:`~QgisLoggerWrapper.setup` attached: the :mod:`logging` registry is process-global and
survives QGIS plugin reloads, so a handler left behind would render every record one extra
time per reload.

Thread safety
-------------
:class:`QgisHandler` owns a :class:`QgisHandlerSignals` instance that lives
on the GUI thread. Cross-thread dispatch is handled by connecting the private
:attr:`~QgisHandlerSignals._render_requested` signal to :meth:`QgisHandler._render`
with the default ``AutoConnection``, which Qt automatically promotes to a
``QueuedConnection`` when the signal is emitted from a worker thread.
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, Final, Protocol, overload, override

from qgis.core import QgsMessageLog
from qgis.PyQt.QtCore import QObject, QThread, pyqtSignal
from qgis.PyQt.QtWidgets import QApplication, QMessageBox, QProgressBar, QWidget

from .logging_records import (
    _K_BAR_CFG,
    _K_BOX_CFG,
    _K_TARGETS,
    SUCCESS,
    EmitPayload,
    MessageBarConfig,
    MessageBoxConfig,
    QgisContextFilter,
    Target,
    TargetFilter,
    _qmsgbox_icon,
    level_to_qgis,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Container, Iterable, Mapping
    from types import TracebackType

    from qgis.gui import QgisInterface, QgsMessageBar

    class _SupportsFilter(Protocol):
        def filter(self, record: logging.LogRecord, /) -> bool | logging.LogRecord: ...

    type _FilterType = (
        logging.Filter | Callable[[logging.LogRecord], bool | logging.LogRecord] | _SupportsFilter
    )
    type _SysExcInfoType = (
        tuple[type[BaseException], BaseException, TracebackType | None] | tuple[None, None, None]
    )


# Re-exported so ``from ...toolbelt.logging import Target`` (and the rest) keeps working; the
# record-level machinery physically lives in ``logging_records``.
__all__: list[str] = [
    "SUCCESS",
    "EmitPayload",
    "MessageBarConfig",
    "MessageBoxConfig",
    "QgisContextFilter",
    "QgisHandler",
    "QgisHandlerSignals",
    "QgisLoggerWrapper",
    "Target",
    "TargetFilter",
    "level_to_qgis",
]

# ---------------------------------------------------------------------------
# Private sentinel key: the ownership marker stamped on objects attached by
# QgisLoggerWrapper.setup (the per-call override keys live in logging_records)
# ---------------------------------------------------------------------------

_K_SETUP_OWNED: Final = "_qgis_setup_owned"
"""
Marker attribute stamped on handlers and filters attached by :meth:`QgisLoggerWrapper.setup`.

Stored on the attached objects themselves (not on records) so that a later call — possibly
made by a fresh import of this module after a QGIS plugin reload, when all class objects
have been re-created — can still recognize and replace them.
"""


# ---------------------------------------------------------------------------
# Logger wrapper
# ---------------------------------------------------------------------------


def _is_setup_owned(obj: object) -> bool:
    """
    Return whether *obj* carries the :data:`_K_SETUP_OWNED` ownership marker.

    :param obj: A handler or filter currently attached to a logger.
    :return: :data:`True` when *obj* was attached by :meth:`QgisLoggerWrapper.setup`.
    """
    return getattr(obj, _K_SETUP_OWNED, False) is True


def _mark_setup_owned(obj: object) -> None:
    """
    Stamp the :data:`_K_SETUP_OWNED` ownership marker onto *obj*, best-effort.

    Objects that reject new attributes (e.g. slotted classes) are left unmarked; stale
    instances of such filters are still replaced by the type matching in
    :meth:`QgisLoggerWrapper.setup`.

    :param obj: A handler or filter being attached by :meth:`QgisLoggerWrapper.setup`.
    """
    with contextlib.suppress(AttributeError):
        setattr(obj, _K_SETUP_OWNED, True)


def _is_qgis_handler_like(handler: logging.Handler) -> bool:
    """
    Return whether *handler* is a :class:`QgisHandler`, including stale-class instances.

    An :func:`isinstance` check alone is not reload-safe: QGIS purges the plugin's modules
    from :data:`sys.modules` on reload and re-imports them, so a handler attached by a
    previous load is an instance of that load's — now stale — class object, which fails
    :func:`isinstance` against the freshly imported :class:`QgisHandler`. Such instances
    are recognized by their type's ``__module__`` / ``__qualname__`` pair instead.

    :param handler: The handler to inspect.
    :return: :data:`True` for current and stale :class:`QgisHandler` instances.
    """
    return isinstance(handler, QgisHandler) or (
        type(handler).__module__ == QgisHandler.__module__
        and type(handler).__qualname__ == QgisHandler.__qualname__
    )


def _detach_setup_artifacts(
    logger: logging.Logger,
    filter_types: Container[tuple[str, str]] = (),
) -> None:
    """
    Detach and dispose everything :meth:`QgisLoggerWrapper.setup` attached to *logger*.

    Handlers are detached when they carry the :data:`_K_SETUP_OWNED` marker or are
    (possibly stale) :class:`QgisHandler` instances; each one is closed, its
    :class:`QgisHandlerSignals` carrier is disconnected and scheduled for deletion, and
    cross-thread render payloads still queued on it are dropped. Filters are detached when
    they carry the marker or when their type's ``(__module__, __qualname__)`` pair is in
    *filter_types*. Handlers and filters attached by other code are left untouched.

    Disposal of each handler is contained: a failure is logged at WARNING level and the
    remaining cleanup proceeds.

    :param logger: The logger to clean.
    :param filter_types: ``(__module__, __qualname__)`` pairs of filter types whose
        unmarked instances (attached by a build of this module predating the marker)
        should also be detached.
    """
    for handler in list(logger.handlers):
        if not (_is_setup_owned(handler) or _is_qgis_handler_like(handler)):
            continue
        logger.removeHandler(handler)
        try:
            handler.close()
            signals = getattr(handler, "signals", None)
            if isinstance(signals, QObject):
                render_requested = getattr(signals, "_render_requested", None)
                if render_requested is not None:
                    # Deletion below would also disconnect, but only once the event loop
                    # spins; disconnecting now stops already-queued worker payloads from
                    # rendering through a handler that is no longer attached.
                    with contextlib.suppress(TypeError):  # raised when nothing is connected
                        render_requested.disconnect()
                signals.deleteLater()
        except Exception:  # noqa: BLE001  # cleanup boundary: keep detaching the rest
            logger.warning("Failed to dispose logging handler %r.", handler, exc_info=True)

    for log_filter in list(logger.filters):
        if _is_setup_owned(log_filter) or (
            (type(log_filter).__module__, type(log_filter).__qualname__) in filter_types
        ):
            logger.removeFilter(log_filter)


class QgisLoggerWrapper:
    """
    A :class:`logging.Logger` wrapper that takes QGIS-specific keyword arguments on logging calls.

    Rather than subclassing :class:`logging.Logger` — which would require
    overriding the private ``logging.Logger._log`` method with a signature incompatible with
    the base class, violating the Liskov Substitution Principle — this class
    holds a plain :class:`logging.Logger` instance via composition and
    delegates all logging calls to it after packing any QGIS-specific kwargs
    into the ``extra`` dict.

    The wrapped logger is accessible via the :attr:`logger` property for the
    rare cases where a plain :class:`logging.Logger` reference may be needed.

    All standard logging methods (:meth:`debug`, :meth:`info`, :meth:`warning`, :meth:`error`,
    :meth:`critical`, :meth:`exception`, :meth:`log`) — plus the custom-level :meth:`success` —
    accept three optional keyword-only arguments in addition to the standard ones:

    * ``targets`` — override the handler's :attr:`QgisHandler.targets` for this record only.
    * ``bar_config`` — override the handler's :attr:`QgisHandler.bar_config` for this record.
    * ``box_config`` — override the handler's :attr:`QgisHandler.box_config` for this record.

    Typical usage — one :meth:`setup` call per plugin, then :meth:`get_logger`
    in every sub-module::

        # plugin/__init__.py
        root = QgisLoggerWrapper.setup("MyPlugin", targets=Target.LOG)

        # plugin/plugin_main.py
        log = QgisLoggerWrapper.get_logger("MyPlugin.plugin_main")

        # plugin/processing/provider.py
        log = QgisLoggerWrapper.get_logger("MyPlugin.processing.provider")

    Do not call the constructor directly; use :meth:`setup` or
    :meth:`get_logger` so that the :mod:`logging` registry is managed
    correctly and the wrapped logger participates in the hierarchy.
    """

    def __init__(self, logger: logging.Logger) -> None:
        """
        Private constructor; use :meth:`setup` or :meth:`get_logger`.

        :param logger: The :class:`logging.Logger` to wrap.
        """
        self._logger: logging.Logger = logger

    @property
    def logger(self) -> logging.Logger:
        """
        The underlying :class:`logging.Logger` instance.

        :return: The wrapped :class:`logging.Logger`.
        """
        return self._logger

    @classmethod
    def setup(
        cls,
        name: str,
        targets: Target = Target.LOG,
        iface: QgisInterface | None = None,
        tag: str | None = None,
        bar_config: MessageBarConfig | None = None,
        box_config: MessageBoxConfig | None = None,
        level: int = logging.DEBUG,
        formatter: logging.Formatter | None = None,
        *,
        propagate: bool = False,
        filters: Iterable[_FilterType] | None = None,
    ) -> QgisLoggerWrapper:
        """
        Create or retrieve the root plugin logger, wired to a :class:`QgisHandler`.

        Call this **once per plugin** (typically in the plugin's
        ``__init__.py`` or ``classFactory``). It obtains a
        :class:`logging.Logger` named *name* from the :mod:`logging` registry,
        attaches a :class:`QgisHandler` to it, wraps it in a
        :class:`QgisLoggerWrapper`, and returns the wrapper.

        Repeated calls are safe and idempotent: handlers and filters attached by a
        previous call are detached and disposed first, then rebuilt from the current
        arguments. This also holds across QGIS plugin reloads — the reloader purges the
        plugin's modules and re-imports them, so the handler left attached to the
        process-global :mod:`logging` registry by the previous load is an instance of a
        stale class object; it is detected by type name and replaced. Leaving it attached
        would render every record one extra time per reload. Call :meth:`teardown` from
        the plugin's ``unload()`` to detach without re-attaching.

        Sub-module loggers should be created with :meth:`get_logger` using
        dotted child names; they propagate records to this root logger
        automatically and require no handler of their own.

        :param name: Logger name and human-readable identifier used in QGIS
            UI targets (e.g. the :class:`~qgis.core.QgsMessageLog` tag). Typically the
            plugin's display name (e.g. ``"MyPlugin"``).
        :param targets: Default output targets. Can be overridden per call.
            Defaults to ``Target.LOG``.
        :param iface: The QGIS interface instance, used to obtain the message
            bar for ``Target.BAR`` output and the main window as the parent for
            ``Target.DIALOG`` modal dialogs.
        :param tag: Topic label for :class:`~qgis.core.QgsMessageLog`; falls
            back to *name* when :data:`None`.
        :param bar_config: Default message-bar display options.
        :param box_config: Default modal-dialog display options.
        :param level: Minimum level this logger forwards to its handler.
        :param formatter: A custom :class:`logging.Formatter`. When :data:`None`,
            :meth:`_default_formatter` is used.
        :param propagate: Whether to propagate records to ancestor loggers.
            Defaults to :data:`False` to prevent duplicate output via the root
            logging handler.
        :param filters: Iterable of filters to add to the logger. Filters of the same
            types attached by a previous call are replaced.
        :return: A :class:`QgisLoggerWrapper` wrapping the configured root logger.
        """
        logger = logging.getLogger(name)

        # Materialized once: consumed both for stale-type matching and for attachment below.
        new_filters: tuple[_FilterType, ...] = tuple(filters) if filters is not None else ()

        # Detach whatever a previous call attached. An isinstance() check is not enough to
        # recognize leftovers: after a plugin reload they are instances of stale class
        # objects (see _is_qgis_handler_like), and each one left attached would render
        # every record one extra time.
        _detach_setup_artifacts(
            logger,
            filter_types={(type(f).__module__, type(f).__qualname__) for f in new_filters},
        )

        logger.setLevel(level)
        logger.propagate = propagate

        handler = QgisHandler(
            plugin_name=name,
            targets=targets,
            tag=tag,
            bar=iface.messageBar() if iface is not None else None,
            box_parent=iface.mainWindow() if iface is not None else None,
            bar_config=bar_config,
            box_config=box_config,
        )
        handler.setFormatter(formatter or cls._default_formatter())
        _mark_setup_owned(handler)
        logger.addHandler(handler)

        for log_filter in new_filters:
            _mark_setup_owned(log_filter)
            logger.addFilter(log_filter)

        return cls(logger)

    @classmethod
    def teardown(cls, name: str) -> None:
        """
        Detach and dispose everything :meth:`setup` attached to the logger named *name*.

        Call this from the plugin's ``unload()`` so the handler does not outlive the
        plugin: the :mod:`logging` registry is process-global, so a handler left attached
        would both leak (its :class:`QgisHandlerSignals` carrier is a
        :class:`~qgis.PyQt.QtCore.QObject`) and render every record once more alongside
        the handler installed by the next load. The handler is closed and its signals
        carrier disconnected and scheduled for deletion; cross-thread render payloads
        still queued on it are dropped. Filters attached by :meth:`setup` are removed;
        handlers and filters attached by other code are left untouched.

        Safe to call when :meth:`setup` never ran for *name*. Records logged after
        teardown fall back to :data:`logging.lastResort` (stderr) until :meth:`setup`
        runs again.

        :param name: Root plugin logger name previously passed to :meth:`setup`.
        """
        _detach_setup_artifacts(logging.getLogger(name))

    @classmethod
    def get_logger(cls, name: str) -> QgisLoggerWrapper:
        """
        Retrieve or create a named child logger with no handler attached.

        Use this in every sub-module that needs a logger. Records propagate
        to the nearest ancestor that has a handler — which should be the root
        plugin logger created by :meth:`setup`::

            log = QgisLoggerWrapper.get_logger("MyPlugin.utils")
            log = QgisLoggerWrapper.get_logger("MyPlugin.network.http")

        :param name: Dotted logger name. Should start with the root plugin
            name to participate in the plugin's logging hierarchy (e.g.
            ``"MyPlugin.utils"``).
        :return: A :class:`QgisLoggerWrapper` around the named logger, which
            has no handlers and ``propagate`` set to :data:`True` (the
            :mod:`logging` default for new loggers).
        """
        return cls(logging.getLogger(name))

    @staticmethod
    def _default_formatter() -> logging.Formatter:
        """
        Build the default structured log formatter.

        The format string produces records like::

            2024-11-01 14:23:05,123 [WARNING ] MyPlugin.plugin_main:42 — File not found.

        :return: A :class:`logging.Formatter` instance.
        """
        fmt = "%(asctime)s [%(levelname)-8s] %(name)s:%(lineno)d — %(message)s"
        datefmt = "%Y-%m-%d %H:%M:%S"
        return logging.Formatter(fmt=fmt, datefmt=datefmt)

    @overload
    @staticmethod
    def _pack_extra(
        extra: None, *, targets: None = ..., bar_config: None = ..., box_config: None = ...
    ) -> None: ...

    @overload
    @staticmethod
    def _pack_extra(
        extra: Mapping[str, object],
        *,
        targets: Target | None = ...,
        bar_config: MessageBarConfig | None = ...,
        box_config: MessageBoxConfig | None = ...,
    ) -> dict[str, object]: ...

    @overload
    @staticmethod
    def _pack_extra(
        extra: Mapping[str, object] | None,
        *,
        targets: Target,
        bar_config: MessageBarConfig | None = ...,
        box_config: MessageBoxConfig | None = ...,
    ) -> dict[str, object]: ...

    @overload
    @staticmethod
    def _pack_extra(
        extra: Mapping[str, object] | None,
        *,
        targets: Target | None = ...,
        bar_config: MessageBarConfig,
        box_config: MessageBoxConfig | None = ...,
    ) -> dict[str, object]: ...

    @overload
    @staticmethod
    def _pack_extra(
        extra: Mapping[str, object] | None,
        *,
        targets: Target | None = ...,
        bar_config: MessageBarConfig | None = ...,
        box_config: MessageBoxConfig,
    ) -> dict[str, object]: ...

    @staticmethod
    def _pack_extra(
        extra: Mapping[str, object] | None,
        *,
        targets: Target | None = None,
        bar_config: MessageBarConfig | None = None,
        box_config: MessageBoxConfig | None = None,
    ) -> dict[str, object] | None:
        r"""
        Merge QGIS-specific overrides into a fresh copy of ``extra``.

        When all arguments are :data:`None`, :data:`None` is returned
        immediately so the common no-override path has no allocation cost.

        :param extra: A dictionary used to populate the __dict__ of the LogRecord
            created for the logging event with user-defined attributes.
        :param targets: Per-call :class:`~.logging_records.Target` override, or
            :data:`None` to use the handler default.
        :param bar_config: Per-call :class:`~.logging_records.MessageBarConfig` override,
            or :data:`None` to use the handler default.
        :param box_config: Per-call :class:`~.logging_records.MessageBoxConfig` override,
            or :data:`None` to use the handler default.
        :return: A new dict merging the provided *extra* with the QGIS-specific
            overrides under the private keys defined in this module, or
            :data:`None` if all arguments are :data:`None`.
        """
        if all(value is None for value in locals().values()):
            return None

        # Merge into a fresh copy so we never mutate the caller's dict.
        new_extra = dict(extra) if extra is not None else {}

        if targets is not None:
            new_extra[_K_TARGETS] = targets
        if bar_config is not None:
            new_extra[_K_BAR_CFG] = bar_config
        if box_config is not None:
            new_extra[_K_BOX_CFG] = box_config

        return new_extra

    def debug(
        self,
        msg: object,
        *args: object,
        exc_info: bool | _SysExcInfoType | BaseException | None = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        extra: Mapping[str, object] | None = None,
        targets: Target | None = None,
        bar_config: MessageBarConfig | None = None,
        box_config: MessageBoxConfig | None = None,
    ) -> None:
        """
        Log ``msg % args`` with severity :data:`~logging.DEBUG`.

        See :meth:`QgisLoggerWrapper.log` for details on parameters.
        """
        self._logger.debug(
            msg,
            *args,
            exc_info=exc_info,
            stack_info=stack_info,
            stacklevel=stacklevel + 1,
            extra=self._pack_extra(
                extra, targets=targets, bar_config=bar_config, box_config=box_config
            ),
        )

    def info(
        self,
        msg: object,
        *args: object,
        exc_info: bool | _SysExcInfoType | BaseException | None = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        extra: Mapping[str, object] | None = None,
        targets: Target | None = None,
        bar_config: MessageBarConfig | None = None,
        box_config: MessageBoxConfig | None = None,
    ) -> None:
        """
        Log ``msg % args`` with severity :data:`~logging.INFO`.

        See :meth:`QgisLoggerWrapper.log` for details on parameters.
        """
        self._logger.info(
            msg,
            *args,
            exc_info=exc_info,
            stack_info=stack_info,
            stacklevel=stacklevel + 1,
            extra=self._pack_extra(
                extra, targets=targets, bar_config=bar_config, box_config=box_config
            ),
        )

    def success(
        self,
        msg: object,
        *args: object,
        exc_info: bool | _SysExcInfoType | BaseException | None = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        extra: Mapping[str, object] | None = None,
        targets: Target | None = None,
        bar_config: MessageBarConfig | None = None,
        box_config: MessageBoxConfig | None = None,
    ) -> None:
        """
        Log ``msg % args`` with severity :data:`~.logging_records.SUCCESS`.

        See :meth:`QgisLoggerWrapper.log` for details on parameters.
        """
        if self._logger.isEnabledFor(SUCCESS):
            # _log is the private but stable hook stdlib uses to emit custom levels.
            self._logger._log(  # noqa: SLF001
                SUCCESS,
                msg,
                args,
                exc_info=exc_info,
                stack_info=stack_info,
                stacklevel=stacklevel + 1,
                extra=self._pack_extra(
                    extra, targets=targets, bar_config=bar_config, box_config=box_config
                ),
            )

    def warning(
        self,
        msg: object,
        *args: object,
        exc_info: bool | _SysExcInfoType | BaseException | None = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        extra: Mapping[str, object] | None = None,
        targets: Target | None = None,
        bar_config: MessageBarConfig | None = None,
        box_config: MessageBoxConfig | None = None,
    ) -> None:
        """
        Log ``msg % args`` with severity :data:`~logging.WARNING`.

        See :meth:`QgisLoggerWrapper.log` for details on parameters.
        """
        self._logger.warning(
            msg,
            *args,
            exc_info=exc_info,
            stack_info=stack_info,
            stacklevel=stacklevel + 1,
            extra=self._pack_extra(
                extra, targets=targets, bar_config=bar_config, box_config=box_config
            ),
        )

    def error(
        self,
        msg: object,
        *args: object,
        exc_info: bool | _SysExcInfoType | BaseException | None = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        extra: Mapping[str, object] | None = None,
        targets: Target | None = None,
        bar_config: MessageBarConfig | None = None,
        box_config: MessageBoxConfig | None = None,
    ) -> None:
        """
        Log ``msg % args`` with severity :data:`~logging.ERROR`.

        See :meth:`QgisLoggerWrapper.log` for details on parameters.
        """
        self._logger.error(
            msg,
            *args,
            exc_info=exc_info,
            stack_info=stack_info,
            stacklevel=stacklevel + 1,
            extra=self._pack_extra(
                extra, targets=targets, bar_config=bar_config, box_config=box_config
            ),
        )

    def exception(
        self,
        msg: object,
        *args: object,
        exc_info: bool | _SysExcInfoType | BaseException | None = True,
        stack_info: bool = False,
        stacklevel: int = 1,
        extra: Mapping[str, object] | None = None,
        targets: Target | None = None,
        bar_config: MessageBarConfig | None = None,
        box_config: MessageBoxConfig | None = None,
    ) -> None:
        """
        Log ``msg % args`` with severity :data:`~logging.ERROR`, including exception information.

        Equivalent to calling :meth:`error` with ``exc_info=True``. Meant
        to be called from an ``except`` block.

        See :meth:`QgisLoggerWrapper.log` for details on parameters.
        """
        self._logger.exception(
            msg,
            *args,
            exc_info=exc_info,
            stack_info=stack_info,
            stacklevel=stacklevel + 1,
            extra=self._pack_extra(
                extra, targets=targets, bar_config=bar_config, box_config=box_config
            ),
        )

    def critical(
        self,
        msg: object,
        *args: object,
        exc_info: bool | _SysExcInfoType | BaseException | None = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        extra: Mapping[str, object] | None = None,
        targets: Target | None = None,
        bar_config: MessageBarConfig | None = None,
        box_config: MessageBoxConfig | None = None,
    ) -> None:
        """
        Log ``msg % args`` with severity :data:`~logging.CRITICAL`.

        See :meth:`QgisLoggerWrapper.log` for details on parameters.
        """
        self._logger.critical(
            msg,
            *args,
            exc_info=exc_info,
            stack_info=stack_info,
            stacklevel=stacklevel + 1,
            extra=self._pack_extra(
                extra, targets=targets, bar_config=bar_config, box_config=box_config
            ),
        )

    def log(
        self,
        level: int,
        msg: object,
        *args: object,
        exc_info: bool | _SysExcInfoType | BaseException | None = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        extra: Mapping[str, object] | None = None,
        targets: Target | None = None,
        bar_config: MessageBarConfig | None = None,
        box_config: MessageBoxConfig | None = None,
    ) -> None:
        r"""
        Log ``msg % args`` with the integer severity ``level``.

        To pass exception information, use the keyword argument exc_info with
        a true value, e.g.

        ```python
        logger.log(level, "We have a %s", "mysterious problem", exc_info=True)
        ```

        The QGIS-specific parameters are removed from *kwargs* so that
        the standard :meth:`logging.Logger.log` never sees them. They are
        instead stored in the ``extra`` dict under the private sentinel keys
        ``_K_TARGETS``, ``_K_BAR_CFG``, and ``_K_BOX_CFG``,
        where :meth:`QgisHandler.emit` will retrieve them.

        :param level: Integer logging level.
        :param msg: The log message (may contain %-style format placeholders).
        :param \*args: Positional arguments for message formatting.
        :param exc_info: If it doesn't evaluate to :data:`False`, it causes exception
            information to be added to the logging message. If an exception tuple (in the
            format returned by sys.exc_info()) or an exception instance is provided, it's
            used; otherwise, sys.exc_info() is called to get the exception information.
        :param stack_info: If true, stack information is added to the logging message,
            including the actual logging call.
        :param stacklevel: If greater than 1, the corresponding number of stack
            frames are skipped when computing the line number and function name
            set in the LogRecord created for the logging event.
        :param extra: A dictionary used to populate the __dict__ of the LogRecord
            created for the logging event with user-defined attributes.
        :param targets: Per-call :class:`~.logging_records.Target` override, or
            :data:`None` to use the handler default.
        :param bar_config: Per-call :class:`~.logging_records.MessageBarConfig` override,
            or :data:`None` to use the handler default.
        :param box_config: Per-call :class:`~.logging_records.MessageBoxConfig` override,
            or :data:`None` to use the handler default.
        """
        self._logger.log(
            level,
            msg,
            *args,
            exc_info=exc_info,
            stack_info=stack_info,
            stacklevel=stacklevel + 1,
            extra=self._pack_extra(
                extra, targets=targets, bar_config=bar_config, box_config=box_config
            ),
        )


# ---------------------------------------------------------------------------
# Handler signals carrier
# ---------------------------------------------------------------------------


class QgisHandlerSignals(QObject):
    """
    Public Qt signals emitted by :class:`QgisHandler` on every handled record.

    This class is a :class:`~qgis.PyQt.QtCore.QObject` signals carrier: it exists solely
    to host :func:`~qgis.PyQt.QtCore.pyqtSignal` definitions, sidestepping the
    :class:`~qgis.PyQt.QtCore.QObject` multiple-inheritance limitations of PyQt6 while
    still providing fully typed, connectable Qt signals.

    An instance is created automatically by :class:`QgisHandler` and exposed
    via :attr:`QgisHandler.signals`. Plugin developers connect to its signals
    to drive custom UI elements — for example a status-bar label or a
    secondary log widget — without needing to subclass or patch the handler.

    Signals are emitted on the **GUI thread** regardless of which thread
    originally called :meth:`QgisHandler.emit`, because the internal
    :attr:`~QgisHandlerSignals._render_requested` signal uses a
    ``QueuedConnection`` for cross-thread delivery and these public signals are
    emitted from :meth:`QgisHandler._render`, which always runs on the GUI thread.

    .. code-block:: python

        handler = QgisHandler(plugin_name="MyPlugin")

        # Show every log message in a custom label.
        handler.signals.message_emitted.connect(lambda msg, level: status_label.setText(msg))

        # Flash the toolbar red on errors.
        handler.signals.error_emitted.connect(lambda msg: toolbar.setStyleSheet("background: red"))
    """

    message_emitted: pyqtSignal = pyqtSignal(str, int)
    """
    Emitted for every successfully handled record, after all render targets have been called.

    Arguments are the formatted message string and the integer logging level
    (e.g. :data:`logging.INFO`).
    """

    error_emitted: pyqtSignal = pyqtSignal(str)
    """
    Emitted only when the record's level is :data:`logging.WARNING` or above.

    Argument is the formatted message string. Useful for connecting a
    single error-notification slot without a level-filtering wrapper.
    """

    _render_requested: pyqtSignal = pyqtSignal(object)
    """
    Private signal used for cross-thread dispatch to :meth:`QgisHandler._render`.

    Plugin code must not connect to this signal directly.
    """


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class QgisHandler(logging.Handler):
    """
    A :class:`logging.Handler` that routes records to QGIS UI targets.

    Handler-level defaults apply to every record. When the record was emitted
    by a :class:`QgisLoggerWrapper`, per-call overrides stored under the private
    sentinel keys take precedence for that record only.

    Each handler owns a :class:`QgisHandlerSignals` instance accessible via
    :attr:`signals`. Connect to :attr:`QgisHandlerSignals.message_emitted` or
    :attr:`QgisHandlerSignals.error_emitted` to react to log records from
    other parts of a plugin without subclassing or patching the handler.

    .. note::
        Cross-thread dispatch is handled by the private
        :attr:`~QgisHandlerSignals._render_requested` signal on :attr:`signals`, which is connected
        to :meth:`_render` with an ``AutoConnection``. Qt automatically
        promotes this to a ``QueuedConnection`` when the signal is emitted
        from a worker thread, ensuring all Qt widget operations execute on
        the GUI thread.
    """

    def __init__(
        self,
        plugin_name: str,
        targets: Target = Target.LOG,
        tag: str | None = None,
        bar: QgsMessageBar | None = None,
        box_parent: QWidget | None = None,
        bar_config: MessageBarConfig | None = None,
        box_config: MessageBoxConfig | None = None,
        level: int = logging.NOTSET,
    ) -> None:
        """
        Initialize the handler.

        :param plugin_name: Human-readable name shown in log tags and dialog titles.
        :param targets: Default combination of :class:`~.logging_records.Target` flags.
            Can be overridden per call via :class:`QgisLoggerWrapper`.
        :param tag: Tag shown in :class:`qgis.core.QgsMessageLog`; falls back to
            *plugin_name* when :data:`None`.
        :param bar: The :class:`qgis.gui.QgsMessageBar` from the QGIS interface.
            Required when ``Target.BAR`` may ever be active.
        :param box_parent: Parent widget for :class:`~qgis.PyQt.QtWidgets.QMessageBox`
            modal dialogs (typically ``iface.mainWindow()``); when :data:`None`,
            dialogs are created without a parent (not recommended).
        :param bar_config: Default message-bar appearance.
        :param box_config: Default modal-dialog appearance.
        :param level: Minimum logging level forwarded by this handler.
        :raise ValueError: If ``Target.BAR`` is enabled but no *bar* was provided.
        """
        super().__init__(level)
        self._plugin_name: str = plugin_name
        self._targets: Target = targets
        self._tag: str = tag if tag is not None else plugin_name
        self._bar: QgsMessageBar | None = bar
        self._box_parent: QWidget | None = box_parent
        self._bar_config: MessageBarConfig = bar_config or MessageBarConfig()
        self._box_config: MessageBoxConfig = box_config or MessageBoxConfig()

        # Signals carrier — owns both the public signals and the private
        # dispatch signal. Created here so it is owned by (lives on) the
        # GUI thread, which is a prerequisite for QueuedConnection delivery.
        self._signals: QgisHandlerSignals = QgisHandlerSignals()
        # _render_requested is this handler's own private cross-thread dispatch signal.
        self._signals._render_requested.connect(self._render)  # noqa: SLF001

        # Validate at construction time so problems surface early.
        if Target.BAR in targets and bar is None:
            msg = "Target.BAR requires a QgsMessageBar instance; pass bar=iface.messageBar()."
            raise ValueError(msg)

    # ------------------------------------------------------------------
    # Public API — runtime reconfiguration
    # ------------------------------------------------------------------

    @property
    def plugin_name(self) -> str:
        """
        Human-readable plugin identifier.

        :return: The plugin name string.
        """
        return self._plugin_name

    @property
    def signals(self) -> QgisHandlerSignals:
        """
        Public Qt signals for this handler.

        Connect to :attr:`QgisHandlerSignals.message_emitted` or
        :attr:`QgisHandlerSignals.error_emitted` to react to log records
        without subclassing the handler::

            handler.signals.message_emitted.connect(my_slot)

        :return: The :class:`QgisHandlerSignals` instance owned by this handler.
        """
        return self._signals

    @property
    def targets(self) -> Target:
        """
        Default output targets (may be overridden per call).

        :return: A :class:`~.logging_records.Target` flag combination.
        """
        return self._targets

    @targets.setter
    def targets(self, value: Target) -> None:
        """
        Replace the default targets at runtime.

        :param value: New :class:`~.logging_records.Target` flag combination.
        :raise ValueError: If ``Target.BAR`` is enabled but no bar was
            provided at construction time.
        """
        if Target.BAR in value and self._bar is None:
            msg = (
                "Cannot enable Target.BAR without a QgsMessageBar; "
                "reconstruct the handler with bar= set."
            )
            raise ValueError(msg)
        self._targets = value

    @property
    def bar_config(self) -> MessageBarConfig:
        """
        Default message-bar configuration (may be overridden per call).

        :return: The current :class:`~.logging_records.MessageBarConfig`.
        """
        return self._bar_config

    @bar_config.setter
    def bar_config(self, value: MessageBarConfig) -> None:
        """
        Replace the default message-bar configuration at runtime.

        :param value: New :class:`~.logging_records.MessageBarConfig`.
        """
        self._bar_config = value

    @property
    def box_config(self) -> MessageBoxConfig:
        """
        Default message-box configuration (may be overridden per call).

        :return: The current :class:`~.logging_records.MessageBoxConfig`.
        """
        return self._box_config

    @box_config.setter
    def box_config(self, value: MessageBoxConfig) -> None:
        """
        Replace the default message-box configuration at runtime.

        :param value: New :class:`~.logging_records.MessageBoxConfig`.
        """
        self._box_config = value

    # ------------------------------------------------------------------
    # Core logging.Handler interface
    # ------------------------------------------------------------------

    @override
    def emit(self, record: logging.LogRecord) -> None:
        """
        Format *record* and dispatch it to all active targets.

        Per-call overrides injected by :class:`QgisLoggerWrapper` — stored on the
        record under the ``_K_TARGETS``, ``_K_BAR_CFG``, and
        ``_K_BOX_CFG`` keys — take precedence over the handler's own
        defaults. When ``Target.BAR`` is requested via a per-call override
        but no :class:`qgis.gui.QgsMessageBar` was supplied to the handler,
        the BAR target is silently dropped from that record's targets to avoid
        a runtime error.

        When called from a worker thread, the private :attr:`~QgisHandlerSignals._render_requested`
        signal is emitted; Qt delivers it to :meth:`_render` on the GUI
        thread via a ``QueuedConnection``. When called from the GUI thread,
        :meth:`_render` is called directly with no event-loop round-trip.

        :param record: The :class:`logging.LogRecord` to handle.
        """
        try:
            message = self.format(record)
        except Exception:  # noqa: BLE001  # handler must not propagate; delegate to handleError
            self.handleError(record)
            return

        # Resolve per-call overrides, falling back to handler defaults.
        targets: Target = getattr(record, _K_TARGETS, self._targets)
        bar_config: MessageBarConfig = getattr(record, _K_BAR_CFG, self._bar_config)
        box_config: MessageBoxConfig = getattr(record, _K_BOX_CFG, self._box_config)

        # Guard: per-call Target.BAR requires a bar to have been provided.
        if Target.BAR in targets and self._bar is None:
            targets = targets & ~Target.BAR

        payload = EmitPayload(
            targets=targets,
            plugin_name=self._plugin_name,
            tag=self._tag,
            message=message,
            level=record.levelno,
            bar_config=bar_config,
            box_config=box_config,
        )

        if _is_main_thread():
            self._render(payload)
        else:
            # Emitting the signal from a worker thread causes Qt to queue the
            # delivery to the GUI thread (AutoConnection → QueuedConnection).
            # The signal holds a reference to its arguments until delivery, so
            # the handler stays alive as long as the payload is pending.
            self._signals._render_requested.emit(payload)  # noqa: SLF001

    # ------------------------------------------------------------------
    # Rendering helpers (must run on the main thread)
    # ------------------------------------------------------------------

    def _render(self, payload: EmitPayload) -> None:
        """
        Dispatch *payload* to each active target and emit public signals.

        Always runs on the GUI thread — either called directly from
        :meth:`emit` when already on the GUI thread, or delivered via the
        ``QueuedConnection`` on :attr:`~QgisHandlerSignals._render_requested` when called from a
        worker thread.

        After all render targets have been called,
        :attr:`QgisHandlerSignals.message_emitted` is emitted with the
        formatted message and logging level. If the level is
        :data:`logging.WARNING` or above, :attr:`QgisHandlerSignals.error_emitted`
        is also emitted.

        A logging sink must never raise into the caller of ``log.xxx()`` (sync path)
        or into Qt's event loop (queued path), so any exception from a render target
        or from a user-connected signal slot is routed to :meth:`logging.Handler.handleError`.

        :param payload: The :class:`~.logging_records.EmitPayload` describing the message.
        """
        try:
            if Target.LOG in payload.targets:
                self._render_log(payload)
            if Target.BAR in payload.targets:
                self._render_bar(payload)
            if Target.DIALOG in payload.targets:
                self._render_dialog(payload)

            self._signals.message_emitted.emit(payload.message, payload.level)
            if payload.level >= logging.ERROR:
                self._signals.error_emitted.emit(payload.message)
        except Exception:  # noqa: BLE001  # see method docstring
            self.handleError(
                logging.makeLogRecord({"msg": payload.message, "levelno": payload.level})
            )

    @staticmethod
    def _render_log(payload: EmitPayload) -> None:
        """
        Write to :class:`qgis.core.QgsMessageLog`.

        :param payload: The :class:`~.logging_records.EmitPayload` describing the message.
        """
        QgsMessageLog.logMessage(
            message=payload.message,
            tag=payload.tag,
            level=level_to_qgis(payload.level),
            notifyUser=False,
        )

    def _render_bar(self, payload: EmitPayload) -> None:
        """
        Push a notification onto :class:`qgis.gui.QgsMessageBar`.

        If :attr:`~.logging_records.MessageBarConfig.show_progress` is :data:`True`, a
        :class:`~qgis.PyQt.QtWidgets.QProgressBar` is created and embedded. Any
        caller-supplied :attr:`~.logging_records.MessageBarConfig.buttons` are also added.

        :param payload: The :class:`~.logging_records.EmitPayload` describing the message.
        :raise RuntimeError: If the handler was not configured with a
            :class:`qgis.gui.QgsMessageBar` but the BAR target is active, or if the
            message bar item layout cannot be obtained when buttons or a progress bar
            need to be added.
        """
        if self._bar is None:
            msg = "Cannot render to message bar because no QgsMessageBar was provided."
            raise RuntimeError(msg)

        cfg = payload.bar_config

        # Create the item first so we can attach widgets to it.
        item = self._bar.createMessage(payload.plugin_name, payload.message)
        if item is None:
            msg = f"Failed to create message bar item for '{payload.plugin_name}'."
            raise RuntimeError(msg)

        if layout := item.layout():
            for btn in cfg.buttons:
                layout.addWidget(btn)

            if cfg.show_progress:
                progress = QProgressBar()
                progress.setMaximum(100)
                # QGS202 targets QgsRasterBlock/QgsRasterAttributeTable; this is plain Qt.
                progress.setValue(cfg.progress_value)  # noqa: QGS202
                progress.setFormat(cfg.progress_format)
                progress.setMaximumWidth(150)
                layout.addWidget(progress)
        elif cfg.buttons or cfg.show_progress:
            msg = "Failed to get message bar item layout."
            raise RuntimeError(msg)

        item.setLevel(level_to_qgis(payload.level))

        # 0 means the user must dismiss the message manually.
        item.setDuration(max(0, cfg.duration))

        self._bar.pushItem(item)

    def _render_dialog(self, payload: EmitPayload) -> None:
        """
        Show a :class:`~qgis.PyQt.QtWidgets.QMessageBox` modal dialog.

        The dialog is parented to the ``box_parent`` widget supplied at
        construction (typically the QGIS main window) so Qt manages its
        lifetime and stacking; when no parent was supplied it is created
        parentless.

        :param payload: The :class:`~.logging_records.EmitPayload` describing the message.
        """
        cfg = payload.box_config

        box = QMessageBox(parent=self._box_parent)
        box.setIcon(_qmsgbox_icon(payload.level))
        box.setWindowTitle(cfg.title or payload.plugin_name)
        box.setText(payload.message)
        box.setStandardButtons(cfg.standard_buttons)
        box.setDefaultButton(cfg.default_button)
        if cfg.detailed_text:
            box.setDetailedText(cfg.detailed_text)

        box.exec()


# ---------------------------------------------------------------------------
# Thread utility
# ---------------------------------------------------------------------------


def _is_main_thread() -> bool | None:
    """
    Return :data:`True` when called from Qt's GUI thread.

    Uses :meth:`qgis.PyQt.QtCore.QThread.currentThread` compared against the thread that owns
    the :class:`~qgis.PyQt.QtWidgets.QApplication` instance, which is always Qt's GUI thread.
    This is reliable across all threading models — Python threads, Qt threads
    created via :class:`~qgis.PyQt.QtCore.QThread`, and threads from Qt's C++ thread pool
    (:class:`~qgis.PyQt.QtCore.QThreadPool` / ``QtConcurrent``) — unlike
    ``threading.current_thread() is threading.main_thread()``, which only
    tracks threads known to the CPython runtime.

    :return: :data:`True` if the caller is running on Qt's GUI thread, :data:`None`
        if there is no running QApplication instance, or :data:`False` otherwise.
    """
    if app := QApplication.instance():
        return QThread.currentThread() is app.thread()
    return None
