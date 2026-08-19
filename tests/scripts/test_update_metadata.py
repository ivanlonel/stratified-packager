"""
Tests for :mod:`scripts.update_metadata` (a ``__main__``-guarded prek-hook script).

The script's logic lives entirely under ``if __name__ == "__main__":``, so it is executed
via :func:`runpy.run_module` with a fake ``qgispluginci`` installed — no QGIS, no network.
"""

from __future__ import annotations

import runpy
import sys
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from types import ModuleType


def _install_fake_qgispluginci(
    monkeypatch: pytest.MonkeyPatch,
    latest_version: Callable[[], str],
    plugin_path: str | Path = "plug_dir",
) -> MagicMock:
    """
    Install a fake ``qgispluginci`` package exposing the three consumed submodules.

    :param monkeypatch: Fixture used to patch :data:`sys.modules`.
    :param latest_version: Implementation behind ``ChangelogParser().latest_version()``.
    :param plugin_path: Directory the fake ``Parameters`` reports as the plugin root.
    :return: The ``utils.replace_in_file`` mock to assert on.
    """
    fake = MagicMock()
    fake.changelog.ChangelogParser.return_value.latest_version.side_effect = latest_version
    fake.parameters.Parameters.make_from.return_value.plugin_path = str(plugin_path)
    # The import system only getattr()s the sys.modules entry, so a mock stands in fine.
    monkeypatch.setitem(sys.modules, "qgispluginci", cast("ModuleType", fake))
    monkeypatch.delitem(sys.modules, "scripts.update_metadata", raising=False)
    return cast("MagicMock", fake.utils.replace_in_file)


def test_main_rewrites_the_metadata_version(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The changelog's latest version lands on metadata.txt's ``version=`` line."""
    (tmp_path / "metadata.txt").write_bytes(b"[general]\r\nversion=0.0.1\r\n")
    replace_in_file = _install_fake_qgispluginci(monkeypatch, lambda: "1.2.3", tmp_path)
    runpy.run_module("scripts.update_metadata", run_name="__main__")
    replace_in_file.assert_called_once_with(
        str(tmp_path / "metadata.txt"), r"^version=.*$", "version=1.2.3"
    )


def test_main_normalizes_metadata_line_endings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The CRLF qgis-plugin-ci leaves behind is rewritten as LF, content untouched."""
    metadata = tmp_path / "metadata.txt"
    metadata.write_bytes(b"[general]\r\nversion=0.0.1\r\n")
    _install_fake_qgispluginci(monkeypatch, lambda: "1.2.3", tmp_path)
    runpy.run_module("scripts.update_metadata", run_name="__main__")
    assert metadata.read_bytes() == b"[general]\nversion=0.0.1\n"


def test_main_fails_loudly_when_the_changelog_has_no_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A changelog without a major.minor.patch version aborts before touching metadata.txt."""

    def boom() -> str:
        detail = "latest_version"
        raise AttributeError(detail)

    replace_in_file = _install_fake_qgispluginci(monkeypatch, boom)
    with pytest.raises(ValueError, match=r"major\.minor\.patch"):
        runpy.run_module("scripts.update_metadata", run_name="__main__")
    replace_in_file.assert_not_called()


def test_import_is_side_effect_free(monkeypatch: pytest.MonkeyPatch) -> None:
    """Importing the module (not running it) must neither parse nor write anything."""
    replace_in_file = _install_fake_qgispluginci(monkeypatch, lambda: "9.9.9")
    runpy.run_module("scripts.update_metadata", run_name="scripts.update_metadata")
    replace_in_file.assert_not_called()
