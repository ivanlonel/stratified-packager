"""
Record-level machinery for the QGIS logging suite: targets, filters, configs, level mapping.

The dependency-free lower layer of :mod:`~.logging`: the :class:`Target` routing flag, the
:class:`QgisContextFilter` / :class:`TargetFilter` filters, the :class:`MessageBarConfig`
/ :class:`MessageBoxConfig` per-target configs, the :class:`EmitPayload` cross-thread
snapshot, the :data:`SUCCESS` level and the :func:`level_to_qgis` mapping.
:class:`~.logging.QgisHandler` and :class:`~.logging.QgisLoggerWrapper` build on these;
nothing here depends on the handler or wrapper, so the import edge runs one way only.
"""
# pylint: disable=duplicate-code  # __all__ overlaps the logging facade's re-export list by design

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Flag, auto
from typing import TYPE_CHECKING, Final, override

from qgis.core import Qgis, QgsApplication, QgsProject
from qgis.PyQt.QtWidgets import QMessageBox, QPushButton

if TYPE_CHECKING:
    from qgis.gui import QgisInterface

__all__: list[str] = [
    "SUCCESS",
    "EmitPayload",
    "MessageBarConfig",
    "MessageBoxConfig",
    "QgisContextFilter",
    "Target",
    "TargetFilter",
    "level_to_qgis",
]

SUCCESS: Final = (logging.INFO + logging.WARNING) // 2
"""
Custom logging level between :data:`logging.INFO` and :data:`logging.WARNING`.

Intended for successful operations that deserve user attention.
"""

# Registered at import so text formatters render "SUCCESS" instead of "Level 25".
logging.addLevelName(SUCCESS, "SUCCESS")

# ---------------------------------------------------------------------------
# Private sentinel keys: per-call overrides smuggled through LogRecord
# ---------------------------------------------------------------------------

_K_TARGETS: Final = "_qgis_targets"
"""Key under which a :class:`Target` override is stored in the record's ``__dict__``."""

_K_BAR_CFG: Final = "_qgis_bar_config"
"""Key under which a per-call :class:`MessageBarConfig` override is stored."""

_K_BOX_CFG: Final = "_qgis_box_config"
"""Key under which a per-call :class:`MessageBoxConfig` override is stored."""

# ---------------------------------------------------------------------------
# Level mapping
# ---------------------------------------------------------------------------

_QGIS_TO_QMSGBOX_ICON: Final[dict[Qgis.MessageLevel, QMessageBox.Icon]] = {
    Qgis.MessageLevel.Info: QMessageBox.Icon.Information,
    Qgis.MessageLevel.Warning: QMessageBox.Icon.Warning,
    Qgis.MessageLevel.Critical: QMessageBox.Icon.Critical,
    Qgis.MessageLevel.Success: QMessageBox.Icon.Information,
    Qgis.MessageLevel.NoLevel: QMessageBox.Icon.NoIcon,
}
"""
Per-level icon used for modal dialogs.

Maps each :class:`qgis.core.Qgis.MessageLevel` to a
:class:`~qgis.PyQt.QtWidgets.QMessageBox.Icon`.
"""


def level_to_qgis(level: int) -> Qgis.MessageLevel:
    """
    Convert a stdlib logging level to the nearest :class:`qgis.core.Qgis.MessageLevel`.

    :param level: Numeric stdlib level (e.g. :data:`logging.WARNING`) or :data:`SUCCESS`.
    :return: The closest matching :class:`qgis.core.Qgis.MessageLevel`.
    """
    if level >= logging.ERROR:
        return Qgis.MessageLevel.Critical
    if level >= logging.WARNING:
        return Qgis.MessageLevel.Warning
    if level >= SUCCESS:
        return Qgis.MessageLevel.Success
    if level >= logging.DEBUG:
        return Qgis.MessageLevel.Info
    return Qgis.MessageLevel.NoLevel


def _qmsgbox_icon(level: int) -> QMessageBox.Icon:
    """
    Return the :class:`~qgis.PyQt.QtWidgets.QMessageBox.Icon` for a stdlib logging level.

    Delegates to :func:`level_to_qgis` and then looks up the result in
    :data:`_QGIS_TO_QMSGBOX_ICON`, so the two mappings stay in sync.

    :param level: Numeric stdlib level (e.g. :data:`logging.WARNING`).
    :return: The corresponding :class:`~qgis.PyQt.QtWidgets.QMessageBox.Icon`.
    """
    return _QGIS_TO_QMSGBOX_ICON[level_to_qgis(level)]


# ---------------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------------


class Target(Flag):
    """
    Bit-flag enum selecting which QGIS outputs receive log records.

    Members can be combined with ``|``::

        Target.LOG | Target.BAR
    """

    LOG = auto()
    """Route to :class:`qgis.core.QgsMessageLog`."""
    BAR = auto()
    """Route to :class:`qgis.gui.QgsMessageBar`."""
    DIALOG = auto()
    """Route to a :class:`~qgis.PyQt.QtWidgets.QMessageBox` modal dialog."""


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


