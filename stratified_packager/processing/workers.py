"""
Background zip publishing: the only work that leaves the algorithm thread (SPEC §8.4/§10).

**This module MUST NOT import ``qgis``** — zip jobs run on plain
:class:`~concurrent.futures.ThreadPoolExecutor` threads and touch only :mod:`zipfile`
and the standard library. An AST test enforces this. GeoPackage writing now happens on the
algorithm thread (see :mod:`~.building`); the algorithm hands each finished bundle here so
the next bundle's GeoPackages can be built while this one is compressed and published.

A job returns its outcome (the algorithm collects it from the future); cancellation
propagates via a :class:`threading.Event` the algorithm sets when the feedback is
canceled. Jobs never raise — failures and cancellations are returned as outcomes and the
partial archive is removed (best-effort policy, SPEC §17).
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from stratified_packager.toolbelt import zipping
from stratified_packager.toolbelt.utils import OperationAbortedError

if TYPE_CHECKING:
    import threading
    from pathlib import Path

__all__: list[str] = ["ZipJob", "ZipOutcome", "run_prefetch", "run_zip"]


@dataclass(frozen=True)
class ZipJob:
    """One zip assembly + publish task (SPEC §10); plain data built on the algorithm thread."""

    zip_rel: str
    """The zip's output-relative path without the ``.zip`` extension (the outcome key)."""

    members: tuple[tuple[Path, str], ...]
    """``(source file, arcname)`` zip members."""

    build_path: Path
    """Where the zip is assembled (run-scoped temp or the output directory)."""

    final_path: Path
    """The published destination (``.part`` + atomic rename)."""

    compression_level: int = 6
    """Deflate level; 0 stores uncompressed."""

    write_checksum: bool = False
    """Whether to write a ``.sha256`` sidecar next to the published zip."""


@dataclass(frozen=True)
class ZipOutcome:
    """The result of one :func:`run_zip` call."""

    zip_rel: str
    """The zip's output-relative path (matches :attr:`ZipJob.zip_rel`)."""

    ok: bool
    """Whether the zip was published."""

    final_path: str = ""
    """The published path (empty on failure)."""

    error: str = ""
    """Failure detail (``canceled`` when aborted by cancellation)."""


def _check_cancel(cancel: threading.Event, token: str) -> None:
    """
    Raise when the run was canceled.

    :param cancel: The run's cancellation event.
    :param token: Identifier carried in the exception.
    :raise OperationAbortedError: If cancellation was requested.
    """
    if cancel.is_set():
        raise OperationAbortedError(token)


def run_prefetch(source: Path, destination: Path, cancel: threading.Event) -> bool:
    """
    Copy one §11 warm-cache file to its build location on a background thread; never raises.

    Submitted before Phase A on ``WARM_START_MODE=use`` runs, so a (possibly remote) cache file is
    already sitting at the stratum's build path when its seeded build starts — the build then
    seeds in place instead of copying on the critical path. Copied chunked via
    :func:`~stratified_packager.toolbelt.zipping.publish_atomic` (``.part`` + rename, *cancel*
    polled between chunks), so a half-copied file is never mistaken for a seed and a canceled
    run does not wait out a large remote copy. Best-effort: ``False`` sends the caller back to
    the seed-time copy from the original cache file.

    :param source: The warm-cache gpkg.
    :param destination: The stratum's build gpkg path.
    :param cancel: The run's cancellation event (set by the algorithm thread).
    :return: Whether the copy completed.
    """
    try:
        zipping.publish_atomic(source, destination, abort=cancel.is_set)
    except OperationAbortedError:
        return False  # publish_atomic already removed the .part file
    except OSError:
        with contextlib.suppress(OSError):
            destination.with_name(destination.name + zipping.PART_SUFFIX).unlink(missing_ok=True)
        return False
    return True


def run_zip(job: ZipJob, cancel: threading.Event) -> ZipOutcome:
    """
    Assemble and publish one zip on a background thread (SPEC §10); never raises.

    Build at :attr:`ZipJob.build_path`, publish to :attr:`ZipJob.final_path` via ``.part``
    + atomic rename, then write the optional checksum sidecar. The build copy is removed
    whatever the outcome — after publishing on success (the build dir shrinks as bundles
    publish instead of holding every archive until run end), best-effort on failure or
    cancellation.

    :param job: The zip job.
    :param cancel: The run's cancellation event (set by the algorithm thread).
    :return: The publish outcome.
    """
    try:
        _check_cancel(cancel, job.zip_rel)
        job.build_path.parent.mkdir(parents=True, exist_ok=True)
        zipping.build_zip(
            job.build_path,
            job.members,
            compression_level=job.compression_level,
            abort=cancel.is_set,
        )
        published = zipping.publish_atomic(job.build_path, job.final_path, abort=cancel.is_set)
        if job.write_checksum:
            zipping.sha256_sidecar(published)
    except OperationAbortedError:
        job.build_path.unlink(missing_ok=True)
        return ZipOutcome(zip_rel=job.zip_rel, ok=False, error="canceled")
    except Exception as err:  # noqa: BLE001  # job boundary: contain, never abort the run
        job.build_path.unlink(missing_ok=True)
        return ZipOutcome(zip_rel=job.zip_rel, ok=False, error=f"{type(err).__name__}: {err}")
    with contextlib.suppress(OSError):  # the published copy is the deliverable
        job.build_path.unlink()
    return ZipOutcome(zip_rel=job.zip_rel, ok=True, final_path=str(job.final_path))
