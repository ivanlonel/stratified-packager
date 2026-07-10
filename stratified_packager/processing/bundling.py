"""
Auxiliary file bundling: ``data/`` payloads and ``resources/`` style assets (SPEC §14).

Runs on the algorithm thread during Phase A. Whole-export local file-based raster, mesh
and point-cloud layers contribute their source file plus sidecars (or the whole
directory for directory-based sources) under ``data/<table name>/``; files referenced by
included layers' symbology land under ``resources/`` — keeping their project-relative
subtree, or ``resources/_ext/<hash8>_<name>`` for files outside the project home. Paths
inside QGIS-builtin resource locations are never bundled (they resolve on any install).
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import TYPE_CHECKING, Final, override

from qgis.core import (
    QgsApplication,
    QgsFileUtils,
    QgsProviderRegistry,
    QgsStyleEntityVisitorInterface,
)

from stratified_packager.toolbelt.zipping import iter_file_members

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from qgis.core import QgsMapLayer, QgsProcessingFeedback, QgsProject, QgsSymbol

__all__: list[str] = [
    "container_sharers",
    "data_payload_members",
    "local_source_path",
    "payload_source_arcname",
    "rewrite_asset_paths",
    "style_asset_mapping",
]

DATA_PREFIX: Final = "data"
"""Zip-root directory of layer payloads (SPEC §10)."""

RESOURCES_PREFIX: Final = "resources"
"""Zip-root directory of style assets (SPEC §10)."""

_PATH_ACCESSORS: Final[tuple[str, ...]] = ("path", "imageFilePath", "svgFilePath")
"""File-path accessors across the file-referencing symbol-layer classes (SPEC §14)."""


def local_source_path(layer: QgsMapLayer) -> Path | None:
    """
    Return the layer's local source path, when its provider exposes one.

    Also the payload-classification test: a raster/mesh/point-cloud layer is a ``data/``
    payload (SPEC §14) iff this returns a path.

    :param layer: Any map layer.
    :return: The decoded ``path`` component, or :data:`None` for non-file sources.
    """
    registry = QgsProviderRegistry.instance()
    if registry is None:
        return None
    decoded = registry.decodeUri(layer.providerType(), layer.source())
    raw = decoded.get("path")
    if not raw:
        return None
    candidate = Path(str(raw))
    return candidate if candidate.exists() else None


def data_payload_members(
    layer: QgsMapLayer, table: str, feedback: QgsProcessingFeedback
) -> list[tuple[Path, str]]:
    """
    Collect one whole-export layer's ``data/`` zip members (SPEC §14).

    File sources contribute the file plus its sidecars
    (:meth:`~qgis.core.QgsFileUtils.sidecarFilesForPath`); directory-based sources
    (e.g. ESRI grid) are copied whole.

    :param layer: The raster/mesh/point-cloud layer.
    :param table: The layer's table name (the ``data/<table>/`` subdirectory).
    :param feedback: Execution feedback channel.
    :return: ``(source file, arcname)`` pairs; empty when the source is not a local
        file (such layers ride only in the embedded project).
    """
    source = local_source_path(layer)
    if source is None:
        feedback.pushDebugInfo(f"bundling[{layer.name()}]: no local file source")
        return []
    if source.is_dir():
        return list(iter_file_members(source, f"{DATA_PREFIX}/{table}/{source.name}"))
    members = [(source, f"{DATA_PREFIX}/{table}/{source.name}")]
    for sidecar in sorted(QgsFileUtils.sidecarFilesForPath(str(source))):
        sidecar_path = Path(sidecar)
        if sidecar_path.is_file():
            members.append((sidecar_path, f"{DATA_PREFIX}/{table}/{sidecar_path.name}"))
    return members


def payload_source_arcname(layer: QgsMapLayer, table: str) -> str:
    """
    Return the zip-internal path an embedded project re-points this payload layer at (§13).

    For a plain file source this is the copied main file's arcname; for a directory-based
    source (e.g. an ESRI grid) it is the copied *directory* — never one of the files inside
    it, which GDAL may not open as the dataset.

    :param layer: The raster/mesh/point-cloud layer.
    :param table: The layer's table name (the ``data/<table>/`` subdirectory).
    :return: The ``data/<table>/<source name>`` arcname, or empty for non-file sources.
    """
    source = local_source_path(layer)
    return f"{DATA_PREFIX}/{table}/{source.name}" if source is not None else ""


def container_sharers(layer: QgsMapLayer, project: QgsProject) -> list[str]:
    """
    Name the other project layers backed by the same container file (SPEC §14 caveat).

    Copying a container (e.g. a GeoPackage) under ``data/`` drags every layer it holds;
    the caller warns when this list is non-empty.

    :param layer: The whole-export layer about to be copied.
    :param project: The project to scan.
    :return: Names of other layers sharing the source file, sorted.
    """
    source = local_source_path(layer)
    if source is None:
        return []
    own = os.path.normcase(str(source.resolve()))
    sharers: list[str] = []
    for other in project.mapLayers().values():
        if other.id() == layer.id():
            continue
        other_path = local_source_path(other)
        if other_path is not None and os.path.normcase(str(other_path.resolve())) == own:
            sharers.append(other.name())
    return sorted(sharers)


class _SymbolPathCollector(QgsStyleEntityVisitorInterface):
    """Collects file paths referenced by a layer's style entities (SPEC §14)."""

    def __init__(self) -> None:
        """Initialize with an empty path set."""
        super().__init__()
        self.paths: set[str] = set()

    @override
    def visit(self, entity: QgsStyleEntityVisitorInterface.StyleLeaf) -> bool:
        """
        Visit one style entity, harvesting symbol-layer file paths.

        :param entity: The visited style leaf.
        :return: :data:`True` to continue visiting.
        """
        inner = entity.entity
        symbol = getattr(inner, "symbol", None)
        if callable(symbol):
            with_symbol = symbol()
            if with_symbol is not None:
                self._walk_symbol(with_symbol)
        for accessor in ("textFormat", "settings"):
            candidate = getattr(inner, accessor, None)
            if callable(candidate):
                self._harvest_text_format(candidate())
        return True

    def _walk_symbol(self, symbol: QgsSymbol) -> None:
        """
        Recurse through a symbol's layers (and sub-symbols), harvesting paths.

        :param symbol: The symbol to walk.
        """
        for symbol_layer in symbol.symbolLayers():
            for accessor in _PATH_ACCESSORS:
                getter = getattr(symbol_layer, accessor, None)
                if callable(getter):
                    value = getter()
                    if isinstance(value, str) and value:
                        self.paths.add(value)
            sub = symbol_layer.subSymbol()
            if sub is not None:
                self._walk_symbol(sub)

    def _harvest_text_format(self, owner: object) -> None:
        """
        Harvest the background SVG of a text format (or of label settings).

        :param owner: A ``QgsTextFormat`` or ``QgsPalLayerSettings``-like object.
        """
        text_format = owner
        format_getter = getattr(owner, "format", None)
        if callable(format_getter):
            text_format = format_getter()
        background_getter = getattr(text_format, "background", None)
        if not callable(background_getter):
            return
        background = background_getter()
        svg = background.svgFile() if background is not None else ""
        if svg:
            self.paths.add(svg)


