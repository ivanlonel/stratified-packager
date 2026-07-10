"""Create/update a .env file with environment variables for development."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from dotenv import dotenv_values, set_key


def _which_qgis() -> list[Path]:
    """Return the ``qgis`` launcher found on ``PATH`` as a single-item list, else empty."""
    found = shutil.which("qgis")
    return [Path(found)] if found else []


def find_default_qgis_executable(python_prefix: str | os.PathLike[str]) -> Path:
    """
    Locate the QGIS application executable for the current platform.

    The search strategy depends on the platform:

    * **Windows**: ``qgis*-bin.exe`` in the ``bin`` directory of the OSGeo4W or
      standalone installation root (two levels above `python_prefix`).
    * **macOS**: the ``Contents/MacOS/QGIS`` binary of a ``QGIS*.app`` bundle in
      ``/Applications`` or ``~/Applications``, then ``qgis`` on :class:`pathlib.Path`.
    * **Linux/other Unix**: ``qgis`` on :class:`pathlib.Path`, then ``<python_prefix>/bin/qgis``
      and ``/usr/bin/qgis``.

    :param python_prefix: The Python installation prefix
        (typically :data:`sys.base_prefix`).

    :raise FileNotFoundError: If no QGIS executable can be located automatically.

    :return: Absolute, resolved path to the first QGIS executable found.
    """
    prefix = Path(python_prefix)

    if sys.platform == "win32":
        candidates = sorted((prefix.parent.parent / "bin").glob("qgis*-bin.exe"))
    elif sys.platform == "darwin":
        candidates = [
            app / "Contents/MacOS/QGIS"
            for apps_dir in (Path("/Applications"), Path.home() / "Applications")
            for app in sorted(apps_dir.glob("QGIS*.app"))
        ] + _which_qgis()
    else:
        candidates = [*_which_qgis(), prefix / "bin/qgis", Path("/usr/bin/qgis")]

    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    msg = (
        f"No QGIS executable could be located automatically for platform '{sys.platform}'. "
        "Use --qgis-executable-path to specify it explicitly."
    )
    raise FileNotFoundError(msg)


def _default_qgis_data_dir() -> Path:
    r"""
    Return the platform's QGIS user-data directory (the parent of the ``QGIS<major>`` dirs).

    * **Windows**: ``%APPDATA%\QGIS`` (``~\AppData\Roaming\QGIS``).
    * **macOS**: ``~/Library/Application Support/QGIS``.
    * **Linux/other Unix**: ``$XDG_DATA_HOME/QGIS`` (``~/.local/share/QGIS``).

    :return: Absolute path to the QGIS user-data directory (not guaranteed to exist).
    """
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "").strip()
        base = Path(appdata) if appdata else Path.home() / "AppData/Roaming"
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        xdg_data_home = os.environ.get("XDG_DATA_HOME", "").strip()
        base = Path(xdg_data_home) if xdg_data_home else Path.home() / ".local/share"
    return base / "QGIS"


def get_default_qgis_profiles_dir() -> Path:
    r"""
    Return the default QGIS profiles directory for the installed version.

    Import :mod:`qgis.core` at runtime to read the major version of the
    installed QGIS, then build the conventional path for the current platform
    (see :func:`_default_qgis_data_dir`):

    * **Windows**: ``%APPDATA%\QGIS\QGIS<major>\profiles``
    * **macOS**: ``~/Library/Application Support/QGIS/QGIS<major>/profiles``
    * **Linux**: ``~/.local/share/QGIS/QGIS<major>/profiles``

    :raise ImportError: If :mod:`qgis.core` cannot be imported (PyQGIS not
        available on :data:`sys.path`).
    :raise FileNotFoundError: If a ``profiles`` directory is not found in the
        default locations.

    :return: Absolute, resolved path to the QGIS profiles directory.
    """
    base = _default_qgis_data_dir()
    if next(base.glob("QGIS*/profiles"), None) is None:
        msg = (
            "No QGIS profiles directory was found in the default locations. "
            "Provide --qgis-settings-dir explicitly."
        )
        raise FileNotFoundError(msg)

    # Defer qgis import until we know there's at least one profiles directory in a default path.
    from qgis.core import Qgis  # noqa: PLC0415

    profiles_path = base / f"QGIS{Qgis.version().split('.')[0]}/profiles"
    if profiles_path.is_dir():
        return profiles_path.resolve()

    msg = f"{profiles_path} is not a directory."
    raise FileNotFoundError(msg)


def build_parser(default_executable: str | os.PathLike[str] | None) -> argparse.ArgumentParser:
    """
    Build and return the command-line argument parser.

    The help text for ``--qgis-executable-path`` is adjusted depending on
    whether a `default_executable` was successfully detected at startup.

    :param default_executable: Absolute path to the automatically detected
        QGIS executable, or :data:`None` if detection failed.

    :return: Fully configured argument parser, ready to call
        :meth:`~argparse.ArgumentParser.parse_args`.
    """
    parser = argparse.ArgumentParser(description="QGIS environment configuration script.")
    parser.add_argument(
        "env_file",
        nargs="?",
        type=Path,
        default=Path(".env"),
        help="Path to the .env file to create/update.",
    )
    parser.add_argument(
        "--qgis-executable-path",
        type=Path,
        help=(
            f"Path to the QGIS executable (default: {default_executable})."
            if default_executable
            else "Path to the QGIS executable (required: none could be detected automatically)."
        ),
    )
    default_profile_hint = f"{_default_qgis_data_dir()}/QGIS<major>/profiles".replace("%", "%%")
    parser.add_argument(
        "--qgis-settings-dir",
        type=Path,
        help=(
            "Path to a specific QGIS profile directory; its parent becomes "
            "QGIS_PROFILES_DIR and its name the development profile (default: the "
            f"'default' profile under {default_profile_hint})."
        ),
    )
    return parser


def report_changes(
    initial: dict[str, str | None],
    final: dict[str, str | None],
) -> None:
    """
    Print a readable summary of the variables added to and changed in ``.env``.

    Compare `initial` (the file state before this run) with `final` (the state
    after all calls to :func:`~dotenv.set_key`) and print:

    * **New variables** — keys present in *final* but absent from *initial*.
    * **Updated variables** — keys present in both mappings whose value changed.
    * A "no changes" message when neither category has any entries.

    :param initial: Mapping of variable names to values read from the ``.env``
        file *before* any modification.
    :param final: Mapping of variable names to values read from the ``.env``
        file *after* all modifications.
    """
    new_vars = {k: v for k, v in final.items() if k not in initial}
    updated_vars = {k: v for k, v in final.items() if k in initial and v != initial[k]}

    if new_vars:
        print("\nNew variables:")
        for key, value in new_vars.items():
            print(f"  {key}={value}")

    if updated_vars:
        print("\nUpdated variables:")
        for key, value in updated_vars.items():
            print(f"  {key}={value}")

    if not new_vars and not updated_vars:
        print("\nNo changes were made to the environment variables.")


def main() -> None:
    """
    Entry point for the QGIS environment configuration script.

    Orchestrate the full configuration flow:

    1. Try to automatically detect the QGIS executable via
       :func:`find_default_qgis_executable`; warn on *stderr* on failure.
    2. Parse the command-line arguments with :func:`build_parser`.
    3. Create the target ``.env`` file if it does not exist.
    4. Read the pre-existing variables with :func:`dotenv.dotenv_values`.
    5. Write the environment variables to the ``.env`` file, skipping keys
       already present unless an explicit CLI argument overrides them.
    6. Print the resolved path of the written file and a summary of changes
       via :func:`report_changes`.

    :raise SystemExit: Via :meth:`~argparse.ArgumentParser.error` when no QGIS
        executable was detected and ``--qgis-executable-path`` was not provided,
        or when :mod:`qgis.core` could not be imported to determine the default
        profiles directory. A missing profiles directory is reported as a warning
        and skipped rather than treated as fatal.
    """
    try:
        default_executable: Path | None = find_default_qgis_executable(Path(sys.base_prefix))
    except FileNotFoundError as e:
        print(f"Warning: {e}", file=sys.stderr)
        default_executable = None

    parser = build_parser(default_executable)
    args = parser.parse_args()

    env_file: Path = args.env_file
    env_file.touch()  # ensure the file exists before dotenv tries to read it

    initial_variables = dotenv_values(env_file)

    # QGIS_EXECUTABLE_PATH
    if args.qgis_executable_path is not None:
        set_key(env_file, "QGIS_EXECUTABLE_PATH", str(args.qgis_executable_path.resolve()))
    elif "QGIS_EXECUTABLE_PATH" not in initial_variables:
        if default_executable is None:
            parser.error(
                "Could not detect a default QGIS executable. Provide --qgis-executable-path."
            )
        set_key(env_file, "QGIS_EXECUTABLE_PATH", str(default_executable))

    # QGIS_PROFILES_DIR + DEVELOPMENT_PROFILE_NAME
    if args.qgis_settings_dir is not None:
        resolved = args.qgis_settings_dir.resolve()
        set_key(env_file, "QGIS_PROFILES_DIR", str(resolved.parent))
        set_key(env_file, "DEVELOPMENT_PROFILE_NAME", resolved.name)
    else:
        if "DEVELOPMENT_PROFILE_NAME" not in initial_variables:
            set_key(env_file, "DEVELOPMENT_PROFILE_NAME", "default")
        if "QGIS_PROFILES_DIR" not in initial_variables:
            try:
                set_key(env_file, "QGIS_PROFILES_DIR", str(get_default_qgis_profiles_dir()))
            except ImportError:
                parser.error(
                    "Could not import from qgis.core to determine the default profiles "
                    "directory. Make sure the QGIS python directory (the parent of the qgis "
                    "package) is on sys.path or provide --qgis-settings-dir explicitly."
                )
            except OSError as e:
                print(
                    f"Warning: could not determine the default QGIS profiles directory "
                    f"({e}). Skipping QGIS_PROFILES_DIR; set it via --qgis-settings-dir "
                    f"or directly in {env_file} if needed.",
                    file=sys.stderr,
                )

    # debugpy attach toggles (consumed by the plugin's debug bootstrap): enabled by default so
    # a launched QGIS opens a listen server, but without blocking startup to wait for an attach.
    if "QGIS_DEBUGPY" not in initial_variables:
        set_key(env_file, "QGIS_DEBUGPY", "1")
    if "QGIS_DEBUGPY_WAIT" not in initial_variables:
        set_key(env_file, "QGIS_DEBUGPY_WAIT", "0")

    print(f".env saved to: {env_file.resolve()}")
    report_changes(initial_variables, dotenv_values(env_file))


if __name__ == "__main__":
    main()
