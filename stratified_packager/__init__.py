"""Stratified Packager QGIS Plugin."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from qgis.gui import QgisInterface

    from .main import StratifiedPackager


def classFactory(iface: QgisInterface) -> StratifiedPackager:  # noqa: N802
    """
    Load the plugin class.

    :param iface: A QGIS interface instance.
    :return: An instance of the plugin class.
    """
    from .__about__ import __title__, __version__  # noqa: PLC0415
    from .settings import StratifiedPackagerSettings  # noqa: PLC0415
    from .toolbelt.logging import QgisContextFilter, QgisLoggerWrapper  # noqa: PLC0415

    # Set up root logger before importing any module that calls QgisContextFilter.get_logger().
    # The level tracks the debug_mode setting (DEBUG when on, INFO otherwise).
    log = QgisLoggerWrapper.setup(
        __name__,
        level=logging.DEBUG if StratifiedPackagerSettings().debug_mode else logging.INFO,
        iface=iface,
        tag=__title__,
        filters=(QgisContextFilter(static_fields={"plugin_version": __version__}, iface=iface),),
    )
    log.debug("Initializing %s plugin: version %s", __title__, __version__)

    from .main import StratifiedPackager  # noqa: PLC0415

    return StratifiedPackager(iface)