class QgisContextFilter(logging.Filter):
    """
    A :class:`logging.Filter` that stamps QGIS context and static fields onto records.

    Attach this filter to a :class:`logging.Logger` (or to any of its handlers)
    to have the fields below stamped onto every :class:`logging.LogRecord`
    automatically, without any changes to call sites.

    **Dynamic fields** (evaluated lazily at emit time):

    ``qgis_version``
        The running QGIS version string (e.g. ``"4.2.0-Belém do Pará"``).

    ``qgis_project_path``
        Absolute path of the currently open project file, or an empty string
        if no project is loaded.

    ``qgis_active_layer_id``
        ID of the layer currently selected in the layer panel, or an empty
        string when no layer is active or ``iface`` is :data:`None`.

    ``qgis_locale``
        The QGIS UI locale string (e.g. ``"pt_BR"``).

    **Static fields** (set once at construction, stamped on every record):

    Any key/value pairs passed via *static_fields* are merged onto every
    record verbatim. This is the intended replacement for call-site
    ``extra=`` dicts: plugin-level constants such as a plugin version, task
    name, or environment tag belong here rather than being repeated on every
    ``log.info(...)`` call. Static fields are stamped before dynamic fields,
    so dynamic fields take precedence on name collision.

    Example::

        log = QgisLoggerWrapper.get_logger("MyPlugin")
        context_filter = QgisContextFilter(static_fields={"plugin_version": "1.4.2"}, iface=iface)
        log.logger.addFilter(context_filter)

        # Every record now carries qgis_version, qgis_project_path,
        # qgis_active_layer_id, qgis_locale, and plugin_version.
        log.info("Processing started.")

        # Per-record context that varies per call still goes in extra=.
        log.warning("Bad geometry.", extra={"feature_id": feat.id()})
    """

    def __init__(
        self,
        static_fields: dict[str, object] | None = None,
        name: str = "",
        iface: QgisInterface | None = None,
    ) -> None:
        """
        Initialize the filter.

        :param static_fields: Plugin-level constant attributes to stamp on every
            record (e.g. ``{"plugin_version": "1.4.2", "task": "import"}``).
            Keys must not clash with standard :class:`logging.LogRecord` attributes.
        :param name: Passed to :class:`logging.Filter`; restricts the filter to
            records from loggers whose name starts with this prefix. An empty
            string (the default) matches all loggers.
        :param iface: The QGIS interface instance, used to obtain the active layer id.
        """
        super().__init__(name)
        self._static_fields: dict[str, object] = static_fields or {}
        self._iface: QgisInterface | None = iface

    @override
    def filter(self, record: logging.LogRecord) -> bool:
        """
        Stamp static and dynamic QGIS context fields onto *record*.

        This filter never blocks records — it always returns :data:`True`.
        Static fields supplied at construction time are applied first; dynamic
        QGIS fields are applied second and take precedence on name collision.

        :param record: The :class:`logging.LogRecord` to enrich.
        :return: Always :data:`True`.
        """
        for key, value in self._static_fields.items():
            setattr(record, key, value)

        record.qgis_version = Qgis.version()
        if app := QgsApplication.instance():
            record.qgis_locale = app.locale()
        if project := QgsProject.instance():
            record.qgis_project_path = project.absoluteFilePath()

        if self._iface is not None:
            map_layer = self._iface.activeLayer()
            record.qgis_active_layer_id = map_layer.id() if map_layer else ""

        return True


