"""
Tests for :mod:`stratified_packager.identity`.

Confirms :data:`~stratified_packager.identity.PLUGIN_SLUG` is the title slug (the value
``settings.py`` previously derived inline) and that it is a usable identifier slug. Requires a
running QGIS because :func:`~stratified_packager.toolbelt.i18n.slugify` calls
:meth:`~qgis.core.QgsStringUtils.unaccent`.
"""

from __future__ import annotations

import re

import pytest

pytest.importorskip("qgis", reason="PLUGIN_SLUG is derived via QgsStringUtils.unaccent.")

# Imported only after the importorskip guard above confirms QGIS is available.
from stratified_packager.__about__ import __title__
from stratified_packager.identity import PLUGIN_SLUG, plugin_icon
from stratified_packager.toolbelt.i18n import slugify

pytestmark = pytest.mark.qgis
"""Marks the whole module as requiring a QGIS runtime."""


def test_plugin_slug_is_the_title_slug() -> None:
    """PLUGIN_SLUG is exactly the slug of the plugin title."""
    assert slugify(__title__) == PLUGIN_SLUG


def test_plugin_slug_is_a_nonempty_lowercase_slug() -> None:
    """The slug is non-empty and only contains underscores, digits and lower-case ascii letters."""
    assert PLUGIN_SLUG
    assert re.search(r"[^_0-9a-z]", PLUGIN_SLUG) is None
    assert re.match(r"\d", PLUGIN_SLUG) is None  # doesn't start with a digit


def test_plugin_icon_carries_the_png_resolutions() -> None:
    """The icon loads the bundled PNGs (bitmap path), not the on-the-fly SVG engine."""
    icon = plugin_icon()
    assert not icon.isNull()
    sizes = {size.width() for size in icon.availableSizes()}
    # availableSizes() is populated from raster entries only; an SVG-backed icon reports none.
    assert {16, 32, 256} <= sizes


def test_plugin_icon_is_cached() -> None:
    """Repeated calls return the same cached, immutable icon instance."""
    assert plugin_icon() is plugin_icon()
