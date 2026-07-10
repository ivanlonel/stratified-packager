"""Generate a QGIS repository file (plugins.xml) from a plugin's metadata.txt."""

from __future__ import annotations

import argparse
import configparser
import zipfile
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from lxml import etree

if TYPE_CHECKING:
    import os
    from collections.abc import Collection, Mapping, Sequence

FIELD_MAP: dict[str, tuple[str, str]] = {
    "name": ("general", "name"),
    "qgis_minimum_version": ("general", "qgisMinimumVersion"),
    "qgis_maximum_version": ("general", "qgisMaximumVersion"),
    "description": ("general", "description"),
    "about": ("general", "about"),
    "version": ("general", "version"),
    "author_name": ("general", "author"),
    "email": ("general", "email"),
    "changelog": ("general", "changelog"),
    "experimental": ("general", "experimental"),
    "deprecated": ("general", "deprecated"),
    "tags": ("general", "tags"),
    "homepage": ("general", "homepage"),
    "repository": ("general", "repository"),
    "tracker": ("general", "tracker"),
    "icon": ("general", "icon"),
    "category": ("general", "category"),
    "plugin_dependencies": ("general", "plugin_dependencies"),
    "server": ("general", "server"),
    "has_processing_provider": ("general", "hasProcessingProvider"),
}
"""Map of XML element name to the corresponding section and key in metadata.txt."""


EXTRA_FIELDS = (
    "download_url",
    "file_name",
    "library",
    "create_date",
    "update_date",
    "uploaded_by",
    "average_vote",
    "nb_downloads",
    "rating_votes",
)
"""XML fields that are not read directly from metadata.txt."""


def resolve_plugin_path(explicit: str | os.PathLike[str] | None = None) -> Path:
    """
    Resolve the path to the plugin directory or zip, falling back to ``pyproject.toml``.

    When `explicit` is :data:`None`, read ``tool.qgis-plugin-ci.plugin_path`` from
    ``pyproject.toml`` in the current directory.

    :param explicit: Path provided by the caller; used directly if not :data:`None`.
        Can be a directory or a ``.zip`` file.
    :return: The resolved path to the plugin directory or zip.
    :raise FileNotFoundError: If `explicit` is :data:`None` and the plugin path
        cannot be determined from ``pyproject.toml``.
    """
    if explicit is not None:
        return Path(explicit).resolve()

    msg = (
        "Could not determine the plugin path: --plugin-path was not provided "
        "and the plugin_path setting could not be obtained from qgis-plugin-ci."
    )

    try:
        from qgispluginci.parameters import (  # type: ignore[import-not-found]  # noqa: PLC0415  # ty: ignore[unresolved-import]
            Parameters,
        )

        plugin_path: str | None = Parameters.make_from().plugin_path
    except Exception as e:
        raise FileNotFoundError(msg) from e

    if plugin_path is None:
        raise FileNotFoundError(msg)

    return Path(plugin_path).resolve()


def _find_metadata_entry_in_zip(zf: zipfile.ZipFile) -> str:
    """
    Locate the internal path of ``metadata.txt`` inside a zip file.

    Look for ``metadata.txt`` inside a single subdirectory present at the
    root. No deeper recursive search is performed.

    :param zf: Open zip file.
    :return: Internal path (``arcname``) of the ``metadata.txt`` found.
    :raise FileNotFoundError: If no ``metadata.txt`` is found at the expected
        location.
    :raise ValueError: If there is more than one subdirectory at the root of
        the zip, because in that case the ``metadata.txt`` location is ambiguous.
    """
    names = zf.namelist()

    # Collect first-level subdirectories present at the root.
    root_dirs = sorted(
        {parts[0] for name in names if (parts := Path(name).parts) and len(parts) > 1}
    )

    if len(root_dirs) > 1:
        listing = "\n  ".join(root_dirs)
        msg = (
            f"The zip contains more than one subdirectory at the root:\n  {listing}\n"
            "Cannot determine where metadata.txt is located."
        )
        raise ValueError(msg)

    if root_dirs:
        candidate = f"{root_dirs[0]}/metadata.txt"
        if candidate in names:
            return candidate

    msg = f"metadata.txt not found in the single root subdirectory. Inspected entries: {names!r}"
    raise FileNotFoundError(msg)


def read_metadata(metadata_path: str | os.PathLike[str]) -> configparser.ConfigParser:
    """
    Parse a ``metadata.txt`` file in INI format.

    :param metadata_path: Path to the ``metadata.txt`` file.
    :return: A populated :class:`configparser.ConfigParser` instance.
    :raise FileNotFoundError: If `metadata_path` does not point to an existing file.
    :raise configparser.Error: If the file cannot be parsed as INI.
    """
    if not Path(metadata_path).is_file():
        msg = f"metadata.txt not found: {metadata_path}"
        raise FileNotFoundError(msg)

    cfg = configparser.ConfigParser()
    cfg.read(metadata_path, encoding="utf-8")
    return cfg


