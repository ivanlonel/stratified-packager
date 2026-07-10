"""Configuration for project documentation using Sphinx."""

from __future__ import annotations

import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any, Final

import keepachangelog
from sphinx.ext.autodoc.mock import _MockModule  # type: ignore[attr-defined]  # not re-exported
from sphinx.ext.intersphinx import InventoryAdapter
from sphinx.ext.intersphinx import missing_reference as intersphinx_missing_reference

if TYPE_CHECKING:
    from collections.abc import Iterable

    from docutils.nodes import TextElement, reference
    from sphinx.addnodes import pending_xref
    from sphinx.application import Sphinx
    from sphinx.environment import BuildEnvironment

# move into project package
sys.path.insert(0, f"{Path(__file__).parent.parent.resolve()}")

# Package
from stratified_packager import __about__

# -- Logging setup --
logger: logging.Logger = logging.getLogger(__name__)

# -- Project information --
changes: dict[str, Any] = keepachangelog.to_dict("../CHANGELOG.md")
latest_version: str = next(v for v in changes if v not in ("Unreleased", "version_tag"))

author: str = __about__.__author__
copyright: str = __about__.__copyright__  # noqa: A001  # Sphinx expects this exact name
description: str = __about__.__summary__
official_repository_id: int | None = None
project: str = __about__.__title__
release: str = latest_version  # latest version from CHANGELOG.md
version: str = __about__.__version__  # defined in metadata.txt

# -- General configuration ---------------------------------------------------

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions: list[str] = [
    # Sphinx included
    "sphinx.ext.autodoc",
    "sphinx.ext.autosectionlabel",
    "sphinx.ext.autosummary",
    "sphinx.ext.extlinks",
    "sphinx.ext.githubpages",
    "sphinx.ext.intersphinx",
    "sphinx.ext.viewcode",
    # 3rd party
    "myst_parser",
    "sphinx_autodoc_typehints",  # load after sphinx.ext.autodoc so it can post-process hints
    "sphinx_copybutton",
    "sphinx_rtd_theme",
]


# The suffix(es) of source filenames.
# You can specify multiple suffix as a list of string:
source_suffix: dict[str, str] = {".md": "markdown", ".rst": "restructuredtext"}
autosectionlabel_prefix_document: bool = True
# The master toctree document.
master_doc: str = "index"


# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This pattern also affects html_static_path and html_extra_path .
exclude_patterns: list[str] = [
    "_build",
    ".venv",
    "Thumbs.db",
    ".DS_Store",
    "_output",
    "ext_libs",
    "tests",
    "demo",
]

# The name of the Pygments (syntax highlighting) style to use.
pygments_style: str = "sphinx"


# -- Options for HTML output -------------------------------------------------

# -- Theme

html_favicon: str = str(__about__.__icon_path__)
html_logo: str = str(__about__.__icon_path__)
html_static_path = ["_static"]
html_theme = "sphinx_rtd_theme"
html_theme_options: dict[str, bool | int | str] = {
    "logo_only": False,
    "prev_next_buttons_location": "both",
    "style_external_links": True,
    "style_nav_header_background": "SteelBlue",
    # Toc options
    "collapse_navigation": True,
    "includehidden": True,
    "navigation_depth": 4,
    "sticky_navigation": False,
    "titles_only": False,
}

# -- EXTENSIONS --------------------------------------------------------

