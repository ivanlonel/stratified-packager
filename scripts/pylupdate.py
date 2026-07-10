"""``pylupdate`` wrapper that updates Qt ``.ts`` files using POSIX-relative source locations."""

from __future__ import annotations

import argparse
import fnmatch
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, override
from xml.etree import ElementTree as ET

from PyQt6.lupdate.designer_source import DesignerSource
from PyQt6.lupdate.python_source import PythonSource
from PyQt6.lupdate.translation_file import TranslationFile
from PyQt6.lupdate.user import UserException
from PyQt6.QtCore import PYQT_VERSION_STR

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from PyQt6.lupdate.translations import Message


class _AppendGlob(argparse.Action):
    @override
    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | Sequence[Any] | None,
        option_string: str | None = None,
    ) -> None:
        current = getattr(namespace, self.dest) or []
        expanded = []
        patterns = [values] if isinstance(values, str) else values or []
        for pattern in patterns:
            p = Path(pattern)
            matches = sorted(p.parent.glob(p.name))
            if not matches:
                parser.error(f"No files matched {pattern!r}")
            expanded.extend(matches)
        setattr(namespace, self.dest, current + expanded)


class MyTranslationFile(TranslationFile):
    """Encapsulate a translation file."""

    @override
    def write(self) -> None:
        """
        Write the translation file back to the filesystem.

        Overriding :meth:`TranslationFile.write` to enforce 2-space indentation.
        """
        # If we are keeping obsolete messages then add them to the updated message elements list.
        for name, message_els in self._contexts.items():
            updated_message_els = None

            for message_el in message_els:
                source_el = message_el.find("source")
                if source_el is None:
                    self.progress(f"Discarded message with no source in context '{name}'")
                    continue
                source = self.pretty(source_el.text)

                translation_el = message_el.find("translation")
                if translation_el is not None and translation_el.text:
                    if self._no_obsolete:
                        self.progress(f"Discarded obsolete message '{source}'")
                        self._nr_discarded_obsolete += 1
                    else:
                        translation_el.set("type", "vanished")

                        if updated_message_els is None:
                            updated_message_els = self._get_updated_message_els(name)

                        self._add_message_el(message_el, updated_message_els)

                        self.progress(f"Kept obsolete message '{source}'")
                        self._nr_kept_obsolete += 1
                else:
                    self.progress(f"Discarded untranslated message '{source}'")
                    self._nr_discarded_untranslated += 1

        # Created the sorted context elements.
        for name in sorted(self._updated_contexts.keys()):
            context_el = ET.Element("context")

            name_el = ET.Element("name")
            name_el.text = name
            context_el.append(name_el)

            context_el.extend(self._updated_contexts[name])

            self._root.append(context_el)

        self.progress(f"Writing {self._ts_file}...")

        # Replicate the indentation used by Qt Linguist.  Note that there are
        # still differences in the way elements are closed.
        for el in self._root:
            ET.indent(el, space="  ")

        with Path(self._ts_file).open("w", encoding="utf-8", newline="\n") as f:
            f.write('<?xml version="1.0" encoding="utf-8"?>\n')
            f.write("<!DOCTYPE TS>\n")
            ET.ElementTree(self._root).write(f, encoding="unicode")
            f.write("\n")

        if not self._no_summary:
            self._summary()

    @override
    def _make_location_el(self, message: Message) -> ET.Element:
        """
        Return a 'location' element.

        Overriding :meth:`TranslationFile._make_location_el` to enforce posix-style paths.
        """
        return ET.Element(
            "location",
            filename=Path(message.filename)
            .resolve()
            .relative_to(Path(self._ts_file).resolve().parent, walk_up=True)
            .as_posix(),
            line=str(message.line_nr),
        )

    @override
    def _make_message_el(self, message: Message) -> ET.Element:
        """
        Return a 'message' element, forcing numerus markup for ``%n`` sources.

        :meth:`TranslationFile._make_message_el` only writes ``numerus="yes"`` and a
        ``<numerusform>`` when the parser flagged the message as plural, which it does only for
        calls carrying a count (``n=`` keyword or a positional count argument). A ``%n`` string
        whose count is applied later would otherwise land without plural markup, silently
        disabling plural handling, so any new message whose source contains ``%n`` is coerced
        into the numerus skeleton here.
        """
        message_el: ET.Element = super()._make_message_el(message)
        if "%n" in (message.source or "") and message_el.get("numerus") != "yes":
            message_el.set("numerus", "yes")
            translation_el = message_el.find("translation")
            if translation_el is not None and translation_el.find("numerusform") is None:
                # Qt keeps plural text in <numerusform>, not as direct translation text.
                numerusform_el = ET.SubElement(translation_el, "numerusform")
                if translation_el.text:
                    numerusform_el.text = translation_el.text
                    translation_el.text = None
        return message_el