def read_metadata_from_zip(zip_path: str | os.PathLike[str]) -> configparser.ConfigParser:
    """
    Parse the ``metadata.txt`` contained in a plugin zip file.

    Locate the ``metadata.txt`` via :func:`_find_metadata_entry_in_zip` and
    parse it without extracting it to disk.

    :param zip_path: Path to the plugin ``.zip`` file.
    :return: A populated :class:`configparser.ConfigParser` instance.
    :raise FileNotFoundError: If the zip does not exist or does not contain
        ``metadata.txt`` at the expected location.
    :raise ValueError: If the zip contains more than one subdirectory at the root.
    :raise configparser.Error: If the ``metadata.txt`` cannot be parsed as INI.
    :raise zipfile.BadZipFile: If the file is not a valid zip.
    """
    zip_path = Path(zip_path)
    if not zip_path.is_file():
        msg = f"Zip file not found: {zip_path}"
        raise FileNotFoundError(msg)

    with zipfile.ZipFile(zip_path) as zf:
        text_content = zf.read(_find_metadata_entry_in_zip(zf)).decode("utf-8")

    cfg = configparser.ConfigParser()
    cfg.read_string(text_content)
    return cfg


def metadata_to_fields(
    cfg: configparser.ConfigParser,
    overrides: Mapping[str, Any] | None = None,
) -> dict[str, str | None]:
    """
    Build the mapping of XML field names to their string values.

    Values are resolved in the following order of priority:

    1. `overrides` (highest priority)
    2. Values from ``metadata.txt``

    Fields that resolve to an empty string are included in the returned dict
    and will be omitted from the XML output by :func:`build_xml`.

    :param cfg: Parsed ``metadata.txt``, as returned by :func:`read_metadata`
        or :func:`read_metadata_from_zip`.
    :param overrides: Mapping of XML element name to override value. Any type is
        accepted; values are converted to ``str`` before being stored.
    :return: Flat mapping ``{xml_element_name: value}`` covering all known fields.
    """
    if overrides is None:
        overrides = {}

    fields: dict[str, str | None] = {}

    for xml_key, (section, meta_key) in FIELD_MAP.items():
        if xml_key in overrides:
            fields[xml_key] = str(overrides[xml_key])
        else:
            fields[xml_key] = cfg.get(section, meta_key, fallback=None)

    for xml_key in EXTRA_FIELDS:
        if xml_key in overrides:
            fields[xml_key] = str(overrides[xml_key])
        else:
            fields[xml_key] = None

    return fields


