"""
Tests for the :mod:`stratified_packager.__about__` metadata module.

Usage from the repo root folder:

.. code-block:: bash

    # for whole tests
    pytest -p no:pytest_qgis -p no:pytest-qt tests/stratified_packager/test___about__.py
    # for specific test
    pytest -p no:pytest_qgis -p no:pytest-qt \
        tests/stratified_packager/test___about__.py::test_version_semver
"""

from pathlib import Path

import semver
import validators

from stratified_packager import __about__


def test_metadata_types() -> None:
    """Test types."""
    # plugin metadata.txt file
    assert isinstance(__about__.PLG_METADATA_FILE, Path)
    assert __about__.PLG_METADATA_FILE.is_file()

    # plugin dir
    assert isinstance(__about__.DIR_PLUGIN_ROOT, Path)
    assert __about__.DIR_PLUGIN_ROOT.is_dir()

    # metadata as dict
    assert isinstance(__about__.__plugin_md__, dict)
    assert all(isinstance(k, str) for k in __about__.__plugin_md__)
    assert all(isinstance(v, dict) for v in __about__.__plugin_md__.values())

    # general
    assert isinstance(__about__.__author__, str)
    assert isinstance(__about__.__copyright__, str)
    assert isinstance(__about__.__email__, str)
    assert validators.email(__about__.__email__)
    assert isinstance(__about__.__keywords__, list)
    assert all(isinstance(kw, str) for kw in __about__.__keywords__)
    assert isinstance(__about__.__license__, str)
    assert isinstance(__about__.__plugin_dependencies__, list)
    assert all(isinstance(dep, str) for dep in __about__.__plugin_dependencies__)
    assert isinstance(__about__.__summary__, str)
    assert isinstance(__about__.__title__, str)
    assert isinstance(__about__.__uri__, str)
    assert validators.url(__about__.__uri__)
    assert __about__.__uri__ == __about__.__uri_repository__
    assert isinstance(__about__.__version__, str)
    assert isinstance(__about__.__version_info__, tuple)
    assert all(isinstance(i, (int, str)) for i in __about__.__version_info__)

    # optionals
    assert (not __about__.__icon_path__) or isinstance(__about__.__icon_path__, Path)
    assert (not __about__.__icon_path__) or __about__.__icon_path__.is_file()

    assert (not __about__.__uri_homepage__) or isinstance(__about__.__uri_homepage__, str)
    assert (not __about__.__uri_homepage__) or validators.url(__about__.__uri_homepage__)

    assert (not __about__.__uri_tracker__) or isinstance(__about__.__uri_tracker__, str)
    assert (not __about__.__uri_tracker__) or validators.url(__about__.__uri_tracker__)

    # misc
    general = __about__.__plugin_md__.get("general")
    assert general
    assert all(isinstance(k, str) for k in general)
    assert all(isinstance(v, str) for v in general.values())

    booleans = {"FALSE", "NO", "TRUE", "YES"}
    assert (not general.get("experimental")) or general["experimental"].strip().upper() in booleans
    assert (not general.get("deprecated")) or general["deprecated"].strip().upper() in booleans
    assert (not general.get("server")) or general["server"].strip().upper() in booleans
    assert (not general.get("hasProcessingProvider")) or general[
        "hasProcessingProvider"
    ].strip().upper() in booleans
    assert (not general.get("category")) or general["category"].strip().upper() in {
        "DATABASE",
        "MESH",
        "RASTER",
        "VECTOR",
        "WEB",
    }

    # QGIS versions
    assert isinstance(general.get("qgisMinimumVersion"), str)
    assert isinstance(general.get("qgisMaximumVersion"), str)

    qgis_min_version_info = tuple(int(i) for i in general["qgisMinimumVersion"].split("."))
    qgis_max_version = general.get("qgisMaximumVersion") or f"{qgis_min_version_info[0]}.99"
    assert qgis_min_version_info <= tuple(int(i) for i in qgis_max_version.split("."))


def test_version_semver() -> None:
    """Test if version complies with semantic versioning."""
    assert semver.Version.is_valid(__about__.__version__)
