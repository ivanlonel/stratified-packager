"""
Plugin identity derived at import.

Holds :data:`PLUGIN_SLUG`, the slug of the plugin title. It lives here — not in
``__about__`` — because deriving it needs QGIS
(:func:`~.toolbelt.i18n.slugify` calls :meth:`~qgis.core.QgsStringUtils.unaccent`),
whereas ``__about__`` must stay stdlib-only so ``setuptools`` can read ``__version__`` at
build time without QGIS. Importing neither :mod:`stratified_packager.settings` nor
:mod:`~.processing.params`, this module is the package-wide home for the slug and keeps
those two free of a circular import.
"""

from functools import cache
from typing import Final

from qgis.PyQt.QtGui import QIcon

from .__about__ import DIR_PLUGIN_ROOT, __title__
from .toolbelt.i18n import slugify

PLUGIN_SLUG: Final = slugify(__title__)
"""
Slug of the plugin title; the ``plugins/<slug>`` settings scope and the ``<slug>_*``
variable/object-name prefix.
"""


@cache
def plugin_icon() -> QIcon:
    """
    Return the plugin icon as a multi-resolution :class:`~qgis.PyQt.QtGui.QIcon`.

    Adds every PNG under ``resources/images/png`` so Qt selects the sharpest bitmap for
    each requested size instead of rasterizing ``icon.svg`` on the fly. The result is
    cached: the icon is immutable and safe to share across every caller.

    :return: the plugin icon carrying all available PNG resolutions.
    """
    icon = QIcon()
    for png in sorted((DIR_PLUGIN_ROOT / "resources/images/png").glob("*.png")):
        icon.addFile(str(png))
    return icon