# autodoc + sphinx-autodoc-typehints + autosummary render the API reference from the package.
# The package imports qgis (incl. qgis.PyQt / qgis.gui), absent from the docs environment, so
# mock it (autodoc_mock_imports below); autodoc only imports the modules to read docstrings.
# gui/wdg_*.py is the awkward case: it does `FORM_CLASS, _ = uic.loadUiType(...)` at
# import and subclasses FORM_CLASS. Seed real namespace packages for qgis / qgis.PyQt with a
# uic.loadUiType stub returning a 2-tuple whose first item is a class with a real __module__
# (Sphinx 9.1 autodoc reads __module__ off base classes). All other qgis.* submodules stay
# mocked. Attributes (incl. __path__) go through __dict__ so static type checkers don't object.
_qgis = sys.modules.setdefault("qgis", ModuleType("qgis"))
_qgis_pyqt = sys.modules.setdefault("qgis.PyQt", ModuleType("qgis.PyQt"))
_qgis_uic = sys.modules.setdefault("qgis.PyQt.uic", ModuleType("qgis.PyQt.uic"))
# Empty __path__ marks qgis / qgis.PyQt as packages so qgis.core, qgis.PyQt.QtCore, … reach
# the autodoc mock finder instead of raising "is not a package".
_qgis.__dict__["__path__"] = []
_qgis_pyqt.__dict__["__path__"] = []
_qgis.__dict__["PyQt"] = _qgis_pyqt
_qgis_pyqt.__dict__["uic"] = _qgis_uic
_qgis_uic.__dict__["loadUiType"] = lambda *_a, **_k: (
    type("FormClass", (), {"__module__": "qgis.PyQt.uic"}),
    object,
)
# qgis.core is otherwise autodoc-mocked, but identity.py runs slugify(__title__) at import,
# which calls QgsStringUtils.unaccent — a bare mock returns a non-str that breaks the
# unicodedata.normalize() inside it. Use autodoc's module mock as qgis.core (its names carry
# the real dotted path, so a base class renders as qgis.core.QgsProcessingAlgorithm rather
# than a bare MockObject xref) but inject a real passthrough QgsStringUtils.unaccent.
_qgis_core = _MockModule("qgis.core")
_qgis_core.__dict__["QgsStringUtils"] = type(
    "QgsStringUtils", (), {"unaccent": staticmethod(lambda s, /, *_a, **_k: s)}
)
sys.modules["qgis.core"] = _qgis_core
_qgis.__dict__["core"] = _qgis_core

# Add type info even for params without an explicit :param: entry
always_document_param_types: bool = True

autodoc_member_order: str = "groupwise"
autodoc_mock_imports: list[str] = ["qgis", "osgeo"]
autodoc_default_options: dict[str, bool | str] = {
    "members": True,
    "private-members": True,
    "undoc-members": True,
    "special-members": "__init__",
    "ignore-module-all": True,
}

autosummary_generate: bool = True

# Build in nitpicky mode so unresolved cross-references surface as warnings.
# Bare Qt/QGIS type names (autodoc renders them without a module from mocked annotations
# and base classes) and a couple of stdlib names are relinked onto the intersphinx
# inventories by ``resolve_bare_type_xref`` below, so they no longer need entries here.
# What remains is the irreducible set that has no documented target to point at.
nitpicky: bool = True
nitpick_ignore: list[tuple[str, str]] = [
    # Unbound TypeVars from generic signatures — no documented object to link to.
    ("py:class", "T"),
    ("py:class", "E"),
    # ``pyqtSignal`` annotation type: PyQt-only, registered under Riverbank's ``sip`` domain
    # (unreachable from ``py`` refs) and absent from the PySide6 inventory.
    ("py:func", "pyqtSignal"),
    # Synthetic class returned by the uic.loadUiType stub (see _qgis_uic above).
    ("py:class", "qgis.PyQt.uic.FormClass"),
]

# Configuration for intersphinx (refer to others docs).
intersphinx_mapping: dict[str, tuple[str, None]] = {
    "gdal": ("https://gdal.org/en/stable/", None),
    "PyQt6": ("https://www.riverbankcomputing.com/static/Docs/PyQt6", None),
    "PySide6": ("https://doc.qt.io/qtforpython-6/", None),
    "python": ("https://docs.python.org/3/", None),
    "qgis": ("https://qgis.org/pyqgis/master/", None),
}

# sphinx-copybutton
# https://sphinx-copybutton.readthedocs.io/
copybutton_exclude = ".linenos, .go, .gp"

# MyST Parser
myst_enable_extensions: list[str] = [
    "amsmath",
    "colon_fence",
    "deflist",
    "dollarmath",
    "html_image",
    "linkify",
    "replacements",
    "smartquotes",
    "substitution",
]