def get_xml_fields(
    plugin_path: str | os.PathLike[str] | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> dict[str, str | None]:
    """
    Read the plugin metadata and return the mapping of XML fields.

    Accepts either a directory or a ``.zip`` file as `plugin_path`. For
    directories, read ``metadata.txt`` directly. For zips, locate and read
    the internal ``metadata.txt`` via :func:`read_metadata_from_zip`.

    :param plugin_path: Path to the plugin directory or ``.zip``. When :data:`None`,
        it is read from ``tool.qgis-plugin-ci.plugin_path`` in ``pyproject.toml``.
    :param overrides: Optional overrides for XML element values.
    :return: Mapping ``{xml_element_name: value}`` covering all known fields.
    :raise FileNotFoundError: If ``metadata.txt`` cannot be located.
    :raise ValueError: If the zip contains more than one subdirectory at the root.
    :raise configparser.Error: If the file cannot be parsed as INI.
    """
    path = resolve_plugin_path(plugin_path)

    return metadata_to_fields(
        read_metadata(path / "metadata.txt") if path.is_dir() else read_metadata_from_zip(path),
        overrides,
    )


def build_xml(
    fields: Mapping[str, str | None], xml_fields: Collection[str] = frozenset()
) -> etree._Element:
    r"""
    Build the ``plugins.xml`` element tree from a dictionary of fields.

    Empty values are silently ignored. Fields listed in `xml_fields` have their
    value parsed as an XML fragment, so that markup such as ``<b>`` or
    ``<a href="…">`` is preserved as real child nodes, instead of being
    escaped as entities (\&lt;a href="…"\&gt;).

    :param fields: Mapping of XML element name to text value, as returned by
        :func:`metadata_to_fields`.
    :param xml_fields: Names of fields whose value must be treated as an XML
        fragment. Each value is wrapped in a throwaway root element, parsed, and
        its content transplanted into the target child element.
    :return: The root ``<plugins>`` element of the built tree.
    :raise ValueError: If a field listed in `xml_fields` contains malformed XML.
    """
    root = etree.Element("plugins")
    plugin_el = etree.SubElement(
        root,
        "pyqgis_plugin",
        name=fields.get("name") or "",
        version=fields.get("version") or "",
    )

    for xml_key, value in fields.items():
        if not value:
            continue
        child = etree.SubElement(plugin_el, xml_key)
        if xml_key in xml_fields:
            # Wrap the value in a throwaway root so etree can parse arbitrary
            # fragments, then move the parsed content (text + children) into child.
            try:
                wrapper = etree.fromstring(f"<_>{value}</_>")
            except etree.ParseError as e:
                msg = f"The field '{xml_key}' is not valid XML: {value!r}"
                raise ValueError(msg) from e
            child.text = wrapper.text
            for node in wrapper:
                child.append(node)
        else:
            child.text = value

    return root


def generate_plugins_xml(
    plugin_path: str | os.PathLike[str] | None = None,
    *,
    xml_fields: Collection[str] | None = None,
    **overrides: object,
) -> str:
    r"""
    Generate the text of a ``plugins.xml`` file from a plugin's ``metadata.txt``.

    Read the plugin metadata, merge any overrides, build the XML tree and
    return the result as a formatted string.

    :param plugin_path: Path to the plugin directory or ``.zip``, which contains
        the ``metadata.txt``. When :data:`None`, it is read from
        ``tool.qgis-plugin-ci.plugin_path`` in ``pyproject.toml``.
    :param xml_fields: Names of XML elements whose value must be parsed as an XML
        fragment instead of plain text, preserving HTML markup for rendering by
        QGIS. Pass :data:`None` or omit to treat all fields as plain text.
    :param \*\*overrides: Arguments mapping XML element names to override values.
        Any XML element accepted by the QGIS repository format can be provided
        (e.g. ``download_url="https://…"``, ``experimental="True"``). The values
        are converted to ``str``.
    :return: The generated XML as a formatted string.
    :raise FileNotFoundError: If ``metadata.txt`` cannot be located.
    :raise ValueError: If a field listed in `xml_fields` contains malformed XML,
        or if the zip contains more than one subdirectory at the root.
    """
    fields = get_xml_fields(plugin_path, overrides)
    root = build_xml(
        fields, xml_fields=frozenset(xml_fields) if xml_fields is not None else frozenset()
    )
    root_c14n2 = etree.fromstring(etree.tostring(root, method="c14n2"))
    return etree.tostring(root_c14n2, pretty_print=True, encoding="unicode")


# ---------------------------------------------------------------------------
# Command-line interface (CLI)
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    """
    Build and return the CLI argument parser.

    :return: Configured :class:`argparse.ArgumentParser` instance.
    """
    parser = argparse.ArgumentParser(
        description="Generate a QGIS plugins.xml repository file from metadata.txt.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "output",
        nargs="?",
        type=Path,
        default=Path("build/plugins.xml"),
        metavar="OUTPUT",
        help="Destination path for the plugins.xml.",
    )
    parser.add_argument(
        "--plugin-path",
        type=Path,
        metavar="PATH",
        help=(
            "Path to the plugin directory (containing metadata.txt) or to a plugin .zip file. "
            "If not provided, qgis-plugin-ci must be installed, "
            "since the value of its plugin_path setting will be used."
        ),
    )
    parser.add_argument(
        "--timezone",
        type=ZoneInfo,
        default=None,
        metavar="TIMEZONE",
        help=(
            "IANA-format time zone used to fill the local time in the update_date field "
            "if it is not provided."
        ),
    )
    parser.add_argument(
        "--xml-fields",
        dest="xml_fields",
        nargs="+",
        metavar="FIELD",
        help=(
            "Space-separated list of XML element names to be parsed as XML "
            "fragments instead of plain text, preserving HTML tags literally "
            "(e.g. about author_name description)."
        ),
    )

    # Expose each known XML field as an optional override argument.
    override_group = parser.add_argument_group("XML field overrides")
    for field in tuple(FIELD_MAP) + EXTRA_FIELDS:
        override_group.add_argument(
            f"--{field.replace('_', '-')}",
            dest=field,
            metavar="VALUE",
            help=f"Override the <{field}> element in plugins.xml.",
        )

    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """
    Entry point for the command-line interface.

    Parse `argv` (or ``sys.argv[1:]`` when empty), resolve the options,
    generate the plugins XML via :func:`generate_plugins_xml` and write the
    resulting XML to the requested output file. Argument or file errors are
    reported via :meth:`argparse.ArgumentParser.error` and exit with code 2.

    :param argv: List of arguments to parse. Defaults to ``sys.argv[1:]`` when :data:`None`.
    """
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    xml_fields: frozenset[str] = frozenset(args.xml_fields) if args.xml_fields else frozenset()

    # Collect only the field overrides that were explicitly provided.
    overrides = {
        key: value
        for key, value in vars(args).items()
        if key not in {"output", "plugin_path", "timezone", "xml_fields"} and value is not None
    }
    if "update_date" not in overrides:
        overrides["update_date"] = datetime.now(args.timezone).isoformat(timespec="seconds")

    try:
        xml = generate_plugins_xml(args.plugin_path, xml_fields=xml_fields, **overrides)
    except (FileNotFoundError, ValueError) as e:
        parser.error(f"Failed to generate the XML: {e}")

    output_path: Path = args.output
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(xml, encoding="utf-8")
    except OSError as e:
        parser.error(f"Failed to save the XML to {output_path}: {e}")

    print(f"XML generated: {output_path}")


if __name__ == "__main__":
    main()
