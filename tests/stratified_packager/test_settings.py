"""
Test suite for :mod:`stratified_packager.settings`.

These tests exercise the plugin's concrete :class:`StratifiedPackagerSettings`
schema. They require a running QGIS and are marked ``qgis`` via the module-level
:data:`pytestmark`. Because the schema persists to the real ``plugins/<slug>``
node, a fixture snapshots and restores those keys around each test.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

pytest.importorskip("qgis", reason="The settings schema and QgsSettings require a running QGIS.")

# Imported only after the importorskip guard above confirms QGIS is available.
from qgis.core import QgsSettings

from stratified_packager.identity import PLUGIN_SLUG
from stratified_packager.settings import StratifiedPackagerSettings
from stratified_packager.toolbelt.settings import BoolSetting, StringSetting

if TYPE_CHECKING:
    from collections.abc import Generator

pytestmark = pytest.mark.qgis
"""Marks the whole module as requiring a QGIS runtime."""


@pytest.fixture(autouse=True)
def preserve_plugin_settings() -> Generator[None, None, None]:
    """
    Snapshot and restore the real plugin's settings keys around each test.

    :return: Nothing; yields control to the test body.
    """
    settings = QgsSettings()
    keys = [
        f"plugins/{PLUGIN_SLUG}/debug_mode",
        f"plugins/{PLUGIN_SLUG}/version_saved",
        f"plugins/{PLUGIN_SLUG}/style_categories",
    ]
    saved = {key: settings.value(key) for key in keys if settings.contains(key)}
    yield
    for key in keys:
        settings.remove(key)
    for key, value in saved.items():
        settings.setValue(key, value)  # restoring saved values in teardown
    StratifiedPackagerSettings.teardown()


class TestStratifiedPackagerSettings:
    """Tests for the concrete :class:`StratifiedPackagerSettings` schema."""

    def test_declares_expected_descriptors(self) -> None:
        """
        The schema must expose :attr:`~StratifiedPackagerSettings.debug_mode` and
        :attr:`~StratifiedPackagerSettings.version_saved` descriptors.
        """
        assert isinstance(StratifiedPackagerSettings.debug_mode, BoolSetting)
        assert isinstance(StratifiedPackagerSettings.version_saved, StringSetting)

    def test_scope_places_keys_under_plugin_node(self) -> None:
        """A descriptor write must land at ``plugins/<slug>/<key>`` in QgsSettings."""
        StratifiedPackagerSettings().debug_mode = True
        assert QgsSettings().value(f"plugins/{PLUGIN_SLUG}/debug_mode", type=bool) is True

    def test_debug_mode_roundtrip(self) -> None:
        """:attr:`~StratifiedPackagerSettings.debug_mode` must persist and read back."""
        StratifiedPackagerSettings().debug_mode = True
        assert StratifiedPackagerSettings().debug_mode is True

    def test_descriptor_and_dict_access_agree(self) -> None:
        """The descriptor and the matching dict key must resolve to the same value."""
        settings = StratifiedPackagerSettings()
        settings.debug_mode = True
        assert settings.get("debug_mode", cast=bool) is True

    def test_reset_defaults(self) -> None:
        """:meth:`PluginSettingsBase.reset_defaults` must restore declared defaults."""
        settings = StratifiedPackagerSettings()
        settings.debug_mode = True
        settings.reset_defaults()
        assert settings.debug_mode is False
