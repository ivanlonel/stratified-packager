"""The plugin's Processing provider and its GUI-only default-refresh hookups (SPEC §5)."""

from __future__ import annotations

from typing import TYPE_CHECKING, override

from qgis.core import QgsProcessingProvider, QgsProject
from qgis.PyQt.QtCore import QMetaObject, QObject, QTimer

from stratified_packager.__about__ import __title__, __version__
from stratified_packager.identity import PLUGIN_SLUG, plugin_icon
from stratified_packager.toolbelt.logging import QgisLoggerWrapper

from .algorithm import StratifiedPackagerAlgorithm

if TYPE_CHECKING:
    from qgis.PyQt.QtGui import QIcon

log = QgisLoggerWrapper.get_logger(__name__)


class StratifiedPackagerProvider(QgsProcessingProvider):
    """
    Registers the plugin's single algorithm and keeps its dynamic defaults fresh.

    The default values shown in the Processing dialog are computed in
    :meth:`.algorithm.StratifiedPackagerAlgorithm.initAlgorithm`
    from the active project's variables and the plugin settings (SPEC §5; ``LAYERS`` alone
    carries no default — see :func:`.params.declare_parameters`). To keep those defaults
    in step with edits to the project,
    :meth:`connect_project_signals` wires the relevant :class:`~qgis.core.QgsProject` signals
    to :meth:`~qgis.core.QgsProcessingProvider.refreshAlgorithms` (which rebuilds every
    algorithm instance). Those hookups are made **only from a GUI session**: connecting
    them headless and refreshing from them mid-run segfaults ``qgis_process`` (SPEC
    §5), so :meth:`connect_project_signals` is called from
    :meth:`~stratified_packager.main.StratifiedPackager.initGui` and never from
    :meth:`~stratified_packager.main.StratifiedPackager.initProcessing`.
    """

    @override
    def __init__(self) -> None:
        """Initialize the provider with no signal hookups (those are GUI-only)."""
        super().__init__()
        self._refresh_timer: QTimer | None = None
        """Single-shot coalescing timer; created lazily by :meth:`connect_project_signals`."""

        self._project_connections: list[QMetaObject.Connection] = []
        """Tokens of the project-level signal connections, for tidy disconnection."""

    @override
    def loadAlgorithms(self) -> None:
        """Load algorithms belonging to this provider."""
        # This is the shallowest plugin frame QGIS invokes, so a failure to register
        # is logged here rather than propagated into the Processing framework.
        alg = StratifiedPackagerAlgorithm()
        if not self.addAlgorithm(alg):
            log.error(self.tr("Failed to register the %s algorithm."), alg.displayName())

    # ------------------------------------------------------------------
    # Dynamic-default refresh hookups (SPEC §5; GUI sessions only)
    # ------------------------------------------------------------------

    def connect_project_signals(self) -> None:
        """
        Wire project edits to a coalesced algorithm refresh (SPEC §5).

        Idempotent. Call from ``initGui`` only — never headless (SPEC §5). Connects the
        project's ``readProject`` / ``cleared`` / ``customVariablesChanged`` signals, each
        routed through a single-shot 0 ms timer so the burst of signals QGIS emits while
        loading a project collapses into one refresh (SPEC §5).
        """
        if self._refresh_timer is not None:
            return
        project = QgsProject.instance()
        if project is None:
            log.warning(self.tr("No project available; default-refresh signals not connected."))
            return

        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(0)
        timer.timeout.connect(self._refresh_algorithms)
        self._refresh_timer = timer

        self._project_connections = [
            project.readProject.connect(self._schedule_refresh),
            project.cleared.connect(self._schedule_refresh),
            project.customVariablesChanged.connect(self._schedule_refresh),
        ]

    def disconnect_project_signals(self) -> None:
        """
        Reverse :meth:`connect_project_signals` (called from ``unload``).

        Disconnects the project-level connections, then stops and disposes the coalescing
        timer, leaving the provider safe to re-register.
        """
        for connection in self._project_connections:
            QObject.disconnect(connection)
        self._project_connections.clear()

        if self._refresh_timer is not None:
            self._refresh_timer.stop()
            self._refresh_timer.deleteLater()
            self._refresh_timer = None

    def _schedule_refresh(self) -> None:
        """
        Restart the single-shot timer, coalescing a burst of signals into one refresh.

        Connected to argument-bearing signals too (e.g. ``readProject``); PyQt drops the
        extra payloads when the slot takes none.
        """
        if self._refresh_timer is not None:
            self._refresh_timer.start()

    def _refresh_algorithms(self) -> None:
        """Rebuild the provider's algorithms so dialog defaults pick up project edits."""
        self.refreshAlgorithms()

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @override
    def id(self) -> str:
        """
        Return the unique provider id string.

        :return: provider ID
        """
        return PLUGIN_SLUG

    @override
    def name(self) -> str:
        """
        Human-friendly provider name, used to describe the provider within the GUI.

        :return: provider name
        """
        return __title__

    @override
    def icon(self) -> QIcon:
        """
        Icon used for the provider inside the Processing toolbox.

        :return: provider icon
        """
        return plugin_icon()

    @override
    def versionInfo(self) -> str:
        """
        Version information for the provider.

        :return: version
        """
        return __version__
