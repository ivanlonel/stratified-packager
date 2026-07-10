"""
Plugin-agnostic zip assembly, atomic publishing and archive-path validation helpers.

DO NOT import from the ``qgis`` package in this module (it must stay usable from worker
threads and ``scripts/``); standard library only.

Archive paths handled here are **relative, slash-separated** paths inside a zip (or below
an output directory). Validation is strict and never sanitizes: callers that build paths
from user expressions are expected to surface the reported violation instead of silently
rewriting the path.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import zipfile
from collections import defaultdict
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import IO, TYPE_CHECKING, Final

from .utils import (
    _ILLEGAL_FILENAME_CHARS,
    _MAX_FILENAME_LENGTH,
    _WINDOWS_RESERVED_NAMES,
    OperationAbortedError,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator

__all__: list[str] = [
    "OperationAbortedError",
    "build_zip",
    "case_insensitive_collisions",
    "filename_component_error",
    "iter_file_members",
    "publish_atomic",
    "remove_stale_parts",
    "sha256_sidecar",
    "split_archive_path",
]

PART_SUFFIX: Final = ".part"
"""Suffix of in-progress zip files; consumers only ever see fully published zips."""

_COPY_CHUNK_SIZE: Final = 1 << 22
"""Chunk size (4 MiB) for abortable file copies."""

_DRIVE_PREFIX: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z]:")
"""Windows drive-letter prefix marking an absolute (or drive-relative) path."""


def _check_abort(abort: Callable[[], bool] | None, token: str) -> None:
    """
    Raise when the abort callback signals cancellation.

    :param abort: Optional abort callback.
    :param token: Identifier carried in the exception (arcname or destination).
    :raise OperationAbortedError: If *abort* is set and returned :data:`True`.
    """
    if abort is not None and abort():
        raise OperationAbortedError(token)


def _copy_stream(
    src: IO[bytes], dst: IO[bytes], abort: Callable[[], bool] | None, token: str
) -> None:
    """
    Copy *src* into *dst* in chunks, polling *abort* between chunks.

    :param src: Readable binary stream.
    :param dst: Writable binary stream.
    :param abort: Optional abort callback polled between chunks.
    :param token: Identifier carried in the abort exception.
    :raise OperationAbortedError: If *abort* returned :data:`True`.
    """
    while chunk := src.read(_COPY_CHUNK_SIZE):
        _check_abort(abort, token)
        dst.write(chunk)


# ---------------------------------------------------------------------------
# Archive-path validation
# ---------------------------------------------------------------------------


def filename_component_error(component: str, /) -> str | None:
    """
    Check one path component against the strict filename rules.

    The rules mirror :func:`.utils.sanitize_filename` (illegal characters, reserved
    Windows device names, trailing dots/spaces, length) but **validate instead of
    fixing** — a violation is reported, never repaired.

    :param component: A single path component (no separators).
    :return: A human-readable violation description, or :data:`None` when valid.
    """
    if not component or component in {".", ".."}:
        return f"component {component!r} is empty or a relative marker"
    if match := _ILLEGAL_FILENAME_CHARS.search(component):
        return f"illegal character {match.group()!r} in component {component!r}"
    if component != component.strip(" ") or component.endswith("."):
        return f"component {component!r} has leading/trailing spaces or a trailing dot"
    if component.partition(".")[0].upper() in _WINDOWS_RESERVED_NAMES:
        return f"component {component!r} is a reserved Windows device name"
    if len(component) > _MAX_FILENAME_LENGTH:
        return f"component of {len(component)} characters exceeds {_MAX_FILENAME_LENGTH}"
    return None


def split_archive_path(path: str, /) -> tuple[str, ...]:
    r"""
    Validate a relative archive path and split it into its components.

    Accepts ``/`` and ``\`` as separators. Rejects absolute paths (POSIX or Windows,
    including drive-letter and UNC forms), ``.``/``..`` components, and any component
    violating :func:`filename_component_error`.

    :param path: The relative path to validate (e.g. an evaluated gpkg or zip path).
    :return: The validated components, in order.
    :raise ValueError: If the path is empty, absolute, escapes the root, or contains
        an invalid component; the message names the violation.
    """
    if not path or not path.strip():
        return _raise_path_error(path, "path is empty")
    if (
        path.startswith(("/", "\\"))
        or _DRIVE_PREFIX.match(path)
        or PureWindowsPath(path).is_absolute()
        or PurePosixPath(path).is_absolute()
    ):
        return _raise_path_error(path, "absolute paths are not allowed")
    components = tuple(part for part in re.split(r"[/\\]", path))
    for component in components:
        if reason := filename_component_error(component):
            return _raise_path_error(path, reason)
    return components


def _raise_path_error(path: str, reason: str) -> tuple[str, ...]:
    """
    Raise the :exc:`ValueError` for an invalid archive path.

    :param path: The offending path, quoted in the message.
    :param reason: The violation description.
    :return: Never returns; the annotation only satisfies callers' ``return`` idiom.
    :raise ValueError: Always.
    """
    msg = f"invalid archive path {path!r}: {reason}"
    raise ValueError(msg)


def case_insensitive_collisions(paths: Iterable[str], /) -> list[list[str]]:
    """
    Group distinct paths that collide case-insensitively (the Windows filesystem rule).

    :param paths: Slash-separated relative paths (duplicates are ignored).
    :return: One group per collision, each listing the distinct colliding spellings;
        empty when all paths are unique case-insensitively.
    """
    groups: defaultdict[str, set[str]] = defaultdict(set)
    for path in paths:
        groups[path.casefold()].add(path)
    return [sorted(group) for _key, group in sorted(groups.items()) if len(group) > 1]


# ---------------------------------------------------------------------------
# Zip assembly
# ---------------------------------------------------------------------------


def iter_file_members(root: Path, arc_prefix: str = "", /) -> Iterator[tuple[Path, str]]:
    """
    Yield ``(source file, arcname)`` pairs for every file below *root*, recursively.

    Directory entries themselves are not yielded (zip directories materialize from
    member paths). Arcnames are slash-separated and prefixed with *arc_prefix*.

    :param root: Directory to walk.
    :param arc_prefix: Prefix for every arcname (no trailing slash needed).
    :yield: ``(path, arcname)`` pairs, sorted for determinism.
    """
    prefix = f"{arc_prefix.rstrip('/')}/" if arc_prefix else ""
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        yield path, f"{prefix}{path.relative_to(root).as_posix()}"


def build_zip(
    zip_path: Path,
    members: Iterable[tuple[Path, str]],
    *,
    compression_level: int,
    abort: Callable[[], bool] | None = None,
) -> Path:
    """
    Assemble a zip from ``(source file, arcname)`` members.

    Compression is Deflate at *compression_level*, except level ``0`` which stores
    entries uncompressed (``ZIP_STORED``). Zip64 extensions are enabled, so archives
    and members beyond 4 GiB are supported. Sources are streamed in chunks, so large
    members do not load into memory.

    :param zip_path: Destination zip file path (parent directory must exist; an
        existing file is overwritten).
    :param members: ``(source file, arcname)`` pairs; arcnames use ``/`` separators.
    :param compression_level: ``0`` to ``9``; ``0`` selects ``ZIP_STORED``.
    :param abort: Optional callback polled before every member and between copy
        chunks; returning :data:`True` aborts the build.
    :return: *zip_path*.
    :raise OperationAbortedError: If *abort* returned :data:`True`; the partial file is
        removed before raising.
    """
    compression = zipfile.ZIP_STORED if compression_level == 0 else zipfile.ZIP_DEFLATED
    try:
        with zipfile.ZipFile(
            zip_path,
            "w",
            compression=compression,
            allowZip64=True,
            compresslevel=compression_level or None,
        ) as archive:
            _write_members(archive, members, compression, compression_level, abort)
    except OperationAbortedError:
        zip_path.unlink(missing_ok=True)
        raise
    return zip_path


def _write_members(
    archive: zipfile.ZipFile,
    members: Iterable[tuple[Path, str]],
    compression: int,
    compression_level: int,
    abort: Callable[[], bool] | None,
) -> None:
    """
    Stream every member into the open *archive*.

    :param archive: Archive open for writing.
    :param members: ``(source file, arcname)`` pairs.
    :param compression: The archive-level compression constant.
    :param compression_level: The Deflate level (``0`` when stored).
    :param abort: Optional abort callback polled per member and per chunk.
    :raise OperationAbortedError: If *abort* returned :data:`True`.
    """
    for source, arcname in members:
        _check_abort(abort, arcname)
        info = zipfile.ZipInfo.from_file(source, arcname)
        # from_file() defaults to ZIP_STORED; mirror ZipFile.write(), which stamps the
        # archive's compression onto each member (no public API exposes the level).
        info.compress_type = compression
        info._compresslevel = compression_level or None  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]  # noqa: SLF001
        with source.open("rb") as src, archive.open(info, "w") as dst:
            _copy_stream(src, dst, abort, arcname)


# ---------------------------------------------------------------------------
# Publishing
# ---------------------------------------------------------------------------


def publish_atomic(built: Path, final: Path, *, abort: Callable[[], bool] | None = None) -> Path:
    """
    Publish *built* at *final* via ``<final>.part`` and an atomic rename.

    The source is copied (chunked, abortable) to ``<final>.part`` in the destination
    directory, then renamed with :func:`os.replace` semantics — consumers of the
    destination directory only ever observe complete files. When *built* already
    lives on the destination filesystem the copy is still performed (simple and
    correct); callers building directly in the output directory pass a ``.part``
    path as *built* instead and use :meth:`pathlib.Path.replace` themselves.

    :param built: The finished zip to publish.
    :param final: The destination path (its parent is created if missing).
    :param abort: Optional callback polled between copy chunks; returning
        :data:`True` aborts the publish.
    :return: *final*.
    :raise OperationAbortedError: If *abort* returned :data:`True`; the ``.part`` file is
        removed before raising.
    """
    part = final.with_name(final.name + PART_SUFFIX)
    final.parent.mkdir(parents=True, exist_ok=True)
    try:
        with built.open("rb") as src, part.open("wb") as dst:
            _copy_stream(src, dst, abort, str(final))
        shutil.copystat(built, part, follow_symlinks=False)
    except OperationAbortedError:
        part.unlink(missing_ok=True)
        raise
    part.replace(final)
    return final


def sha256_sidecar(path: Path, /) -> Path:
    """
    Write a ``<name>.sha256`` checksum file next to *path*.

    The content follows the ``sha256sum`` convention: ``<hex digest>  <filename>``
    with a trailing newline, so standard tools can verify it. Written UTF-8: the filename
    may carry non-ASCII characters (e.g. an accented stratum name), which ``sha256sum``
    reads back in the locale byte encoding.

    :param path: The file to checksum (typically a published zip).
    :return: The sidecar path.
    """
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(_COPY_CHUNK_SIZE):
            digest.update(chunk)
    sidecar = path.with_name(path.name + ".sha256")
    sidecar.write_text(f"{digest.hexdigest()}  {path.name}\n", encoding="utf-8")
    return sidecar


def remove_stale_parts(directory: Path, zip_names: Iterable[str], /) -> list[Path]:
    """
    Remove leftover ``<name>.part`` files for this run's target zip names.

    Only the given names are touched — foreign ``.part`` files (other tools, other
    runs with different targets) are left alone.

    :param directory: The output directory.
    :param zip_names: Final zip file names (e.g. ``north.zip``) whose stale parts to drop.
    :return: The paths that were removed.
    """
    removed: list[Path] = []
    for name in zip_names:
        part = directory / f"{name}{PART_SUFFIX}"
        if part.is_file():
            part.unlink()
            removed.append(part)
    return removed
