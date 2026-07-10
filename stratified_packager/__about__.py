"""
Metadata about the package to easily retrieve informations about it.

See: https://packaging.python.org/guides/single-sourcing-package-version/
"""

from configparser import ConfigParser
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal, Required, TypedDict, cast, override

__all__: list[str] = [
    "__author__",
    "__copyright__",
    "__email__",
    "__license__",
    "__summary__",
    "__title__",
    "__uri__",
    "__version__",
]


class QgisPluginMetadataGeneral(TypedDict, total=False):
    """
    dict representation of the ``[general]`` section from a QGIS plugin ``metadata.txt`` file.

    All values are ``str`` because ConfigParser does not perform type coercion.
    Boolean fields (e.g. ``experimental``, ``deprecated``) will be the raw
    strings ``"True"`` or ``"False"``.
    """

    name: Required[str]
    """Human-readable plugin name."""

    qgisMinimumVersion: Required[str]
    """Minimum QGIS version required, e.g. ``"3.34"``."""

    qgisMaximumVersion: str
    """Maximum QGIS version supported, e.g. ``"4.99"``."""

    description: Required[str]
    """Short, plain-text description shown in the plugin manager."""

    about: Required[str]
    """Longer description; supports a subset of HTML in recent QGIS versions."""

    version: Required[str]
    """Plugin version string, e.g. ``"1.0.0"``."""

    author: Required[str]
    """Author name(s)."""

    email: Required[str]
    """Contact e-mail address for the author."""

    changelog: str
    """Free-text changelog; can be multiline (indented continuation lines)."""

    experimental: str
    """``"True"`` if the plugin is experimental; ``"False"`` otherwise."""

    deprecated: str
    """``"True"`` if the plugin is deprecated; ``"False"`` otherwise."""

    tags: str
    """Comma-separated list of tags."""

    homepage: str
    """URL to the plugin homepage."""

    repository: Required[str]
    """URL to the source code repository."""

    tracker: str
    """URL to the issue tracker."""

    icon: str
    """Relative path to the plugin icon (PNG/SVG)."""

    category: Literal["Database", "Mesh", "Raster", "Vector", "Web"]
    """Legacy top-level menu category."""

    plugin_dependencies: str
    """Comma-separated list of plugin names this plugin depends on."""

    server: str
    """``"True"`` if the plugin targets QGIS Server."""

    hasProcessingProvider: str
    """``"True"`` if the plugin registers a Processing provider."""


class QgisPluginMetadata(TypedDict):
    """
    Full dict built by iterating a :class:`ConfigParser` instance after parsing ``metadata.txt``.

    :class:`ConfigParser` always exposes a synthetic ``DEFAULT`` section and the real sections.
    For a standard plugin file the only real section is ``general``.
    """

    general: QgisPluginMetadataGeneral


DIR_PLUGIN_ROOT: Final[Path] = Path(__file__).parent.resolve()
PLG_METADATA_FILE: Final[Path] = DIR_PLUGIN_ROOT / "metadata.txt"


class _CaseSensitiveConfigParser(ConfigParser):
    """A :class:`~configparser.ConfigParser` that preserves the case of option keys."""

    @override
    def optionxform(self, optionstr: str) -> str:
        """
        Return the option name unchanged so key casing is preserved.

        :param optionstr: The raw option name.
        :return: The option name verbatim.
        """
        return optionstr


def _plugin_metadata_as_dict() -> QgisPluginMetadata:
    """
    Read plugin metadata.txt and return it as a Python dict.

    :raise FileNotFoundError: if metadata.txt is not found.
    :raise ValueError: if metadata.txt has no ``[general]`` section or is missing required fields.
    :return: dict of dicts, where each key represents a section in metadata.txt
        and its value is another dict of key-value pairs from that section.
    """
    if not PLG_METADATA_FILE.is_file():
        msg = f"Plugin metadata.txt not found at {PLG_METADATA_FILE.parent}"
        raise FileNotFoundError(msg)

    config = _CaseSensitiveConfigParser(interpolation=None)
    config.read(PLG_METADATA_FILE, encoding="UTF-8")
    raw: dict[str, dict[str, str]] = {
        section: dict(config.items(section)) for section in config.sections()
    }

    if "general" not in raw:
        msg = f"No [general] section in {PLG_METADATA_FILE}"
        raise ValueError(msg)

    if missing := QgisPluginMetadataGeneral.__required_keys__ - raw["general"].keys():
        msg = (
            f"Required fields missing from [general] section in metadata.txt: {', '.join(missing)}"
        )
        raise ValueError(msg)

    return cast("QgisPluginMetadata", raw)


# store full metadata.txt as dict into a var
__plugin_md__ = _plugin_metadata_as_dict()

__author__: str = __plugin_md__["general"]["author"]
__copyright__: str = f"2026 - {datetime.now(UTC).year}, {__author__}"
__email__: str = __plugin_md__["general"]["email"]
__icon_path__: Path | None = (
    (DIR_PLUGIN_ROOT / __plugin_md__["general"]["icon"]).resolve()
    if __plugin_md__["general"].get("icon")
    else None
)
__keywords__: list[str] = [
    t.strip() for t in __plugin_md__["general"].get("tags", "").split(",") if t.strip()
]
__license__: str = "GPLv2+"
__plugin_dependencies__: list[str] = [
    dep.strip()
    for dep in __plugin_md__["general"].get("plugin_dependencies", "").split(",")
    if dep.strip()
]
__summary__: str = "\n".join(
    dsc
    for dsc in (__plugin_md__["general"].get("description"), __plugin_md__["general"].get("about"))
    if dsc
)

__title__: str = __plugin_md__["general"]["name"]

__uri_homepage__: str | None = __plugin_md__["general"].get("homepage") or None
__uri_repository__: str = __plugin_md__["general"]["repository"]
__uri_tracker__: str | None = __plugin_md__["general"].get("tracker") or None
__uri__: str = __uri_repository__

__version__: str = __plugin_md__["general"]["version"]
__version_info__: tuple[int | str, ...] = tuple(
    int(num) if num.isdigit() else num for num in (__version__).replace("-", ".", 1).split(".")
)


if __name__ == "__main__":
    print(f"Plugin: {__title__}")
    print(f"By: {__author__}")
    print(f"Version: {__version__}")
    print(f"Description: {__summary__}")
    print(f"Repository: {__uri_repository__}")
    print(f"Icon: {__icon_path__}")

    general_md = __plugin_md__["general"]
    qgis_max_ver = (
        general_md.get("qgisMaximumVersion")
        or general_md["qgisMinimumVersion"].split(".", 1)[0] + ".99"
    )
    print(f"For: {general_md['qgisMinimumVersion']} < QGIS < {qgis_max_ver}")

    if __plugin_dependencies__:
        print(f"Depends on other plugins: {__plugin_dependencies__}")
