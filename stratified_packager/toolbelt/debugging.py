"""
Optional debugpy bootstrap for attaching an IDE to the (possibly embedded) Python.

:func:`start_debug_server` opens a `debugpy <https://github.com/microsoft/debugpy>`_ listen
socket when the :envvar:`QGIS_DEBUGPY` environment variable is truthy, so an IDE can attach to
the running interpreter; it is a no-op otherwise, which keeps it dormant in normal use while
costing nothing to leave wired in.

When Python is embedded in a host application — QGIS runs the interpreter inside its ``qgis``
/ ``qgis_process`` executable — :data:`sys.executable` points at that host binary rather than
at Python. Since debugpy needs the real interpreter to spawn its adapter subprocess, the
bootstrap resolves it with :func:`~.utils.python_executable` and
passes it to ``debugpy.configure`` before listening.

Recognised environment variables (explicit ``host`` / ``port`` arguments take precedence),
read through the typed :class:`~.mapping_proxy.EnvironmentVariables`
subclass ``_DebugEnv``:

.. envvar:: QGIS_DEBUGPY

    Truthy (``1`` / ``true`` / ``yes`` / ``on``) to enable the listen server.

.. envvar:: QGIS_DEBUGPY_HOST

    Host/address to listen on (default ``"localhost"``).

.. envvar:: QGIS_DEBUGPY_PORT

    TCP port to listen on (default ``5678``).

.. envvar:: QGIS_DEBUGPY_WAIT

    Truthy to block startup until an IDE attaches — needed to break on early load (e.g.
    ``classFactory`` / ``initGui``) or on a short-lived ``qgis_process`` run.

``debugpy`` is an optional dependency imported lazily inside :func:`start_debug_server`;
when it is not installed the resulting :exc:`ImportError` is contained like any other failure,
so the bootstrap never breaks loading.
"""

from __future__ import annotations

from typing import Final

from qgis.PyQt.QtCore import QCoreApplication

from .logging import QgisLoggerWrapper
from .mapping_proxy import BoolEnvVar, EnvironmentVariables, IntEnvVar, StrEnvVar
from .utils import python_executable

log = QgisLoggerWrapper.get_logger(__name__)


_LISTEN_LATCH: Final[dict[str, bool]] = {"started": False}
"""Process-global latch (mutated in place, never rebound): ``debugpy.listen`` may be
called only once per process, so re-entry (e.g. on plugin reload) stays a quiet no-op."""


class _DebugEnv(EnvironmentVariables):
    """Typed view of the ``QGIS_DEBUGPY*`` environment toggles (see the module docstring)."""

    QGIS_DEBUGPY = BoolEnvVar(default=False)
    QGIS_DEBUGPY_HOST = StrEnvVar(default="localhost")
    QGIS_DEBUGPY_PORT = IntEnvVar(default=5678)
    QGIS_DEBUGPY_WAIT = BoolEnvVar(default=False)


def start_debug_server(host: str | None = None, port: int | None = None) -> bool:
    """
    Start a debugpy listen server when :envvar:`QGIS_DEBUGPY` is truthy, else do nothing.

    Resolve the listen address from the arguments, then the ``QGIS_DEBUGPY*`` environment
    variables, then the module defaults. Safe to call on every plugin load: a repeat call, a
    missing ``debugpy`` or a busy port is logged and swallowed so that loading never fails
    because of the debugger.

    :param host: Host/address to listen on; overrides :envvar:`QGIS_DEBUGPY_HOST`.
    :param port: TCP port to listen on; overrides :envvar:`QGIS_DEBUGPY_PORT`.
    :return: :data:`True` when the server is (already) listening, :data:`False` otherwise.
    """
    if _LISTEN_LATCH["started"]:
        return True
    env = _DebugEnv()
    if not env.QGIS_DEBUGPY:
        return False
    try:
        # debugpy is an optional dependency, imported lazily so a missing install is a contained
        # ImportError; it is absent from the type-checking environment.
        import debugpy  # noqa: PLC0415  # ty: ignore[unresolved-import]

        # sys.executable is the QGIS host binary, not the interpreter; tell debugpy which
        # Python to use for its adapter subprocess.
        if python := python_executable():
            debugpy.configure(python=str(python))
        # debugpy.listen() returns the bound (host, port); pylint can't infer the return of the
        # dynamically-resolved optional import, so it wrongly flags the tuple unpacking.
        # pylint: disable-next=unpacking-non-sequence
        bound_host, bound_port = debugpy.listen(
            (host or env.QGIS_DEBUGPY_HOST, port or env.QGIS_DEBUGPY_PORT)
        )
        _LISTEN_LATCH["started"] = True
        log.info(
            QCoreApplication.translate("Debugging", "debugpy is listening on %s:%s."),
            bound_host,
            bound_port,
        )
        if env.QGIS_DEBUGPY_WAIT:
            log.warning(
                QCoreApplication.translate("Debugging", "Waiting for a debugger to attach...")
            )
            debugpy.wait_for_client()
    except Exception:  # noqa: BLE001  # the debugger must never break plugin loading
        log.warning(
            QCoreApplication.translate("Debugging", "Could not start the debugpy server."),
            exc_info=True,
        )
        return False
    return True
