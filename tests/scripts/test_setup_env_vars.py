"""
Tests for :mod:`scripts.setup_env_vars` cross-platform helpers.

Usage from the repo root folder:

.. code-block:: bash

    pytest -p no:pytest_qgis -p no:pytest-qt tests/scripts/test_setup_env_vars.py
"""

from __future__ import annotations

import shutil
import sys
import types
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from dotenv import dotenv_values

from scripts import setup_env_vars

if TYPE_CHECKING:
    from collections.abc import Sequence


def _inject_fake_qgis_core(monkeypatch: pytest.MonkeyPatch, version: str) -> None:
    """Register a fake ``qgis.core`` whose ``Qgis.version`` returns `version`."""
    qgis_mod = types.ModuleType("qgis")
    core_mod = types.ModuleType("qgis.core")

    class _Qgis:
        @staticmethod
        def version() -> str:
            """Return the fake QGIS version string."""
            return version

    core_mod.__dict__["Qgis"] = _Qgis
    qgis_mod.__dict__["core"] = core_mod
    monkeypatch.setitem(sys.modules, "qgis", qgis_mod)
    monkeypatch.setitem(sys.modules, "qgis.core", core_mod)


def test_which_qgis_found(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`_which_qgis` wraps a launcher found on PATH in a single-item list."""
    exe = tmp_path / "qgis"
    monkeypatch.setattr(shutil, "which", lambda _name: str(exe))
    assert setup_env_vars._which_qgis() == [exe]


def test_which_qgis_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """`_which_qgis` returns an empty list when nothing is on PATH."""
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    assert not setup_env_vars._which_qgis()


@pytest.mark.parametrize(
    ("platform", "expected_parts"),
    [
        ("win32", ("AppData", "Roaming", "QGIS")),
        ("darwin", ("Library", "Application Support", "QGIS")),
        ("linux", (".local", "share", "QGIS")),
    ],
)
def test_default_data_dir_home_relative(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    platform: str,
    expected_parts: Sequence[str],
) -> None:
    """Without env overrides the data dir is derived from the home directory."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(sys, "platform", platform)
    for var in ("APPDATA", "XDG_DATA_HOME"):
        monkeypatch.delenv(var, raising=False)
    assert setup_env_vars._default_qgis_data_dir() == tmp_path.joinpath(*expected_parts)


@pytest.mark.parametrize(
    ("platform", "env_var"), [("win32", "APPDATA"), ("linux", "XDG_DATA_HOME")]
)
def test_default_data_dir_env_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    platform: str,
    env_var: str,
) -> None:
    """An explicit base env var takes precedence over the home-relative default."""
    monkeypatch.setattr(sys, "platform", platform)
    custom = tmp_path / "custom_base"
    monkeypatch.setenv(env_var, str(custom))
    assert setup_env_vars._default_qgis_data_dir() == custom / "QGIS"


def test_find_executable_windows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """On Windows the OSGeo4W ``bin/qgis*-bin.exe`` is discovered from the prefix."""
    monkeypatch.setattr(sys, "platform", "win32")
    prefix = tmp_path / "apps/Python312"
    prefix.mkdir(parents=True)
    exe = tmp_path / "bin/qgis-bin.exe"
    exe.parent.mkdir()
    exe.write_text("")
    assert setup_env_vars.find_default_qgis_executable(prefix) == exe.resolve()


def test_find_executable_linux_prefix_bin(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """On Linux ``<prefix>/bin/qgis`` is used when nothing is on PATH."""
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    exe = tmp_path / "bin/qgis"
    exe.parent.mkdir()
    exe.write_text("")
    assert setup_env_vars.find_default_qgis_executable(tmp_path) == exe.resolve()


def test_find_executable_via_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A launcher on PATH is the first candidate on Unix-like platforms."""
    monkeypatch.setattr(sys, "platform", "linux")
    exe = tmp_path / "qgis"
    exe.write_text("")
    monkeypatch.setattr(shutil, "which", lambda _name: str(exe))
    assert setup_env_vars.find_default_qgis_executable(tmp_path / "missing") == exe.resolve()


def test_find_executable_macos_bundle(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """On macOS the ``QGIS*.app`` bundle binary under ``~/Applications`` is found."""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    binary = tmp_path / "Applications/QGIS.app/Contents/MacOS/QGIS"
    binary.parent.mkdir(parents=True)
    binary.write_text("")
    assert setup_env_vars.find_default_qgis_executable(tmp_path / "missing") == binary.resolve()


def test_find_executable_not_found(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A missing executable raises :exc:`FileNotFoundError`."""
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(FileNotFoundError):
        setup_env_vars.find_default_qgis_executable(tmp_path)


def test_profiles_dir_not_found(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """An empty data directory raises :exc:`FileNotFoundError` before importing qgis."""
    monkeypatch.setattr(setup_env_vars, "_default_qgis_data_dir", lambda: tmp_path)
    with pytest.raises(FileNotFoundError):
        setup_env_vars.get_default_qgis_profiles_dir()


def test_profiles_dir_happy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The profiles dir is built from the QGIS major version reported by PyQGIS."""
    base = tmp_path / "QGIS"
    profiles = base / "QGIS4/profiles"
    profiles.mkdir(parents=True)
    monkeypatch.setattr(setup_env_vars, "_default_qgis_data_dir", lambda: base)
    _inject_fake_qgis_core(monkeypatch, version="4.0.3")
    assert setup_env_vars.get_default_qgis_profiles_dir() == profiles.resolve()


def test_main_writes_debugpy_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`main` seeds the debugpy attach toggles (enabled, non-blocking) into a fresh ``.env``."""
    env_file = tmp_path / ".env"
    monkeypatch.setattr(sys, "argv", ["setup_env_vars", str(env_file)])
    monkeypatch.setattr(
        setup_env_vars, "find_default_qgis_executable", lambda _prefix: tmp_path / "qgis"
    )
    monkeypatch.setattr(
        setup_env_vars, "get_default_qgis_profiles_dir", lambda: tmp_path / "profiles"
    )
    setup_env_vars.main()
    values = dotenv_values(env_file)
    assert values["QGIS_DEBUGPY"] == "1"
    assert values["QGIS_DEBUGPY_WAIT"] == "0"
