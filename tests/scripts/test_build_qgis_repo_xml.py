"""
Tests for :mod:`scripts.build_qgis_repo_xml`.

The script imports :mod:`lxml`, which belongs to the QGIS-bundled stack rather than the
``test`` dependency group, so the whole module is skipped where lxml is unavailable (e.g. the
QGIS-free test job). Where lxml is present it runs without a QGIS installation:

.. code-block:: bash

    pytest -p no:pytest_qgis -p no:pytest-qt tests/scripts/test_build_qgis_repo_xml.py
"""
# pylint: disable=redefined-outer-name  # pytest fixtures are used as test parameters by design

from __future__ import annotations

import argparse
import configparser
import sys
import types
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("lxml", reason="build_qgis_repo_xml imports lxml.etree at module load.")

# Imported only after the importorskip guard above confirms lxml is available.
from lxml import etree

from scripts import build_qgis_repo_xml as mod

if TYPE_CHECKING:
    from collections.abc import Mapping

_METADATA = """\
[general]
name=Test Plugin
qgisMinimumVersion=3.34
qgisMaximumVersion=4.99
description=A plugin used in tests
about=An <b>about</b> section with markup
version=1.2.3
author=Jane Doe
email=jane@example.com
tags=python,testing
experimental=False
"""
"""Minimal but representative ``metadata.txt`` content shared across tests."""


def _write_zip(path: Path, entries: Mapping[str, str]) -> Path:
    """
    Write a zip file containing `entries` and return its path.

    :param path: Destination path of the zip file.
    :param entries: Mapping of in-zip arcname to text content.
    :return: The `path` that was written.
    """
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return path


def _cfg(text: str = _METADATA) -> configparser.ConfigParser:
    """
    Parse `text` as INI and return the resulting parser.

    :param text: INI-formatted metadata text.
    :return: A populated :class:`configparser.ConfigParser`.
    """
    cfg = configparser.ConfigParser()
    cfg.read_string(text)
    return cfg


def _el(parent: etree._Element, path: str) -> etree._Element:
    """
    Return the single element matching `path`, asserting that it exists.

    :param parent: Element to search within.
    :param path: ElementPath expression passed to :meth:`find`.
    :return: The found element (never :data:`None`).
    """
    found = parent.find(path)
    assert found is not None, f"missing element: {path}"
    return found


