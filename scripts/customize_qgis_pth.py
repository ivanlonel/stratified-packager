"""
QGIS .pth customization script.

Ensure the virtual environment created by ``qgis-venv-creator`` can import the
Python packages that ship inside the QGIS installation but are not on
:data:`sys.path` by default: the bundled ``processing`` plugin (under the QGIS
``python/plugins`` directory) and the GRASS Python package.

The script is platform-agnostic. It locates the QGIS ``python`` directory from
the importable :mod:`qgis` package (instead of assuming the Windows/OSGeo4W
``apps`` layout), finds the environment's ``site-packages`` directory via
:mod:`sysconfig`, and searches platform-appropriate locations for GRASS.

Steps:

- Validate that ``qgis.pth`` exists in the ``site-packages`` directory; if it
  sits directly in :data:`sys.prefix` instead, move it into ``site-packages``.
- Ensure :data:`sys.path` (via ``qgis.pth``) contains the QGIS ``plugins`` directory.
- Best-effort: add the GRASS Python directory when it can be located.
"""

from __future__ import annotations

import os
import sys
import sysconfig
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator


def _get_pth_file() -> Path:
    """
    Return the qgis.pth path in ``site-packages``, creating or relocating it as needed.

    The ``site-packages`` directory is resolved via :mod:`sysconfig`, so the
    correct per-platform venv layout is used (``Lib/site-packages`` on Windows,
    ``lib/python<x.y>/site-packages`` on Linux and macOS). When qgis.pth sits directly
    in :data:`sys.prefix` it is moved into ``site-packages``; when no qgis.pth exists at
    all — as in the ``--system-site-packages`` venv that ``qgis-venv-creator`` builds on
    Linux, where :mod:`qgis` is already importable via the system Python — an empty one is
    created so the plugins/GRASS paths can still be appended.

    :raise OSError: If an existing qgis.pth cannot be moved into ``site-packages`` or a
        new one can't be created.
    :return: Path to the qgis.pth file inside the ``site-packages`` directory.
    """
    pth_file = Path(sysconfig.get_path("purelib")) / "qgis.pth"

    if pth_file.is_file():
        return pth_file

    src_pth_file = Path(sys.prefix) / "qgis.pth"

    if src_pth_file.is_file():
        src_pth_file.rename(pth_file)
        print(f"Moved qgis.pth from {src_pth_file.parent} to {pth_file.parent}")
        return pth_file

    pth_file.touch()
    print(f"Created empty qgis.pth in {pth_file.parent}")
    return pth_file


def _get_resolved_sys_path() -> Generator[Path]:
    for path in sys.path:
        if path:
            try:
                yield Path(path).resolve()
            except OSError as e:
                print(f"Error resolving path {path}: {e!r}", file=sys.stderr)


def _get_qgis_python_dir() -> Path:
    """
    Resolve the QGIS ``python`` directory from the importable :mod:`qgis` package.

    The parent of the :mod:`qgis` package directory is the QGIS ``python`` directory
    on every platform: ``apps/qgis/python`` on Windows/OSGeo4W,
    ``/usr/share/qgis/python`` on Linux, ``Contents/Resources/python`` inside the
    macOS application bundle. This avoids hard-coding any platform layout.

    :raise RuntimeError: If :mod:`qgis` cannot be imported, meaning its ``python``
        directory is not on :data:`sys.path` (the interpreter is not the
        ``qgis-venv-creator`` one, or ``qgis.pth`` is misconfigured).
    :return: Resolved path to the QGIS ``python`` directory.
    """
    try:
        # Deferred: the qgis package is only importable inside the QGIS-aware venv.
        import qgis  # noqa: PLC0415
    except ImportError as e:
        msg = (
            "Could not import 'qgis'. Run this script with the Python interpreter of the "
            "qgis-venv-creator virtual environment, where qgis.pth (or PYTHONPATH) places "
            "the QGIS 'python' directory on 'sys.path'."
        )
        raise RuntimeError(msg) from e

    # A regular package always sets __file__ to its __init__.py; its grandparent is `python`.
    return Path(qgis.__file__).resolve().parent.parent


