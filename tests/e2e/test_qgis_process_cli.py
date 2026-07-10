"""
End-to-end smoke test of the ``qgis_process`` CLI path (SPEC §1: CLI entry).

Drives a real ``qgis_process`` executable as a subprocess against the committed fixture
project in ``tests/fixtures/e2e`` — provider registration, headless ``--PROJECT_PATH``
resolution and the full package run (spatial + relation-attribute matching, zip
publishing, §9.2 per-zip report). This module never imports ``qgis``: everything QGIS
happens inside the subprocess, so the test runs from any interpreter and skips itself
when no ``qgis_process`` can be found.

The executable is discovered from ``PATH``, from ``QGIS_EXECUTABLE_PATH`` (the ``.env``
variable ``just qgis-process`` uses; loaded via :mod:`dotenv` when present), or from the
``qgis`` package location visible to this venv. The subprocess runs against an isolated,
throw-away QGIS config root (``QGIS_CUSTOM_CONFIG_PATH``) and picks the plugin up from
the working tree via ``QGIS_PLUGINPATH`` — no deploy step and no touching of user
profiles.
"""
# pylint: disable=redefined-outer-name

from __future__ import annotations

import csv
import io
import os
import shutil
import sqlite3
import subprocess
import sys
import zipfile
from importlib.util import find_spec
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
FIXTURE_PROJECT: Final = REPO_ROOT / "tests/fixtures/e2e/project.qgs"
PLUGIN_SLUG: Final = "stratified_packager"
ALGORITHM_ID: Final = f"{PLUGIN_SLUG}:package"
SUBPROCESS_TIMEOUT: Final = 300.0
"""Per-call ceiling in seconds; a cold qgis_process start stays well under it."""

EXPECTED_COUNTS: Final[dict[str, dict[str, int]]] = {
    "A": {"points": 2, "details": 2},
    "B": {"points": 1, "details": 1},
    "C": {"points": 1, "details": 1},
}
"""Fixture ground truth: features per (stratum, table) — see the .geojsonl sources."""


def _load_dotenv_executable() -> str | None:
    """
    Return ``QGIS_EXECUTABLE_PATH`` from the environment, falling back to ``.env``.

    :return: The configured QGIS executable path, or :data:`None`.
    """
    if value := os.environ.get("QGIS_EXECUTABLE_PATH"):
        return value
    env_file = REPO_ROOT / ".env"
    if env_file.is_file():
        try:
            from dotenv import dotenv_values  # noqa: PLC0415  # optional, test-group-only dep
        except ImportError:
            return None
        return dotenv_values(env_file).get("QGIS_EXECUTABLE_PATH")
    return None


def _process_in_dir(directory: Path) -> Path | None:
    """
    Return the preferred ``qgis_process*`` executable inside *directory*, if any.

    On Windows the ``.bat``/``.cmd`` launchers are preferred over the bare ``.exe``:
    they run the OSGeo4W environment setup the executable needs.

    :param directory: The directory to search (non-directories yield :data:`None`).
    :return: The executable path, or :data:`None`.
    """
    if not directory.is_dir():
        return None
    candidates = [
        path
        for path in directory.glob("qgis_process*")
        if path.is_file()
        and (sys.platform != "win32" or path.suffix.lower() in (".bat", ".cmd", ".exe"))
    ]
    candidates.sort(key=lambda path: path.suffix.lower() not in (".bat", ".cmd"))
    return candidates[0] if candidates else None


def _candidate_directories() -> Iterator[Path]:
    """
    Yield the directories that may hold ``qgis_process``, most authoritative first.

    :yield: Candidate directories (possibly repeated; the caller stops at the first hit).
    """
    if configured := _load_dotenv_executable():
        bin_dir = Path(configured).parent
        yield bin_dir
        yield bin_dir / "bin"  # macOS app bundle layout
    spec = find_spec("qgis") if "qgis" not in sys.builtin_module_names else None
    if spec is not None and spec.origin:
        # <prefix>/python/qgis/__init__.py: prefix is parents[2]; on Windows the
        # OSGeo4W install root (which owns bin/qgis_process*.bat) is parents[4].
        origin = Path(spec.origin)
        for ancestor_index in (2, 4):
            if ancestor_index < len(origin.parents):
                yield origin.parents[ancestor_index] / "bin"


def _find_qgis_process() -> Path | None:
    """
    Locate a runnable ``qgis_process`` executable, or return :data:`None` to skip.

    :return: The executable path, or :data:`None` when this machine has no QGIS.
    """
    if on_path := shutil.which("qgis_process"):
        return Path(on_path)
    return next(
        (found for directory in _candidate_directories() if (found := _process_in_dir(directory))),
        None,
    )


QGIS_PROCESS: Final = _find_qgis_process()

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(QGIS_PROCESS is None, reason="no qgis_process executable found"),
]


