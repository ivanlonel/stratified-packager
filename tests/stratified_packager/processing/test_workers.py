"""
Tests for :mod:`stratified_packager.processing.workers`.

QGIS-free **and** GDAL-free by design: the module — now only the background zip publishing
that leaves the algorithm thread (SPEC §8.4) — and the toolbelt it uses must never import
``qgis``, enforced by the AST gate below. Pure standard library, so this runs in the
non-qgis lane too.
"""
# pylint: disable=redefined-outer-name

from __future__ import annotations

import ast
import threading
import zipfile
from pathlib import Path

import pytest

import stratified_packager
from stratified_packager.processing.workers import ZipJob, ZipOutcome, run_prefetch, run_zip

_PACKAGE_ROOT = Path(stratified_packager.__file__).parent

QGIS_FREE_MODULES = [
    _PACKAGE_ROOT / "processing/workers.py",
    _PACKAGE_ROOT / "toolbelt/gpkg.py",
    _PACKAGE_ROOT / "toolbelt/zipping.py",
    _PACKAGE_ROOT / "toolbelt/utils.py",
    _PACKAGE_ROOT / "toolbelt/mapping_proxy.py",
]
"""The modules whose qgis-free contract the AST gate enforces (SPEC §8/§18)."""


class TestQgisFreePurity:
    """The architecture invariant: workers (and their toolbelt) import no qgis."""

    @pytest.mark.parametrize(
        "module_path", QGIS_FREE_MODULES, ids=lambda p: p.relative_to(_PACKAGE_ROOT).as_posix()
    )
    def test_no_qgis_imports(self, module_path: Path) -> None:
        """
        The module's AST contains no ``qgis`` import in any form.

        :param module_path: The module under inspection.
        """
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not any(alias.name.partition(".")[0] == "qgis" for alias in node.names), (
                    f"{module_path.name} imports qgis"
                )
            elif isinstance(node, ast.ImportFrom):
                root = (node.module or "").partition(".")[0]
                assert root != "qgis", f"{module_path.name} imports from qgis"


@pytest.fixture
def cancel() -> threading.Event:
    """Return an unset cancellation event."""
    return threading.Event()


class TestRunZip:
    """The §10/§8.4 background zip assembly + publish (returns its outcome, never raises)."""

    def test_publish_with_checksum(self, tmp_path: Path, cancel: threading.Event) -> None:
        """The zip publishes atomically with its members and a checksum sidecar."""
        member = tmp_path / "north.gpkg"
        member.write_bytes(b"gpkg-bytes")
        job = ZipJob(
            zip_rel="north",
            members=((member, "north.gpkg"),),
            build_path=tmp_path / "build/north.zip",
            final_path=tmp_path / "out/north.zip",
            write_checksum=True,
        )
        outcome = run_zip(job, cancel)
        assert isinstance(outcome, ZipOutcome)
        assert outcome.ok
        assert outcome.final_path == str(job.final_path)
        with zipfile.ZipFile(job.final_path) as archive:
            assert archive.namelist() == ["north.gpkg"]
        assert job.final_path.with_name("north.zip.sha256").exists()
        assert not job.final_path.with_name("north.zip.part").exists()
        assert not job.build_path.exists()  # the build copy is dropped once published

    def test_cancellation(self, tmp_path: Path) -> None:
        """A pre-set cancel event aborts the zip with no published output."""
        canceled = threading.Event()
        canceled.set()
        member = tmp_path / "m.gpkg"
        member.write_bytes(b"x")
        job = ZipJob(
            zip_rel="z",
            members=((member, "m.gpkg"),),
            build_path=tmp_path / "build/z.zip",
            final_path=tmp_path / "out/z.zip",
        )
        outcome = run_zip(job, canceled)
        assert not outcome.ok
        assert outcome.error == "canceled"
        assert not job.final_path.exists()

    def test_failure_reports(self, tmp_path: Path, cancel: threading.Event) -> None:
        """A missing member fails the zip with a serialized error."""
        job = ZipJob(
            zip_rel="z",
            members=((tmp_path / "missing.gpkg", "m.gpkg"),),
            build_path=tmp_path / "build/z.zip",
            final_path=tmp_path / "out/z.zip",
        )
        outcome = run_zip(job, cancel)
        assert not outcome.ok
        assert "FileNotFoundError" in outcome.error


class TestRunPrefetch:
    """The §11 warm-cache prefetch copy (best-effort, never raises)."""

    def test_copies_to_the_build_path(self, tmp_path: Path, cancel: threading.Event) -> None:
        """The cache file lands whole at the destination; no ``.part`` remains."""
        source = tmp_path / "warm/A.gpkg"
        source.parent.mkdir()
        source.write_bytes(b"warm-cache-bytes")
        destination = tmp_path / "zip_000/deep/A.gpkg"
        assert run_prefetch(source, destination, cancel)
        assert destination.read_bytes() == b"warm-cache-bytes"
        assert not destination.with_name("A.gpkg.part").exists()

    def test_cancellation_and_missing_source(self, tmp_path: Path) -> None:
        """A pre-set cancel event or a missing source reports False and writes nothing."""
        canceled = threading.Event()
        canceled.set()
        source = tmp_path / "warm/A.gpkg"
        destination = tmp_path / "zip_000/A.gpkg"
        assert not run_prefetch(source, destination, canceled)
        assert not run_prefetch(source, destination, threading.Event())  # source missing
        assert not destination.exists()
        assert not destination.with_name("A.gpkg.part").exists()