def numerus_violations(ts_files: Iterable[Path]) -> list[str]:
    """
    List every ``%n`` message lacking ``numerus="yes"`` in the given ``.ts`` files.

    ``lupdate`` may emit a new plural-aware (``%n``) message without the ``numerus``
    attribute, which silently disables plural handling for that message in every locale,
    so freshly-written files are re-checked.

    :param ts_files: Paths of ``.ts`` files to inspect.
    :return: One human-readable description per violation, empty when every message complies.
    """
    violations: list[str] = []
    for ts_file in ts_files:
        # S314 guards untrusted XML; these are repo files this tool itself just wrote.
        root = ET.parse(ts_file).getroot()  # noqa: S314
        for context in root.iter("context"):
            context_name = context.findtext("name", default="?")
            violations.extend(
                f"{ts_file}: context '{context_name}': source '{message.findtext('source')}'"
                for message in context.iter("message")
                if "%n" in (message.findtext("source") or "") and message.get("numerus") != "yes"
            )
    return violations


def _check_numerus(ts_files: Iterable[Path]) -> None:
    """
    Abort when a written ``.ts`` file has a ``%n`` message without ``numerus="yes"``.

    :param ts_files: Paths of ``.ts`` files to inspect.
    :raise UserException: If any ``%n`` message lacks the ``numerus`` attribute.
    """
    if violations := numerus_violations(ts_files):
        msg = (
            'Plural (%n) messages must carry numerus="yes"; add the attribute and its '
            "<numerusform> entries by hand, then rerun:\n" + "\n".join(violations)
        )
        raise UserException(msg)


def lupdate(
    sources: Iterable[Path],
    translation_files: Iterable[Path],
    *,
    no_obsolete: bool = False,
    no_summary: bool = True,
    verbose: bool = False,
    excludes: Sequence[str] | None = None,
) -> None:
    """
    Update translation (.ts) files from source files.

    The source files can be Python source (.py) files, Designer source (.ui)
    files or directories containing source files.

    :param sources: ``.py`` / ``.ui`` files, or directories to scan recursively.
    :param translation_files: ``.ts`` files to update.
    :param no_obsolete: Drop obsolete messages instead of keeping them as ``vanished``.
    :param no_summary: Suppress the per-file update summary.
    :param verbose: Show progress messages.
    :param excludes: ``fnmatch`` patterns pruning directory scans.
    :raise UserException: If a source has an unsupported type, or a written ``.ts``
        contains a ``%n`` message without ``numerus="yes"``.
    """
    if excludes is None:
        excludes = ()

    ts_paths = list(translation_files)

    # Read the .ts files.
    translations = [
        MyTranslationFile(ts, no_obsolete=no_obsolete, no_summary=no_summary, verbose=verbose)
        for ts in ts_paths
    ]

    # Read the sources.
    source_files: list[PythonSource | DesignerSource] = []
    for source in sources:
        if source.is_dir():
            # Sort on the POSIX path string so the scan order — and therefore the message
            # order inside each written .ts context — is identical across filesystems and
            # platforms (Path ordering would case-fold on Windows).
            for candidate in sorted(source.rglob("*"), key=lambda p: p.as_posix()):
                if candidate.is_file() and not any(
                    fnmatch.fnmatch(part, pattern)
                    for part in candidate.relative_to(source).parts
                    for pattern in excludes
                ):
                    if candidate.suffix == ".py":
                        source_files.append(PythonSource(filename=candidate, verbose=verbose))
                    elif candidate.suffix == ".ui":
                        source_files.append(DesignerSource(filename=candidate, verbose=verbose))
        elif source.suffix == ".py":
            source_files.append(PythonSource(filename=source, verbose=verbose))
        elif source.suffix == ".ui":
            source_files.append(DesignerSource(filename=source, verbose=verbose))
        else:
            msg = f"{source} must be a directory or a .py or a .ui file"
            raise UserException(msg)

    # Update each translation for each source.
    for t in translations:
        for s in source_files:
            t.update(s)
        t.write()

    _check_numerus(ts_paths)


def main() -> int:
    """Update a .ts file from a .py file."""
    # Parse the command line.
    parser = argparse.ArgumentParser(description="Python Language Update Tool")

    parser.add_argument("-V", "--version", action="version", version=PYQT_VERSION_STR)
    parser.add_argument(
        "--exclude",
        action="append",
        metavar="PATTERN",
        help="exclude matching files when reading a directory",
    )
    parser.add_argument(
        "--no-obsolete",
        "-no-obsolete",
        action="store_true",
        help="remove any obsolete translated messages",
    )
    parser.add_argument("--no-summary", action="store_true", help="suppress the summary")
    parser.add_argument(
        "--ts",
        "-ts",
        nargs="+",
        type=str,  # keep as str; Path conversion happens after glob expansion
        action=_AppendGlob,
        metavar="FILE",
        required=True,
        help="one or more .ts files to update or create (globs are expanded)",
    )
    parser.add_argument("--verbose", action="store_true", help="show progress messages")
    parser.add_argument(
        "file",
        nargs="+",
        type=str,
        action=_AppendGlob,
        help="the .py or .ui file, or directory to be read",
    )

    args = parser.parse_args()

    # Update the translation files.
    try:
        lupdate(
            args.file,
            args.ts,
            no_obsolete=args.no_obsolete,
            no_summary=args.no_summary,
            verbose=args.verbose,
            excludes=args.exclude,
        )
    except UserException as e:
        print(e, file=sys.stderr)
        return 1
    except Exception:  # noqa: BLE001
        if args.verbose:
            import traceback  # noqa: PLC0415

            traceback.print_exception(*sys.exc_info())
        else:
            print("An unexpected error occurred.", file=sys.stderr)

        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