myst_substitutions: dict[str, str] = {
    "author": author,
    "date_update": datetime.now(UTC).strftime("%d %B %Y"),
    "description": description,
    "qgis_version_max": __about__.__plugin_md__["general"].get("qgisMaximumVersion", ""),
    "qgis_version_min": __about__.__plugin_md__["general"]["qgisMinimumVersion"],
    "repo_url": __about__.__uri__,
    "title": project,
    "version": version,
    "release_version": release,
}

myst_url_scheme: tuple[str, str, str] = ("http", "https", "mailto")

# -- Cross-reference remapping for the qgis.PyQt shim ------------------------

PYQT_SHIM_PREFIX: Final[str] = "qgis.PyQt."
"""Dotted-path prefix under which QGIS re-exports the active Qt binding."""


def resolve_qgis_pyqt_xref(
    app: Sphinx,
    env: BuildEnvironment,
    node: pending_xref,
    contnode: TextElement,
) -> reference | None:
    """
    Resolve ``qgis.PyQt.*`` Python cross-references against external Qt inventories.

    QGIS's :mod:`qgis.PyQt` shim re-exports the active Qt binding, so autodoc and
    :mod:`sphinx_autodoc_typehints` emit references such as :class:`qgis.PyQt.QtGui.QColor`
    that match no inventory. Riverbank's PyQt docs further register the Qt classes under
    a custom ``sip`` domain that ``py`` cross-references cannot reach. Retarget each shim
    path onto the Qt for Python (PySide6) inventory first — its classes live in the
    standard ``py`` domain — then fall back to PyQt6 for binding-specific callables such
    as :func:`~qgis.PyQt.QtCore.pyqtSignal`.

    :param app: The running Sphinx application.
    :param env: The current build environment.
    :param node: The unresolved Python-domain cross-reference.
    :param contnode: The reference's content node, forwarded to intersphinx.
    :return: The resolved reference node, or :obj:`None` to leave it unresolved.
    """
    target: str = node.get("reftarget", "")
    if node.get("refdomain") != "py" or not target.startswith(PYQT_SHIM_PREFIX):
        return None
    suffix = target.removeprefix(PYQT_SHIM_PREFIX)
    original = node["reftarget"]
    try:
        for inventory_prefix in ("PySide6.", "PyQt6."):
            node["reftarget"] = f"{inventory_prefix}{suffix}"
            resolved = intersphinx_missing_reference(app, env, node, contnode)
            if resolved is not None:
                return resolved
    finally:
        node["reftarget"] = original  # restore so a failed lookup warns on the real name
    return None


# -- Relink bare Qt/QGIS type names onto the intersphinx inventories ----------
#
# autodoc and sphinx_autodoc_typehints emit the short name (``QObject``, ``QgsFeature``,
# ``Qgis.LayerType``) that mocked annotations and base classes carry, but the inventories
# key each object under its full dotted path (``PySide6.QtCore.QObject`` etc.). The py
# domain only matches fully-qualified names, so those refs would go unresolved and need a
# ``nitpick_ignore`` entry each. ``resolve_bare_type_xref`` looks the short name up by
# dotted-suffix and retargets it, so it links instead.

_XREF_ALIASES: Final[dict[str, str]] = {
    # Bare stdlib name autodoc renders without a resolvable module.
    "Path": "pathlib.Path",
    # Private submodule path autodoc reads off ``Future.__module__``.
    "concurrent.futures._base.Future": "concurrent.futures.Future",
}
"""Fixed retargets for names autodoc renders bare or via a private submodule."""

_XREF_PRIORITY: Final[tuple[str, ...]] = ("qgis.", "PySide6.", "PyQt6.")
"""Module-prefix preference, best-first, when a bare name matches several inventories."""