def _run(arguments: Sequence[str], env: Mapping[str, str]) -> subprocess.CompletedProcess[str]:
    """
    Run ``qgis_process`` with *arguments* and return the completed process.

    :param arguments: The CLI arguments after the executable.
    :param env: The full subprocess environment.
    :return: The completed process (stdout/stderr captured as text).
    """
    assert QGIS_PROCESS is not None  # narrowed by the module-level skipif
    return subprocess.run(  # noqa: S603  # trusted executable discovered from the QGIS install
        [str(QGIS_PROCESS), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=dict(env),
        timeout=SUBPROCESS_TIMEOUT,
        check=False,
    )


@pytest.fixture(scope="session")
def qgis_process_env(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    """
    Return the subprocess environment: isolated config root + working-tree plugin path.

    :param tmp_path_factory: Session-scoped temporary directory factory.
    :return: The environment mapping for every ``qgis_process`` call.
    """
    env = os.environ.copy()
    # An isolated config ROOT (the parent of profiles/) keeps the run off any user profile.
    env["QGIS_CUSTOM_CONFIG_PATH"] = str(tmp_path_factory.mktemp("qgis_config"))
    env["QGIS_PLUGINPATH"] = str(REPO_ROOT)
    if sys.platform != "win32":
        env.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless CI containers
    return env


@pytest.fixture(scope="session")
def enabled_plugin(qgis_process_env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """
    Enable the plugin in the isolated profile once per session.

    :param qgis_process_env: The shared subprocess environment.
    :return: The completed ``plugins enable`` process, for assertions on its output.
    """
    return _run(["plugins", "enable", PLUGIN_SLUG], qgis_process_env)


def test_plugin_loads_and_registers_provider(
    enabled_plugin: subprocess.CompletedProcess[str],
) -> None:
    """The plugin imports cleanly under qgis_process and registers its provider (``*``)."""
    assert enabled_plugin.returncode == 0, enabled_plugin.stderr
    listing = enabled_plugin.stdout
    assert f"* {PLUGIN_SLUG}" in listing, listing


def test_package_run_produces_zips_and_reports(
    enabled_plugin: subprocess.CompletedProcess[str],
    qgis_process_env: dict[str, str],
    tmp_path: Path,
) -> None:
    """A full headless run packages the fixture into per-stratum zips with §9.2 reports."""
    assert enabled_plugin.returncode == 0, enabled_plugin.stderr
    out_dir = tmp_path / "out"
    result = _run(
        [
            "run",
            ALGORITHM_ID,
            f"--PROJECT_PATH={FIXTURE_PROJECT}",
            "--LAYERS=points",
            "--LAYERS=details",
            "--STRATIFICATION_LAYER=strata",
            "--STRATUM_NAME_EXPRESSION=name",
            f"--OUTPUT_DIRECTORY={out_dir}",
        ],
        qgis_process_env,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "FAILED_STRATA:\t[]" in result.stdout, result.stdout

    for stratum, counts in EXPECTED_COUNTS.items():
        zip_path = out_dir / f"{stratum}.zip"
        assert zip_path.is_file(), sorted(out_dir.iterdir())
        with zipfile.ZipFile(zip_path) as bundle:
            _assert_gpkg_contents(bundle, stratum, counts, tmp_path)
            _assert_zip_report(bundle, stratum, counts)


def _assert_gpkg_contents(
    bundle: zipfile.ZipFile, stratum: str, counts: Mapping[str, int], scratch: Path
) -> None:
    """
    Assert the stratum GeoPackage carries the expected tables and feature counts.

    :param bundle: The published zip.
    :param stratum: The stratum name (also the gpkg basename, §3 defaults).
    :param counts: Expected feature count per table.
    :param scratch: Directory to extract into.
    """
    member = f"{stratum}.gpkg"
    assert member in bundle.namelist(), bundle.namelist()
    extracted = bundle.extract(member, scratch / stratum)
    connection = sqlite3.connect(extracted)
    try:
        tables = {row[0] for row in connection.execute("SELECT table_name FROM gpkg_contents")}
        assert set(counts) <= tables, tables
        for table, expected in counts.items():
            (actual,) = connection.execute(
                f'SELECT COUNT(*) FROM "{table}"'  # noqa: S608  # fixture-defined table names
            ).fetchone()
            assert actual == expected, (stratum, table, actual, expected)
    finally:
        connection.close()


def _assert_zip_report(bundle: zipfile.ZipFile, stratum: str, counts: Mapping[str, int]) -> None:
    """
    Assert the §9.2 ``report.csv`` rows match the fixture ground truth.

    :param bundle: The published zip.
    :param stratum: The stratum name every row must carry.
    :param counts: Expected feature count per layer.
    """
    assert "report.csv" in bundle.namelist(), bundle.namelist()
    with bundle.open("report.csv") as handle:
        rows = list(csv.DictReader(io.TextIOWrapper(handle, encoding="utf-8")))
    by_layer = {row["layer_name"]: row for row in rows}
    assert set(counts) <= set(by_layer), by_layer
    for layer, expected in counts.items():
        row = by_layer[layer]
        assert row["stratum"] == stratum, row
        assert row["status"] == "ok", row
        assert int(row["feature_count"]) == expected, row
    assert by_layer["points"]["matching_method"] == "spatial", by_layer["points"]
    assert by_layer["details"]["matching_method"] == "attribute", by_layer["details"]