def _grass_python_candidates(qgis_python_dir: Path) -> list[Path]:
    """
    Build the ordered list of candidate GRASS ``etc/python`` directories to probe.

    The QGIS installation ships GRASS in a platform-specific location relative to
    ``qgis_python_dir``. A :envvar:`GISBASE` environment variable, when set, takes
    precedence over the conventional locations.

    :param qgis_python_dir: The QGIS ``python`` directory (parent of the :mod:`qgis` package).
    :return: Candidate directories, most specific first. Entries are not guaranteed to exist.
    """
    candidates: list[Path] = []

    gisbase = os.environ.get("GISBASE", "").strip()
    if gisbase:
        candidates.append(Path(gisbase) / "etc/python")

    if sys.platform == "win32":
        # OSGeo4W/standalone: <root>/apps/qgis/python -> <root>/apps/grass/grass*/etc/python.
        apps_dir = qgis_python_dir.parent.parent
        candidates += sorted(apps_dir.glob("grass/grass*/etc/python"))
    elif sys.platform == "darwin":
        # Bundle: <app>/Contents/Resources/python -> Contents/{Resources,MacOS}/grass*/etc/python.
        contents_dir = qgis_python_dir.parent.parent
        candidates += sorted(contents_dir.glob("Resources/grass*/etc/python"))
        candidates += sorted(contents_dir.glob("MacOS/grass*/etc/python"))
    else:
        # Linux/other Unix: GRASS is a system package under the standard library directories.
        for lib_dir in (Path("/usr/lib"), Path("/usr/lib64"), Path("/usr/local/lib")):
            candidates += sorted(lib_dir.glob("grass*/etc/python"))

    return candidates


def _find_grass_python_dir(qgis_python_dir: Path) -> Path | None:
    """
    Return the first existing GRASS ``etc/python`` directory, or :data:`None` if none is found.

    :param qgis_python_dir: The QGIS ``python`` directory (parent of the :mod:`qgis`
        package).
    :return: Resolved path to the GRASS Python directory, or :data:`None` when GRASS
        is not installed alongside QGIS.
    """
    for candidate in _grass_python_candidates(qgis_python_dir):
        if candidate.is_dir():
            return candidate.resolve()
    return None


def _add_to_pth(pth_file: Path, resolved_path: Path) -> None:
    """
    Append a path to the .pth file if it is not already listed there.

    :param pth_file: Path to the qgis.pth file to modify.
    :param resolved_path: Resolved path to append.
    """
    lines = pth_file.read_text(encoding="utf-8").splitlines()
    if resolved_path in {Path(line).resolve() for line in lines if line}:
        print(f"  Already present in qgis.pth: {resolved_path}")
        return

    lines.append(resolved_path.as_posix())
    pth_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  Added to qgis.pth: {resolved_path}")


def _ensure_in_sys_path(pth_file: Path, resolved_path: Path, label: str) -> None:
    """
    Add a path to the .pth file if it is not already present in ``sys.path``.

    :param pth_file: Path to the qgis.pth file to modify.
    :param resolved_path: Resolved path to check and potentially add.
    :param label: Human-readable label for the path, used in console output.
    """
    if resolved_path in set(_get_resolved_sys_path()):
        print(f"{label} already in sys.path: {resolved_path}")
    else:
        print(f"{label} not found in sys.path — adding to qgis.pth …")
        _add_to_pth(pth_file, resolved_path)


def main() -> None:
    """
    Entry point for the .pth customization script.

    Validate the qgis.pth file and ensure the QGIS ``plugins`` directory is
    present in :data:`sys.path`, adding it to qgis.pth when missing. The GRASS Python
    directory is added on a best-effort basis: a warning is printed when it
    cannot be located, since not every QGIS installation ships GRASS.
    """
    pth_file = _get_pth_file()
    qgis_python_dir = _get_qgis_python_dir()

    _ensure_in_sys_path(pth_file, qgis_python_dir / "plugins", "QGIS plugins directory")

    grass_python_dir = _find_grass_python_dir(qgis_python_dir)
    if grass_python_dir is None:
        print(
            "GRASS Python directory not found in the usual locations — skipping. "
            "Set GISBASE or edit qgis.pth manually if the GRASS provider is required.",
            file=sys.stderr,
        )
    else:
        _ensure_in_sys_path(pth_file, grass_python_dir, "GRASS Python directory")


if __name__ == "__main__":
    main()