def best_inventory_match(target: str, candidates: Iterable[str]) -> str | None:
    """
    Return the best fully-qualified name in *candidates* whose dotted suffix is *target*.

    A candidate matches when it equals *target* or ends with ``"." + target``, so a bare
    ``QObject`` matches ``PySide6.QtCore.QObject`` and a nested ``Qgis.LayerType`` matches
    ``qgis.core.Qgis.LayerType``. Two rounds of disambiguation run over the matches:
    ``_``-prefixed private aliases (the PyQGIS inventory lists every class twice, e.g.
    ``qgis._gui.QgsMessageBar``) are dropped, then :data:`_XREF_PRIORITY` picks a source
    when a name lives in several (every Qt class is in both the PySide6 and PyQt6
    inventories). Only a tie *within* the winning source — genuine ambiguity — returns
    :obj:`None`, leaving the reference to warn rather than linking it arbitrarily.

    :param target: The bare or partially-qualified cross-reference target.
    :param candidates: Fully-qualified object names from the merged inventory.
    :return: The chosen fully-qualified name, or :obj:`None`.
    """
    suffix = f".{target}"
    matches = {name for name in candidates if name == target or name.endswith(suffix)}
    matches = {
        name for name in matches if not any(seg.startswith("_") for seg in name.split("."))
    } or matches
    for prefix in _XREF_PRIORITY:
        if tier := {name for name in matches if name.startswith(prefix)}:
            return next(iter(tier)) if len(tier) == 1 else None
    return next(iter(matches)) if len(matches) == 1 else None


def _search_inventories(env: BuildEnvironment, target: str) -> str | None:
    """
    Find *target*'s fully-qualified name in the merged intersphinx inventory.

    Uses :attr:`~sphinx.ext.intersphinx.InventoryAdapter.main_inventory` — the same merged
    view intersphinx's own resolver reads — rather than the per-project ``named_inventory``,
    which is not reliably populated during a cold parallel build's resolve phase.

    :param env: The current build environment (carries the intersphinx inventories).
    :param target: The bare or partially-qualified cross-reference target.
    :return: The chosen retarget name, or :obj:`None` when nothing matches unambiguously.
    """
    inventory = InventoryAdapter(env).main_inventory
    names = {name for by_type in inventory.values() for name in by_type}
    return best_inventory_match(target, names)


def resolve_bare_type_xref(
    app: Sphinx,
    env: BuildEnvironment,
    node: pending_xref,
    contnode: TextElement,
) -> reference | None:
    """
    Relink a bare Qt/QGIS (or aliased stdlib) Python cross-reference onto an inventory.

    Applies the :data:`_XREF_ALIASES` fixups, then — for names whose leading component starts
    with ``Q`` (every Qt/QGIS type, which also excludes the ``T``/``E`` TypeVars) — searches
    the inventories by dotted-suffix. The ``qgis.PyQt.*`` shim is left to
    :func:`resolve_qgis_pyqt_xref`.

    :param app: The running Sphinx application.
    :param env: The current build environment.
    :param node: The unresolved Python-domain cross-reference.
    :param contnode: The reference's content node, forwarded to intersphinx.
    :return: The resolved reference node, or :obj:`None` to leave it unresolved.
    """
    target: str = node.get("reftarget", "")
    if node.get("refdomain") != "py" or target.startswith(PYQT_SHIM_PREFIX):
        return None

    retarget = _XREF_ALIASES.get(target)
    if retarget is None and target.split(".", 1)[0].startswith("Q"):
        retarget = _search_inventories(env, target)
    if retarget is None:
        return None

    node["reftarget"] = retarget
    try:
        return intersphinx_missing_reference(app, env, node, contnode)
    finally:
        node["reftarget"] = target  # restore so a failed lookup warns on the real name


def setup(app: Sphinx) -> None:
    """
    Register the cross-reference resolvers and the custom CSS file.

    :param app: The running Sphinx application.
    """
    # priority 600 > intersphinx's default 500, so these run only for targets
    # intersphinx itself could not resolve.
    app.connect("missing-reference", resolve_qgis_pyqt_xref, priority=600)
    app.connect("missing-reference", resolve_bare_type_xref, priority=600)

    app.add_css_file("custom.css")
