"""
Tests for the plugin lifecycle object (:mod:`stratified_packager.main`).

The QGIS-mandated ``initGui`` / ``initProcessing`` / ``unload`` lifecycle is exercised
against pytest-qgis's mock interface (any unstubbed ``iface`` method resolves to a recording
:class:`~unittest.mock.MagicMock`), so the only real side effect under test is registration in
the live Processing registry. ``unload`` must reverse ``initGui`` (CLAUDE.md *Cleanup* rule).

Usage from the repo root folder:

.. code-block:: bash

    pytest tests/stratified_packager/test_main.py
    pytest tests/stratified_packager/test_main.py::TestLifecycle::test_unload_reverses_init_gui
"""
# pylint: disable=redefined-outer-name

from __future__ import annotations

from typing import TYPE_CHECKING, Never
from unittest.mock import Mock

import pytest

pytest.importorskip("qgis", reason="The lifecycle wires QGIS providers, factories and menus.")

# Imported only after the importorskip guard above confirms QGIS is available.
from qgis.core import QgsApplication, QgsSettings
from qgis.PyQt.QtWidgets import QDialog

from stratified_packager import main as main_module
from stratified_packager.identity import PLUGIN_SLUG
from stratified_packager.main import StratifiedPackager
from stratified_packager.settings import StratifiedPackagerSettings
from stratified_packager.toolbelt.logging import QgisLoggerWrapper

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from qgis.gui import QgisInterface

pytestmark = pytest.mark.qgis
"""Marks the whole module as requiring a QGIS runtime."""


@pytest.fixture
def packager(
    qgis_iface: QgisInterface,
    qgis_processing: Never,  # noqa: ARG001  # initialises the Processing framework + registry
    qgis_new_project: Never,  # noqa: ARG001  # start each test from an empty project
) -> Generator[StratifiedPackager, None, None]:
    """
    Build a plugin instance and guarantee the Processing registry is left clean.

    :param qgis_iface: pytest-qgis mock QGIS interface.
    :param qgis_processing: pytest-qgis fixture that initialises the Processing framework.
    :param qgis_new_project: pytest-qgis fixture giving each test a clean project.
    :yield: A freshly constructed plugin instance.
    """
    plugin = StratifiedPackager(qgis_iface)
    yield plugin
    # Idempotent cleanup: only unload when a test left the provider registered, so a test that
    # already unloaded is not torn down twice. ``unload`` contains its own failures.
    if plugin.provider is not None:
        plugin.unload()


_RESETTABLE_ATTRS = (
    "provider",
    "plugin_options_factory",
    "project_options_factory",
    "layer_options_factory",
    "action_help",
    "action_settings",
    "action_project_defaults",
    "action_layers",
    "action_plugin_help_menu_separator",
    "action_plugin_help_menu_documentation",
)
"""Every owned QObject attribute ``unload`` must reset to :data:`None`."""


class TestInit:
    """Tests for :meth:`StratifiedPackager.__init__`."""

    def test_starts_with_no_owned_objects(self, packager: StratifiedPackager) -> None:
        """Construction wires nothing: every owned provider/factory/action attribute is None."""
        assert all(getattr(packager, attr) is None for attr in _RESETTABLE_ATTRS)
        # The locale is reduced to a (at most) two-letter language code.
        assert isinstance(packager.locale, str)
        assert len(packager.locale) <= 2

    @pytest.mark.parametrize(
        ("stored_locale", "expected_language", "qm_found"),
        [
            ("pt_BR", "pt", True),
            ("pt_PT", "pt", True),  # every pt locale shares the Brazilian Portuguese file
            ("pt", "pt", True),
            ("es_ES", "es", False),  # no <slug>_es.qm in the fake plugin root below
        ],
    )
    def test_locale_reduces_to_language_and_finds_its_qm(
        self,
        qgis_iface: QgisInterface,
        qgis_new_project: Never,  # noqa: ARG002  # start from an empty project
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        stored_locale: str,
        expected_language: str,
        qm_found: bool,
    ) -> None:
        """
        Any regional variant resolves to its base ``<slug>_<language>.qm`` file.

        Only a ``_pt.qm`` exists under the fake plugin root, so a translator attribute
        appears exactly when the stored locale reduces to ``pt`` — for ``pt_PT`` just as
        for ``pt_BR`` (the TODO's cross-region concern).
        """
        qm_dir = tmp_path / "resources/i18n"
        qm_dir.mkdir(parents=True)
        (qm_dir / f"{PLUGIN_SLUG}_pt.qm").write_bytes(b"")
        monkeypatch.setattr(main_module, "DIR_PLUGIN_ROOT", tmp_path)

        settings = QgsSettings()
        previous = settings.value("locale/userLocale")
        settings.setValue("locale/userLocale", stored_locale)
        try:
            plugin = StratifiedPackager(qgis_iface)
        finally:
            if previous is None:
                settings.remove("locale/userLocale")
            else:
                settings.setValue("locale/userLocale", previous)

        assert plugin.locale == expected_language
        assert hasattr(plugin, "translator") is qm_found


