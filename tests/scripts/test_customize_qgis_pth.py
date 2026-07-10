"""
Tests for :mod:`scripts.customize_qgis_pth` cross-platform helpers.

Usage from the repo root folder:

.. code-block:: bash

    pytest -p no:pytest_qgis -p no:pytest-qt tests/scripts/test_customize_qgis_pth.py
"""

from __future__ import annotations

import sys
import sysconfig
import types
from typing import TYPE_CHECKING

import pytest

from scripts import customize_qgis_pth

if TYPE_CHECKING:
    from pathlib import Path


def test_get_pth_file_in_site_packages(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """An existing ``qgis.pth`` in site-packages is returned as-is."""
    purelib = tmp_path / "site-packages"
    purelib.mkdir()
    pth = purelib / "qgis.pth"
    pth.write_text("")
    monkeypatch.setattr(sysconfig, "get_path", lambda _name: str(purelib))
    assert customize_qgis_pth._get_pth_file() == pth


def test_get_pth_file_moved_from_prefix(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A ``qgis.pth`` sitting directly in sys.prefix is moved into site-packages."""
    purelib = tmp_path / "site-packages"
    purelib.mkdir()
    prefix = tmp_path / "prefix"
    prefix.mkdir()
    (prefix / "qgis.pth").write_text("data")
    monkeypatch.setattr(sysconfig, "get_path", lambda _name: str(purelib))
    monkeypatch.setattr(sys, "prefix", str(prefix))
    result = customize_qgis_pth._get_pth_file()
    assert result == purelib / "qgis.pth"
    assert result.read_text() == "data"
    assert not (prefix / "qgis.pth").exists()


def test_get_pth_file_created_when_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With no qgis.pth anywhere (e.g. a --system-site-packages venv), an empty one is created."""
    purelib = tmp_path / "site-packages"
    purelib.mkdir()
    prefix = tmp_path / "prefix"
    prefix.mkdir()
    monkeypatch.setattr(sysconfig, "get_path", lambda _name: str(purelib))
    monkeypatch.setattr(sys, "prefix", str(prefix))
    result = customize_qgis_pth._get_pth_file()
    assert result == purelib / "qgis.pth"
    assert result.is_file()
    assert result.read_text() == ""


def test_get_qgis_python_dir_from_package(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The QGIS python dir is the grandparent of the ``qgis`` package ``__file__``."""
    init_file = tmp_path / "python/qgis/__init__.py"
    init_file.parent.mkdir(parents=True)
    init_file.write_text("")
    qgis_mod = types.ModuleType("qgis")
    qgis_mod.__file__ = str(init_file)
    monkeypatch.setitem(sys.modules, "qgis", qgis_mod)
    assert customize_qgis_pth._get_qgis_python_dir() == (tmp_path / "python").resolve()


def test_get_qgis_python_dir_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-importable ``qgis`` is surfaced as :exc:`RuntimeError`."""
    monkeypatch.setitem(sys.modules, "qgis", None)
    with pytest.raises(RuntimeError):
        customize_qgis_pth._get_qgis_python_dir()


def test_grass_candidates_gisbase_first(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``GISBASE`` is honored ahead of the conventional locations."""
    gisbase = tmp_path / "grass"
    (gisbase / "etc/python").mkdir(parents=True)
    monkeypatch.setenv("GISBASE", str(gisbase))
    candidates = customize_qgis_pth._grass_python_candidates(tmp_path / "python")
    assert candidates[0] == gisbase / "etc/python"


def test_grass_candidates_windows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The Windows branch probes ``apps/grass/grass*/etc/python``."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("GISBASE", raising=False)
    qgis_python = tmp_path / "apps/qgis/python"
    qgis_python.mkdir(parents=True)
    grass = tmp_path / "apps/grass/grass84/etc/python"
    grass.mkdir(parents=True)
    assert grass in customize_qgis_pth._grass_python_candidates(qgis_python)


def test_grass_candidates_macos(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The macOS branch probes the application bundle's ``grass*`` directory."""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv("GISBASE", raising=False)
    qgis_python = tmp_path / "Contents/Resources/python"
    qgis_python.mkdir(parents=True)
    grass = tmp_path / "Contents/Resources/grass8/etc/python"
    grass.mkdir(parents=True)
    assert grass in customize_qgis_pth._grass_python_candidates(qgis_python)


def test_find_grass_python_dir_none(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """When no candidate exists the result is :data:`None`."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("GISBASE", raising=False)
    assert customize_qgis_pth._find_grass_python_dir(tmp_path / "apps/qgis/python") is None


def test_find_grass_python_dir_found(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The first existing candidate directory is returned, resolved."""
    gisbase = tmp_path / "grass"
    (gisbase / "etc/python").mkdir(parents=True)
    monkeypatch.setenv("GISBASE", str(gisbase))
    expected = (gisbase / "etc/python").resolve()
    assert customize_qgis_pth._find_grass_python_dir(tmp_path / "python") == expected


def test_add_to_pth_appends_once(tmp_path: Path) -> None:
    """`_add_to_pth` appends a new path and never duplicates an existing one."""
    pth = tmp_path / "qgis.pth"
    pth.write_text("existing\n")
    target = (tmp_path / "plugins").resolve()
    customize_qgis_pth._add_to_pth(pth, target)
    assert target.as_posix() in pth.read_text()
    customize_qgis_pth._add_to_pth(pth, target)
    assert pth.read_text().count(target.as_posix()) == 1


def test_ensure_in_sys_path_skips_when_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`_ensure_in_sys_path` leaves the file untouched when the path is already known."""
    pth = tmp_path / "qgis.pth"
    pth.write_text("")
    target = (tmp_path / "plugins").resolve()
    monkeypatch.setattr(customize_qgis_pth, "_get_resolved_sys_path", lambda: iter([target]))
    customize_qgis_pth._ensure_in_sys_path(pth, target, "plugins")
    assert pth.read_text() == ""
