"""
Internationalization helpers: Qt translation support and accent-folding slug creation.

Provides :class:`Translatable`, a :class:`~typing.Protocol` giving non-``QObject`` classes a
``tr`` classmethod backed by :meth:`~qgis.PyQt.QtCore.QCoreApplication.translate`, and
:func:`slugify`, which folds accents via :meth:`qgis.core.QgsStringUtils.unaccent` before reducing
a string to a lower-case identifier slug.
"""

from __future__ import annotations

from typing import Protocol

from qgis.core import QgsStringUtils
from qgis.PyQt.QtCore import QCoreApplication

from .utils import sanitize_identifier_name

__all__: list[str] = ["Translatable", "slugify"]


class Translatable(Protocol):
    """Protocol for non-QObject classes that support translation using Qt translation API."""

    @classmethod
    def tr(
        cls,
        sourceText: str,  # noqa: N803  # Just to keep the same name as in QObject.tr
        disambiguation: str | None = None,
        n: int = -1,
    ) -> str:
        """
        Get the translation for a string using Qt translation API.

        :param sourceText: String for translation.
        :param disambiguation: Identifying string for when the same text is used
            in different roles within the context.
        :param n: Number to support plural forms.
            https://doc.qt.io/qt-6/i18n-source-translation.html#handle-plural-forms
        :return: Translated version of the source text.
        """
        return QCoreApplication.translate(cls.__name__, sourceText, disambiguation, n)


def slugify(txt: str, /) -> str:
    """
    Turn input string into a valid lower-case slug by removing non-alphanumerics after unaccenting.

    :param txt: Original string.
    :return: A slug created by calling :meth:`qgis.core.QgsStringUtils.unaccent` on the
        original string (QGIS 4.0+ only), replacing runs of remaining non-alphanumeric
        characters by ``_`` and lower-casing the result. If the original string starts
        with a numeric digit, a ``_`` is inserted at the beginning.
    """
    try:
        unaccented = QgsStringUtils.unaccent(txt)  # QGIS 4.0+
    except AttributeError:
        unaccented = txt
    return sanitize_identifier_name(unaccented).lower()