class TestLifecycle:
    """Tests for the ``initGui`` / ``initProcessing`` / ``unload`` lifecycle."""

    def test_init_gui_registers_provider_and_builds_ui(self, packager: StratifiedPackager) -> None:
        """``initGui`` registers the provider and builds the factories and menu actions."""
        packager.initGui()

        registry = QgsApplication.processingRegistry()
        assert registry is not None
        assert packager.provider is not None
        assert registry.providerById(packager.provider.id()) is not None

        assert packager.plugin_options_factory is not None
        assert packager.project_options_factory is not None
        assert packager.layer_options_factory is not None
        assert packager.action_help is not None
        assert packager.action_settings is not None
        assert packager.action_project_defaults is not None
        assert packager.action_layers is not None

    def test_unload_reverses_init_gui(self, packager: StratifiedPackager) -> None:
        """``unload`` unregisters the provider and resets every owned attribute (Cleanup rule)."""
        packager.initGui()
        registry = QgsApplication.processingRegistry()
        assert registry is not None
        assert packager.provider is not None
        provider_id = packager.provider.id()
        assert registry.providerById(provider_id) is not None

        packager.unload()

        assert registry.providerById(provider_id) is None
        for attr in _RESETTABLE_ATTRS:
            assert getattr(packager, attr) is None, attr

    def test_unload_without_init_gui_is_safe(self, packager: StratifiedPackager) -> None:
        """``unload`` on a plugin whose ``initGui`` never ran (headless lifecycle) is a no-op."""
        packager.unload()
        for attr in _RESETTABLE_ATTRS:
            assert getattr(packager, attr) is None, attr

    def test_init_processing_registers_provider(self, packager: StratifiedPackager) -> None:
        """``initProcessing`` alone adds the provider to the live registry."""
        packager.initProcessing()
        registry = QgsApplication.processingRegistry()
        assert registry is not None
        assert packager.provider is not None
        assert registry.providerById(packager.provider.id()) is not None

    def test_open_layers_dialog_returns_dialog_code(self, packager: StratifiedPackager) -> None:
        """The all-layers dialog opens and returns its exec code (``QDialog.exec`` is patched)."""
        # The autouse ``block_qdialog_exec`` fixture patches ``QDialog.exec`` -> Accepted, so
        # this cannot block on a modal dialog.
        packager.initGui()
        assert packager._open_layers_dialog() == QDialog.DialogCode.Accepted

    @pytest.mark.parametrize(
        ("target", "attribute"),
        [
            (StratifiedPackagerSettings, "teardown"),
            (QgisLoggerWrapper, "teardown"),
        ],
    )
    def test_unload_survives_teardown_failure(
        self,
        packager: StratifiedPackager,
        monkeypatch: pytest.MonkeyPatch,
        target: type,
        attribute: str,
    ) -> None:
        """A failing teardown step is contained — ``unload`` still unregisters the provider."""
        packager.initGui()
        registry = QgsApplication.processingRegistry()
        assert registry is not None
        assert packager.provider is not None
        provider_id = packager.provider.id()

        monkeypatch.setattr(target, attribute, Mock(side_effect=RuntimeError("boom")))

        packager.unload()  # must not raise despite the failing teardown step

        # The provider was still unregistered, proving _teardown_provider ran past the failure.
        assert registry.providerById(provider_id) is None
