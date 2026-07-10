"""
Miscellaneous utility functions.

DO NOT import from the ``qgis`` package in this module outside of
:data:`~typing.TYPE_CHECKING` guards.
"""

from __future__ import annotations

import re
import shutil
import sys
import sysconfig
import time
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterable

_ILLEGAL_FILENAME_CHARS: Final[re.Pattern[str]] = re.compile(r'[\x00-\x1f\x7f<>:"/\\|?*]')
"""Characters Windows forbids in filenames (a superset of the POSIX restrictions)."""

_WINDOWS_RESERVED_NAMES: Final[frozenset[str]] = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"{dev}{digit}" for dev in ("COM", "LPT") for digit in "0123456789¹²³"}
)
"""Reserved device names (base name before the first dot, case-insensitive)."""

_MAX_FILENAME_LENGTH: Final = 255
"""Per-component filename length limit on the common filesystems (NTFS, ext4, APFS)."""


_TRUE_TOKENS: Final[frozenset[str]] = frozenset({"true", "1", "yes", "on", "t", "y"})
_FALSE_TOKENS: Final[frozenset[str]] = frozenset({"false", "0", "no", "off", "f", "n", ""})


class OperationAbortedError(RuntimeError):
    """Raised when a long-running toolbelt operation is aborted via its abort callback."""


def coerce_bool(raw: object, /) -> bool:
    """
    Interpret a raw value as a boolean.

    Native booleans pass through and numbers use their truthiness; strings are matched
    case-insensitively (after stripping) against the true tokens (``"true"``, ``"1"``,
    ``"yes"``, ``"on"``, ``"t"``, ``"y"``) and false tokens (``"false"``, ``"0"``,
    ``"no"``, ``"off"``, ``"f"``, ``"n"``, ``""``).

    :param raw: The raw value.
    :return: The boolean value.
    :raise ValueError: If *raw* is not a recognizable boolean token.
    """
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    token = str(raw).strip().lower()
    if token in _TRUE_TOKENS:
        return True
    if token in _FALSE_TOKENS:
        return False
    msg = f"{raw!r} is not a boolean"
    raise ValueError(msg)


def sanitize_filename(txt: str, /) -> str:
    """
    Turn a string into a valid cross-platform filename, preserving Unicode letters.

    Strips path separators and the characters Windows forbids in filenames (including
    control characters), collapses whitespace runs into single spaces, trims leading and
    trailing whitespace and trailing dots, prefixes ``_`` to reserved Windows device names
    (``CON``, ``NUL``, ``COM1``, ... — matched against the base name before the first dot,
    case-insensitively), and truncates to the 255-character filesystem component limit.
    Unlike :func:`sanitize_identifier_name`, Unicode letters and diacritics are preserved.

    The result is never empty (``_`` stands in when nothing survives) and the function is
    idempotent, but distinct inputs MAY collide — callers that require uniqueness must
    detect collisions themselves (case-insensitively, for Windows).

    :param txt: Original string (e.g. a stratum name).
    :return: A copy of the original string safe to use as a single filename component.
    """
    cleaned = re.sub(r"\s+", " ", _ILLEGAL_FILENAME_CHARS.sub("", txt)).strip(" ").rstrip(". ")
    if cleaned.partition(".")[0].rstrip(" ").upper() in _WINDOWS_RESERVED_NAMES:
        cleaned = f"_{cleaned}"
    return cleaned[:_MAX_FILENAME_LENGTH].rstrip(". ") or "_"


def remove_diacritical_marks(txt: str, /) -> str:
    """
    Remove diacritical marks from a string (such as accents, tildes and cedillas).

    :param txt: Original string.
    :return: A copy of the original string with the diacritical marks removed.
    """
    return "".join(c for c in unicodedata.normalize("NFD", txt) if unicodedata.category(c) != "Mn")


def sanitize_identifier_name(txt: str, /) -> str:
    """
    Turn a string into a valid identifier by removing non-alphanumerics and diacritical marks.

    :param txt: Original string.
    :return: A copy of the original string with the diacritical marks removed and
        ``_`` in place of runs of non-alphanumeric characters. If the original string
        starts with a numeric digit, a ``_`` is inserted at the beginning.
    """
    return re.sub(r"[^_0-9A-Za-z]+|^(?=\d)", "_", remove_diacritical_marks(txt))


def dedupe_names(names: Iterable[str], /) -> list[str]:
    """
    Disambiguate duplicate names by suffixing ``_2``, ``_3``, ... in encounter order.

    The first occurrence keeps its name; later duplicates get the lowest free suffix
    (collisions with pre-existing suffixed names are themselves disambiguated).
    Comparison is case-insensitive, matching SQLite/GeoPackage table-name semantics.

    :param names: The candidate names, in order.
    :return: A same-length list of unique names.
    """
    result: list[str] = []
    taken: set[str] = set()
    for name in names:
        candidate = name
        suffix = 2
        while candidate.casefold() in taken:
            candidate = f"{name}_{suffix}"
            suffix += 1
        result.append(candidate)
        taken.add(candidate.casefold())
    return result


def remove_tree(path: Path, /, *, attempts: int = 3, delay: float = 0.5) -> bool:
    """
    Best-effort recursive directory removal, retrying briefly on undeletable entries.

    On Windows a file some handle still holds open (e.g. a lingering GDAL or SQLite
    handle on a GeoPackage) cannot be deleted; a plain :func:`shutil.rmtree` either
    raises or, with ``ignore_errors``, silently leaves the residue behind. This helper
    swallows per-entry errors, sleeps *delay* seconds before each retry (locks are often
    released moments after their owner is garbage-collected), and reports whether the
    tree is actually gone. A missing *path* counts as success.

    :param path: The directory to remove.
    :param attempts: Total removal attempts.
    :param delay: Seconds slept before each retry.
    :return: Whether *path* no longer exists afterwards.
    """
    for attempt in range(attempts):
        if attempt:
            time.sleep(delay)
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            return True
    return False


def python_executable() -> Path | None:
    """
    Return the path to the Python interpreter, even when embedded in a host application.

    When Python is embedded (e.g. in QGIS) :data:`sys.executable` points at the host binary
    rather than the interpreter; reconstruct the interpreter path from the installation
    layout in that case. Useful for tools that must spawn a Python subprocess, like debugpy.

    :return: Path to the interpreter, or :data:`None` if it cannot be located.
    """
    for raw in (sys.executable, getattr(sys, "_base_executable", None)):
        if raw:
            candidate = Path(raw)
            if candidate.stem.lower().startswith("python") and candidate.is_file():
                return candidate
    if sys.platform == "win32":
        # On Windows python.exe sits in the interpreter's prefix root.
        prefixes = (sys.exec_prefix, sys.base_exec_prefix)
        guesses = [Path(prefix) / "python.exe" for prefix in prefixes]
    else:
        # On POSIX the interpreter lives in BINDIR, named pythonX.Y (with fallbacks).
        bindir = Path(sysconfig.get_config_var("BINDIR") or Path(sys.exec_prefix) / "bin")
        v = sys.version_info
        names = (f"python{v.major}.{v.minor}", f"python{v.major}", "python3", "python")
        guesses = [bindir / name for name in names]
    return next((guess for guess in guesses if guess.is_file()), None)
