"""
Tests for :mod:`stratified_packager.toolbelt.debugging`.

The module imports :class:`~qgis.PyQt.QtCore.QCoreApplication`, so the whole module
requires a QGIS installation: the module-level :func:`pytest.importorskip` skips it when
QGIS is unavailable, and it is marked ``qgis`` via :data:`pytestmark`.

The real :mod:`debugpy` is never imported: each test installs a stand-in module in
:data:`sys.modules` so the env-gated bootstrap can be exercised without the dependency.
"""
# pylint: disable=redefined-outer-name  # pytest fixtures are used as test parameters by design

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytest.importorskip("qgis", reason="The bootstrap logs via qgis.PyQt.QtCore.QCoreApplication")

# Imported only after the importorskip guard above confirms QGIS is available.
import stratified_packager.toolbelt.debugging as debugging_module
from stratified_packager.toolbelt.debugging import start_debug_server

pytestmark = pytest.mark.qgis
"""Marks the whole module as requiring a QGIS runtime."""


@pytest.fixture(autouse=True)
def _isolate_debug_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Clear the ``QGIS_DEBUGPY*`` variables and reset the listen latch before each test.

    :param monkeypatch: Fixture used to mutate the environment in isolation.
    """
    for var in ("QGIS_DEBUGPY", "QGIS_DEBUGPY_HOST", "QGIS_DEBUGPY_PORT", "QGIS_DEBUGPY_WAIT"):
        monkeypatch.delenv(var, raising=False)
    debugging_module._LISTEN_LATCH["started"] = False


@pytest.fixture(autouse=True)
def mock_log(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """
    Replace the module-level logger so its calls can be asserted and never reach QGIS.

    :param monkeypatch: Fixture used to patch the module attribute in isolation.
    :return: The mock standing in for the module logger.
    """
    fake = MagicMock(name="log")
    monkeypatch.setattr(debugging_module, "log", fake)
    return fake


@pytest.fixture
def fake_debugpy(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """
    Install a stand-in :mod:`debugpy` module in :data:`sys.modules` and return it.

    :param monkeypatch: Fixture used to patch :data:`sys.modules` in isolation.
    :return: The mock standing in for the :mod:`debugpy` module.
    """
    fake = MagicMock(name="debugpy")
    fake.listen.return_value = ("127.0.0.1", 5678)  # the bootstrap unpacks listen()'s result
    monkeypatch.setitem(sys.modules, "debugpy", fake)
    return fake


class TestStartDebugServer:
    """Tests for :func:`start_debug_server`."""

    def test_disabled_is_noop(self, fake_debugpy: MagicMock) -> None:
        """
        Without ``QGIS_DEBUGPY`` the server is not started and the result is ``False``.

        :param fake_debugpy: Stand-in :mod:`debugpy` module that must stay untouched.
        """
        assert start_debug_server() is False
        fake_debugpy.listen.assert_not_called()

    def test_enabled_listens_on_defaults(
        self, monkeypatch: pytest.MonkeyPatch, mock_log: MagicMock, fake_debugpy: MagicMock
    ) -> None:
        """
        A truthy ``QGIS_DEBUGPY`` listens on the default host/port and does not wait.

        :param monkeypatch: Fixture used to set the enabling environment variable.
        :param mock_log: Patched module logger.
        :param fake_debugpy: Stand-in :mod:`debugpy` module.
        """
        monkeypatch.setenv("QGIS_DEBUGPY", "1")
        assert start_debug_server() is True
        fake_debugpy.listen.assert_called_once_with(("localhost", 5678))
        fake_debugpy.wait_for_client.assert_not_called()
        mock_log.info.assert_called_once()

    def test_env_host_and_port_are_honored(
        self, monkeypatch: pytest.MonkeyPatch, fake_debugpy: MagicMock
    ) -> None:
        """
        ``QGIS_DEBUGPY_HOST`` / ``QGIS_DEBUGPY_PORT`` override the module defaults.

        :param monkeypatch: Fixture used to set the environment variables.
        :param fake_debugpy: Stand-in :mod:`debugpy` module.
        """
        monkeypatch.setenv("QGIS_DEBUGPY", "1")
        monkeypatch.setenv("QGIS_DEBUGPY_HOST", "example.test")
        monkeypatch.setenv("QGIS_DEBUGPY_PORT", "5680")
        assert start_debug_server() is True
        fake_debugpy.listen.assert_called_once_with(("example.test", 5680))

    def test_explicit_args_override_env(
        self, monkeypatch: pytest.MonkeyPatch, fake_debugpy: MagicMock
    ) -> None:
        """
        Explicit ``host`` / ``port`` arguments take precedence over the environment.

        :param monkeypatch: Fixture used to set the (overridden) environment variables.
        :param fake_debugpy: Stand-in :mod:`debugpy` module.
        """
        monkeypatch.setenv("QGIS_DEBUGPY", "1")
        monkeypatch.setenv("QGIS_DEBUGPY_HOST", "example.test")
        monkeypatch.setenv("QGIS_DEBUGPY_PORT", "5680")
        assert start_debug_server(host="example.org", port=5681) is True
        fake_debugpy.listen.assert_called_once_with(("example.org", 5681))

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "Yes", "on", " on "])
    def test_truthy_values_enable(
        self, value: str, monkeypatch: pytest.MonkeyPatch, fake_debugpy: MagicMock
    ) -> None:
        """
        Every accepted truthy spelling of ``QGIS_DEBUGPY`` starts the server.

        :param value: Truthy environment-variable spelling under test.
        :param monkeypatch: Fixture used to set the environment variable.
        :param fake_debugpy: Stand-in :mod:`debugpy` module.
        """
        monkeypatch.setenv("QGIS_DEBUGPY", value)
        assert start_debug_server() is True
        fake_debugpy.listen.assert_called_once()

    def test_configure_uses_resolved_interpreter(
        self, monkeypatch: pytest.MonkeyPatch, fake_debugpy: MagicMock
    ) -> None:
        """
        The resolved interpreter is passed to :func:`debugpy.configure` before listening.

        :param monkeypatch: Fixture used to enable the server and stub the interpreter.
        :param fake_debugpy: Stand-in :mod:`debugpy` module.
        """
        monkeypatch.setenv("QGIS_DEBUGPY", "1")
        monkeypatch.setattr(debugging_module, "python_executable", lambda: Path("/opt/py/python"))
        assert start_debug_server() is True
        fake_debugpy.configure.assert_called_once_with(python=str(Path("/opt/py/python")))

    def test_configure_skipped_when_interpreter_missing(
        self, monkeypatch: pytest.MonkeyPatch, fake_debugpy: MagicMock
    ) -> None:
        """
        When the interpreter cannot be located, :func:`debugpy.configure` is skipped.

        :param monkeypatch: Fixture used to enable the server and stub the interpreter.
        :param fake_debugpy: Stand-in :mod:`debugpy` module.
        """
        monkeypatch.setenv("QGIS_DEBUGPY", "1")
        monkeypatch.setattr(debugging_module, "python_executable", lambda: None)
        assert start_debug_server() is True
        fake_debugpy.configure.assert_not_called()
        fake_debugpy.listen.assert_called_once()

    def test_wait_for_client_when_requested(
        self, monkeypatch: pytest.MonkeyPatch, fake_debugpy: MagicMock
    ) -> None:
        """
        ``QGIS_DEBUGPY_WAIT`` makes the bootstrap block on :func:`debugpy.wait_for_client`.

        :param monkeypatch: Fixture used to set the environment variables.
        :param fake_debugpy: Stand-in :mod:`debugpy` module.
        """
        monkeypatch.setenv("QGIS_DEBUGPY", "1")
        monkeypatch.setenv("QGIS_DEBUGPY_WAIT", "1")
        assert start_debug_server() is True
        fake_debugpy.wait_for_client.assert_called_once_with()

    def test_repeated_calls_are_idempotent(
        self, monkeypatch: pytest.MonkeyPatch, fake_debugpy: MagicMock
    ) -> None:
        """
        A second call is a no-op: :func:`debugpy.listen` runs only once per process.

        :param monkeypatch: Fixture used to set the enabling environment variable.
        :param fake_debugpy: Stand-in :mod:`debugpy` module.
        """
        monkeypatch.setenv("QGIS_DEBUGPY", "1")
        assert start_debug_server() is True
        assert start_debug_server() is True
        fake_debugpy.listen.assert_called_once()

    def test_missing_debugpy_is_swallowed(
        self, monkeypatch: pytest.MonkeyPatch, mock_log: MagicMock
    ) -> None:
        """
        A missing :mod:`debugpy` is logged as a warning and never propagates.

        :param monkeypatch: Fixture used to set the env var and break the import.
        :param mock_log: Patched module logger.
        """
        monkeypatch.setenv("QGIS_DEBUGPY", "1")
        # A ``None`` entry in sys.modules makes ``import debugpy`` raise ImportError.
        monkeypatch.setitem(sys.modules, "debugpy", None)
        assert start_debug_server() is False
        mock_log.warning.assert_called_once()

    def test_listen_failure_is_swallowed(
        self, monkeypatch: pytest.MonkeyPatch, mock_log: MagicMock, fake_debugpy: MagicMock
    ) -> None:
        """
        A failure inside :func:`debugpy.listen` is logged as a warning and contained.

        :param monkeypatch: Fixture used to set the enabling environment variable.
        :param mock_log: Patched module logger.
        :param fake_debugpy: Stand-in :mod:`debugpy` whose ``listen`` raises.
        """
        monkeypatch.setenv("QGIS_DEBUGPY", "1")
        fake_debugpy.listen.side_effect = OSError("port already in use")
        assert start_debug_server() is False
        mock_log.warning.assert_called_once()