@pytest.fixture
def plugin_dir(tmp_path: Path) -> Path:
    """
    Create a plugin directory holding a minimal ``metadata.txt``.

    :param tmp_path: Per-test temporary directory.
    :return: Path to the directory containing ``metadata.txt``.
    """
    (tmp_path / "metadata.txt").write_text(_METADATA, encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# resolve_plugin_path
# ---------------------------------------------------------------------------


class TestResolvePluginPath:
    """Tests for :func:`resolve_plugin_path`."""

    def test_explicit_path_is_resolved(self, tmp_path: Path) -> None:
        """An explicit path must be returned resolved to an absolute path."""
        assert mod.resolve_plugin_path(tmp_path) == tmp_path.resolve()

    def test_explicit_str_path_is_resolved(self, tmp_path: Path) -> None:
        """An explicit string path must be accepted and resolved."""
        assert mod.resolve_plugin_path(str(tmp_path)) == tmp_path.resolve()

    def test_none_without_qgispluginci_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With no explicit path and qgis-plugin-ci unavailable, raise :exc:`FileNotFoundError`."""
        monkeypatch.setitem(sys.modules, "qgispluginci", None)
        monkeypatch.setitem(sys.modules, "qgispluginci.parameters", None)
        with pytest.raises(FileNotFoundError):
            mod.resolve_plugin_path(None)

    def test_none_reads_plugin_path_from_qgispluginci(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """With no explicit path, the value is read from qgis-plugin-ci's ``plugin_path``."""
        params = types.SimpleNamespace(
            make_from=lambda: types.SimpleNamespace(plugin_path=str(tmp_path))
        )
        fake = types.ModuleType("qgispluginci.parameters")
        fake.__dict__["Parameters"] = params
        monkeypatch.setitem(sys.modules, "qgispluginci", types.ModuleType("qgispluginci"))
        monkeypatch.setitem(sys.modules, "qgispluginci.parameters", fake)
        assert mod.resolve_plugin_path(None) == tmp_path.resolve()

    def test_none_with_null_plugin_path_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        A ``plugin_path`` of :data:`None` from qgis-plugin-ci must raise
        :exc:`FileNotFoundError`.
        """
        params = types.SimpleNamespace(make_from=lambda: types.SimpleNamespace(plugin_path=None))
        fake = types.ModuleType("qgispluginci.parameters")
        fake.__dict__["Parameters"] = params
        monkeypatch.setitem(sys.modules, "qgispluginci", types.ModuleType("qgispluginci"))
        monkeypatch.setitem(sys.modules, "qgispluginci.parameters", fake)
        with pytest.raises(FileNotFoundError):
            mod.resolve_plugin_path(None)


# ---------------------------------------------------------------------------
# _find_metadata_entry_in_zip
# ---------------------------------------------------------------------------


class TestFindMetadataEntryInZip:
    """Tests for :func:`_find_metadata_entry_in_zip`."""

    def test_single_root_subdir(self, tmp_path: Path) -> None:
        """The ``metadata.txt`` inside the single root subdirectory must be located."""
        zip_path = _write_zip(
            tmp_path / "p.zip", {"plugin/metadata.txt": _METADATA, "plugin/__init__.py": ""}
        )
        with zipfile.ZipFile(zip_path) as zf:
            assert mod._find_metadata_entry_in_zip(zf) == "plugin/metadata.txt"

    def test_multiple_root_subdirs_raises(self, tmp_path: Path) -> None:
        """More than 1 root subdirectory makes the location ambiguous: raise :exc:`ValueError`."""
        zip_path = _write_zip(tmp_path / "p.zip", {"a/metadata.txt": _METADATA, "b/x.py": ""})
        with zipfile.ZipFile(zip_path) as zf, pytest.raises(ValueError, match="more than one"):
            mod._find_metadata_entry_in_zip(zf)

    def test_missing_metadata_raises(self, tmp_path: Path) -> None:
        """A single subdirectory without ``metadata.txt`` must raise :exc:`FileNotFoundError`."""
        zip_path = _write_zip(tmp_path / "p.zip", {"plugin/other.txt": "x"})
        with zipfile.ZipFile(zip_path) as zf, pytest.raises(FileNotFoundError):
            mod._find_metadata_entry_in_zip(zf)

    def test_metadata_at_root_is_not_accepted(self, tmp_path: Path) -> None:
        """A ``metadata.txt`` at the zip root (no subdir) must raise :exc:`FileNotFoundError`."""
        zip_path = _write_zip(tmp_path / "p.zip", {"metadata.txt": _METADATA})
        with zipfile.ZipFile(zip_path) as zf, pytest.raises(FileNotFoundError):
            mod._find_metadata_entry_in_zip(zf)


# ---------------------------------------------------------------------------
# read_metadata / read_metadata_from_zip
# ---------------------------------------------------------------------------


class TestReadMetadata:
    """Tests for :func:`read_metadata`."""

    def test_reads_general_section(self, plugin_dir: Path) -> None:
        """A valid ``metadata.txt`` must parse into a config exposing ``[general]`` keys."""
        cfg = mod.read_metadata(plugin_dir / "metadata.txt")
        assert cfg.get("general", "name") == "Test Plugin"
        assert cfg.get("general", "version") == "1.2.3"

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        """A non-existent path must raise :exc:`FileNotFoundError`."""
        with pytest.raises(FileNotFoundError):
            mod.read_metadata(tmp_path / "nope.txt")


class TestReadMetadataFromZip:
    """Tests for :func:`read_metadata_from_zip`."""

    def test_reads_from_zip(self, tmp_path: Path) -> None:
        """The ``metadata.txt`` inside a plugin zip must be parsed without extraction."""
        zip_path = _write_zip(tmp_path / "p.zip", {"plugin/metadata.txt": _METADATA})
        cfg = mod.read_metadata_from_zip(zip_path)
        assert cfg.get("general", "name") == "Test Plugin"

    def test_missing_zip_raises(self, tmp_path: Path) -> None:
        """A non-existent zip path must raise :exc:`FileNotFoundError`."""
        with pytest.raises(FileNotFoundError):
            mod.read_metadata_from_zip(tmp_path / "nope.zip")

    def test_not_a_zip_raises(self, tmp_path: Path) -> None:
        """A file that is not a valid zip must raise :exc:`zipfile.BadZipFile`."""
        bad = tmp_path / "bad.zip"
        bad.write_text("definitely not a zip", encoding="utf-8")
        with pytest.raises(zipfile.BadZipFile):
            mod.read_metadata_from_zip(bad)


# ---------------------------------------------------------------------------
# metadata_to_fields
# ---------------------------------------------------------------------------


class TestMetadataToFields:
    """Tests for :func:`metadata_to_fields`."""

    def test_maps_known_fields(self) -> None:
        """Known XML keys must be populated from their mapped ``metadata.txt`` entries."""
        fields = mod.metadata_to_fields(_cfg())
        assert fields["name"] == "Test Plugin"
        assert fields["version"] == "1.2.3"
        assert fields["qgis_minimum_version"] == "3.34"

    def test_absent_metadata_key_is_none(self) -> None:
        """A known field absent from ``metadata.txt`` must resolve to :data:`None`."""
        assert mod.metadata_to_fields(_cfg())["icon"] is None

    def test_extra_fields_default_to_none(self) -> None:
        """Every entry in :data:`EXTRA_FIELDS` must default to :data:`None` without overrides."""
        fields = mod.metadata_to_fields(_cfg())
        assert all(fields[key] is None for key in mod.EXTRA_FIELDS)

    def test_overrides_take_priority(self) -> None:
        """Overrides must win over both ``metadata.txt`` values and extra-field defaults."""
        fields = mod.metadata_to_fields(_cfg(), {"version": "9.9.9", "download_url": "http://x"})
        assert fields["version"] == "9.9.9"
        assert fields["download_url"] == "http://x"

    def test_override_values_are_coerced_to_str(self) -> None:
        """Non-string override values must be stored as their ``str`` form."""
        assert mod.metadata_to_fields(_cfg(), {"experimental": True})["experimental"] == "True"


# ---------------------------------------------------------------------------
# build_xml
# ---------------------------------------------------------------------------


class TestBuildXml:
    """Tests for :func:`build_xml`."""

    def test_root_and_plugin_attributes(self) -> None:
        """The tree must root at ``<plugins>`` with name/version attributes on the plugin."""
        root = mod.build_xml({"name": "N", "version": "1.0"})
        assert root.tag == "plugins"
        plugin = root.find("pyqgis_plugin")
        assert plugin is not None
        assert plugin.get("name") == "N"
        assert plugin.get("version") == "1.0"

    def test_missing_name_and_version_default_to_empty(self) -> None:
        """Absent name/version must yield empty-string attributes, never :data:`None`."""
        plugin = mod.build_xml({"description": "d"}).find("pyqgis_plugin")
        assert plugin is not None
        assert plugin.get("name") == ""
        assert plugin.get("version") == ""

    @pytest.mark.parametrize("value", ["", None], ids=["empty-string", "none"])
    def test_empty_values_are_skipped(self, value: str | None) -> None:
        """Fields whose value is empty or :data:`None` must not produce a child element."""
        root = mod.build_xml({"name": "N", "version": "1.0", "about": value})
        assert root.find("pyqgis_plugin/about") is None

    def test_plain_text_field(self) -> None:
        """A non-XML field must store its value as element text."""
        root = mod.build_xml({"name": "N", "version": "1.0", "description": "plain"})
        assert _el(root, "pyqgis_plugin/description").text == "plain"

    def test_xml_field_is_parsed_as_fragment(self) -> None:
        """A field listed in ``xml_fields`` must turn markup into real child nodes."""
        root = mod.build_xml(
            {"name": "N", "version": "1.0", "about": "An <b>x</b> y"}, xml_fields={"about"}
        )
        about = root.find("pyqgis_plugin/about")
        assert about is not None
        assert about.text == "An "
        bold = about.find("b")
        assert bold is not None
        assert bold.text == "x"

    def test_markup_is_escaped_when_field_not_listed(self) -> None:
        """Markup in a plain (non-``xml_fields``) field must be stored as literal text."""
        root = mod.build_xml({"name": "N", "version": "1.0", "about": "An <b>x</b>"})
        about = root.find("pyqgis_plugin/about")
        assert about is not None
        assert about.text == "An <b>x</b>"
        assert about.find("b") is None

    def test_malformed_xml_field_raises_valueerror(self) -> None:
        """Malformed markup in an ``xml_fields`` field must raise :exc:`ValueError`."""
        with pytest.raises(ValueError, match="not valid XML"):
            mod.build_xml(
                {"name": "N", "version": "1.0", "about": "<b>unclosed"}, xml_fields={"about"}
            )


# ---------------------------------------------------------------------------
# generate_plugins_xml
# ---------------------------------------------------------------------------


class TestGeneratePluginsXml:
    """Tests for :func:`generate_plugins_xml`."""

    def test_generates_from_directory(self, plugin_dir: Path) -> None:
        """A plugin directory must yield XML carrying the metadata values."""
        parsed = etree.fromstring(mod.generate_plugins_xml(plugin_dir).encode("utf-8"))
        assert parsed.tag == "plugins"
        assert _el(parsed, "pyqgis_plugin").get("name") == "Test Plugin"
        # Without xml_fields, markup in `about` is escaped and round-trips as literal text.
        assert _el(parsed, "pyqgis_plugin/about").text == "An <b>about</b> section with markup"

    def test_generates_from_zip(self, tmp_path: Path) -> None:
        """A plugin zip must yield XML carrying the metadata values."""
        zip_path = _write_zip(tmp_path / "p.zip", {"plugin/metadata.txt": _METADATA})
        assert "Test Plugin" in mod.generate_plugins_xml(zip_path)

    def test_overrides_are_applied(self, plugin_dir: Path) -> None:
        """Keyword overrides must appear as elements in the generated XML."""
        xml = mod.generate_plugins_xml(plugin_dir, download_url="http://example.com/p.zip")
        parsed = etree.fromstring(xml.encode("utf-8"))
        assert _el(parsed, "pyqgis_plugin/download_url").text == "http://example.com/p.zip"

    def test_xml_fields_preserve_markup(self, plugin_dir: Path) -> None:
        """Fields named in ``xml_fields`` must keep their markup as child nodes."""
        xml = mod.generate_plugins_xml(plugin_dir, xml_fields={"about"})
        about = _el(etree.fromstring(xml.encode("utf-8")), "pyqgis_plugin/about")
        assert _el(about, "b").text == "about"

    def test_returns_str(self, plugin_dir: Path) -> None:
        """The generated XML must be returned as a ``str``."""
        assert isinstance(mod.generate_plugins_xml(plugin_dir), str)


# ---------------------------------------------------------------------------
# build_arg_parser
# ---------------------------------------------------------------------------


class TestBuildArgParser:
    """Tests for :func:`build_arg_parser`."""

    def test_returns_argument_parser(self) -> None:
        """The factory must return an :class:`argparse.ArgumentParser`."""
        assert isinstance(mod.build_arg_parser(), argparse.ArgumentParser)

    def test_default_output(self) -> None:
        """With no arguments, the output defaults to ``build/plugins.xml``."""
        assert mod.build_arg_parser().parse_args([]).output == Path("build/plugins.xml")

    def test_override_and_xml_fields_args(self) -> None:
        """Override flags and ``--xml-fields`` must populate their namespace destinations."""
        args = mod.build_arg_parser().parse_args(
            ["--download-url", "http://x", "--xml-fields", "about", "description"]
        )
        assert args.download_url == "http://x"
        assert args.xml_fields == ["about", "description"]

    def test_output_and_plugin_path(self, tmp_path: Path) -> None:
        """
        The positional output and ``--plugin-path`` must parse into :class:`pathlib.Path`
        objects.
        """
        args = mod.build_arg_parser().parse_args(
            [str(tmp_path / "out.xml"), "--plugin-path", str(tmp_path)]
        )
        assert args.output == tmp_path / "out.xml"
        assert args.plugin_path == tmp_path


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestMain:
    """Tests for :func:`main`."""

    def test_writes_output_file(self, plugin_dir: Path, tmp_path: Path) -> None:
        """``main`` must write the generated XML, auto-filling ``update_date``."""
        out = tmp_path / "out/plugins.xml"
        mod.main([str(out), "--plugin-path", str(plugin_dir)])
        assert out.is_file()
        parsed = etree.fromstring(out.read_text(encoding="utf-8").encode("utf-8"))
        assert _el(parsed, "pyqgis_plugin").get("name") == "Test Plugin"
        assert parsed.find("pyqgis_plugin/update_date") is not None

    def test_creates_missing_parent_dirs(self, plugin_dir: Path, tmp_path: Path) -> None:
        """``main`` must create intermediate output directories as needed."""
        out = tmp_path / "a/b/c.xml"
        mod.main([str(out), "--plugin-path", str(plugin_dir)])
        assert out.is_file()

    def test_explicit_update_date_is_kept(self, plugin_dir: Path, tmp_path: Path) -> None:
        """An explicit ``--update-date`` must not be overwritten by the generated default."""
        out = tmp_path / "out.xml"
        mod.main(
            [str(out), "--plugin-path", str(plugin_dir), "--update-date", "2020-01-01T00:00:00"]
        )
        parsed = etree.fromstring(out.read_text(encoding="utf-8").encode("utf-8"))
        assert _el(parsed, "pyqgis_plugin/update_date").text == "2020-01-01T00:00:00"

    def test_invalid_plugin_path_exits(self, tmp_path: Path) -> None:
        """A plugin path without ``metadata.txt`` must exit via ``parser.error``."""
        with pytest.raises(SystemExit):
            mod.main([str(tmp_path / "out.xml"), "--plugin-path", str(tmp_path / "missing")])