class TargetFilter(logging.Filter):
    """
    :class:`logging.Filter` that gates records based on :class:`Target` and minimum logging level.

    Intended to be attached to a :class:`~.logging.QgisHandler`.

    This filter expresses *permanent, handler-level routing rules* — complementing the
    per-call overrides available through :class:`~.logging.QgisLoggerWrapper` methods.
    A typical use is to restrict a :class:`~.logging.QgisHandler` configured with
    ``Target.DIALOG`` to only show modal dialogs for :data:`~logging.ERROR` and above,
    while the same handler (or a sibling one) routes :data:`~logging.INFO` and
    :data:`~logging.WARNING` records to the message bar or log panel.

    When the record carries a per-call :class:`Target` override (injected by
    :class:`~.logging.QgisLoggerWrapper`), that override is compared against
    *allowed_targets*: the record is allowed through only if the two share at least one
    flag in common. Records emitted by a plain :class:`logging.Logger` (no override) are
    always allowed through, since target routing is the handler's responsibility in that case.

    Example — restrict a DIALOG handler to errors only::

        handler = QgisHandler(
            plugin_name="MyPlugin",
            targets=Target.DIALOG,
            box_config=MessageBoxConfig(title="Error"),
        )
        handler.addFilter(
            TargetFilter(
                allowed_targets=Target.DIALOG,
                min_level=logging.ERROR,
            )
        )

    Example — a BAR handler that ignores records explicitly routed elsewhere::

        bar_handler = QgisHandler(
            plugin_name="MyPlugin",
            targets=Target.BAR,
            bar=iface.messageBar(),
        )
        bar_handler.addFilter(TargetFilter(allowed_targets=Target.BAR))
    """

    def __init__(
        self,
        allowed_targets: Target,
        min_level: int = logging.NOTSET,
        name: str = "",
    ) -> None:
        """
        Initialize the filter.

        :param allowed_targets: The :class:`Target` flags this handler is
            permitted to process. Records whose per-call target override shares
            no flag with this value are dropped.
        :param min_level: Minimum :mod:`logging` level to allow through. Records
            below this level are dropped regardless of target. Defaults to
            :data:`logging.NOTSET` (no additional level gate beyond the logger's own).
        :param name: Passed to :class:`logging.Filter`; restricts the filter to
            records from loggers whose name starts with this prefix.
        """
        super().__init__(name)
        self._allowed_targets: Target = allowed_targets
        self._min_level: int = min_level

    @property
    def allowed_targets(self) -> Target:
        """
        The :class:`Target` flags permitted by this filter.

        :return: The current allowed :class:`Target` combination.
        """
        return self._allowed_targets

    @allowed_targets.setter
    def allowed_targets(self, value: Target) -> None:
        """
        Replace the allowed targets at runtime.

        :param value: New :class:`Target` combination.
        """
        self._allowed_targets = value

    @property
    def min_level(self) -> int:
        """
        Minimum logging level permitted by this filter.

        :return: An integer logging level constant.
        """
        return self._min_level

    @min_level.setter
    def min_level(self, value: int) -> None:
        """
        Replace the minimum level at runtime.

        :param value: New minimum level (e.g. :data:`logging.WARNING`).
        """
        self._min_level = value

    @override
    def filter(self, record: logging.LogRecord) -> bool:
        """
        Allow the record through only if it passes both gates.

        The two gates, applied in order:

        1. **Level gate** — the record's level must be ``>=`` :attr:`min_level`.
        2. **Target gate** — if the record carries a per-call :class:`Target`
           override, it must share at least one flag with
           :attr:`allowed_targets`. Records without an override always pass
           this gate.

        :param record: The :class:`logging.LogRecord` to evaluate.
        :return: :data:`True` if the record should be processed, :data:`False` if it
            should be silently dropped.
        """
        if record.levelno < self._min_level:
            return False

        per_call_targets: Target | None = getattr(record, _K_TARGETS, None)
        if per_call_targets is not None:
            return bool(per_call_targets & self._allowed_targets)

        return True


# ---------------------------------------------------------------------------
# Configuration dataclasses
# ---------------------------------------------------------------------------


@dataclass
class MessageBarConfig:
    """Configuration for the :class:`qgis.gui.QgsMessageBar` target."""

    duration: int = 5
    """Seconds the message stays visible (``0`` = permanent)."""

    buttons: list[QPushButton] = field(default_factory=list)
    """
    Extra :class:`~qgis.PyQt.QtWidgets.QPushButton` instances to embed in the bar.

    They are created by the caller and passed here so that signal connections
    can be set up before the bar shows them.
    """

    show_progress: bool = False
    """
    Whether the message bar shows a progress indicator.

    When :data:`True`, a :class:`~qgis.PyQt.QtWidgets.QProgressBar` is added to
    the bar widget.
    """

    progress_value: int = 0
    """Initial value of the progress bar (0-100)."""

    progress_format: str = "%p%"
    """
    Format string for the progress bar.

    Passed to :meth:`~qgis.PyQt.QtWidgets.QProgressBar.setFormat` (e.g. ``"%p%"``).
    """


@dataclass
class MessageBoxConfig:
    """Configuration for the :class:`~qgis.PyQt.QtWidgets.QMessageBox` target."""

    title: str | None = None
    """
    Window title of the dialog.

    When :data:`None`, the plugin name supplied to :class:`~.logging.QgisHandler` is used.
    """

    standard_buttons: QMessageBox.StandardButton = QMessageBox.StandardButton.Ok
    """Combination of :class:`~qgis.PyQt.QtWidgets.QMessageBox.StandardButton` flags to display."""

    default_button: QMessageBox.StandardButton = QMessageBox.StandardButton.Ok
    """The button that receives focus by default."""

    detailed_text: str | None = None
    """Optional detailed-text string shown via the *Show Details* expander."""


# ---------------------------------------------------------------------------
# Internal payload for cross-thread dispatch
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EmitPayload:
    """
    Immutable snapshot of everything needed to render a log record on the main thread.

    Constructed inside :meth:`~.logging.QgisHandler.emit` (possibly on a worker thread)
    and consumed by :meth:`~.logging.QgisHandler._render`. Per-call overrides — if present
    on the record — take precedence over the handler's own defaults before this object is
    built, so the render path never needs to inspect the record again.
    """

    targets: Target
    """Resolved :class:`Target` flags for this record."""

    plugin_name: str
    """Human-readable plugin identifier."""

    tag: str
    """Tag / topic for :class:`qgis.core.QgsMessageLog`."""

    message: str
    """Formatted log message."""

    level: int
    """Original :mod:`logging` level integer."""

    bar_config: MessageBarConfig
    """Resolved :class:`MessageBarConfig` for this record."""

    box_config: MessageBoxConfig
    """Resolved :class:`MessageBoxConfig` for this record."""