def style_asset_mapping(
    layers: Iterable[QgsMapLayer],
    project_home: Path | None,
    feedback: QgsProcessingFeedback,
) -> dict[str, str]:
    """
    Map every bundleable style-asset path to its ``resources/`` arcname (SPEC §14).

    Files under the project home keep their project-relative subtree; foreign files
    land in ``resources/_ext/<hash8>_<name>`` (hash of the absolute source path).
    Paths under the QGIS-builtin resource locations
    (:meth:`~qgis.core.QgsApplication.svgPaths` and the application prefix) are skipped.

    :param layers: The included layers.
    :param project_home: The project home directory (absolute), or :data:`None`.
    :param feedback: Execution feedback channel.
    :return: ``original path -> arcname`` for every existing, non-builtin asset.
    """
    builtin_roots = [
        os.path.normcase(str(Path(root).resolve()))
        for root in (*QgsApplication.svgPaths(), QgsApplication.prefixPath())
        if root
    ]
    home = os.path.normcase(str(project_home.resolve())) if project_home is not None else None
    mapping: dict[str, str] = {}
    for layer in layers:
        collector = _SymbolPathCollector()
        layer.accept(collector)
        for raw in sorted(collector.paths):
            if raw in mapping or raw.startswith(("base64:", ":")):
                continue
            candidate = Path(raw)
            if not candidate.is_file():
                continue
            resolved = os.path.normcase(str(candidate.resolve()))
            if any(resolved.startswith(root) for root in builtin_roots):
                continue
            if home is not None and resolved.startswith(home + os.sep):
                relative = Path(resolved[len(home) + 1 :]).as_posix()
                mapping[raw] = f"{RESOURCES_PREFIX}/{relative}"
            else:
                digest = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:8]
                mapping[raw] = f"{RESOURCES_PREFIX}/_ext/{digest}_{candidate.name}"
            feedback.pushDebugInfo(f"bundling asset: {raw} -> {mapping[raw]}")
    return mapping


def rewrite_asset_paths(document: str, mapping: Mapping[str, str], to_root: str) -> str:
    """
    Rewrite bundled asset paths inside a QML (or project XML) document (SPEC §14).

    Each original path is replaced by its bundled location, made relative to the
    document's directory inside the zip via *to_root* (empty at the zip root, ``../``
    per directory level below it). Both the original spelling and its slash-normalized
    variant are replaced.

    :param document: The QML/XML text.
    :param mapping: ``original path -> arcname`` from :func:`style_asset_mapping`.
    :param to_root: Prefix walking from the document's directory up to the zip root.
    :return: The rewritten document.
    """
    rewritten = document
    for original, arcname in mapping.items():
        target = f"{to_root}{arcname}"
        rewritten = rewritten.replace(original, target)
        # Normalize backslashes directly, not via Path.as_posix(), which is a no-op on POSIX
        # for a Windows-style path — so both spellings are rewritten regardless of the host OS.
        posix = original.replace("\\", "/")
        if posix != original:
            rewritten = rewritten.replace(posix, target)
    return rewritten
